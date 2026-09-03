#!/usr/bin/env python3
"""Idempotent hook registration in a harness settings file (G105 R14).

``install.sh`` calls this to add Cicada's Stop hook to
``~/.claude/settings.json`` (and ``~/.codex/hooks.json``, same shape —
verified 2026-09-03), ``--uninstall`` to remove it, and ``make doctor`` to
report it. The file is the user's own configuration, so the rules are:
merge, never replace — every other key and every other hook survives; a
file that does not parse is left untouched (exit 3), never rewritten as
``{}``; writes are atomic (temp file + ``os.replace``); an entry is OURS iff
its command contains :data:`MARKER`, so re-running install after the repo
moved UPDATES the path rather than adding a second hook (portability: the
registered command embeds the venv and repo paths, both of which move with
the checkout).

Stdlib only; run by path (no ``api.*`` import).

    registry.py install   --settings <file> --event Stop --command "<cmd>"
    registry.py uninstall --settings <file>
    registry.py status    --settings <file> --event Stop --command "<cmd>"
        exit 0 present · 1 absent · 2 stale (present with another command)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

MARKER = "api/hooks/capture.py"
DEFAULT_TIMEOUT_S = 5


class RegistryError(Exception):
    pass


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except ValueError as exc:
        raise RegistryError(f"{path} is not valid JSON ({exc}); not touching it") from exc
    if not isinstance(data, dict):
        raise RegistryError(f"{path} is not a JSON object; not touching it")
    return data


def _save(path: Path, data: dict) -> None:
    """Atomic write: a crash mid-write must never leave the harness with a
    half-written settings file it refuses to start on."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ours(hook: dict) -> bool:
    return isinstance(hook, dict) and MARKER in str(hook.get("command") or "")


def _entries(data: dict, event: str) -> list:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise RegistryError("'hooks' is not an object; not touching it")
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        raise RegistryError(f"'hooks.{event}' is not a list; not touching it")
    return entries


def install(path: Path, *, event: str, command: str, timeout: int = DEFAULT_TIMEOUT_S) -> str:
    data = load(path)
    entries = _entries(data, event)
    found = [h for e in entries if isinstance(e, dict) for h in (e.get("hooks") or []) if _ours(h)]
    if found:
        if all(h.get("command") == command for h in found) and len(found) == 1:
            return "present"
        # Collapse to one, with the current command (a moved repo, a
        # duplicate from an older installer).
        for e in entries:
            if isinstance(e, dict):
                e["hooks"] = [h for h in (e.get("hooks") or []) if not _ours(h)]
        _prune(data, event)
        _entries(data, event).append({"hooks": [{"type": "command", "command": command, "timeout": timeout}]})
        _save(path, data)
        return "updated"
    entries.append({"hooks": [{"type": "command", "command": command, "timeout": timeout}]})
    _save(path, data)
    return "added"


def _prune(data: dict, event: str | None = None) -> None:
    """Drop entries whose ``hooks`` list emptied, then empty events, then an
    empty ``hooks`` key — so uninstalling the only hook leaves ``{}``, not a
    skeleton the user never wrote."""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    for ev in list(hooks.keys()) if event is None else [event]:
        entries = hooks.get(ev)
        if isinstance(entries, list):
            hooks[ev] = [e for e in entries if not (isinstance(e, dict) and not e.get("hooks"))]
            if not hooks[ev]:
                del hooks[ev]
    if not hooks:
        del data["hooks"]


def uninstall(path: Path) -> int:
    if not path.exists():
        return 0
    data = load(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("hooks"), list):
                keep = [h for h in e["hooks"] if not _ours(h)]
                removed += len(e["hooks"]) - len(keep)
                e["hooks"] = keep
    if removed:
        _prune(data)
        _save(path, data)
    return removed


def status(path: Path, *, event: str, command: str) -> str:
    try:
        data = load(path)
    except RegistryError:
        return "absent"
    entries = data.get("hooks", {}).get(event, []) if isinstance(data.get("hooks"), dict) else []
    ours = [h for e in entries if isinstance(e, dict) for h in (e.get("hooks") or []) if _ours(h)]
    if not ours:
        return "absent"
    return "present" if any(h.get("command") == command for h in ours) else "stale"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("install", "uninstall", "status"))
    ap.add_argument("--settings", required=True)
    ap.add_argument("--event", default="Stop")
    ap.add_argument("--command", default="")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    args = ap.parse_args(argv)
    path = Path(args.settings).expanduser()
    try:
        if args.action == "install":
            if not args.command:
                ap.error("--command is required for install")
            print(f"{install(path, event=args.event, command=args.command, timeout=args.timeout)}: {path}")
            return 0
        if args.action == "uninstall":
            print(f"removed {uninstall(path)} hook(s): {path}")
            return 0
        state = status(path, event=args.event, command=args.command)
        print(f"{state}: {path}")
        return {"present": 0, "absent": 1, "stale": 2}[state]
    except RegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
