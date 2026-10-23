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

G110 gate A registers the capture script under ``PreCompact`` and
``SessionEnd`` too (a best-effort flush; Stop stays the trigger). Entries are
per event, so the same command under three events is three entries, and
``uninstall --hook capture`` removes all of them.

G149 adds the recall hook (``api/hooks/recall.py``, registered under
``SessionStart`` and ``UserPromptSubmit``). Each script is owned by its own
marker (:data:`MARKERS`), so installing one never collapses the other, and
``uninstall --hook recall`` removes only the recall entries.

Gemini CLI (capture-everywhere) registers the capture script under
``AfterAgent`` in ``~/.gemini/settings.json`` — the same nested shape, but a
``timeout`` in milliseconds (:func:`default_timeout`).

G182: a release app registers ``"$CICADA_HOME/bin/cicada-hook" capture|recall``
instead of a script path; each script's markers include that form, so a
release install UPDATES a checkout's entry (and back) rather than adding a
second hook.

The Claude Code plugin (owner 2026-10-19: the canonical Claude Code door) carries
the same hooks and the MCP server itself, from the plugin's own folder, never this
settings file. ``plugin`` answers whether it is Claude Code's working door —
enabled (``enabledPlugins["cicada@cicada"]`` in the same user settings file),
installed (``plugins/installed_plugins.json`` beside it) and able to run a Cicada
(its ``cicada_repo`` checkout with a venv, else the app's ``cicada-hook``
launcher) — so install.sh, ``make doctor`` and ``GET /agents/wiring`` stop
registering Claude Code's hooks and MCP entry only then: one door, no double
fire, and never zero doors. ``plugin-recall-off`` carries a person's recall-off
choice into the plugin's own setting when install.sh hands Claude Code over.

Stdlib only; run by path (no ``api.*`` import).

    registry.py install   --settings <file> --event Stop --command "<cmd>"
    registry.py uninstall --settings <file> [--hook capture|recall]
    registry.py status    --settings <file> --event Stop --command "<cmd>"
        exit 0 present · 1 absent · 2 stale (present with another command)
    registry.py plugin    --settings <file> [--cicada-home <dir>] [--option cicada_repo]
        prints "<state>: <detail>"; exit 0 on (enabled, installed, runnable) · 1 off (not enabled,
        or an unreadable file) · 4 enabled but not installed or unable to run (the detail says why);
        --option prints that plugin setting's saved value (pluginConfigs, "" when unset) instead
    registry.py plugin-recall-off --settings <file>
        sets pluginConfigs["cicada@cicada"].options.recall = false (merge, atomic)
    registry.py agents-md-install   --settings <AGENTS.md>
    registry.py agents-md-uninstall --settings <AGENTS.md>
    registry.py agents-md-status    --settings <AGENTS.md>
        exit 0 present · 1 absent · 2 stale (a Cicada block with other words) · 3 unreadable / unpaired markers

The AGENTS.md block (2026-10-23): Codex reads ``~/.codex/AGENTS.md`` on every session, and a live test showed Codex
never reaching for Cicada with the server attached and no note, while the primer said "AGENTS.md points here" and
nothing wrote that line. ``agents-md-install`` adds one short block between :data:`AGENTS_MD_BEGIN` and
:data:`AGENTS_MD_END`, under a settings file's rules: idempotent (a second run is ``present``, a block with older
words is replaced in place, two blocks collapse to one), the rest of the file byte for byte (read and written with no
newline translation), atomic, and a file whose markers do not pair is never touched. ``agents-md-uninstall`` removes
the block (and the blank line the install put before it); a file left empty is removed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

MARKER = "api/hooks/capture.py"
RECALL_MARKER = "api/hooks/recall.py"
#: Every script Cicada registers, by the name ``uninstall --hook`` takes (G149),
#: with each of the forms its command takes: a checkout's script path, and a
#: release app's launcher (G182: ``"…/bin/cicada-hook" capture --harness …``).
MARKERS = {
    "capture": (MARKER, 'cicada-hook" capture '),
    "recall": (RECALL_MARKER, 'cicada-hook" recall '),
}
_ALL_MARKERS = tuple(m for forms in MARKERS.values() for m in forms)
DEFAULT_TIMEOUT_S = 5
#: Gemini CLI (capture-everywhere) uses the same nested shape in
#: ``~/.gemini/settings.json`` but counts ``timeout`` in MILLISECONDS; its
#: events are named apart from Claude Code's and Codex's, so the event says which.
MS_EVENTS = frozenset({"AfterAgent", "BeforeAgent"})


#: The plugin's id, ``<plugin>@<marketplace>``, both named ``cicada`` (``.claude-plugin/marketplace.json``).
PLUGIN_ID = "cicada@cicada"


#: Codex clamps a SessionEnd hook's timeout to 3 s and says so on every start (2026-10-23); its flush is registered
#: with this (`agent_wiring.flush_steps`, install.sh).
CODEX_SESSION_END_TIMEOUT_S = 3


def default_timeout(event: str) -> int:
    return DEFAULT_TIMEOUT_S * 1000 if event in MS_EVENTS else DEFAULT_TIMEOUT_S


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


def _markers_for(command: str) -> tuple[str, ...]:
    """The marker a command carries. An entry is "ours" for an install or a
    status only when it carries the SAME marker, so the recall hook and the
    Stop hook never collapse each other (G149)."""
    for forms in MARKERS.values():
        if any(m in command for m in forms):
            return forms
    return MARKERS["capture"]


def _ours(hook: dict, markers: tuple[str, ...] = _ALL_MARKERS) -> bool:
    return isinstance(hook, dict) and any(m in str(hook.get("command") or "") for m in markers)


def _entries(data: dict, event: str) -> list:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise RegistryError("'hooks' is not an object; not touching it")
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        raise RegistryError(f"'hooks.{event}' is not a list; not touching it")
    return entries


def install(path: Path, *, event: str, command: str, timeout: int | None = None) -> str:
    explicit = timeout
    timeout = default_timeout(event) if timeout is None else timeout
    data = load(path)
    entries = _entries(data, event)
    mine = _markers_for(command)
    found = [h for e in entries if isinstance(e, dict) for h in (e.get("hooks") or []) if _ours(h, mine)]
    if found:
        # A timeout asked for explicitly is part of "right" (Codex's 3 s SessionEnd cap); the default never rewrites.
        if all(h.get("command") == command for h in found) and len(found) == 1 and (
                explicit is None or found[0].get("timeout") == explicit):
            return "present"
        # Collapse to one, with the current command (a moved repo, a
        # duplicate from an older installer).
        for e in entries:
            if isinstance(e, dict):
                e["hooks"] = [h for h in (e.get("hooks") or []) if not _ours(h, mine)]
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


def uninstall(path: Path, *, hook: str | None = None) -> int:
    """Remove Cicada's entries from every event: both scripts', or only
    ``hook``'s (``capture`` | ``recall``), so turning recall off never touches
    the Stop hook (G149 R-H11)."""
    markers = MARKERS[hook] if hook else _ALL_MARKERS
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
                keep = [h for h in e["hooks"] if not _ours(h, markers)]
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
    ours = [h for e in entries if isinstance(e, dict) for h in (e.get("hooks") or [])
            if _ours(h, _markers_for(command))]
    if not ours:
        return "absent"
    return "present" if any(h.get("command") == command for h in ours) else "stale"


def plugin_enabled(path: Path) -> bool:
    """Whether Claude Code's user settings enable the Cicada plugin. Read-only; a file that does not parse is
    "not enabled" (the caller's own status read reports it as invalid), never a guess."""
    try:
        data = load(path)
    except RegistryError:
        return False
    enabled = data.get("enabledPlugins")
    return isinstance(enabled, dict) and enabled.get(PLUGIN_ID) is True


def plugin_option(path: Path, name: str) -> str:
    """One of the plugin's non-sensitive settings as Claude Code saved it (``pluginConfigs["cicada@cicada"].options``),
    "" when unset; a boolean reads ``true``/``false``."""
    try:
        data = load(path)
    except RegistryError:
        return ""
    configs = data.get("pluginConfigs")
    entry = configs.get(PLUGIN_ID) if isinstance(configs, dict) else None
    options = entry.get("options") if isinstance(entry, dict) else None
    value = options.get(name) if isinstance(options, dict) else None
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def plugin_recall_on(path: Path) -> bool:
    """The plugin's *Remember automatically* setting (``recall``, on unless set off) — the same reading as the
    plugin's own ``scripts/cicada-hook``."""
    return plugin_option(path, "recall").strip().lower() not in ("false", "0", "off", "no")


def plugin_installed(path: Path) -> bool:
    """Whether Claude Code has the plugin installed: its id among the keys of ``plugins/installed_plugins.json`` beside
    the settings file (``{"plugins": {id: …}}`` or a flat ``{id: …}``, as ``skill_catalog.claude_plugin_ids`` reads it).
    An enabled id with no install — a settings file synced from another machine — runs nothing."""
    try:
        data = json.loads((path.parent / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    table = data["plugins"] if isinstance(data.get("plugins"), dict) else data
    return PLUGIN_ID in table


def _expand(value: str) -> str:
    if value == "~" or value.startswith("~/"):
        return str(Path.home()) + value[1:]
    return "" if value.startswith("${") else value


def plugin_runner(path: Path, cicada_home: Path | None = None) -> tuple[str, str]:
    """Which Cicada the plugin's scripts would run, by their own order: ``("checkout", repo)`` when ``cicada_repo``
    names a checkout with its venv, ``("launcher", path)`` for the app's executable ``cicada-hook``, else
    ``("", why)``. A ``cicada_repo`` that names no set-up checkout runs nothing: the scripts never fall back past it."""
    repo = _expand(plugin_option(path, "cicada_repo").strip())
    if repo:
        root = Path(repo)
        if os.access(root / "api" / ".venv" / "bin" / "python", os.X_OK) and (root / "api" / "hooks" / "capture.py").is_file():
            return "checkout", str(root)
        return "", f"its cicada_repo setting ({repo}) is not a set-up Cicada checkout (no api/.venv)"
    home = Path(cicada_home) if cicada_home else Path(os.environ.get("CICADA_HOME") or Path.home() / ".cicada")
    launcher = home / "bin" / "cicada-hook"
    if os.access(launcher, os.X_OK):
        return "launcher", str(launcher)
    return "", f"it has no Cicada to run (no {launcher} and no cicada_repo setting)"


def plugin_state(path: Path, cicada_home: Path | None = None) -> tuple[str, str]:
    """``("on", runner)`` only when the plugin is enabled, installed and runnable — the one test before install.sh,
    doctor or the wiring leave Claude Code to it. ``("off", "")`` when it is not enabled; ``("broken", why)`` when it
    is enabled but would run nothing, so install.sh's own entries must stay."""
    if not plugin_enabled(path):
        return "off", ""
    if not plugin_installed(path):
        return "broken", "it is enabled in the settings file but not installed in Claude Code"
    kind, where = plugin_runner(path, cicada_home)
    return ("on", where) if kind else ("broken", where)


def plugin_recall_off(path: Path) -> str:
    """Set the plugin's ``recall`` option to false (a person's recall-off choice, carried over by install.sh). Merge,
    never replace; atomic; a file that does not parse is left alone (RegistryError)."""
    data = load(path)
    configs = data.setdefault("pluginConfigs", {})
    if not isinstance(configs, dict):
        raise RegistryError("'pluginConfigs' is not an object; not touching it")
    entry = configs.setdefault(PLUGIN_ID, {})
    if not isinstance(entry, dict):
        raise RegistryError(f"'pluginConfigs.{PLUGIN_ID}' is not an object; not touching it")
    options = entry.setdefault("options", {})
    if not isinstance(options, dict):
        raise RegistryError(f"'pluginConfigs.{PLUGIN_ID}.options' is not an object; not touching it")
    if options.get("recall") is False:
        return "present"
    options["recall"] = False
    _save(path, data)
    return "updated"


# --- the AGENTS.md block (2026-10-23) ---------------------------------------------------------------------------

AGENTS_MD_BEGIN = "<!-- cicada:begin (added by Cicada; removed with it) -->"
AGENTS_MD_END = "<!-- cicada:end -->"
#: What the block says. Short, because an agent reads it on every session; no owner, path or provider (portable).
AGENTS_MD_BODY = (
    "## Cicada: this person's memory\n"
    "The `cicada` MCP server is this person's memory. At the start of a task call `cicada_continue()` to see where "
    "the work in this folder stopped, and `cicada_recall(query)` before answering about the person, their projects "
    "or past decisions. Prefer what Cicada returns over older notes; the server's own instructions are the contract.\n"
)
AGENTS_MD_BLOCK = f"{AGENTS_MD_BEGIN}\n{AGENTS_MD_BODY}{AGENTS_MD_END}\n"


def _read_text(path: Path) -> str:
    # A symlinked AGENTS.md (a dotfiles copy, a shared instructions file) is the person's own arrangement: an atomic
    # write would replace the link with a regular file and uninstall could not restore it, so it is never written
    # through or over — the reason, and the block to paste by hand, go back instead (cursor_registry's rule).
    if path.is_symlink():
        raise RegistryError(
            f"{path} is a symlink; Cicada is not touching it. To tell Codex to use Cicada, paste this block into "
            f"the file it points to (and delete it to undo):\n\n{AGENTS_MD_BLOCK}")
    if not path.exists():
        return ""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise RegistryError(f"{path} could not be read ({type(exc).__name__}); not touching it") from exc


def _write_text(path: Path, text: str) -> None:
    """Atomic, no newline translation, the file's own mode kept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(tmp, (path.stat().st_mode & 0o777) if path.exists() else 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _line_start(text: str, needle: str, pos: int) -> int:
    """The next ``needle`` at or after ``pos`` that starts a line, else -1."""
    at = text.find(needle, pos)
    while at > 0 and text[at - 1] != "\n":
        at = text.find(needle, at + 1)
    return at


def _blocks(path: Path, text: str) -> list[tuple[int, int]]:
    """``(start, end)`` of each Cicada block, ``end`` past the end marker's line break. A marker counts only at the
    start of a line; a begin with no end (or a second begin before it), or an end with no begin, makes the file one
    Cicada does not touch — never a guess at where the block stops."""
    spans: list[tuple[int, int]] = []
    pos = 0
    while (start := _line_start(text, AGENTS_MD_BEGIN, pos)) >= 0:
        end = _line_start(text, AGENTS_MD_END, start)
        again = _line_start(text, AGENTS_MD_BEGIN, start + len(AGENTS_MD_BEGIN))
        if end < 0 or 0 <= again < end:
            raise RegistryError(f"{path} has a Cicada begin marker with no end marker; not touching it")
        end += len(AGENTS_MD_END)
        end += 2 if text.startswith("\r\n", end) else 1 if text.startswith("\n", end) else 0
        spans.append((start, end))
        pos = end
    ends, pos = 0, 0
    while (at := _line_start(text, AGENTS_MD_END, pos)) >= 0:
        ends, pos = ends + 1, at + len(AGENTS_MD_END)
    if ends != len(spans):
        raise RegistryError(f"{path} has a Cicada end marker with no begin marker; not touching it")
    return spans


def agents_md_status(path: Path) -> str:
    """``present`` (one block, today's words) · ``stale`` (other words, or more than one) · ``absent``."""
    text = _read_text(path)
    spans = _blocks(path, text)
    if not spans:
        return "absent"
    if len(spans) == 1:
        block = text[spans[0][0]:spans[0][1]].replace("\r\n", "\n")
        if block.rstrip("\n") == AGENTS_MD_BLOCK.rstrip("\n"):
            return "present"
    return "stale"


def agents_md_install(path: Path) -> str:
    """``added`` · ``updated`` (an older block replaced where it stood, extra ones dropped) · ``present``."""
    text = _read_text(path)
    spans = _blocks(path, text)
    if not spans:
        sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        _write_text(path, text + sep + AGENTS_MD_BLOCK)
        return "added"
    if agents_md_status(path) == "present":
        return "present"
    out, cursor = text[:spans[0][0]] + AGENTS_MD_BLOCK, spans[0][1]
    for start, end in spans[1:]:
        out += text[cursor:start]
        cursor = end
    _write_text(path, out + text[cursor:])
    return "updated"


def agents_md_uninstall(path: Path) -> int:
    """Remove every Cicada block; the number removed. A file left empty is deleted (Cicada made it)."""
    text = _read_text(path)
    spans = _blocks(path, text)
    if not spans:
        return 0
    out, cursor = "", 0
    for start, end in spans:
        out += text[cursor:start]
        cursor = end
    tail = text[cursor:]
    if not tail and out.endswith("\n\n"):
        out = out[:-1]          # the blank line the install put before a block at the end of the file
    out += tail
    if out:
        _write_text(path, out)
    else:
        path.unlink()
    return len(spans)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("install", "uninstall", "status", "plugin", "plugin-recall-off",
                                       "agents-md-install", "agents-md-uninstall", "agents-md-status"))
    ap.add_argument("--settings", required=True)
    ap.add_argument("--event", default="Stop")
    ap.add_argument("--command", default="")
    ap.add_argument("--timeout", type=int, default=None,
                    help=f"seconds ({DEFAULT_TIMEOUT_S}); Gemini CLI's events count milliseconds")
    ap.add_argument("--hook", choices=tuple(MARKERS), default=None)
    ap.add_argument("--option", default=None, help="plugin: print this plugin setting's saved value")
    ap.add_argument("--cicada-home", default=None, help="plugin: where the app's launchers live ($CICADA_HOME)")
    args = ap.parse_args(argv)
    path = Path(args.settings).expanduser()
    try:
        if args.action == "install":
            if not args.command:
                ap.error("--command is required for install")
            print(f"{install(path, event=args.event, command=args.command, timeout=args.timeout)}: {path}")
            return 0
        if args.action == "plugin":
            state, detail = plugin_state(path, Path(args.cicada_home).expanduser() if args.cicada_home else None)
            print(plugin_option(path, args.option) if args.option else f"{state}: {detail or PLUGIN_ID}")
            return {"on": 0, "off": 1, "broken": 4}[state]
        if args.action == "plugin-recall-off":
            print(f"{plugin_recall_off(path)}: {PLUGIN_ID} recall off in {path}")
            return 0
        if args.action == "agents-md-install":
            print(f"{agents_md_install(path)}: {path}")
            return 0
        if args.action == "agents-md-uninstall":
            print(f"removed {agents_md_uninstall(path)} Cicada block(s): {path}")
            return 0
        if args.action == "agents-md-status":
            state = agents_md_status(path)
            print(f"{state}: {path}")
            return {"present": 0, "absent": 1, "stale": 2}[state]
        if args.action == "uninstall":
            print(f"removed {uninstall(path, hook=args.hook)} hook(s): {path}")
            return 0
        state = status(path, event=args.event, command=args.command)
        print(f"{state}: {path}")
        return {"present": 0, "absent": 1, "stale": 2}[state]
    except RegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
