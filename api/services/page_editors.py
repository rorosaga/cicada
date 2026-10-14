"""The agents the person lets edit a page directly (owner ruling 2026-10-14, G198): a machine-wide file, never in a
bank.

``$CICADA_HOME/editors.json`` (0600, atomic write) holds ``{"trusted": {<harness>: <day granted>}}``. A harness on
it applies a page edit (``cicada_edit_page``) at once, committed under its own name; any other agent's edit becomes a
proposal in the inbox that the person accepts with one tap (agent proposes, user disposes — UX principle 3).

**What is trusted is a harness label, never a model.** An MCP client does not disclose its model (``Cicada-Author``
never names one), so the only name Cicada can check at write time is the harness the client says it is
(``agent_commits.author_for``). The list is a policy, not an authentication: a local process can claim any label,
which is no more than it can already do with the files on the same Mac. Two names are never trustable: ``agent``
(a client that said nothing about itself) and every remote connector's app (``catalog``-style remote labels): the edit
tool is stdio and command line only in this slice.

**Empty by default.** Nobody edits a page directly until the person adds an agent in Settings; until then every edit
is a proposal. Only the backend's ``PUT /settings/editors`` writes this file (the app's Settings); no MCP tool or
agent-shell command can. Read on every call and never cached — the stdio MCP server and the backend are two
processes that both read it (the split-brain rule).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from api.services.auth import cicada_home

FILENAME = "editors.json"

#: Harness labels that name a remote app or nobody in particular — never on the list.
_NEVER = frozenset({"agent", "unknown", "user", "cicada", "claude-web", "chatgpt", "perplexity", "grok",
                    "claude-code-remote", "codex-remote", "remote-app"})


class EditorsError(ValueError):
    """A change the trust list refuses, with a sentence the person can read."""


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
    fd, tmp = tempfile.mkstemp(prefix=".editors-", suffix=".tmp", dir=str(target.parent))
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


def candidates() -> dict[str, str]:
    """``{harness: display name}`` — the local harnesses the person can trust (the Sources page's one table)."""
    from api.services.source_overview import HARNESS_LABELS

    return {k: v for k, v in HARNESS_LABELS.items() if k not in _NEVER}


def trustable(harness: str | None) -> bool:
    value = (harness or "").strip()
    return bool(value) and value not in _NEVER


def trusted() -> dict[str, str]:
    """``{harness: day granted}`` as stored; an entry that could never be trusted grants nothing."""
    raw = _load().get("trusted")
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for key in sorted(raw):
            if isinstance(key, str) and trustable(key):
                out[key] = str(raw[key] or "")[:10]
    return out


def is_trusted(author: str | None, *, remote: bool = False) -> bool:
    """May ``author`` (a ``Cicada-Author`` harness label) edit a page directly? Never for a remote caller."""
    return not remote and trustable(author) and (author or "").strip() in trusted()


def snapshot() -> dict:
    held = trusted()
    names = candidates()
    return {
        "trusted": [{"harness": h, "label": names.get(h, h), "since": day} for h, day in held.items()],
        "candidates": [{"harness": h, "label": label} for h, label in names.items()],
    }


def update(changes: dict, *, today: date | None = None) -> dict:
    """Apply a patch ``{harness: bool}`` (True adds with today's date, False removes) and return the snapshot.
    A name that can never be trusted refuses the whole call, nothing written; a no-op writes nothing."""
    if not isinstance(changes, dict):
        raise EditorsError("Send a map of agent to true or false.")
    bad = sorted(str(k) for k, v in changes.items() if v and not trustable(str(k)))
    if bad:
        raise EditorsError(f"{', '.join(bad)} can't be allowed to edit pages directly. Nothing was changed.")
    data = _load()
    held = trusted()
    before = dict(held)
    for key, on in changes.items():
        key = str(key).strip()
        if on:
            held.setdefault(key, (today or date.today()).isoformat())
        else:
            held.pop(key, None)
    if held != before:
        data["trusted"] = dict(sorted(held.items()))
        _save(data)
    return snapshot()
