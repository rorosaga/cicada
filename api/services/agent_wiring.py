"""Read-only: is each agent CLI wired to Cicada? (Track I T3 — design §9.3)

``GET /agents/wiring`` answers two questions per harness — does it *recall* (the
MCP server is registered) and does it *auto-save* (the G105 Stop hook is in its
settings file) — and hands back the exact commands that would wire it, as argv
lists the APP runs after the person's click (spec decision 14, D-1). The backend
never runs them and never writes a harness root: a bearer-authenticated endpoint
that installed a command running on every agent turn would widen the backend's
blast radius (design §1, the rejected ``POST /agents/{id}/enable``).

Computed per request, never persisted (the ``sleep.next_at`` pattern). Each CLI
probe gets 2 s; a timeout is ``unknown``, never ``off`` (verified 2026-09-23:
``claude mcp get`` health-checks the server, ~1.3 s when registered). The only
``~/.claude`` read is ``settings.json`` through ``api/hooks/registry.py`` —
``~/.claude/projects`` is never opened (CLAUDE.md, transcripts rail).

G149 adds *auto-recall*: the SessionStart + UserPromptSubmit recall hooks' state
and argv (``autorecall``, ``autorecall_on``, ``autorecall_off``), kept apart from
``connect``, which onboarding runs, so turning recall on stays its own click
(R-H11).
"""
from __future__ import annotations

import asyncio
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from api.hooks import registry as hook_registry
from api.services.connections import base

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_TIMEOUT_S = 2.0

Runner = Callable[..., Awaitable[base.CliResult]]


@dataclass(frozen=True)
class Harness:
    id: str
    binary: str
    settings: str             # relative to HOME
    probe: tuple[str, ...]    # exit 0 = registered (verified on the installed CLIs)
    scope: tuple[str, ...]
    config_touch: str


HARNESSES = (
    Harness("claude-code", "claude", ".claude/settings.json", ("mcp", "get", "cicada"),
            ("--scope", "user"), "~/.claude.json"),
    Harness("codex", "codex", ".codex/hooks.json", ("mcp", "get", "cicada", "--json"),
            (), "~/.codex/config.toml"),
)


def venv_python(repo: Path = REPO_ROOT) -> str:
    """install.sh's ``VENV_PY`` (``$API_DIR/.venv/bin/python``), spelled the same
    way, so the hook command below is byte-identical to the one install.sh
    registered — a ``sys.executable`` spelled differently would make
    ``registry.status`` read every correct install as ``stale`` (R-IA15)."""
    candidate = repo / "api" / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def hook_command(python: str, repo: Path, harness: str) -> str:
    """``install.sh:55``'s ``hook_command``, character for character."""
    return f'"{python}" "{repo}/api/hooks/capture.py" --harness {harness}'


def _step(step: str, argv: list[str], touches: list[str]) -> dict:
    return {"step": step, "display": shlex.join(argv), "argv": argv, "touches": touches}


def _autosave(path: Path, command: str) -> str:
    try:
        hook_registry.load(path)
    except hook_registry.RegistryError:
        return "invalid"
    state = hook_registry.status(path, event="Stop", command=command)
    return {"present": "on", "absent": "off", "stale": "stale"}[state]


RECALL_EVENTS = ("SessionStart", "UserPromptSubmit")


def recall_hook_command(python: str, repo: Path, harness: str) -> str:
    """install.sh's ``recall_command``, character for character (G149), for the
    same reason this module's ``hook_command`` mirrors install.sh's
    ``hook_command``: ``registry.status`` compares bytes (R-IA15)."""
    return f'"{python}" "{repo}/api/hooks/recall.py" --harness {harness}'


def autorecall_argv(h: Harness, *, home: Path, repo: Path, python: str) -> dict[str, list[dict]]:
    """Both of the recall hook's command sets for one harness, whatever its
    state. ``on`` registers SessionStart and UserPromptSubmit; it is idempotent
    (``install`` answers ``present`` for an event already right, and updates a
    stale one). ``off`` removes Cicada's recall entries and nothing else
    (``--hook recall``): the Stop hook stays."""
    settings = str(home / h.settings)
    registry = str(repo / "api" / "hooks" / "registry.py")
    command = recall_hook_command(python, repo, h.id)
    touches = [f"~/{h.settings}"]
    return {
        "on": [_step("autorecall", [python, registry, "install", "--settings", settings, "--event", event,
                                    "--command", command], touches) for event in RECALL_EVENTS],
        "off": [_step("autorecall-off", [python, registry, "uninstall", "--settings", settings, "--hook", "recall"],
                      touches)],
    }


def _autorecall(path: Path, command: str) -> str:
    try:
        hook_registry.load(path)
    except hook_registry.RegistryError:
        return "invalid"
    states = {hook_registry.status(path, event=event, command=command) for event in RECALL_EVENTS}
    return "on" if states == {"present"} else "off" if states == {"absent"} else "stale"


def autorecall_fields(h: Harness, *, home: Path, repo: Path, python: str) -> dict:
    """``GET /agents/wiring``'s G149 half for one installed harness. It is
    additive: ``connect`` (what onboarding and the C5 setup prompt run) is
    untouched, so turning recall on stays its own click (R-H11). A half
    registered or moved hook is ``stale`` and offers both lists; an unparseable
    file offers nothing."""
    state = _autorecall(home / h.settings, recall_hook_command(python, repo, h.id))
    argv = autorecall_argv(h, home=home, repo=repo, python=python)
    return {"autorecall": state,
            "autorecall_on": argv["on"] if state in ("off", "stale") else [],
            "autorecall_off": argv["off"] if state in ("on", "stale") else []}


async def _harness(h: Harness, *, home: Path, memory_root: Path, repo: Path, python: str,
                   runner: Runner, resolve) -> dict:
    binary = resolve(h.binary)
    if binary is None:
        return {"id": h.id, "installed": False, "binary": None, "recall": "off",
                "autosave": "n/a", "connect": [], "detail": None}
    result = await runner([binary, *h.probe], timeout=PROBE_TIMEOUT_S)
    recall = "on" if result.rc == 0 else ("unknown" if result.rc in (124, 127) else "off")
    settings_path = home / h.settings
    command = hook_command(python, repo, h.id)
    autosave = _autosave(settings_path, command)
    connect: list[dict] = []
    if recall == "off":
        connect.append(_step("mcp", [binary, "mcp", "add", "cicada", *h.scope, "--env",
                                     f"CICADA_MEMORY_PATH={memory_root}", "--", python,
                                     str(repo / "mcp" / "server.py")], [h.config_touch]))
    if autosave in ("off", "stale"):
        connect.append(_step("hook", [python, str(repo / "api" / "hooks" / "registry.py"), "install",
                                      "--settings", str(settings_path), "--event", "Stop",
                                      "--command", command], [f"~/{h.settings}"]))
    detail = None
    if autosave == "invalid":
        detail = f"~/{h.settings} isn't valid JSON, so Cicada won't touch it."
    elif recall == "unknown":
        detail = "Couldn't check in time. Try again."
    return {"id": h.id, "installed": True, "binary": binary, "recall": recall,
            "autosave": autosave, "connect": connect, "detail": detail}


def _gemini_cli(home: Path, resolve) -> dict:
    """Read-only until its CLI registration is verified (R-IA15)."""
    binary = resolve("gemini")
    if binary is None:
        return {"id": "gemini-cli", "installed": False, "binary": None, "recall": "off",
                "autosave": "n/a", "connect": [], "detail": None}
    path = home / ".gemini" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        recall = "on" if isinstance(servers, dict) and "cicada" in servers else "off"
    except (OSError, ValueError):
        recall = "unknown"
    return {"id": "gemini-cli", "installed": True, "binary": binary, "recall": recall,
            "autosave": "n/a", "connect": [], "detail": None}


async def probe(*, home: Path, memory_root: Path, repo: Path = REPO_ROOT, python: str | None = None,
                runner: Runner | None = None, resolve=base.resolve_binary) -> dict:
    python = python or venv_python(repo)
    runner = runner or base.run_cli
    rows = await asyncio.gather(*(
        _harness(h, home=home, memory_root=memory_root, repo=repo, python=python, runner=runner, resolve=resolve)
        for h in HARNESSES))
    # G149, additive: each installed harness row gains its recall hooks' state
    # and argv; a harness that is not installed keeps the schema's "n/a".
    by_id = {h.id: h for h in HARNESSES}
    rows = [{**row, **autorecall_fields(by_id[row["id"]], home=home, repo=repo, python=python)}
            if row["installed"] else row for row in rows]
    return {"agents": [*rows, _gemini_cli(home, resolve)], "python": python,
            "repo": str(repo), "memory": str(memory_root)}
