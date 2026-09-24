"""Read-only: is each agent CLI wired to Cicada? (Track I T3 — design §9.3)

``GET /agents/wiring`` answers two questions per harness — does it *recall* (the
MCP server is registered) and does it *auto-save* (the G105 Stop hook is in its
settings file) — and hands back the exact commands that would wire it, as argv
lists the APP runs after the person's click (spec decision 14, D-1). The backend
never runs them and never writes a harness root: a bearer-authenticated endpoint
that installed a command running on every agent turn would widen the backend's
blast radius (design §1, the rejected ``POST /agents/{id}/enable``).

Computed per request, never persisted (the ``sleep.next_at`` pattern). Each CLI
probe gets 6 s and they run side by side; a timeout is ``unknown``, never
``off``. That was 2 s until round 4 (R4B-12), when the live Welcome read Claude
Code as 'couldn't check in time': ``claude mcp get`` starts the server to
health-check it, ~1.3 s warm and longer cold. The only ``~/.claude`` read is
``settings.json`` through ``api/hooks/registry.py`` — ``~/.claude/projects`` is
never opened (CLAUDE.md, transcripts rail).

G149 adds *auto-recall*: the SessionStart + UserPromptSubmit recall hooks' state
and argv (``autorecall``, ``autorecall_on``, ``autorecall_off``), kept apart from
``connect``, which onboarding runs, so turning recall on stays its own click
(R-H11).

``setup`` (round 4 D5, C5; G76's in-app half) serves what to hand an agent
instead of running anything: a prompt that names exactly the commands this
module's step builders produce, Cursor's install link, or a config merge the app
performs. No probe, no subprocess, no harness file read.
"""
from __future__ import annotations

import asyncio
import base64
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote

from api.hooks import registry as hook_registry
from api.services.connections import base

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_TIMEOUT_S = 6.0

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


def mcp_step(h: Harness, binary: str, *, memory_root: Path, repo: Path, python: str) -> dict:
    """install.sh's MCP registration — the ONE argv `/agents/wiring` offers and
    `/agents/setup` names (C5: the two can never disagree)."""
    return _step("mcp", [binary, "mcp", "add", "cicada", *h.scope, "--env", f"CICADA_MEMORY_PATH={memory_root}",
                         "--", python, str(repo / "mcp" / "server.py")], [h.config_touch])


def hook_step(h: Harness, *, home: Path, repo: Path, python: str) -> dict:
    """install.sh's G105 Stop-hook registration, merged in by `registry.py`."""
    return _step("hook", [python, str(repo / "api" / "hooks" / "registry.py"), "install",
                          "--settings", str(home / h.settings), "--event", "Stop",
                          "--command", hook_command(python, repo, h.id)], [f"~/{h.settings}"])


GEMINI_SETTINGS = ".gemini/settings.json"


def gemini_mcp_step(binary: str, *, memory_root: Path, repo: Path, python: str) -> dict:
    """`gemini mcp add [options] <name> <command> [args...]` with user scope, per
    the Gemini CLI docs (checked 2026-09-24, not run). Served only inside a
    prompt the person's own agent runs; `/agents/wiring`'s row stays read-only
    until the app has verified it (R-IA15, R4B-10)."""
    return _step("mcp", [binary, "mcp", "add", "-s", "user", "-e", f"CICADA_MEMORY_PATH={memory_root}",
                         "cicada", python, str(repo / "mcp" / "server.py")], [f"~/{GEMINI_SETTINGS}"])


def server_spec(*, memory_root: Path, repo: Path, python: str) -> dict:
    """The MCP server as a config object — the shape `ConnectView.swift` already
    writes for Cursor and the Claude app."""
    return {"command": python, "args": [str(repo / "mcp" / "server.py")],
            "env": {"CICADA_MEMORY_PATH": str(memory_root)}}


CURSOR_INSTALL = "cursor://anysphere.cursor-deeplink/mcp/install"
CLAUDE_DESKTOP_CONFIG = "~/Library/Application Support/Claude/claude_desktop_config.json"
PROMPT_MAX_CHARS = 1200
_PRODUCT = {"claude-code": "Claude Code", "codex": "Codex", "gemini-cli": "Gemini CLI"}
_NEW_SESSION = "Once it's done, start a new conversation so it can see your memory."


def cursor_deeplink(spec: dict) -> str:
    """Cursor's install link: base64 of the inner server object, percent-encoded —
    the bytes the app already builds (R4B-10), so `+`/`=` survive the query."""
    raw = json.dumps(spec, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"{CURSOR_INSTALL}?name=cicada&config={quote(base64.b64encode(raw).decode('ascii'), safe='')}"


def setup_prompt(product: str, steps: list[dict]) -> str:
    """What a person pastes into an agent (C5): every command verbatim and
    numbered, nothing else numbered, a request to change nothing else, and what
    it does not do. ≈ 420 characters of prose, so the commands fit the 1,200 cap
    for a checkout path up to about 60 characters — a command is never shortened
    (R4B-11)."""
    numbered = "\n".join(f"{i}. {s['display']}" for i, s in enumerate(steps, 1))
    why = ("The first lets you read and add to my memory; the second saves our conversations into Cicada "
           "after each reply." if len(steps) > 1 else "It lets you read and add to my memory.")
    return (f"Please connect Cicada, the memory app on this Mac, to {product}. Run these commands exactly as "
            f"written, one at a time, and change nothing else:\n\n{numbered}\n\n{why} If one says Cicada is "
            "already set up, that's fine. This uploads nothing: my memory stays on this computer. Then tell me "
            "in one sentence whether it worked.")


def _prompt_setup(harness: str, steps: list[dict], note: str = _NEW_SESSION) -> dict:
    return {"harness": harness, "kind": "prompt", "title": f"Connect {_PRODUCT[harness]}",
            "prompt": setup_prompt(_PRODUCT[harness], steps), "argv": [s["argv"] for s in steps],
            "display": [s["display"] for s in steps], "note": note}


def setup(harness: str, *, home: Path, memory_root: Path, repo: Path = REPO_ROOT, python: str | None = None,
          resolve=base.resolve_binary) -> dict | None:
    """`GET /agents/setup` (C5). Both steps always for Claude Code and Codex —
    the prompt tells the agent a step already done is fine — so it never needs
    a probe; the binary is the absolute path when this process can resolve it,
    else the bare name the agent's own shell resolves. None = unknown harness."""
    python = python or venv_python(repo)
    spec = server_spec(memory_root=memory_root, repo=repo, python=python)
    known = {h.id: h for h in HARNESSES}
    if harness in known:
        h = known[harness]
        binary = resolve(h.binary) or h.binary
        return _prompt_setup(harness, [mcp_step(h, binary, memory_root=memory_root, repo=repo, python=python),
                                       hook_step(h, home=home, repo=repo, python=python)])
    if harness == "gemini-cli":
        binary = resolve("gemini") or "gemini"
        return _prompt_setup(harness, [gemini_mcp_step(binary, memory_root=memory_root, repo=repo, python=python)],
                             note="Once it's done, start a new Gemini CLI session so it can see your memory. "
                                  "Gemini CLI conversations aren't saved into Cicada on their own yet.")
    if harness == "cursor":
        return {"harness": harness, "kind": "deeplink", "title": "Connect Cursor", "deeplink": cursor_deeplink(spec),
                "note": "Cursor asks you to confirm. Then open a new chat so it can see your memory."}
    if harness == "claude-desktop":
        return {"harness": harness, "kind": "config-merge", "title": "Connect the Claude app",
                "config": {"path": CLAUDE_DESKTOP_CONFIG, "key": "mcpServers.cicada", "value": spec},
                "note": "Quit and reopen Claude so it picks Cicada up."}
    return None


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
        connect.append(mcp_step(h, binary, memory_root=memory_root, repo=repo, python=python))
    if autosave in ("off", "stale"):
        connect.append(hook_step(h, home=home, repo=repo, python=python))
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
