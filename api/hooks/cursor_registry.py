#!/usr/bin/env python3
"""Merge/uninstall ONLY Cicada's user-level Cursor startup command; stdlib.

hooks.json v1 uses flat event arrays, unlike Claude/Codex nested hook lists.
Invalid/unknown configs are untouched. No stop hook: capture is unsupported.
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


def install(path: Path, *, command: str):
    if not _ours({"command": command}):
        raise RegistryError("Only Cicada's Cursor startup command may be installed")
    data = load(path)
    hooks = data.setdefault("hooks", {})
    entries = hooks.get(EVENT, [])
    ours = [e for e in entries if _ours(e)]
    desired = {"command": command, "timeout": 2}
    if ours == [desired] and data.get("version") == 1:
        return "present"
    hooks[EVENT] = [e for e in entries if not _ours(e)] + [desired]
    data["version"] = 1
    _save(path, data)
    return "updated" if ours else "added"


def uninstall(path: Path):
    data = load(path)
    hooks = data.get("hooks", {})
    count = 0
    for event, entries in list(hooks.items()):
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


def status(path: Path, *, command: str):
    try:
        data = load(path)
    except RegistryError:
        return "invalid"
    ours = [e for e in data.get("hooks", {}).get(EVENT, []) if _ours(e)]
    if not ours:
        return "absent"
    return "present" if ours == [{"command": command, "timeout": 2}] else "stale"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("install", "uninstall", "status"))
    parser.add_argument("--settings", required=True)
    parser.add_argument("--command", default=default_command())
    args = parser.parse_args(argv)
    path = Path(args.settings).expanduser()
    try:
        if args.action == "install":
            print(install(path, command=args.command)); return 0
        if args.action == "uninstall":
            print(f"removed {uninstall(path)} Cicada hook(s)"); return 0
        state = status(path, command=args.command)
        print(state)
        return {"present": 0, "absent": 1, "stale": 2, "invalid": 3}[state]
    except RegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
