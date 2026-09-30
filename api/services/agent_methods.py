"""How the person's own agent does a job Cicada asks of it — a selection, not a mechanism (G166, G178 generalises it).

A **job** is something the person's agent does for Cicada that has more than one
way to be done. One ships here, ``reading`` ("How your agent reads"); the video
branch adds ``watching``. The person's **choice** for a job is one of three
kinds:

* ``auto`` (the default) — "Let my agent choose": Cicada names no tool, and
  every prompt and reply is exactly the default text;
* ``own`` — the agent's own built-in tools (named neutrally: no app, plan or
  vendor). Cicada says "don't load a separate skill for it";
* a **skill** — a catalog id (``recommended_skills.json``) whose ``roles`` list
  the job. Cicada says "the person chose the ``<name>`` skill for this: use it. If
  it is not installed for you, say so and stop."

A choice is an *instruction to the person's own agent*, never authority: it
changes what Cicada SAYS, not what Cicada does (ruling 14: Cicada asks, it cannot
see or limit what the agent does). It lives in ``$CICADA_HOME/agent_methods.json``
(0600, atomic, machine-wide, never in a bank), read on every call and never
cached: the backend and each stdio MCP process both read it (the split-brain
rule). An unknown or removed id reads as ``auto``.

The person's own hand-off prompt ("Copy for an agent", "Ask an agent") goes to whichever
agent they paste it into, so its skill clause is conditional: use the skill if you run on
this Mac and can load skills, else your own browser tools.

A tool's reply to a remote connection gets no clause at all — a cloud app has no local skill folder,
so "use <skill>" would end its run — and neither does a client that is not one of
``skill_catalog.AGENTS`` (a skill is named only where it can be installed; the
agent's own tools may still be named). Every string here is neutral: skill names
arrive from the catalog as data the person picked, never from a template.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from api.services import skill_catalog
from api.services.auth import cicada_home

FILENAME = "agent_methods.json"
AUTO, OWN = "auto", "own"


@dataclass(frozen=True)
class Job:
    job: str
    question: str
    own_title: str
    own_detail: str
    #: What the default text says the agent opens pages with, before any choice.
    default_tools: str
    #: The argument the agent records which tool it used in (``cicada_record_read``'s ``via``;
    #: ``cicada_record_watch``'s ``engine``) — named in a clause only where the tool has it (R12).
    via_arg: str = "via"
    #: A shorter first-person skill sentence for a prompt with a hard character cap (the video
    #: hand-off's 1,200); ``None`` uses the shared template.
    person_skill: str | None = None


JOBS: dict[str, Job] = {
    "reading": Job(
        job="reading", question="How your agent reads",
        own_title="Its own browser or computer tools",
        own_detail="Whatever your agent already has where you use it.",
        default_tools="your browser tools"),
    "watching": Job(
        job="watching", question="How your agent watches",
        own_title="Its own tools for watching",
        own_detail="Whatever your agent already has where you use it.",
        default_tools="your own tools", via_arg="engine",
        person_skill="I chose the {name} skill: if you can load skills, use it (`engine` \"{invoke}\"), "
                     "else say so and stop."),
}

AUTO_TITLE = "Let my agent choose"
AUTO_DETAIL = "Cicada doesn't name a tool."


class MethodError(ValueError):
    """A choice Cicada refuses, with a sentence the person can read."""


def path() -> Path:
    return cicada_home() / FILENAME


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".methods-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _skills_for(job: str, catalog: dict | None = None) -> list[dict]:
    catalog = catalog or skill_catalog.load()
    return [e for e in sorted(catalog["skills"], key=skill_catalog._rank)
            if e.get("kind") == "skill" and job in (e.get("roles") or []) and e.get("invoke")]


def skill_entry(job: str, choice_id: str, catalog: dict | None = None) -> dict | None:
    return next((e for e in _skills_for(job, catalog) if e["id"] == choice_id), None)


def choice(job: str, catalog: dict | None = None) -> str:
    """The person's choice for ``job``: ``auto``, ``own`` or a catalog skill id that
    still lists the job; anything else reads as ``auto`` (a stale choice never steers
    an agent to something Cicada no longer lists)."""
    if job not in JOBS:
        return AUTO
    raw = (_load().get("choices") or {}).get(job)
    if raw == OWN:
        return OWN
    if isinstance(raw, str) and skill_entry(job, raw, catalog) is not None:
        return raw
    return AUTO


def set_choice(job: str, chosen: str, catalog: dict | None = None) -> str:
    """Store the choice, or raise :class:`MethodError`. Returns the stored value.
    Choosing a skill that is not installed is allowed and saved: the row says so,
    and the agent's half of the same contract is to say so and stop."""
    if job not in JOBS:
        raise MethodError("That isn't something Cicada asks your agent to do.")
    chosen = str(chosen or "").strip()
    if chosen not in (AUTO, OWN) and skill_entry(job, chosen, catalog) is None:
        raise MethodError(f"That isn't one of the choices for {JOBS[job].question.lower()}.")
    data = _load()
    choices = dict(data.get("choices") or {}) if isinstance(data.get("choices"), dict) else {}
    if chosen == AUTO:
        choices.pop(job, None)
    else:
        choices[job] = chosen
    new = {**data, "choices": choices}
    if new != data:
        _save(new)
    return chosen


def mtime() -> float:
    try:
        return path().stat().st_mtime
    except OSError:
        return 0.0


def fingerprint() -> str:
    """Part of the handshake cache key: flipping a choice must never serve yesterday's primer."""
    parts = [f"{job}={choice(job)}" for job in sorted(JOBS)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:8]


# --- what the person sees ----------------------------------------------------------------------------------


def options(job: str, *, home: Path | None = None, catalog: dict | None = None) -> list[dict]:
    """The picker: auto, own, then one entry per catalog skill that lists the job
    (through ``skill_catalog._view``, so the app decodes it like a Skills card)."""
    spec = JOBS[job]
    home = home or skill_catalog.agent_home()
    catalog = catalog or skill_catalog.load()
    plugin_ids = skill_catalog.claude_plugin_ids(home)
    out = [
        {"id": AUTO, "kind": "auto", "title": AUTO_TITLE, "detail": AUTO_DETAIL},
        {"id": OWN, "kind": "own", "title": spec.own_title, "detail": spec.own_detail},
    ]
    for entry in _skills_for(job, catalog):
        view = skill_catalog._view(entry, home, plugin_ids)
        view["kind"] = "skill"
        view["title"] = entry.get("pageName") or entry["invoke"]
        view["detail"] = entry.get("summary", "")
        out.append(view)
    return out


# --- what the agent is told --------------------------------------------------------------------------------
#
# One template table, two voices (the person's own hand-off prompt, and a tool's reply about the person),
# so there is one prose source. Nothing here names a product; a skill's name is filled from the catalog.

_PERSON = {
    OWN: "I chose your own built-in tools for this; don't load a separate skill for it.",
    # The person pastes this into whichever agent they use, possibly an app connected from
    # anywhere that cannot load a local skill — so the skill is conditional here.
    "skill": "I chose the {name} skill for this. If you run on this Mac and can load skills, use it, and set "
             "`{via_arg}` to \"{invoke}\"; if it is not installed for you, say so and stop. If you cannot load skills "
             "where you run (an app connected from anywhere, say), use your own browser tools instead.",
}
_REPLY = {
    OWN: "The person chose your own built-in tools for this; don't load a separate skill for it.",
    "skill": "The person chose the {name} skill for this: use it, and set `{via_arg}` to \"{invoke}\". "
             "If it is not installed for you, say so and stop.",
}


def _name(entry: dict) -> str:
    return f"`{entry['invoke']}`"


def _clause(job: str, table: dict, *, variant: str | None, gate_variant: bool) -> str | None:
    chosen = choice(job)
    if chosen == AUTO:
        return None
    if chosen == OWN:
        return table[OWN]
    if gate_variant and variant not in skill_catalog.AGENTS:
        return None  # a skill is named only where it can be installed
    entry = skill_entry(job, chosen)
    if not entry:
        return None
    spec = JOBS[job]
    template = (spec.person_skill if table is _PERSON and spec.person_skill else table["skill"])
    return template.format(name=_name(entry), invoke=entry["invoke"], via_arg=spec.via_arg)


def tool_phrase(job: str, *, voice: str = "person") -> str:
    """What the default text says pages are opened with — replaced by a neutral
    pointer once the person chose something, so the text never contradicts the clause."""
    if choice(job) == AUTO:
        return JOBS[job].default_tools
    return "the tool I chose" if voice == "person" else "the tool the person chose"


def prompt_clause(job: str) -> str | None:
    """First person, for the person's own hand-off prompt (they pass it to whichever
    agent they use, so the skill clause is conditional on the agent being able to load one)."""
    return _clause(job, _PERSON, variant=None, gate_variant=False)


def reply_clause(job: str, *, variant: str | None = None, remote: bool = False) -> str | None:
    """Third person, for a tool's reply to a local agent. Nothing for a remote
    connection, and a skill only for a client that is one of the catalog's agents."""
    if remote:
        return None
    return _clause(job, _REPLY, variant=variant, gate_variant=True)


def capability_line(job: str, variant: str) -> str | None:
    """One primer line for a local variant when the choice for ``job`` is not ``auto``
    (reading also needs the person's agent reading on). Names only real tools with their
    real arguments (R12)."""
    from api.services import reading_settings

    if job == "reading" and not reading_settings.agent_enabled():
        return None
    if job not in _LINES:
        return None
    chosen = choice(job)
    if chosen == AUTO:
        return None
    lead, own, skill = _LINES[job]
    if chosen == OWN:
        return f"- {lead}: {own}"
    if variant not in skill_catalog.AGENTS:
        return None
    entry = skill_entry(job, chosen)
    if entry is None:
        return None
    return f"- {lead}: " + skill.format(name=_name(entry), invoke=entry["invoke"])


#: The primer line per job: (lead, own-tools sentence, skill sentence). Kept short — the primer's
#: fixed part has a budget test that is not raised for a new line.
_LINES = {  # item 9 and item 3 already name the tools; a line only says which skill
    "reading": (
        "Reading pages",
        "the person chose your own built-in browser or computer tools for it; don't load a separate skill.",
        "the person chose the {name} skill for it. Use it for item 9; set `via` to \"{invoke}\". "
        "If it is not installed for you, say so and stop."),
    "watching": (
        "Watching videos",
        "the person chose your own built-in tools for it; don't load a separate skill.",
        "the person chose the {name} skill for it. Use it for their video queue; set `engine` to "
        "\"{invoke}\". If it is not installed for you, say so and stop."),
}


def method_lines(variant: str) -> tuple[str, ...]:
    """The primer's method lines for a local variant, at most ``MAX_METHOD_LINES``."""
    lines = []
    for job in JOBS:
        try:
            line = capability_line(job, variant)
        except Exception:  # noqa: BLE001 — a primer is never worth a failed connect
            line = None
        if line:
            lines.append(line)
    return tuple(lines)[: skill_catalog.MAX_METHOD_LINES]
