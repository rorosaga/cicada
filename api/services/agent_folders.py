"""Which of the person's folders Cicada's own agent may read: the person's choice (ruling 84, G209; owner 2026-11-26).

The rule in `harness_files` proposes: a top-level folder of the home is granted when it is a place a person keeps documents, and
refused by name or by what it holds (secrets, tooling, Cicada's own, too large, another disk, a folder macOS protects). Proposing
is all it does. The person disposes, here: **what they turned on stays on, what they turned off stays off, and a folder they add by
hand is granted even when the rule would have refused it**. Three things never move, whatever they choose: a folder that is Cicada's
own or too large to walk completely stays closed, and the file rules inside any granted folder (document kinds only, no hidden or
secret-shaped file or folder readable, key-shaped text never stored) apply to a folder the person added exactly as to one the rule
chose. A folder named for a vault that holds notes is on by default (`harness_files.notes_vault`); every other name that says
secrets is offered off, with the reason.

**Per device, outside every bank.** ``$CICADA_HOME/agent_folders.json`` (0600, atomic write, never in a bank or git):
``{"folders": {<id>: {"state": "on"|"off", "added": bool, "day": "YYYY-MM-DD"}}}``, where ``<id>`` is the folder's path below the
home (never an absolute path). A choice is stored only when it differs from what the rule proposes (an added folder always is), so
the file is the person's own decisions and nothing else. Read on every call and never cached: the backend, the CLI and Sleep's tail
are separate processes (the split-brain rule). Only the backend's routes write it, and only the app's Settings calls them; no
agent tool and no agent's shell command can (``cli_map``: the list is readable, never writable from an agent's shell).

The app picks the folder and sends the path; the backend never reads it before the person added it, and an added path is resolved
and refused when it is outside the home, hidden, ``Library``, a folder macOS protects, Cicada's home or bank (or holds one), on
another disk, behind a link, not a folder, or too large to walk. Each refusal is a sentence the person can read.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from api.services import harness_files as hf
from api.services.auth import cicada_home

FILENAME = "agent_folders.json"

#: Why an added path is refused, in words (``harness_files.location_problem`` and the walk give the code).
ADD_REFUSALS = {
    "outside": "Choose a folder inside your home folder.",
    "hidden": "A hidden folder holds settings and keys, so it is never read.",
    "protected": "macOS keeps this folder closed to a read Cicada starts by itself.",
    "link": "That folder is, or sits behind, a link. Choose the folder itself.",
    "missing": "That is not a folder.",
    "mount": "That folder is on another disk, so it stays closed.",
    "cicada": "That folder holds Cicada's own files, so it is never read.",
    "too_large": "That folder is too large to check completely, so it stays closed.",
    "too_varied": "That folder holds too many kinds of files to check, so it stays closed.",
}


class FoldersError(ValueError):
    """A change the list refuses, with a sentence the person can read. ``status`` is the HTTP code a route answers."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def path() -> Path:
    return cicada_home() / FILENAME


def load() -> dict:
    """The person's decisions as ``{id: {"state", "added", "day"}}``. No file, or one that cannot be read as a map, is no decisions."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = data.get("folders") if isinstance(data, dict) else None
    out: dict = {}
    for fid, choice in (raw.items() if isinstance(raw, dict) else ()):
        if isinstance(fid, str) and isinstance(choice, dict) and choice.get("state") in ("on", "off"):
            out[fid] = {"state": choice["state"], "added": bool(choice.get("added")), "day": str(choice.get("day") or "")}
    return out


def _save(choices: dict) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".agent-folders-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"folders": choices}, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def refused_paths(memory_path: Path) -> tuple[str, ...]:
    from api.services import harness_questions

    return harness_questions.refused_paths(memory_path)


def listing(memory_path: Path, *, home: Path | None = None, attended: bool = False) -> hf.Grant:
    """Every folder the list shows with its state, and the grant a run would use (``Grant.folders``, ``Grant.roots``)."""
    return hf.folder_list(home or Path.home(), attended=attended, refused=refused_paths(memory_path), choices=load())


def public(folder: hf.Folder) -> dict:
    """A row on the wire: the person's folder by its name (never its path), the state, the rule's own verdict and the words."""
    return {"id": folder.id, "name": folder.name, "state": folder.state, "why": folder.why, "granted": folder.granted,
            "locked": folder.locked, "added": folder.added, "reason": folder.reason}


def rows(memory_path: Path, *, home: Path | None = None, attended: bool = False) -> list[dict]:
    return [public(f) for f in listing(memory_path, home=home, attended=attended).folders]


def _find(grant: hf.Grant, folder_id: str) -> hf.Folder:
    for row in grant.folders:
        if row.id == folder_id:
            return row
    raise FoldersError("That folder is not in the list.", 404)


def set_state(memory_path: Path, folder_id: str, on: bool, *, home: Path | None = None, today: str | None = None) -> list[dict]:
    """Turn one listed folder on or off. A folder the rule already proposes this way keeps no decision (the file holds only what
    differs), so a person who turns a proposal back to what it was leaves nothing behind."""
    row = _find(listing(memory_path, home=home), str(folder_id))
    if row.locked:
        raise FoldersError(row.reason, 409)
    choices = load()
    if row.added or on != row.default_on:
        choices[row.id] = {"state": "on" if on else "off", "added": row.added, "day": today or date.today().isoformat()}
    else:
        choices.pop(row.id, None)
    _save(choices)
    return rows(memory_path, home=home)


def add(memory_path: Path, typed: str, *, home: Path | None = None, today: str | None = None) -> tuple[list[dict], dict]:
    """Add a folder by hand, on. The path is what the person typed or picked; it is resolved here and refused with a reason in words
    when it can never be read (see the module). A folder that is already in the list is only turned on. Returns the list and the row."""
    home = home or Path.home()
    text = str(typed or "").strip()
    if not text:
        raise FoldersError("Choose a folder.")
    if "\0" in text:
        raise FoldersError(ADD_REFUSALS["missing"])
    expanded = os.path.expanduser(text) if text.startswith("~") else text
    if not os.path.isabs(expanded):
        raise FoldersError("Choose a folder by its full path.")
    problem = hf.location_problem(home, expanded)
    if problem:
        raise FoldersError(ADD_REFUSALS[problem])
    lexical = os.path.normpath(expanded)
    folder_id = os.path.relpath(lexical, os.path.normpath(str(home))).replace(os.sep, "/")
    refused = refused_paths(memory_path)
    real = os.path.realpath(lexical)
    if any(hf.under(real, r) or hf.under(r, real) for r in refused):
        raise FoldersError(ADD_REFUSALS["cicada"])
    cen = hf.census(lexical)
    hard = hf.hard_refusal(Path(lexical).name, cen)
    if hard:
        raise FoldersError(ADD_REFUSALS[hard])
    listed = {f.id: f for f in listing(memory_path, home=home).folders}
    if folder_id in listed and listed[folder_id].locked:
        raise FoldersError(listed[folder_id].reason, 409)
    choices = load()
    top = folder_id in listed and not listed[folder_id].added
    if top and listed[folder_id].default_on:
        choices.pop(folder_id, None)                      # a proposal already on: nothing to remember
    else:
        choices[folder_id] = {"state": "on", "added": not top, "day": today or date.today().isoformat()}
    _save(choices)
    new = rows(memory_path, home=home)
    return new, next(r for r in new if r["id"] == folder_id)


def remove(memory_path: Path, folder_id: str, *, home: Path | None = None) -> list[dict]:
    """Forget a folder the person added by hand (a proposed folder is switched, never removed)."""
    choices = load()
    choice = choices.get(str(folder_id))
    if not choice or not choice.get("added"):
        raise FoldersError("Only a folder you added can be removed.", 404)
    del choices[str(folder_id)]
    _save(choices)
    return rows(memory_path, home=home)


def describe(grant: hf.Grant) -> list[str]:
    """The list as lines for a shell or a dry run: one per folder, its state and the reason."""
    out = []
    for f in grant.folders:
        mark = {"default": "on (default)", "on": "on (you)", "off": "off (you)", "refused": "off", "protected": "closed"}[f.state]
        out.append(f"{f.name}{' (added)' if f.added else ''}: {mark}. {f.reason}")
    return out
