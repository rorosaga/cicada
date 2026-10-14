"""Small local Cursor setup/status adapter, not a capture or engine provider."""
from api.hooks import cursor_registry
from api.services import runtime_layout

ID = "cursor"
EVENTS = ("session_start",)
CAPABILITIES = {"startup": "documented", "capture": "unsupported", "surface": "local-ide", "verification": "synthetic"}
SETTINGS = ".cursor/hooks.json"
NOTE = ("Cursor asks you to confirm MCP. Turn on startup context separately, then open a new local chat. "
        "Automatic capture is unsupported. Startup timing in installed Cursor is unverified.")


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
    return {"on": [_step("autorecall", prefix + ["install", "--settings", path, "--command", command(python, repo)], touches)],
            "off": [_step("autorecall-off", prefix + ["uninstall", "--settings", path], touches)]}


MCP_CONFIG = "~/.cursor/mcp.json"
MCP_KEY = "mcpServers.cicada"


def setup(*, home, repo, python, spec):
    """The install link, plus (2026-10-14) a prompt for Cursor's own agent that
    adds the same server to ``~/.cursor/mcp.json``. The prompt adds MCP only:
    the startup hook stays its own click on the row, its command shown first
    (R-H11), so a paste never registers something that runs on every chat."""
    from api.services.agent_wiring import config_prompt, cursor_deeplink
    on = steps(home=home, repo=repo, python=python)["on"]
    return {"harness": ID, "kind": "deeplink", "title": "Connect Cursor", "deeplink": cursor_deeplink(spec),
            "prompt": config_prompt("Cursor", MCP_CONFIG, MCP_KEY, spec),
            "argv": [s["argv"] for s in on], "display": [s["display"] for s in on], "note": NOTE}


def wiring(*, home, repo, python):
    from api.services.agent_wiring import config_state
    if not (home / ".cursor").is_dir():
        return {"id": ID, "installed": False, "binary": None, "recall": "off", "autosave": "n/a",
                "connect": [], "capabilities": dict(CAPABILITIES), "detail": NOTE}
    state = {"present": "on", "absent": "off", "stale": "stale", "invalid": "invalid"}[
        cursor_registry.status(home / SETTINGS, command=command(python, repo))]
    commands = steps(home=home, repo=repo, python=python)
    return {"id": ID, "installed": True, "binary": None,
            "recall": config_state(ID, home), "autosave": "n/a", "connect": [], "autorecall": state,
            "autorecall_on": commands["on"] if state in ("off", "stale") else [],
            "autorecall_off": commands["off"] if state in ("on", "stale") else [],
            "capabilities": dict(CAPABILITIES),
            "detail": ("~/.cursor/hooks.json is invalid or unreadable; repair it before retrying. " if state == "invalid" else "") + NOTE}
