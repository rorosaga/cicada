"""Each engine's models, as its own harness reports them, with when and from where (vision item 4, 2026-10-28).

The owner, 2026-10-28: "easily swap between models and keep that model list updated." Every card on the Sleep
engine picker already carries a ``models`` list; this module says, beside it, **where each model came from and when**
(``source``, ``as_of``), which family it belongs to, when Cicada first saw it, what an alias last resolved to — and,
when a harness's output format changes under its parser, **says so in words** (``drift``) instead of showing an empty
list as if the plan offered nothing.

Rails:

* **Harness-reported only.** Cicada fetches no vendor web page or model list: every entry comes from the person's own
  installed tool (``claude --help``, ``agent models``, ``opencode models``, ``grok models``, the ChatGPT plan's
  app-server ``model/list``, Ollama's local tags) or from what Cicada's own runs were told they ran on. A public vendor
  list is the owner's call (TODO "Needs the owner").
* **The Claude plan list needs no code edit.** Claude Code has no listing command; its ``--help`` names the aliases it
  accepts ("an alias for the latest model (e.g. 'fable', 'opus', or 'sonnet')"), and each alias always means the
  newest model of its family. Those aliases are read from the help text, cached on disk for a day, and refreshed in a
  background thread — never on a view load's critical path and never from a hook. The documented aliases stay as a
  floor (``source: documented``), so a model the harness accepts but its help example leaves out (haiku) never
  disappears; what an alias resolved to on a real run (``resolvesTo``) is noted from the run's own reply.
* **Never a silent swap.** A saved model stays listed whether or not a list still names it
  (``cli_engines.stale_model_sentence`` holds); this module only describes lists.
* **Drift fails loudly.** Each parser has a fixture per harness (``api/tests/fixtures/model_lists/``); a format change
  turns into ``drift`` — a sentence and a warning in the log — never an empty list.

The cache file (``$CICADA_HOME/model_catalogue.json``) holds ids, days and times only: machine-local, outside every
bank, disposable (a missing or corrupt file is rebuilt).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from loguru import logger

#: Claude Code's aliases as its documentation lists them (code.claude.com, checked 2026-10-28): the floor under what
#: ``--help`` names, never a list a new model needs a code edit to join.
DOCUMENTED_CLAUDE_ALIASES = ("sonnet", "haiku", "opus")
CLAUDE_HELP_TTL_S = 24 * 3600.0
HELP_TIMEOUT_S = 8.0
NEW_DAYS = 14
FILE_NAME = "model_catalogue.json"
DRIFT_SENTENCE = ("This tool's model list changed shape, so Cicada couldn't read it — showing the last list it gave. "
                  "A Cicada update reads the new shape.")

_LOCK = threading.Lock()
_REFRESHING = threading.Event()
_ALIAS = re.compile(r"'([A-Za-z][A-Za-z0-9._-]{0,40})'")


class FormatDrift(ValueError):
    """A harness answered in a shape its parser cannot read."""


# ---- parsers (pure; one fixture per harness) -------------------------------------------------------------------


def parse_claude_help(text: str) -> list[str]:
    """The aliases ``claude --help`` names for ``--model``, in its order. Raises :class:`FormatDrift` when the option
    or its quoted aliases are gone — the help moved under the parser, which is not the same as "no models"."""
    lines = (text or "").splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^\s*--model\b", line)), None)
    if start is None:
        raise FormatDrift("no --model option in the help text")
    block = [lines[start]]
    for line in lines[start + 1:]:
        if re.match(r"^\s*-", line):   # the next option
            break
        block.append(line)
    aliases = list(dict.fromkeys(m.group(1).lower() for m in _ALIAS.finditer(" ".join(block))))
    if not aliases:
        raise FormatDrift("the --model option names no alias")
    return aliases


#: Model lines that share one family heading in the picker (ruling 48 part 11: "families from the catalogue"). A
#: line not listed here is its own family, named by its first word. The words are the models' own names — what the
#: person picks — never a claim about who runs the read (provider-neutral copy, owner 2026-09-30).
_FAMILIES = (
    ("claude", "Claude", ("claude", "sonnet", "opus", "haiku", "fable")),
    ("gpt", "GPT", ("gpt", "chatgpt", "codex", "o1", "o3", "o4")),
    ("gemini", "Gemini", ("gemini", "gemma")),
    ("grok", "Grok", ("grok",)),
)
#: A tool's own models (Cursor's Composer and its own Auto): one heading, "<tool>'s own" (the card's own name).
_OWN = ("composer", "auto", "cursor")
_VARIANT = re.compile(r"(?:^|[-_.])(?:mini|nano|flash|fast|lite|small|tiny)(?:$|[-_.])")


def _bare(model_id: str) -> str:
    return (model_id or "").strip().split("/")[-1].lower()


def family(model_id: str) -> str:
    """A model's family for grouping: the line it belongs to (``claude``, ``gpt``, ``gemini``, ``grok``), ``own`` for a
    tool's own models, else its first word (``github-copilot/kimi-k3`` → ``kimi``)."""
    bare = _bare(model_id)
    words = re.findall(r"[a-z]+|\d+", bare)
    first = next((w for w in words if w.isalpha()), bare)
    if re.match(r"o\d", bare):   # o3, o4-mini: the reasoning line of GPT
        return "gpt"
    for key, _label, members in _FAMILIES:
        if first in members or (key == "claude" and any(w in members for w in words)):
            return key
    if first in _OWN:
        return "own"
    return first


def family_label(key: str, *, tool: str = "") -> str:
    """The family's heading: its line's name, ``"<tool>'s own"`` for a tool's own models, else the word capitalised."""
    for k, label, _members in _FAMILIES:
        if k == key:
            return label
    if key == "own":
        return f"{tool}'s own" if tool else "The tool's own"
    return key[:1].upper() + key[1:]


def version_key(model_id: str) -> tuple:
    """Newest first within a family: the numbers in the id, largest first; a smaller variant (mini, flash…) after its
    full model; an id with no number keeps its place after the numbered ones. Harnesses list no release dates, so the
    id's own version is the only order on the record."""
    nums = [int(n) for n in re.findall(r"\d+", _bare(model_id))[:3]]
    padded = tuple(-n for n in nums + [0] * (3 - len(nums)))   # 5.5 is newer than 5
    return (0 if nums else 1, padded, 1 if _VARIANT.search(_bare(model_id)) else 0)


def ordered(rows: list[dict], *, tool: str = "") -> list[dict]:
    """The catalogue's rows for the picker: families in the order the harness first lists them, newest first inside
    each, every row carrying its ``familyLabel``. The card's ``models`` keep the harness's own order (a tap on a card
    writes its first model, R-HS7); only these rows are reordered."""
    first_seen_at: dict[str, int] = {}
    for i, row in enumerate(rows):
        first_seen_at.setdefault(row["family"], i)
    indexed = sorted(enumerate(rows), key=lambda p: (first_seen_at[p[1]["family"]],
                                                     version_key(p[1]["id"]) if p[1]["source"] != "saved" else (2,),
                                                     p[0]))
    return [dict(row, familyLabel=family_label(row["family"], tool=tool)) for _, row in indexed]


# ---- the cache file ----------------------------------------------------------------------------------------------


def _path() -> Path:
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    return Path(raw).expanduser() / FILE_NAME


_MEMO: dict[str, tuple[tuple[int, int], dict]] = {}


def _read(*, fresh: bool = False) -> dict:
    """The cache file, parsed once per stamp (a picker read asks once per card). The memo's dict is shared: callers
    only read it; a writer asks ``fresh`` for its own copy."""
    path = _path()
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
        hit = _MEMO.get(str(path))
        if hit is not None and hit[0] == stamp and not fresh:
            return hit[1]
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    data = data if isinstance(data, dict) else {}
    if not fresh:
        _MEMO[str(path)] = (stamp, data)
    return data


def _load() -> dict:
    """A copy of the cache file to change and :func:`_save`."""
    return _read(fresh=True)


def _save(data: dict) -> None:
    path = _path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:   # a cache that cannot be written is rebuilt next time
        logger.warning(f"model catalogue not saved: {type(exc).__name__}")


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- the Claude plan's list --------------------------------------------------------------------------------------


def refresh_claude(*, runner=None) -> dict:
    """Read ``claude --help`` now and store what it names. Returns the stored entry
    (``{aliases, at, drift}``). Never raises: a tool not installed or not answering keeps the last entry."""
    from api.services import agent_engine
    from api.services.connections import base

    binary = base.resolve_binary("claude")
    with _LOCK:
        data = _load()
        entry = dict(data.get("claude") or {})
    if binary is None:
        return entry
    run = runner or agent_engine._default_runner()
    try:
        result = run([binary, "--help"], stdin=None, timeout=HELP_TIMEOUT_S, cwd=None,
                     env_overrides={"CICADA_CAPTURE": "off", "CICADA_RECALL": "off"})
    except Exception as exc:  # noqa: BLE001 — a probe never fails its caller
        logger.warning(f"claude --help failed: {type(exc).__name__}")
        return entry
    if getattr(result, "rc", 1) != 0:
        return entry
    try:
        entry.update({"aliases": parse_claude_help(result.stdout), "at": time.time(), "drift": False})
    except FormatDrift as exc:
        logger.warning(f"claude --help: model aliases unreadable ({exc}); keeping the last list")
        entry.update({"at": time.time(), "drift": True})
    with _LOCK:
        data = _load()
        data["claude"] = entry
        _save(data)
    return entry


def _claude_entry(*, wait: bool = False) -> dict:
    """The stored entry; a day-old or missing one starts one background refresh (``wait``: run it here instead —
    only an explicit refresh asks)."""
    with _LOCK:
        entry = dict(_read().get("claude") or {})
    stale = time.time() - float(entry.get("at") or 0) > CLAUDE_HELP_TTL_S
    if wait and stale:
        return refresh_claude()
    if stale and not _REFRESHING.is_set() and os.environ.get("CICADA_MODEL_CATALOGUE_REFRESH", "on") != "off":
        _REFRESHING.set()

        def run():
            try:
                refresh_claude()
            finally:
                _REFRESHING.clear()

        threading.Thread(target=run, name="model-catalogue-claude", daemon=True).start()
    return entry


def note_resolved(engine: str, requested: str | None, served: str | None) -> None:
    """A run asked for ``requested`` (an alias) and the harness reported serving ``served``: remember it, so the
    picker can say what the alias means today. Ids only; never raises; writes only when the answer changed."""
    requested, served = (requested or "").strip(), (served or "").strip()
    if not engine or not requested or not served or requested == served:
        return
    try:
        with _LOCK:
            if (((_read().get("resolved") or {}).get(engine) or {}).get(requested) or {}).get("id") == served:
                return   # the common case on every run: nothing new, nothing read twice, nothing written
            data = _load()
            resolved = data.setdefault("resolved", {}).setdefault(engine, {})
            resolved[requested] = {"id": served, "at": time.time()}
            _save(data)
    except Exception as exc:  # noqa: BLE001 — never fails a run
        logger.warning(f"model catalogue: resolved id not noted ({type(exc).__name__})")


# ---- one engine's catalogue --------------------------------------------------------------------------------------


def _first_seen(data: dict, engine: str, ids: list[str], today: str) -> dict[str, str | None]:
    """When each id first appeared in this engine's list. Ids present the first time an engine is catalogued are
    ``None`` (known since the catalogue began — never all "new" at once)."""
    seen = data.setdefault("seen", {})
    known = seen.get(engine)
    if known is None:
        seen[engine] = {m: None for m in ids}
        return dict(seen[engine])
    for m in ids:
        known.setdefault(m, today)
    return {m: known.get(m) for m in ids}


def catalogue(engine: str, models: list[tuple[str, str]], *, as_of: float | str | None, source: str,
              drift: bool = False, saved: str | None = None, today: date | None = None, tool: str = "") -> dict:
    """One card's catalogue: ``models`` is ``[(id, source)]`` in the card's order; the rows come back grouped by family,
    newest first (:func:`ordered`; ``tool`` names a tool's own family). ``saved`` is listed (``source: saved``) when no
    list names it. Records first-seen days in the cache file when a new id appears."""
    today_s = (today or date.today()).isoformat()
    rows = list(dict.fromkeys(models))
    ids = [m for m, _ in rows]
    if saved and saved not in ids:
        rows.append((saved, "saved"))
        ids.append(saved)
    listed = [m for m, s in rows if s != "saved"]
    with _LOCK:
        data = _read()
        known = (data.get("seen") or {}).get(engine)
        if known is None or any(m not in known for m in listed):
            # A new id (or a first catalogue of this engine): write it down, on a copy of the file.
            data = _load()
            first = _first_seen(data, engine, listed, today_s)
            _save(data)
        else:
            first = {m: known.get(m) for m in listed}
        resolved = (data.get("resolved") or {}).get(engine) or {}
    stamp = as_of if isinstance(as_of, str) else _iso(as_of)
    out = []
    for model_id, how in rows:
        seen = first.get(model_id)
        new = bool(seen) and (date.fromisoformat(today_s) - date.fromisoformat(seen)).days < NEW_DAYS
        row = {"id": model_id, "source": how, "asOf": stamp if how not in ("saved", "documented") else None,
               "family": family(model_id), "firstSeen": seen, "new": new}
        if (r := resolved.get(model_id)) and r.get("id"):
            row["resolvesTo"] = r["id"]
            row["resolvedAt"] = _iso(r.get("at"))
        out.append(row)
    return {"engine": engine, "asOf": stamp, "source": source, "drift": DRIFT_SENTENCE if drift else None,
            "models": ordered(out, tool=tool)}


def claude_plan(saved: str | None = None, *, wait: bool = False) -> tuple[list[str], dict]:
    """The Claude plan card's model ids and catalogue: the documented aliases in their old order (a tap on the card
    writes its first model, R-HS7, so the first never moves), each ``harness`` when ``claude --help`` names it too,
    then every alias only the help names, then a saved choice no list names."""
    entry = _claude_entry(wait=wait)
    reported = [a for a in entry.get("aliases") or [] if isinstance(a, str)]
    rows = [(a, "harness" if a in reported else "documented") for a in DOCUMENTED_CLAUDE_ALIASES]
    rows += [(a, "harness") for a in reported if a not in DOCUMENTED_CLAUDE_ALIASES]
    cat = catalogue("claude-cli", rows, as_of=entry.get("at"), source="claude --help" if reported else "documented",
                    drift=bool(entry.get("drift")), saved=saved)
    ids = [m for m, _ in rows]
    return ids + ([saved] if saved and saved not in ids else []), cat
