#!/usr/bin/env python3
"""Merge/uninstall ONLY Cicada's user-level Cursor hook entries; stdlib.

hooks.json v1 uses flat event arrays, unlike Claude/Codex nested hook lists.
Invalid/unknown configs are untouched; every other tool's entry is kept.

One command (``api/hooks/cursor.py``) in two groups, each its own switch
(``--hook``): ``startup`` is ``sessionStart`` (startup context, G149) and
``capture`` is ``beforeSubmitPrompt`` + ``afterAgentResponse`` (the person's
turns and the agent's replies, capture-everywhere). Turning one group off never
touches the other; ``uninstall`` with no ``--hook`` removes both. No ``stop``,
thought or tool hook is ever registered.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

if __package__:
    from .registry import RegistryError, _save
else:
    sys.path.insert(0, str(Path(__file__).parent))
    from registry import RegistryError, _save

MAX_BYTES = 256 * 1024
EVENT = "sessionStart"
#: group -> {event: timeout in seconds}. ``beforeSubmitPrompt`` holds the person's
#: message until it answers, so its bound is tight (the hook's request gives up first).
HOOKS = {
    "startup": {EVENT: 2},
    "capture": {"beforeSubmitPrompt": 2, "afterAgentResponse": 5},
}


def _ours(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
        return False
    try:
        words = shlex.split(entry["command"])
    except ValueError:
        return False
    return len(words) == 2 and words[0].startswith("/") and (
        (re.fullmatch(r"python(?:\d+(?:\.\d+)?)?|cicada-python", Path(words[0]).name)
         and words[1].startswith("/") and words[1].endswith("/api/hooks/cursor.py"))
        or (Path(words[0]).name == "cicada-hook" and words[1] == "cursor"))


def default_command():
    def quote(value):
        return "'" + str(value).replace("'", "'\\''") + "'"
    if os.environ.get("CICADA_DISTRIBUTION") == "release":
        home = Path(os.environ.get("CICADA_HOME") or (Path.home() / ".cicada"))
        return quote(home / "bin/cicada-hook") + " cursor"
    return quote(sys.executable) + " " + quote(Path(__file__).absolute().with_name("cursor.py"))


def load(path: Path):
    try:
        if path.is_symlink() or path.absolute().parent != path.parent.resolve():
            raise RegistryError("Cursor config has a symlink parent/file; not touching it")
        if not path.exists():
            return {}
        if path.stat().st_size > MAX_BYTES:
            raise RegistryError("Cursor config exceeds 256KB; not touching it")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or ("version" in data and data["version"] != 1):
            raise RegistryError("Cursor hooks config must be a version1 object; not touching it")
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict) or any(not isinstance(v, list) for v in hooks.values()):
            raise RegistryError("Cursor hooks must contain event arrays; not touching it")
        return data
    except (OSError, ValueError) as exc:
        raise RegistryError("Cursor hooks config cannot be read as JSON; repair it before retrying") from exc


def install(path: Path, *, command: str, hook: str = "startup"):
    if not _ours({"command": command}):
        raise RegistryError("Only Cicada's Cursor hook command may be installed")
    data = load(path)
    hooks = data.setdefault("hooks", {})
    present, had = True, False
    for event, timeout in HOOKS[hook].items():
        entries = hooks.get(event, [])
        ours = [e for e in entries if _ours(e)]
        desired = {"command": command, "timeout": timeout}
        had = had or bool(ours)
        if ours == [desired]:
            continue
        present = False
        hooks[event] = [e for e in entries if not _ours(e)] + [desired]
    if present and data.get("version") == 1:
        return "present"
    data["version"] = 1
    _save(path, data)
    return "updated" if had else "added"


def uninstall(path: Path, *, hook: str | None = None):
    data = load(path)
    hooks = data.get("hooks", {})
    events = set(HOOKS[hook]) if hook else None
    count = 0
    for event, entries in list(hooks.items()):
        if events is not None and event not in events:
            continue
        keep = [e for e in entries if not _ours(e)]
        count += len(entries) - len(keep)
        if keep:
            hooks[event] = keep
        elif entries:
            del hooks[event]
    if count:
        if not hooks:
            data.pop("hooks", None)
        _save(path, data)
    return count


def status(path: Path, *, command: str, hook: str = "startup"):
    try:
        data = load(path)
    except RegistryError:
        return "invalid"
    states = set()
    for event, timeout in HOOKS[hook].items():
        ours = [e for e in data.get("hooks", {}).get(event, []) if _ours(e)]
        states.add("absent" if not ours else "present" if ours == [{"command": command, "timeout": timeout}]
                   else "stale")
    return states.pop() if len(states) == 1 else "stale"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("install", "uninstall", "status"))
    parser.add_argument("--settings", required=True)
    parser.add_argument("--command", default=default_command())
    parser.add_argument("--hook", choices=tuple(HOOKS), default=None,
                        help="startup (sessionStart) or capture (prompt + reply); "
                             "install/status default to startup, uninstall without it removes both")
    args = parser.parse_args(argv)
    path = Path(args.settings).expanduser()
    try:
        if args.action == "install":
            print(install(path, command=args.command, hook=args.hook or "startup")); return 0
        if args.action == "uninstall":
            print(f"removed {uninstall(path, hook=args.hook)} Cicada hook(s)"); return 0
        state = status(path, command=args.command, hook=args.hook or "startup")
        print(state)
        return {"present": 0, "absent": 1, "stale": 2, "invalid": 3}[state]
    except RegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
