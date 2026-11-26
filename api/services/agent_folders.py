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

import contextlib
import fcntl
import json
import os
import tempfile
from datetime import date
from pathlib import Path

from api.services import harness_files as hf
from api.services.auth import cicada_home

FILENAME = "agent_folders.json"
LOCK_FILENAME = ".agent_folders.lock"

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
#: What a refused add answers: "the person cannot choose this", the 409 the neighbouring routes use (an empty or malformed path is a 400).
REFUSED = 409


class FoldersError(ValueError):
    """A change the list refuses, with a sentence the person can read. ``status`` is the HTTP code a route answers."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def path() -> Path:
    return cicada_home() / FILENAME


def _read_doc() -> dict:
    """The whole file as it is (every key, known or not). No file, or one that cannot be read as a map, is an empty one."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalise(raw) -> dict:
    out: dict = {}
    for fid, choice in (raw.items() if isinstance(raw, dict) else ()):
        if isinstance(fid, str) and isinstance(choice, dict) and choice.get("state") in ("on", "off"):
            out[fid] = {**choice, "state": choice["state"], "added": bool(choice.get("added")), "day": str(choice.get("day") or "")}
    return out


def load() -> dict:
    """The person's decisions as ``{id: {"state", "added", "day"}}``. No file, or one that cannot be read as a map, is no decisions."""
    return _normalise(_read_doc().get("folders"))


@contextlib.contextmanager
def _edit():
    """Change the file under one cross-process lock (the backend's routes run in threads, the CLI and the app in other processes): yields
    the ``folders`` map to change in place and writes the whole file back, every other key kept as found, only when the block ends
    without an error (a refusal leaves nothing behind)."""
    lock = path().with_name(LOCK_FILENAME)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            doc = _read_doc()
            folders = doc.get("folders")
            if not isinstance(folders, dict):
                folders = doc["folders"] = {}
            yield folders
            _write(doc)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _names(home: Path, key: str, folder_id: str) -> bool:
    """Does a stored key name this folder: the same id, or one spelled in another casing or normal form that is the same folder (or no
    folder any more). A disk that keeps two folders differing only in case keeps their decisions apart."""
    if key == folder_id:
        return True
    if hf.fold_id(key) != hf.fold_id(folder_id):
        return False
    problem, canon = hf.resolve_location(home, os.path.join(str(home), *key.split("/")))
    return bool(problem) or os.path.relpath(canon, os.path.normpath(str(home))).replace(os.sep, "/") == folder_id


def _forget(folders: dict, folder_id: str, home: Path) -> None:
    """Drop every decision kept for this folder, whatever the casing or normal form it was written in."""
    for key in [k for k in folders if _names(home, str(k), folder_id)]:
        del folders[key]


def _remember(folders: dict, folder_id: str, state: str, added: bool, day: str, home: Path) -> None:
    _forget(folders, folder_id, home)
    folders[folder_id] = {"state": state, "added": added, "day": day}


def _write(doc: dict) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".agent-folders-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
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
    """The listed folder: the id as written, else the one that is the same name in another casing or normal form."""
    exact = [r for r in grant.folders if r.id == folder_id]
    same = exact or [r for r in grant.folders if hf.fold_id(r.id) == hf.fold_id(folder_id)]
    if len(same) != 1:
        raise FoldersError("That folder is not in the list.", 404)
    return same[0]


def set_state(memory_path: Path, folder_id: str, on: bool, *, home: Path | None = None, today: str | None = None) -> list[dict]:
    """Turn one listed folder on or off. A folder the rule already proposes this way keeps no decision (the file holds only what
    differs), so a person who turns a proposal back to what it was leaves nothing behind."""
    home = home or Path.home()
    with _edit() as folders:
        row = _find(listing(memory_path, home=home), str(folder_id))
        if row.locked:
            raise FoldersError(row.reason, REFUSED)
        if row.added or on != row.default_on:
            _remember(folders, row.id, "on" if on else "off", row.added, today or date.today().isoformat(), home)
        else:
            _forget(folders, row.id, home)
    return rows(memory_path, home=home)


def add(memory_path: Path, typed: str, *, home: Path | None = None, today: str | None = None) -> tuple[list[dict], dict]:
    """Add a folder by hand, on. The path is what the person typed or picked; it is resolved here (every part spelled as the disk spells
    it, so ``library`` is ``Library`` and is refused) and refused with a reason in words when it can never be read (see the module). A
    folder that is already in the list is only turned on. Returns the list and the row."""
    home = home or Path.home()
    text = str(typed or "").strip()
    if not text:
        raise FoldersError("Choose a folder.")
    if "\0" in text:
        raise FoldersError(ADD_REFUSALS["missing"])
    expanded = os.path.expanduser(text) if text.startswith("~") else text
    if not os.path.isabs(expanded):
        raise FoldersError("Choose a folder by its full path.")
    problem, lexical = hf.resolve_location(home, expanded)
    if problem:
        raise FoldersError(ADD_REFUSALS[problem], REFUSED)
    folder_id = os.path.relpath(lexical, os.path.normpath(str(home))).replace(os.sep, "/")
    refused = refused_paths(memory_path)
    real = os.path.realpath(lexical)
    if any(hf.under(real, r) or hf.under(r, real) for r in refused):
        raise FoldersError(ADD_REFUSALS["cicada"], REFUSED)
    cen = hf.census(lexical)
    hard = hf.hard_refusal(Path(lexical).name, cen)
    if hard:
        raise FoldersError(ADD_REFUSALS[hard], REFUSED)
    with _edit() as folders:
        listed = {f.id: f for f in listing(memory_path, home=home).folders}
        known = listed.get(folder_id)
        if known is not None and known.locked:
            raise FoldersError(known.reason, REFUSED)
        top = known is not None and not known.added
        if top and known.default_on:
            _forget(folders, folder_id, home)              # a proposal already on: nothing to remember
        else:
            _remember(folders, folder_id, "on", not top, today or date.today().isoformat(), home)
            # The row as it would stand: a folder inside a granted one, under a name that one's rules refuse, could never be read
            # (a deny always wins over an allow), so it is not added at all rather than listed on and reading nothing.
            trial = hf.folder_list(home, refused=refused, choices=_normalise(folders))
            row = next((f for f in trial.folders if f.id == folder_id), None)
            if row is not None and row.locked:
                raise FoldersError(row.reason, REFUSED)
    new = rows(memory_path, home=home)
    return new, next(r for r in new if r["id"] == folder_id)


def remove(memory_path: Path, folder_id: str, *, home: Path | None = None) -> list[dict]:
    """Forget a folder the person added by hand (a proposed folder is switched, never removed)."""
    home = home or Path.home()
    with _edit() as folders:
        try:
            mine = _find(listing(memory_path, home=home), str(folder_id)).id
        except FoldersError:                              # a folder that vanished is still forgotten
            mine = str(folder_id)
        if not any(_names(home, str(k), mine) and isinstance(c, dict) and c.get("added") for k, c in folders.items()):
            raise FoldersError("Only a folder you added can be removed.", 404)
        _forget(folders, mine, home)
    return rows(memory_path, home=home)


def describe(grant: hf.Grant) -> list[str]:
    """The list as lines for a shell or a dry run: one per folder, its state and the reason."""
    out = []
    for f in grant.folders:
        mark = {"default": "on (default)", "on": "on (you)", "off": "off (you)", "refused": "off", "protected": "closed"}[f.state]
        out.append(f"{f.name}{' (added)' if f.added else ''}: {mark}. {f.reason}")
    return out
