"""Small local Cursor setup/status adapter: startup context and turn capture, never an engine.

Two switches in the user's ``~/.cursor/hooks.json``, one command (``api/hooks/cursor.py``):
``autorecall`` is the ``sessionStart`` startup hook, ``autosave`` the
``beforeSubmitPrompt`` + ``afterAgentResponse`` capture hooks (``turn_capture``).
``connect`` carries the capture install — the same place Claude Code's Stop hook
sits — because Cursor's MCP registration is its own install link."""
from api.hooks import cursor_registry
from api.services import runtime_layout

ID = "cursor"
EVENTS = ("session_start",)
CAPABILITIES = {"startup": "documented", "capture": "documented", "surface": "local-ide", "verification": "synthetic"}
SETTINGS = ".cursor/hooks.json"
NOTE = ("Cursor asks you to confirm MCP. Startup context and saving chats are each their own switch; "
        "then open a new local chat. Saving keeps what you type and each final reply, never files, tools or "
        "thinking. Both are built from Cursor's hook docs and not yet checked in an installed Cursor.")


def _quote(value):
    return "'" + str(value).replace("'", "'\\''") + "'"


def registry_argv(python, repo):
    if runtime_layout.is_release():
        return [runtime_layout.launcher("cicada-hook"), "cursor_registry"]
    return [python, str(repo / "api/hooks/cursor_registry.py")]


def command(python, repo):
    if runtime_layout.is_release():
        return _quote(runtime_layout.launcher("cicada-hook")) + " cursor"
    return _quote(python) + " " + _quote(repo / "api/hooks/cursor.py")


def steps(*, home, repo, python):
    from api.services.agent_wiring import _step
    prefix = registry_argv(python, repo)
    path = str(home / SETTINGS)
    touches = ["~/" + SETTINGS]
    cmd = command(python, repo)
    return {"on": [_step("autorecall", prefix + ["install", "--settings", path, "--command", cmd], touches)],
            "off": [_step("autorecall-off", prefix + ["uninstall", "--settings", path, "--hook", "startup"], touches)],
            "save_on": [_step("hook", prefix + ["install", "--settings", path, "--command", cmd, "--hook", "capture"],
                              touches)],
            "save_off": [_step("hook-off", prefix + ["uninstall", "--settings", path, "--hook", "capture"], touches)]}


MCP_CONFIG = "~/.cursor/mcp.json"
MCP_KEY = "mcpServers.cicada"


def setup(*, home, repo, python, spec):
    """The install link, plus (2026-10-14) a prompt for Cursor's own agent that
    adds the same server to ``~/.cursor/mcp.json``. The prompt adds MCP only:
    the startup and capture hooks stay their own clicks on the row, their commands
    shown first (R-H11), so a paste never registers something that runs on every chat.
    ``argv``/``display`` carry both hook installs (startup, then capture)."""
    from api.services.agent_wiring import config_prompt, cursor_deeplink
    commands = steps(home=home, repo=repo, python=python)
    on = commands["on"] + commands["save_on"]
    return {"harness": ID, "kind": "deeplink", "title": "Connect Cursor", "deeplink": cursor_deeplink(spec),
            "prompt": config_prompt("Cursor", MCP_CONFIG, MCP_KEY, spec),
            "argv": [s["argv"] for s in on], "display": [s["display"] for s in on], "note": NOTE}


def wiring(*, home, repo, python):
    from api.services.agent_wiring import config_state
    if not (home / ".cursor").is_dir():
        return {"id": ID, "installed": False, "binary": None, "recall": "off", "autosave": "n/a",
                "connect": [], "capabilities": dict(CAPABILITIES), "detail": NOTE}
    words = {"present": "on", "absent": "off", "stale": "stale", "invalid": "invalid"}
    cmd = command(python, repo)
    state = words[cursor_registry.status(home / SETTINGS, command=cmd, hook="startup")]
    save = words[cursor_registry.status(home / SETTINGS, command=cmd, hook="capture")]
    commands = steps(home=home, repo=repo, python=python)
    return {"id": ID, "installed": True, "binary": None,
            "recall": config_state(ID, home), "autosave": save,
            "connect": commands["save_on"] if save in ("off", "stale") else [], "autorecall": state,
            "autorecall_on": commands["on"] if state in ("off", "stale") else [],
            "autorecall_off": commands["off"] if state in ("on", "stale") else [],
            "autosave_off": commands["save_off"] if save in ("on", "stale") else [],
            "capabilities": dict(CAPABILITIES),
            "detail": ("~/.cursor/hooks.json is invalid or unreadable; repair it before retrying. " if state == "invalid" else "") + NOTE}
