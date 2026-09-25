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
performs. Round 4 C8 adds two more shapes. OpenCode, Hermes and OpenClaw get a
prompt with no commands (``argv: []``) that names the server and where it lives
in the agent's own settings, so the agent writes the entry itself — their CLIs'
registration flags could not be verified, and a wrong argv the app runs is worse
than a prompt an agent reads (R-AG3). Claude (on the web), ChatGPT and Grok get
``kind: "remote"``: the two steps before Confirm on the G135 connector, worded
here so Settings and onboarding read one source (R-AG19). No probe, no
subprocess, no harness file read.

The config reads behind ``recall`` for the agents with no verified CLI probe
(R-AG4) open ONE file each — the agent's own MCP config — parse-only, at most
256 KB, never written, and only ``on | off | unknown`` leaves the function
(those files can hold other servers' secrets). None of them is under
``~/Library`` (the app's alone) or Claude Code's ``~/.claude.json`` (its state
file, not a config Cicada owns); the ``~/.claude`` sentence above stays true.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote

import yaml

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


# --- Round 4 C8 (R-AG4): an agent's own MCP config, read to say whether it names Cicada ---

CONFIG_MAX_BYTES = 256 * 1024


@dataclass(frozen=True)
class ConfigProbe:
    """Where one agent keeps its MCP servers. ``files`` are HOME-relative and
    the first that exists wins; ``key`` is the dict path to Cicada's entry.
    Parse-only and bounded: a config file is never written here (the backend
    never writes a harness root, design §1) and a huge one is ``unknown``."""
    files: tuple[str, ...]
    key: tuple[str, ...]


CONFIG_PROBES: dict[str, ConfigProbe] = {
    "gemini-cli": ConfigProbe((GEMINI_SETTINGS,), ("mcpServers", "cicada")),
    "opencode": ConfigProbe((".config/opencode/opencode.json", ".config/opencode/opencode.jsonc"), ("mcp", "cicada")),
    "hermes": ConfigProbe((".hermes/config.yaml",), ("mcp_servers", "cicada")),
    "openclaw": ConfigProbe((".openclaw/openclaw.json",), ("mcp", "servers", "cicada")),
    "cursor": ConfigProbe((".cursor/mcp.json",), ("mcpServers", "cicada")),
    "codex": ConfigProbe((".codex/config.toml",), ("mcp_servers", "cicada")),
}


def _loads_jsonc(text: str):
    """OpenCode accepts JSON with comments and trailing commas (``opencode.jsonc``).
    Comments are dropped outside strings only, so ``"http://x"`` survives."""
    out: list[str] = []
    i, n, in_string = 0, len(text), False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            in_string = ch != '"'
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(ch)
            i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def _parse_config(path: Path):
    """One reader per format. Every ``.json``/``.jsonc`` goes through the
    comment- and trailing-comma-tolerant reader: OpenClaw's ``openclaw.json``
    is written as JSON5 and Cursor's ``mcp.json`` as JSONC by hand, and strict
    JSON is a subset, so a commented file reads ``on``/``off`` rather than a
    false ``unknown``. (Unquoted keys or single quotes still fail → ``unknown``.)"""
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    if path.suffix == ".toml":
        return tomllib.loads(text)
    return _loads_jsonc(text)


def config_state(agent_id: str, home: Path) -> str:
    """``on`` when the agent's own config names Cicada, ``off`` when it does not
    (or there is no file), ``unknown`` when it cannot be read — never ``off``
    for a file Cicada failed to parse (R-IA15's rule for ``recall``)."""
    probe = CONFIG_PROBES[agent_id]
    path = next((home / rel for rel in probe.files if (home / rel).is_file()), None)
    if path is None:
        return "off"
    try:
        if path.stat().st_size > CONFIG_MAX_BYTES:
            return "unknown"
        node = _parse_config(path)
    except (OSError, ValueError, yaml.YAMLError):
        return "unknown"
    for part in probe.key:
        if not isinstance(node, dict) or part not in node:
            return "off"
        node = node[part]
    return "on"


def stop_hook_state(home: Path, python: str, repo: Path, harness: str = "claude-code") -> str:
    """The G105 Stop hook's state in the harness's own settings file — Claude
    Code's only config signal, because its MCP registration lives in
    ``~/.claude.json``, which Cicada never opens (R-AG4)."""
    h = next(h for h in HARNESSES if h.id == harness)
    return _autosave(home / h.settings, hook_command(python, repo, h.id))


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


# Round 4 C8 (R-AG3): agents that write Cicada into their own settings.
CONFIG_SETUPS: dict[str, tuple[str, str, str, str]] = {
    # id: (product, where the entry lives, its key, what to do after)
    "opencode": ("OpenCode", "~/.config/opencode/opencode.json", "mcp.cicada",
                 "Once it's done, start a new OpenCode session so it can see your memory."),
    "hermes": ("Hermes", "~/.hermes/config.yaml", "mcp_servers.cicada",
               "Once it's done, run /reload-mcp in Hermes or start a new session."),
    "openclaw": ("OpenClaw", "~/.openclaw/openclaw.json", "mcp.servers.cicada",
                 "OpenClaw picks the change up on its own."),
}


def config_value(agent_id: str, spec: dict) -> dict:
    """The entry in the agent's own shape. OpenCode's local server is a
    ``command`` array with ``environment`` (its docs); Hermes and OpenClaw take
    the same ``command``/``args``/``env`` object Cursor and Claude do."""
    if agent_id == "opencode":
        return {"type": "local", "command": [spec["command"], *spec["args"]],
                "environment": dict(spec["env"]), "enabled": True}
    return spec


def config_prompt(product: str, where: str, key: str, spec: dict) -> str:
    """C5's promises, for an agent that edits a file instead of running a
    command: what to add, where, change nothing else, nothing is uploaded."""
    memory = spec["env"]["CICADA_MEMORY_PATH"]
    return (f"Please connect Cicada, the memory app on this Mac, to {product}. Add one MCP server named cicada "
            f"to your own settings — {where}, at {key} — and change nothing else. It runs:\n\n"
            f"command: {spec['command']}\nargument: {spec['args'][0]}\nenvironment: CICADA_MEMORY_PATH={memory}\n\n"
            "It lets you read and add to my memory. If Cicada is already there, that's fine. This uploads nothing: "
            "my memory stays on this computer. Then tell me in one sentence whether it worked.")


# Round 4 C8 (R-AG19): cloud agents reach this Mac only through the G135 connector.
# From anywhere is its own Settings row (Customize: Integrations · Agents · From anywhere, G139), not a part of
# Agents — the step names the row the person will actually find.
REACH_STEP = ("In Cicada's Settings, open From anywhere and turn it on. It needs a tunnel you run, like "
              "Tailscale Funnel or ngrok.")
REMOTE_SETUPS: dict[str, tuple[str, str, str]] = {
    # id: (title, product, the link step)
    "claude": ("Connect Claude on the web", "Claude",
               "Create a link for Claude, then paste it in claude.ai → Settings → Connectors → Add custom "
               "connector, with sign-in off. It works in the Claude app on your phone too."),
    "chatgpt": ("Connect ChatGPT", "ChatGPT",
                "Create a link for ChatGPT, then in ChatGPT on the web turn on Developer mode and add an app "
                "with the link and no authentication."),
    "grok": ("Connect Grok", "Grok",
             "Create a link for Grok, then send Grok the message Cicada shows you. Grok adds the link itself."),
}


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
    if harness in CONFIG_SETUPS:
        product, where, key, note = CONFIG_SETUPS[harness]
        value = config_value(harness, spec)
        return {"harness": harness, "kind": "prompt", "title": f"Connect {product}",
                "prompt": config_prompt(product, where, key, spec), "argv": [], "display": [],
                "config": {"path": where, "key": key, "value": value}, "note": note}
    if harness in REMOTE_SETUPS:
        title, product, link_step = REMOTE_SETUPS[harness]
        return {"harness": harness, "kind": "remote", "title": title, "display": [REACH_STEP, link_step],
                "note": (f"{product} saves to your memory only when you or it asks — it has no automatic save. "
                         "It reaches this Mac while this Mac is awake and online.")}
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


CONFIG_AGENT_BINARIES = {"gemini-cli": "gemini", "opencode": "opencode", "hermes": "hermes", "openclaw": "openclaw"}


def _config_agent(agent_id: str, home: Path, resolve) -> dict:
    """Read-only until the app has verified a registration command for it
    (R-IA15, R-AG3): the row reports the agent's own config and offers nothing.
    Dict order is the row order — Gemini CLI stays where it was, the three
    round-4 agents follow it."""
    binary = resolve(CONFIG_AGENT_BINARIES[agent_id])
    if binary is None:
        return {"id": agent_id, "installed": False, "binary": None, "recall": "off",
                "autosave": "n/a", "connect": [], "detail": None}
    return {"id": agent_id, "installed": True, "binary": binary, "recall": config_state(agent_id, home),
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
    return {"agents": [*rows, *(_config_agent(a, home, resolve) for a in CONFIG_AGENT_BINARIES)], "python": python,
            "repo": str(repo), "memory": str(memory_root)}
