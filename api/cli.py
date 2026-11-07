"""The `cicada` command (G180, TODO ruling 21): a shell door onto the same memory as the MCP tools.

An agent with a shell runs `cicada recall "…"` instead of loading every tool schema up
front. The command calls the same bodies as the stdio MCP server (`api/services/mcp_tools.py`),
in this process, under the same locks — one implementation, two thin doors. Its names come
from one table (`api/services/cli_map.py`), checked against the MCP schemas. There is no
generic `call <tool>` door.

**One bootstrap, before any service import** (`bootstrap`, PLAN §3.3): the caller's working
folder is recorded and never used to find configuration; litellm's import-time dotenv load is
off; the memory root is resolved as one field (caller env PATH > caller env ROOT > a developer
checkout's `api/.env` PATH > ROOT > `~/cicada/memory`), canonicalised once and published as the
only root in the environment; `Settings` then reads no `.env` at all, so every `get_settings()`
in every service sees that root; and the active bank is pinned once, in a context every command
runs in, so a bank switch mid-command never splits its work. The running backend's `/healthz`
is a cross-check (`confirmed | mismatch | backend_down | unverified`); with the backend down,
this bootstrap is the authority.

**Output.** Text by default; `--json` (or `--format json`) prints exactly one envelope —
`{schema, command, ok, code, bank, data, text, warnings, version}` — and nothing else on either
stream, in every outcome. Exit codes: 0 ok, 1 refused, 2 usage, 3 bank/root mismatch, 4 demo
bank, 5 sandbox denied, 6 the app's backend is not running (or did not answer) for a command that acts on
it, 70 internal (the exception's class name only, never its message).

**The app's commands** (`api/cli_app.py`): what the Cicada app does — browsing, the inbox, Sleep, the search
model, sources, settings, pictures, banks. Reads of the bank run here like every other read; actions on state
the running backend owns go to its HTTP API with the token, as the app's own requests do (`cli_map.Row.via`).
"""
from __future__ import annotations

import argparse
import contextvars
import io
import json
import os
import re
import sys
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from api import LITELLM_PINNED, cli_app, pin_litellm
from api.cli_types import EXIT_CODES, REFUSAL_CODES, Refusal, RemotePin, Result, UsageError  # noqa: F401
from api.services import cli_map
from api.version import __version__

SCHEMA = "cicada.cli/1"
ROOT_KEYS = ("CICADA_MEMORY_PATH", "CICADA_MEMORY_ROOT")
#: Keys the bootstrap decides itself: no config file may set them.
CONTROL_KEYS = ROOT_KEYS + ("LITELLM_MODE", *LITELLM_PINNED)
DEFAULT_ROOT = "~/cicada/memory"
HEALTH_TIMEOUT_S = 1.0


class BootstrapError(Exception):
    """The command could not establish one root and one bank."""


class _HelpShown(Exception):
    """argparse printed help; ``topic`` is the subcommand it was for (None for the top level)."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog)
        words = prog.split()[1:]
        self.topic = " ".join(words) or None


@dataclass
class Boot:
    caller_cwd: str | None
    root: Path
    root_source: str
    distribution: str
    pin: object
    ctx: contextvars.Context
    backend_url: str
    probe: dict = field(default_factory=dict)
    #: G181 phase 2: ``CICADA_API_BASE`` names a backend on another machine. Then there is no local root or bank
    #: (``root`` is None); ``pin`` is the server's active bank, its name and id, read from the server
    #: (``client_probe``), and every command goes through the server's own routes.
    client: bool = False


# --- bootstrap ----------------------------------------------------------------------------------

def resolve_root(environ, file_values) -> tuple[str, str]:
    """The memory root as ONE field: the caller's PATH, then ROOT (``Settings``' own alias
    order), then a developer checkout's ``api/.env`` PATH, then ROOT, then the default."""
    for source, values in (("env", environ), ("checkout-env", file_values)):
        for key in ROOT_KEYS:
            value = (values.get(key) or "").strip()
            if value:
                return value, source
    return DEFAULT_ROOT, "default"


def _force_production(environ) -> None:
    """litellm runs ``load_dotenv()`` at import unless ``LITELLM_MODE`` is not ``DEV``: forced here, and
    re-forced after every overlay, so no inherited value and no config file can turn that load back on. The price
    table stays the installed litellm's own (``api.pin_litellm``) for the same reason."""
    environ["LITELLM_MODE"] = "PRODUCTION"
    pin_litellm(environ)


def bootstrap(environ=None) -> Boot:
    """PLAN §3.3. ``environ`` is the process environment (``Settings`` reads ``os.environ``)."""
    environ = os.environ if environ is None else environ
    try:
        caller_cwd = os.getcwd()
    except OSError:          # the caller's folder was deleted under it
        caller_cwd = None
    _force_production(environ)

    checkout = (environ.get("CICADA_CHECKOUT") or "").strip()
    if (environ.get("CICADA_DISTRIBUTION") or "").strip() == "release":
        distribution = "release"
    else:
        distribution = "checkout" if checkout else "other"
    file_values: dict[str, str] = {}
    if checkout:
        env_file = Path(checkout) / "api" / ".env"
        if env_file.is_file():
            from dotenv import dotenv_values

            file_values = {k: v for k, v in dotenv_values(env_file).items() if v is not None}

    if _client_mode(environ):
        return _client_bootstrap(environ, caller_cwd, distribution)
    raw, source = resolve_root(environ, file_values)
    for key, value in file_values.items():     # the app-spawned dev backend's overlay: the file wins
        if key not in CONTROL_KEYS:
            environ[key] = value
    canonical = Path(os.path.realpath(os.path.expanduser(raw)))
    environ["CICADA_MEMORY_PATH"] = str(canonical)
    environ.pop("CICADA_MEMORY_ROOT", None)

    from api import config

    config.disable_dotenv()
    try:
        from api.services.connections import secrets as connection_secrets

        connection_secrets.load_secrets()      # the backend lifespan's call: fills unset keys only
    except Exception:  # noqa: BLE001 - an unreadable secrets file never stops a read
        pass
    _force_production(environ)                 # last word, after every overlay, before any service import

    from api.services import bank_registry, runtime_layout

    ctx = contextvars.copy_context()
    pin = ctx.run(bank_registry.pin_request_bank, canonical)
    settings_root = ctx.run(lambda: Path(config.get_settings().memory_root))
    if settings_root != canonical:
        raise BootstrapError("the settings root and the pinned root differ")
    return Boot(caller_cwd=caller_cwd, root=canonical, root_source=source, distribution=distribution,
                pin=pin, ctx=ctx, backend_url=runtime_layout.backend_url(environ))


def _replica_mode(environ=None) -> bool:
    from api.services import runtime_layout

    return runtime_layout.is_replica(os.environ if environ is None else environ)


def _client_mode(environ) -> bool:
    from api.services import runtime_layout

    return runtime_layout.is_client(environ)


def _client_bootstrap(environ, caller_cwd, distribution) -> Boot:
    """G181 phase 2: this shell is a client of a backend on another machine. No root is resolved and no local bank is
    opened — the bank is on the server; the pin comes from the server itself (``client_probe``, in ``main``)."""
    from api import config
    from api.services import runtime_layout

    config.disable_dotenv()
    _force_production(environ)
    try:
        base = runtime_layout.api_base(environ)
    except ValueError as exc:
        raise BootstrapError(str(exc)) from None
    return Boot(caller_cwd=caller_cwd, root=None, root_source="server", distribution=distribution, pin=None,
                ctx=contextvars.copy_context(), backend_url=base, client=True)


def _opener():
    from api.services import runtime_layout

    # Loopback never goes through a proxy, and no redirect is followed with the token (a server elsewhere, G181).
    return runtime_layout.opener()


def probe_backend(url: str, root: Path, timeout: float = HEALTH_TIMEOUT_S, bank_id: str | None = None) -> dict:
    """Ask a running backend which memory it serves (`cli_app.probe_backend`, one copy): by bank identity when both
    sides have one, else by the root's path."""
    return cli_app.probe_backend(url, root, timeout, bank_id=bank_id)


def _backend_headers(environ=None) -> dict[str, str]:
    return cli_app.backend_headers(environ)


def _sleep_writing(url: str) -> bool | None:
    import urllib.request

    try:
        req = urllib.request.Request(f"{url}/sleep/status", headers=_backend_headers(), method="GET")
        with _opener().open(req, timeout=HEALTH_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return bool(body["writing"]) if "writing" in body else body.get("status") == "running"
    except Exception:  # noqa: BLE001 - status is informative; it never fails over this
        return None


def _root_warnings(boot: Boot) -> list[str]:
    state = boot.probe.get("state")
    return {"mismatch": ["root_mismatch"], "unverified": ["root_unverified"]}.get(state, [])


def _check_bank(boot: Boot, wanted: str | None) -> None:
    """``--bank`` / ``CICADA_BANK`` asserts the active bank; it never selects another one."""
    if wanted is not None and wanted != boot.pin.name:
        raise Refusal("bank_mismatch", f"The active memory is '{boot.pin.name}', not '{wanted}'. "
                                       "Nothing was read or written.")


# --- commands -----------------------------------------------------------------------------------

def _identity():
    from api.services import session_identity

    return session_identity.cli_identity()


def _project_dir(boot: Boot) -> str | None:
    """The folder a CLI write or `continue` is about: the harness's project dir when it names one,
    else the caller's working folder (recorded before the bootstrap, never used for configuration)."""
    return _identity().project_dir or boot.caller_cwd


def _tool_context(boot: Boot):
    from api.services import mcp_tools

    path = boot.pin.path
    # Ruling 21 / ruling 50: the one caller identity, shared with a client's door (`cli_app.caller`).
    session_id, harness = cli_app.caller()
    return mcp_tools.ToolContext(memory_path=lambda: path, session_id=session_id,
                                 harness=harness, project_dir=_project_dir(boot),
                                 read_surface="cli", available=cli_map.exposed_tools(),
                                 headers=lambda: {"Content-Type": "application/json", **_backend_headers()},
                                 backend_url=boot.backend_url)


def _door(boot: Boot, tool: str, arguments: dict, options: dict | None = None):
    """G181 phase 2: a tool mirror run on the server (``cli_app.door``)."""
    return cli_app.door(boot, tool, arguments, options, project_dir=_project_dir(boot))


def _vector_state(bank: Path) -> str:
    db = bank / "vector_index.db"
    if not db.exists():
        return "absent"
    try:
        from api.services.vector_index import SqliteVecIndexer

        return "present" if SqliteVecIndexer(bank).index_info() else "empty"
    except Exception:  # noqa: BLE001
        return "unreadable"


def _recall_data(payload) -> dict:
    """Recall's structured data: the generated hints payload the body handed back beside its text
    (``Reply.data``), never anything parsed out of the text, where memory's own words also live."""
    payload = payload if isinstance(payload, dict) else {}

    def ids(value) -> list[str]:
        return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []

    hub, state = payload.get("relevant_hub"), payload.get("state")
    return {"suggested_entities": ids(payload.get("suggested_entities")),
            "relevant_hub": hub if isinstance(hub, str) else None,
            "hub_members_preview": ids(payload.get("hub_members_preview")),
            "state": state if isinstance(state, dict) else None}


def cmd_recall(boot: Boot, args) -> Result:
    from api.services import mcp_tools

    if boot.client:
        reply = _door(boot, "cicada_recall", {"query": args.query})
    else:
        reply = mcp_tools.recall(_tool_context(boot), args.query)
    warnings = _root_warnings(boot)            # a refusal keeps what the root cross-check found
    code = getattr(reply, "code", None)
    if code in REFUSAL_CODES:
        return Result(text=str(reply), data=None, warnings=warnings, code=code)
    if not boot.client and _vector_state(boot.pin.path) != "present":
        warnings.append("degraded:vector")
    return Result(text=str(reply), data=_recall_data(getattr(reply, "data", None)), warnings=warnings)


_VERIFIED_WORDS = {"confirmed": "matches the app's backend", "mismatch": "the app's backend uses a DIFFERENT folder",
                   "backend_down": "the app's backend is not running", "unverified": "the app's backend did not answer"}


def _waiting_captures(base: str | None) -> dict:
    """D3 (G202): what waits on this machine to be sent, by the server it was meant for — the hooks' spool
    (``$CICADA_HOME/spool/capture``) and the app's outbox (``spool/app``). ``{"waiting": n for base, "elsewhere":
    {host: n}}``; ``base`` None (this machine holds its own memory) makes everything elsewhere. Counts only."""
    from api.hooks import hook_client
    from api.services import runtime_layout

    spool = hook_client.spool_module()
    home = runtime_layout.cicada_home(os.environ)
    out = spool.waiting(home, base)
    here, elsewhere = out["here"], dict(out["elsewhere"])
    folder = Path(home) / "spool" / "app"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        if path.name.startswith("."):
            continue
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meant = entry.get("base") if isinstance(entry, dict) and isinstance(entry.get("base"), str) else None
        if base is not None and (meant is None or spool.same_server(meant, base)):
            here += 1
            continue
        host = spool.host_of(meant) if meant else ""
        elsewhere[host] = elsewhere.get(host, 0) + 1
    return {"waiting": here, "elsewhere": elsewhere}


def _waiting_lines(captures: dict, *, client: bool) -> list[str]:
    lines = []
    if client and captures.get("waiting"):
        n = captures["waiting"]
        lines.append(f"Waiting to be sent to this server: {n} capture{'s' if n != 1 else ''}")
    for host, n in sorted((captures.get("elsewhere") or {}).items()):
        where = f"another server ({host})" if host else "a server this machine no longer names"
        lines.append(f"Waiting for {where}: {n} capture{'s' if n != 1 else ''} — kept, sent only there")
    return lines


def _client_status(boot: Boot) -> Result:
    """`cicada status` on a client (G181 phase 2): the server this shell uses, its bank and whether it answered."""
    state = boot.probe.get("state", "unverified")
    backend = {"state": state}
    if boot.probe.get("version"):
        backend["version"] = boot.probe["version"]
    if state == "confirmed":
        writing = _sleep_writing(boot.backend_url)
        if writing is not None:
            backend["writing"] = writing
    pin = boot.pin
    data = {"version": __version__, "distribution": boot.distribution, "caller_cwd": boot.caller_cwd,
            "client": True, "server": boot.backend_url,
            "bank": {"name": pin.name, "id": pin.id} if pin is not None else None, "backend": backend}
    words = {"confirmed": "answered", "backend_down": "is not reachable", "unauthorized":
             "did not accept this device's token", "unverified": "did not answer",
             "no_token": "was not asked: this device has no token (CICADA_API_TOKEN or ~/.cicada/device_token)",
             "redirected": "answered with a redirect, which is never followed with this device's token"}
    lines = [f"Memory: on the server at {boot.backend_url}"
             + (f" (bank '{pin.name}')" if pin is not None else ""),
             f"  the server {words.get(state, 'did not answer')}"]
    if state == "redirected" and boot.probe.get("text"):
        lines.append(f"  {boot.probe['text']}")
    if state == "confirmed":
        detail = f"version {backend.get('version', 'unknown')}"
        if "writing" in backend:
            detail += ", Sleep is writing" if backend["writing"] else ", Sleep is not writing"
        lines.append(f"Backend: running ({detail})")
        flushed = cli_app.flush_spool()        # D3 (G202): the server answered — what waits for it goes now
        if flushed:
            data["flushed"] = flushed[0]
            if flushed[0]:
                lines.append(f"Sent {flushed[0]} waiting capture{'s' if flushed[0] != 1 else ''} to this server")
    data["captures"] = _waiting_captures(boot.backend_url)
    lines += _waiting_lines(data["captures"], client=True)
    lines.append(f"cicada {__version__} ({boot.distribution}, a client of that server)")
    return Result(text="\n".join(lines), data=data, warnings=[] if state == "confirmed" else ["server_" + state])


def cmd_status(boot: Boot, args) -> Result:
    from api.services import agentic_write, demo_guard

    if boot.client:
        return _client_status(boot)

    bank = Path(boot.pin.path)
    backend = {"state": boot.probe.get("state", "unverified")}
    if backend["state"] in ("confirmed", "mismatch"):
        if boot.probe.get("version"):
            backend["version"] = boot.probe["version"]
        writing = _sleep_writing(boot.backend_url)
        if writing is not None:
            backend["writing"] = writing
    data = {
        "version": __version__,
        "distribution": boot.distribution,
        "caller_cwd": boot.caller_cwd,
        "root": {"path": str(boot.root), "source": boot.root_source, "verified": backend["state"]},
        "bank": {"name": boot.pin.name, "path": os.path.realpath(bank), "demo": demo_guard.is_demo(bank)},
        "episodes": {"unprocessed": len(agentic_write.list_unprocessed_episodes(bank, limit=1_000_000))},
        "backend": backend,
        "index": {"vector": _vector_state(bank)},
    }
    lines = [
        f"Memory: {data['bank']['path']} (bank '{boot.pin.name}'{', a demo' if data['bank']['demo'] else ''})",
        f"  root from {boot.root_source}; {_VERIFIED_WORDS[backend['state']]}",
        f"Not consolidated yet: {data['episodes']['unprocessed']} conversation(s)",
    ]
    if backend["state"] in ("confirmed", "mismatch"):
        detail = f"version {backend.get('version', 'unknown')}"
        if "writing" in backend:
            detail += ", Sleep is writing" if backend["writing"] else ", Sleep is not writing"
        lines.append(f"Backend: running ({detail})")
    else:
        lines.append("Backend: not running" if backend["state"] == "backend_down" else "Backend: no answer")
    lines.append(f"Search index: {data['index']['vector']}")
    data["captures"] = _waiting_captures(None)     # D3 (G202): left waiting for a server this machine used to use
    lines += _waiting_lines(data["captures"], client=False)
    lines.append(f"cicada {__version__} ({boot.distribution})")
    return Result(text="\n".join(lines), data=data, warnings=_root_warnings(boot))


def cmd_commands(boot: Boot | None, args) -> Result:
    catalog = cli_map.catalog()
    app_names = {r.name for r in cli_map.rows() if r.app}
    exposed = [c for c in catalog if c["exposed"] and c["command"] not in app_names]
    app = [c for c in catalog if c["command"] in app_names]
    later = [c for c in catalog if not c["exposed"]]
    width = max(len(c["command"]) for c in catalog) + 2

    def line(c):
        return f"  {c['command']:<{width}}{(c['mirrors'] or '(CLI only)'):<26}{c['summary']}"

    def app_line(c):
        marks = ", ".join(m for m, on in (("needs the app's backend", c["via"] == "backend"),
                                          ("a chat export needs the app's backend", c["via"] == "both"),
                                          ("the person only", c["person"])) if on)
        return f"  {c['command']:<{width}}{c['summary']}" + (f" [{marks}]" if marks else "")

    text = "\n".join(["Commands:", *map(line, exposed), "", "The app's commands:", *map(app_line, app), "",
                      "Not in this command line yet (use the MCP tool):", *map(line, later)])
    return Result(text=text, data={"commands": catalog})


def _typed(reply, data=None, warnings=None) -> Result:
    """A body's reply as a Result: its typed refusal (``Reply.code``) decides ok/exit; never its sentence."""
    code = getattr(reply, "code", None)
    payload = getattr(reply, "data", None) if data is None else data
    return Result(text=str(reply), data=None if code in REFUSAL_CODES else payload,
                  warnings=list(warnings or []), code=code)


_RANGE = re.compile(r"^(?P<base>.+?):(?P<start>\d+)(?::(?P<end>\d+))?$")


def _slice(text: str, start: int | None, count: int | None, numbered: bool) -> tuple[str, dict]:
    lines = text.splitlines()
    total = len(lines)
    first = 1 if start is None else start
    if first < 1 or (count is not None and count < 1):
        raise UsageError("--from and --count must be 1 or more")
    if first > max(total, 1):
        raise UsageError(f"the page has {total} lines; --from {first} is past its end")
    last = total if count is None else min(total, first + count - 1)
    shown = lines[first - 1:last]
    if numbered:
        shown = [f"{n}: {line}" for n, line in enumerate(shown, first)]
    return "\n".join(shown), {"from": first, "count": len(shown), "total_lines": total}


def cmd_get(boot: Boot, args) -> Result:
    """The page, read literally first — a name or a legacy stem may contain a colon — and only when
    that finds nothing, as the ``ENTITY:START[:END]`` shorthand (lines START to END, 1-based)."""
    from api.services import mcp_tools

    start, count = args.__dict__.get("from"), args.count
    numbered = bool(getattr(args, "line_numbers", False))
    # Vision item 5: `--include` blocks ride the unbounded read only (a line range is the page's own lines).
    include = getattr(args, "include", None) or None
    if boot.client:
        def detail(entity_id, start=None, whole=False, include=None):
            body = {"entity_id": entity_id, "start": start, **({"include": include} if include else {})}
            return _door(boot, "cicada_recall_detail", body, {"whole": whole})
    else:
        ctx = _tool_context(boot)

        def detail(entity_id, start=None, whole=False, include=None):
            return mcp_tools.recall_detail(ctx, entity_id, start=start, whole=whole, include=include)
    # A bounded read slices the whole page; an unbounded one is the tool's own reply (F5: an over-budget fence elided).
    bounded = start is not None or count is not None or numbered
    reply = detail(args.entity_id, start=getattr(args, "start", None), whole=bounded,
                   include=None if bounded else include)
    if getattr(reply, "code", None) == "not_found" and (m := _RANGE.match(args.entity_id)):
        if start is not None or count is not None:
            raise UsageError("give the line range once: ENTITY:START[:END] or --from/--count")
        start = int(m.group("start"))
        if m.group("end") is not None:
            end = int(m.group("end"))
            if end < start:
                raise UsageError("the range ends before it starts")
            count = end - start + 1
        if start < 1:
            raise UsageError("lines are numbered from 1")
        reply = detail(m.group("base"), whole=True)
    if getattr(reply, "code", None) in REFUSAL_CODES:
        return _typed(reply, warnings=_root_warnings(boot))
    if start is None and count is None and not numbered:
        total = len(str(reply).splitlines())                # the whole page, byte for byte
        return Result(text=str(reply), data={**(reply.data or {}), "from": 1, "count": total, "total_lines": total},
                      warnings=_root_warnings(boot))
    text, window = _slice(str(reply), start, count, numbered)
    return Result(text=text, data={**(reply.data or {}), **window}, warnings=_root_warnings(boot))


def cmd_project(boot: Boot, args) -> Result:
    from api.services import mcp_tools

    if boot.client:
        reply = _door(boot, "cicada_project", {"project": args.project, "since": args.since, "tz": args.tz})
    else:
        reply = mcp_tools.project(_tool_context(boot), args.project, args.since, args.tz)
    return _typed(reply, warnings=_root_warnings(boot))


def _continue_spelling():
    from api.services import local_tools

    return local_tools.cli_continue_spelling()


def cmd_continue(boot: Boot, args) -> Result:
    from api.services import local_tools

    ident = _identity()
    if boot.client:
        reply = _door(boot, "cicada_continue", {"session": args.session, "before": args.before},
                      {"cwd": _project_dir(boot)})
        return _typed(reply, warnings=_root_warnings(boot))
    # Whatever the harness gave — possibly nothing: the shared body still applies the current-conversation
    # rules for an unknown identity (#229), exactly as for cicada_continue.
    reply = local_tools.continue_text(boot.pin.path, root=boot.root, cwd=_project_dir(boot),
                                      identity=(ident.harness, ident.session_id), session=args.session,
                                      before=args.before, spelling=_continue_spelling())
    return _typed(reply, warnings=_root_warnings(boot))


NO_SESSION_LINE = ("No session id came from this shell, so this note is not grouped with a conversation "
                   "(set CICADA_SESSION_ID and CICADA_SESSION_HARNESS to group it).")


def cmd_save(boot: Boot, args) -> Result:
    """The one write: Awake capture through the MCP's own body — scrub, dedup by hash, ``episode_lock``,
    an atomic create, the demo refusal — into the pinned bank. Like every Awake capture it takes no
    write admission (``write_admission``: capture is allowed while Sleep runs). A backend that serves
    another memory root refuses it before anything is written."""
    from api.services import mcp_tools

    if boot.probe.get("state") == "mismatch":
        raise Refusal("root_mismatch", "The app's backend uses a different memory folder than this command. "
                                       "Nothing was saved; check `cicada status`.")
    if boot.client:
        reply = _door(boot, "cicada_save_episode", {"content": args.content, "title": args.title})
        session_id = _identity().session_id
    else:
        ctx = _tool_context(boot)
        reply = mcp_tools.save_episode(ctx, args.content, args.title)
        session_id = ctx.session_id
    warnings = _root_warnings(boot)
    text = str(reply)
    if getattr(reply, "code", None) not in REFUSAL_CODES and not session_id \
            and (reply.data or {}).get("episode_id"):
        warnings.append("no_session")
        text = f"{text}\n{NO_SESSION_LINE}"
    result = _typed(reply, warnings=warnings)
    result.text = text
    return result


def _read_export(path: Path, include_history: bool):
    """A platform export the person named in this shell: ``(items, label, from_bookmark_file, warnings)``.

    The command line reads the path itself, as the app does — the backend is never asked to open one. A
    folder goes through the same archive reader as an uploaded zip (``saved_exports``), so the two cannot
    read an export differently; one file goes through ``parse_upload`` exactly as an upload would."""
    from api.services import media_ingestor, saved_exports

    if path.is_dir():
        members = []
        for f in sorted(path.rglob("*")):
            if f.is_file() and not f.is_symlink():
                members.append((f.relative_to(path).as_posix(), f.stat().st_size, f.read_bytes))
        result = saved_exports.parse_members(members, include_history=include_history)
        return result.items, result.label, False, result.warnings
    warnings: list[str] = []
    try:
        items, label, from_bookmark_file = media_ingestor.parse_upload(
            path.read_bytes(), path.name, include_history=include_history, warnings=warnings)
    except ValueError as exc:
        raise Refusal("not_an_export", str(exc)) from None
    return items, label, from_bookmark_file, warnings


def cmd_import(boot: Boot, args) -> Result:
    """One `cicada import` for both kinds of export (person-only: it writes as the person; --preview writes
    nothing and is allowed). The path is sniffed as the backend sniffs a dropped file: a chat export the intake's
    reader finds conversations in goes to the backend's intake (`cli_app.import_chat_export`, the app's path);
    anything else — a platform's save lists, a folder — is read here (`_import_platform_export`). Nothing under
    ~/.claude is read by either."""
    path = Path(args.path)
    cli_app.refuse_harness_folder(path)
    if not args.preview:
        cli_app.require_person("Importing a file into memory")
    content = cli_app.chat_export(path)
    if content is not None:
        return cli_app.import_chat_export(boot, args, path, content)
    if boot.client:
        raise Refusal("on_server", ON_SERVER_TEXT)
    return _import_platform_export(boot, args)


def _import_platform_export(boot: Boot, args) -> Result:
    """A platform's data export into the pinned bank through the upload's own parser and writer
    (``media_ingestor``: scrub, ``url_index`` dedup against every channel, connectors included,
    ``MAX_BATCH`` at a time). The demo refusal and the root cross-check come first; ``--preview``
    writes nothing. Enrichment reads the public page of a link the export did not describe, as an
    upload does — a request the person just made."""
    import asyncio

    from api.services import demo_guard, media_ingestor

    bank = Path(boot.pin.path)
    if demo_guard.is_demo(bank):
        raise Refusal("demo_bank", demo_guard.REFUSAL)
    if boot.probe.get("state") == "mismatch" and not args.preview:
        raise Refusal("root_mismatch", "The app's backend uses a different memory folder than this command. "
                                       "Nothing was imported; check `cicada status`.")
    path = Path(args.path)
    try:
        items, label, from_bookmark_file, warnings = _read_export(path, args.include_history)
    except PermissionError:
        raise Refusal("unreadable", f"This shell may not read {path}.") from None
    described = media_ingestor.describe_items(items, label, warnings)
    data = {"source": label, "platform": described.platform, "total": described.total,
            "collections": described.collections}
    if described.history_videos:
        data.update(history_videos=described.history_videos, history_days=described.history_days)
    warnings = list(described.warnings) + _root_warnings(boot)
    if args.preview:
        lines = [f"{label}: {described.total} saved item(s)"]
        lines += [f"  {c['name']}: {c['count']}" for c in described.collections]
        if described.history_videos:
            lines.append(f"  Watch history: {described.history_videos} video(s) over {described.history_days} day(s), "
                         "one entry per day, not saves")
        return Result(text="\n".join(lines), data=data, warnings=warnings)
    if not described.recognized:
        raise Refusal("not_an_export", f"Found no saved links in {path.name}.")
    from api.services import listening_history as _listening

    saves = sum(1 for it in items if not _listening.is_play(it))   # G32: plays become days, never saves
    if saves > media_ingestor.MAX_UPLOAD_ITEMS:
        raise Refusal("too_large", f"{saves:,} items is past the {media_ingestor.MAX_UPLOAD_ITEMS:,}-item "
                                   "import cap; nothing was imported.")
    # History is experience, never a save (G71, 2026-10-16): one episode per day, committed alone first.
    from api.services import listening_history, watch_history

    items, play_rows = listening_history.split(items)
    items, history_rows = watch_history.split(items)
    history_text = ""
    if history_rows:
        history = asyncio.run(watch_history.import_history(bank, history_rows, door="takeout",
                                                           trigger="user/watch_history"))
        data.update(history_added=history.added, history_days_created=history.days_created,
                    history_days_updated=history.days_updated)
        history_text = " " + watch_history.summary(history)
    if play_rows:
        # G32: Spotify's plays, one listening day each, committed alone — never saved links.
        listened = asyncio.run(listening_history.import_history(bank, play_rows, trigger="user/listening_history"))
        data.update(plays_added=listened.added, listening_days_created=listened.days_created,
                    listening_days_updated=listened.days_updated)
        history_text += " " + listening_history.summary(listened)
    created, duplicates = asyncio.run(media_ingestor.ingest_chunked(items, bank, from_bookmark_file))
    data.update(created=created, duplicates=duplicates)
    return Result(text=f"Imported {created} new item(s) from {label}; {duplicates} already in memory.{history_text}",
                  data=data, warnings=warnings)


def cmd_handshake(boot: Boot, args) -> Result:
    from api.services import handshake, state_dictionary

    if boot.client:
        from api.services import tool_client

        # G202 (D6): the server is named by the host this machine reaches it on — never a path or a token.
        reply = _door(boot, "cicada_handshake", {}, {"tz": handshake.local_timezone(),
                                                     "server": tool_client.host_of(boot.backend_url)})
        return Result(text=str(reply), data=reply.data or {"tokens_est": len(reply) // 4},
                      warnings=_root_warnings(boot))
    names = frozenset(r.name for r in cli_map.exposed())
    text = handshake.build_cli(state_dictionary.with_live_engine(state_dictionary.read_state(boot.pin.path)),
                               commands=names, bank=boot.pin.name,
                               tz=handshake.local_timezone())
    handshake.record("cli", {"variant": handshake.CLI_VARIANT}, bank=boot.pin.path.name,
                     harness=_identity().harness)
    return Result(text=text, data={"tokens_est": len(text) // 4}, warnings=_root_warnings(boot))


def cmd_skills_list(boot: Boot, args) -> Result:
    from api.services import mcp_tools

    if boot.client:
        return _typed(_door(boot, "cicada_skills", {}), warnings=_root_warnings(boot))
    return _typed(mcp_tools.skills(_tool_context(boot)), warnings=_root_warnings(boot))


def cmd_skills_propose(boot: Boot, args) -> Result:
    from api.services import mcp_tools

    if boot.client:
        reply = _door(boot, "cicada_propose_skill", {"action": args.action, "source": args.source,
                                                     "skill": args.skill, "agents": args.agents,
                                                     "reason": args.reason})
    else:
        reply = mcp_tools.propose_skill(_tool_context(boot), args.action, args.source, args.skill, args.agents,
                                        args.reason)
    return _typed(reply, warnings=_root_warnings(boot))


def cmd_skills_create(boot: Boot, args) -> Result:
    from api.services import mcp_tools

    body = sys.stdin.read() if args.body == "-" else args.body
    if boot.client:
        reply = _door(boot, "cicada_create_skill", {"skill": args.skill, "description": args.description,
                                                    "body": body, "reason": args.reason})
    else:
        reply = mcp_tools.create_skill(_tool_context(boot), args.skill, args.description, body, args.reason)
    return _typed(reply, warnings=_root_warnings(boot))


def _page_join(tool: str):
    """G227 follow-up (coordinator 2026-10-29): `page merge` / `page split` — the MCP bodies, G198's trust list deciding
    as it does there (a listed harness applies under its own name, any other shell's call is an inbox proposal). An
    edit already uncommitted on a page is committed apart first (`agent_commits.setting_apart`)."""
    def handler(boot: Boot, args) -> Result:
        from api.services import agent_commits, mcp_tools

        row = cli_map.by_tool()[tool]
        arguments = {a.prop: getattr(args, a.prop, None) for a in row.args if getattr(args, a.prop, None) is not None}
        if boot.client:
            return _typed(_door(boot, tool, arguments), warnings=_root_warnings(boot))
        ctx = _tool_context(boot)
        with agent_commits.setting_apart(boot.pin.path):
            if tool == "cicada_undo_join":
                reply = mcp_tools.undo_join(ctx, arguments.get("page", ""), arguments.get("reason", ""))
            elif tool == "cicada_merge_pages":
                reply = mcp_tools.merge_pages(ctx, arguments.get("page", ""), arguments.get("into", ""),
                                              arguments.get("reason", ""))
            else:
                reply = mcp_tools.split_page(
                    ctx, arguments.get("page", ""), arguments.get("reason", ""), arguments.get("sentences"),
                    arguments.get("claims"), arguments.get("sources"), arguments.get("episodes"),
                    arguments.get("references"), arguments.get("name"), arguments.get("page_type"),
                    bool(arguments.get("preview", False)))
        return _typed(reply, warnings=_root_warnings(boot))
    return handler


ON_SERVER_TEXT = ("This command reads the memory folder, and this shell is a client of a Cicada server "
                  "(CICADA_API_BASE): the folder is on the server. Run it there, or use the MCP tools here. "
                  "Nothing was read or written.")
#: G181 phase 2: what a client shell runs, through the server's own routes — the tool mirrors (the tool door) and
#: the read of the bank list; every `backend` command already goes to the backend's routes.
CLIENT_DOOR_COMMANDS = frozenset({"recall", "get", "project", "continue", "save", "handshake", "timeline",
                                  "skills list", "skills propose", "skills create", "page merge", "page split", "page undo",
                                  "status", "commands",
                                  "bank list", "import"})


def _client_gate(command: str, boot: Boot) -> None:
    """On a client, a command that would read a local memory folder refuses (there is none); every other one needs
    the server: refused when it is down or did not accept this device's token (``status`` reports instead)."""
    row = cli_map.by_name().get(command)
    if command not in CLIENT_DOOR_COMMANDS and not (row is not None and row.via in ("backend", "both")):
        raise Refusal("on_server", ON_SERVER_TEXT)
    if command == "status":
        return
    state = boot.probe.get("state")
    if state == "backend_down":
        raise Refusal("backend_down", cli_app.CLIENT_DOWN_TEXT)
    if state == "no_token":
        raise Refusal("unauthorized", cli_app.CLIENT_NO_TOKEN_TEXT)
    if state == "unauthorized":
        raise Refusal("unauthorized", cli_app.CLIENT_UNAUTHORIZED_TEXT)
    if state == "redirected":
        raise Refusal("backend_error", boot.probe.get("text") or "Cicada's server answered with a redirect.")
    if state != "confirmed" or boot.pin is None:
        raise Refusal("root_unverified", cli_app.CLIENT_UNVERIFIED_TEXT, ["root_unverified"])


#: name → handler. A test may swap a handler. The app's commands (`cli_app`) join the agent's.
COMMANDS: dict[str, Callable] = {"recall": cmd_recall, "get": cmd_get, "project": cmd_project,
                                 "continue": cmd_continue, "save": cmd_save, "handshake": cmd_handshake,
                                 "status": cmd_status, "commands": cmd_commands, **cli_app.COMMANDS,
                                 "import": cmd_import, "skills list": cmd_skills_list,
                                 "skills propose": cmd_skills_propose, "skills create": cmd_skills_create,
                                 "page merge": _page_join("cicada_merge_pages"),
                                 "page split": _page_join("cicada_split_page"),
                                 "page undo": _page_join("cicada_undo_join")}
_NO_BOOT = {"commands"}


# --- parsing ------------------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)

    def exit(self, status=0, message=None):
        if status:
            raise UsageError((message or "").strip() or "invalid command line")
        raise _HelpShown(self.prog)


def _globals(parser: argparse.ArgumentParser, *, top: bool) -> None:
    suppress = argparse.SUPPRESS
    parser.add_argument("--json", action="store_true", default=False if top else suppress,
                        help="Print one JSON envelope (same as --format json).")
    parser.add_argument("--format", choices=("text", "json"), default="text" if top else suppress,
                        help="Output format.")
    parser.add_argument("--bank", default=None if top else suppress, metavar="NAME",
                        help="Refuse unless NAME is the active memory bank (never switches banks).")


def _json_value(raw: str):
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not valid JSON: {exc.msg}") from None


def _pair(raw: str) -> tuple[str, str]:
    key, sep, value = raw.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    return key, value


_TYPES = {"str": str, "int": int, "float": float, "json": _json_value, "list": str, "pairs": _pair}


def _add_arguments(sub: argparse.ArgumentParser, row: cli_map.Row) -> None:
    for arg in row.args:
        if arg.positional:
            sub.add_argument(arg.prop, metavar=arg.prop.replace("_", "-"), type=_TYPES[arg.kind],
                             nargs="+" if arg.kind == "list" else None)
        elif arg.kind == "bool":
            sub.add_argument(arg.flag, dest=arg.prop, action="store_true", default=None)
        elif arg.kind in ("list", "pairs"):
            sub.add_argument(arg.flag, dest=arg.prop, action="append", type=_TYPES[arg.kind])
        else:
            sub.add_argument(arg.flag, dest=arg.prop, type=_TYPES[arg.kind])
    for opt in row.options:
        dest = opt.flag.lstrip("-").replace("-", "_")
        if opt.kind == "bool":
            sub.add_argument(opt.flag, dest=dest, action="store_true", help=opt.help)
        else:
            sub.add_argument(opt.flag, dest=dest, type=_TYPES[opt.kind], help=opt.help)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="cicada", allow_abbrev=False,
                     description="Cicada's memory from a shell: the same memory as the MCP tools. "
                                 "`cicada commands` lists every command and the tool it mirrors.")
    _globals(parser, top=True)
    parser.add_argument("--version", action="store_true", help="Print the version.")
    subs = parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)
    groups: dict[str, argparse._SubParsersAction] = {}
    for row in cli_map.exposed():
        if len(row.command) == 1:
            sub = subs.add_parser(row.command[0], help=row.summary, description=row.summary, allow_abbrev=False)
        else:
            group, verb = row.command
            if group not in groups:
                gp = subs.add_parser(group, help=f"{group} commands", allow_abbrev=False)
                _globals(gp, top=False)
                groups[group] = gp.add_subparsers(dest="verb", metavar="VERB", parser_class=_Parser)
            sub = groups[group].add_parser(verb, help=row.summary, description=row.summary, allow_abbrev=False)
        _globals(sub, top=False)
        _add_arguments(sub, row)
    return parser


def _wants_json(argv: list[str]) -> bool:
    """Read the output mode before parsing, so a malformed command line still answers in it."""
    for i, word in enumerate(argv):
        if word == "--":
            break
        if word == "--json" or word == "--format=json" or (word == "--format" and argv[i + 1:i + 2] == ["json"]):
            return True
    return False


# --- running ------------------------------------------------------------------------------------

@contextmanager
def _quiet(enabled: bool):
    """In JSON mode nothing but the envelope may reach either stream: every library log line,
    warning and stray print goes to /dev/null at the descriptor level while the command runs."""
    if not enabled:
        yield
        return
    sys.stdout.flush()
    sys.stderr.flush()
    saved, devnull = [], None
    try:
        saved = [os.dup(1), os.dup(2)]
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
    except OSError:
        saved = []
    old = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old
        if saved:
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            for fd in saved:
                os.close(fd)
        if devnull is not None:
            os.close(devnull)


def _emit(as_json: bool, *, command, ok, code, bank, data, text, warnings) -> None:
    if as_json:
        sys.stdout.write(json.dumps({"schema": SCHEMA, "command": command, "ok": ok, "code": code, "bank": bank,
                                     "data": data, "text": text, "warnings": warnings, "version": __version__},
                                    ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return
    if ok:
        if text:
            sys.stdout.write(text.rstrip("\n") + "\n")
        for w in warnings:
            sys.stderr.write(f"cicada: warning: {w}\n")
    else:
        sys.stderr.write(f"cicada: {text}\n")
        for w in warnings:
            sys.stderr.write(f"cicada: warning: {w}\n")


def _validate(command: str, args) -> None:
    """Checks that need no memory, before the bootstrap. ``save -`` reads the text from stdin here."""
    if command == "recall" and not args.query.strip():
        raise UsageError("the query is empty")
    if command == "get" and not args.entity_id.strip():
        raise UsageError("the entity is empty")
    if command == "project" and not args.project.strip():
        raise UsageError("the project is empty")
    if command == "import":
        path = Path(os.path.expanduser(args.path))
        if not path.exists():
            raise UsageError(f"nothing at {args.path}")
        args.path = os.path.abspath(path)
    if command == "save":
        if args.content == "-":
            try:
                args.content = sys.stdin.read()
            except (OSError, UnicodeDecodeError, ValueError):
                raise UsageError("could not read the text from stdin") from None
        if not args.content.strip():
            raise UsageError("there is nothing to save")
    cli_app.validate(command, args)


def _in_process(command: str, handler, boot: Boot, args):
    """One command over this machine's bank. A tool mirror that writes runs with the bank's dirty pages snapshotted
    first, so its commit keeps an edit already there apart (`agent_commits.setting_apart`, owner 2026-10-16)."""
    row = cli_map.by_name().get(command)
    if row is not None and row.tool and row.mutates and row.via == "bank":
        from api.services import agent_commits

        with agent_commits.setting_apart(boot.pin.path):
            return handler(boot, args)
    return handler(boot, args)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = _wants_json(argv)
    parser = build_parser()
    command: str | None = None
    try:
        help_text = io.StringIO()
        try:
            with redirect_stdout(help_text):
                args = parser.parse_args(argv)
        except _HelpShown as shown:
            if as_json:
                _emit(True, command="help", ok=True, code=None, bank=None, data={"topic": shown.topic},
                      text=help_text.getvalue(), warnings=[])
            else:
                sys.stdout.write(help_text.getvalue())
            return 0
        as_json = args.json or args.format == "json"
        if args.version and not args.command:
            if as_json:
                _emit(True, command="version", ok=True, code=None, bank=None, data={"version": __version__},
                      text=__version__, warnings=[])
            else:
                sys.stdout.write(__version__ + "\n")
            return 0
        if not args.command:
            raise UsageError("a command is required (try `cicada --help`)")
        command = " ".join(w for w in (args.command, getattr(args, "verb", None)) if w)
        _validate(command, args)
    except UsageError as exc:
        if as_json:
            _emit(True, command=command, ok=False, code="usage", bank=None, data=None, text=str(exc), warnings=[])
        else:
            sys.stderr.write(f"cicada: error: {exc}\n(see `cicada --help`)\n")
        return EXIT_CODES["usage"]

    handler = COMMANDS[command]
    bank_name = None
    try:
        with _quiet(as_json):
            if command in _NO_BOOT:
                result = handler(None, args)
            else:
                try:
                    boot = bootstrap()
                except PermissionError:
                    raise                      # a sandboxed shell: exit 5 with the MCP fallback, below
                except BootstrapError:
                    raise                      # already says what is wrong (a client's address names its rule)
                except Exception as exc:  # noqa: BLE001
                    raise BootstrapError(type(exc).__name__) from None
                if boot.client:
                    boot.probe, boot.pin = cli_app.client_probe(boot.backend_url)
                    _client_gate(command, boot)
                    bank_name = boot.pin.name if boot.pin is not None else None
                    if boot.pin is not None:
                        _check_bank(boot, args.bank if args.bank is not None else os.environ.get("CICADA_BANK"))
                    result = boot.ctx.run(handler, boot, args)
                else:
                    bank_name = boot.pin.name
                    _check_bank(boot, args.bank if args.bank is not None else os.environ.get("CICADA_BANK"))
                    boot.probe = probe_backend(boot.backend_url, boot.root, bank_id=getattr(boot.pin, "id", None))
                    row = cli_map.by_name().get(command)
                    if row is not None and row.tool and row.replica_side == "home" and _replica_mode():
                        # G132 phase 1 B: this computer keeps a copy — a write goes to the home, through this
                        # computer's own backend (its outbox), the same tool body the MCP door runs there.
                        if row.person:
                            cli_app.require_person(row.summary.rstrip("."))
                        arguments = {a.prop: getattr(args, a.prop, None) for a in row.args
                                     if getattr(args, a.prop, None) is not None}
                        if arguments.get("content") == "-":
                            arguments["content"] = sys.stdin.read()   # `cicada save -` reads stdin, as locally
                        result = _typed(_door(boot, row.tool, arguments), warnings=_root_warnings(boot))
                    else:
                        journal = row is not None and row.tool and row.mutates
                        if journal:
                            from api.services import home_move

                            if home_move.writes_closed():
                                # G132 phase 2: this computer's home is moving (or moved): no write is made here.
                                raise Refusal("refused", home_move.closed_text())
                        result = boot.ctx.run(_in_process, command, handler, boot, args)
                        if journal and result.ok:
                            # G132 phase 2: a publishing home keeps what it admitted, to offer it back if it is ever
                            # taken over while away (`admitted_log`; nothing at all while it shares nothing).
                            from api.services import admitted_log

                            arguments = {a.prop: getattr(args, a.prop, None) for a in row.args
                                         if getattr(args, a.prop, None) not in (None, "-")}
                            admitted_log.record_tool(boot.pin.path,
                                                     tool=row.tool, arguments=arguments,
                                                     caller={"harness": cli_app.caller()[1]}, surface="cli")
    except UsageError as exc:                  # a check that needed the page (a `get` range past its end)
        _emit(as_json, command=command, ok=False, code="usage", bank=bank_name, data=None, text=str(exc),
              warnings=[])
        return EXIT_CODES["usage"]
    except Refusal as exc:
        _emit(as_json, command=command, ok=False, code=exc.code, bank=bank_name, data=None, text=str(exc),
              warnings=list(getattr(exc, "warnings", []) or []))
        return EXIT_CODES.get(exc.code, 1)
    except BootstrapError as exc:
        _emit(as_json, command=command, ok=False, code="bootstrap", bank=None, data=None,
              text=f"Could not open the memory ({exc}).", warnings=[])
        return EXIT_CODES["bootstrap"]
    except PermissionError as exc:
        from api.services import replica_guard

        if isinstance(exc, replica_guard.ReplicaReadOnly):
            _emit(as_json, command=command, ok=False, code="refused", bank=bank_name, data=None, text=str(exc),
                  warnings=[])
            return EXIT_CODES.get("refused", 1)
        where = f" ({exc.filename})" if getattr(exc, "filename", None) else ""
        _emit(as_json, command=command, ok=False, code="sandbox_denied", bank=bank_name, data=None,
              text=f"This shell may not use the memory folder{where}. Where the shell is sandboxed, "
                   "use Cicada's MCP tools instead.", warnings=[])
        return EXIT_CODES["sandbox_denied"]
    except Exception as exc:  # noqa: BLE001 - the class only: a message can carry memory text
        _emit(as_json, command=command, ok=False, code="internal", bank=bank_name, data=None,
              text=f"Internal error ({type(exc).__name__}).", warnings=[])
        return EXIT_CODES["internal"]
    _emit(as_json, command=command, ok=result.ok, code=result.code, bank=bank_name, data=result.data,
          text=result.text, warnings=result.warnings)
    return 0 if result.ok else EXIT_CODES.get(result.code, 1)


def run() -> int:
    """`python -m api.cli`: library logging is kept to warnings on stderr (JSON mode silences it entirely)."""
    try:
        from loguru import logger

        logger.remove()
        logger.add(sys.stderr, level="WARNING")
    except Exception:  # noqa: BLE001
        pass
    return main()


if __name__ == "__main__":
    sys.exit(run())
