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
bank, 5 sandbox denied, 70 internal (the exception's class name only, never its message).
"""
from __future__ import annotations

import argparse
import contextvars
import io
import json
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from api.services import cli_map
from api.version import __version__

SCHEMA = "cicada.cli/1"
ROOT_KEYS = ("CICADA_MEMORY_PATH", "CICADA_MEMORY_ROOT")
DEFAULT_ROOT = "~/cicada/memory"
HEALTH_TIMEOUT_S = 1.0
EXIT_CODES = {"usage": 2, "not_found": 1, "empty_graph": 1, "bank_mismatch": 3, "root_mismatch": 3,
              "demo_bank": 4, "sandbox_denied": 5, "internal": 70, "bootstrap": 70}
_HINTS = re.compile(r"```cicada-hints\n(.*?)\n```", re.S)


class UsageError(Exception):
    """A malformed command line: exit 2."""


class Refusal(Exception):
    """A rule said no before anything was read or written."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BootstrapError(Exception):
    """The command could not establish one root and one bank."""


class _HelpShown(Exception):
    pass


@dataclass
class Result:
    text: str
    data: dict | None
    warnings: list[str] = field(default_factory=list)


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


def bootstrap(environ=None) -> Boot:
    """PLAN §3.3. ``environ`` is the process environment (``Settings`` reads ``os.environ``)."""
    environ = os.environ if environ is None else environ
    try:
        caller_cwd = os.getcwd()
    except OSError:          # the caller's folder was deleted under it
        caller_cwd = None
    environ["LITELLM_MODE"] = "PRODUCTION"      # litellm's import-time load_dotenv() stays off

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

    raw, source = resolve_root(environ, file_values)
    for key, value in file_values.items():     # the app-spawned dev backend's overlay: the file wins
        if key not in ROOT_KEYS:
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

    from api.services import bank_registry, runtime_layout

    ctx = contextvars.copy_context()
    pin = ctx.run(bank_registry.pin_request_bank, canonical)
    settings_root = ctx.run(lambda: Path(config.get_settings().memory_root))
    if settings_root != canonical:
        raise BootstrapError("the settings root and the pinned root differ")
    return Boot(caller_cwd=caller_cwd, root=canonical, root_source=source, distribution=distribution,
                pin=pin, ctx=ctx, backend_url=runtime_layout.backend_url(environ))


def _opener():
    import urllib.request

    return urllib.request.build_opener(urllib.request.ProxyHandler({}))   # loopback never goes through a proxy


def probe_backend(url: str, root: Path, timeout: float = HEALTH_TIMEOUT_S) -> dict:
    """Ask a running backend which memory root it serves. ``backend_down`` only on a refused
    connection; a timeout or an error answer is ``unverified``, never "no backend"."""
    import socket
    import urllib.error

    try:
        with _opener().open(f"{url}/healthz", timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return {"state": "unverified"}
    except urllib.error.URLError as exc:
        return {"state": "backend_down" if isinstance(exc.reason, ConnectionRefusedError) else "unverified"}
    except ConnectionRefusedError:
        return {"state": "backend_down"}
    except (TimeoutError, socket.timeout, OSError, ValueError):
        return {"state": "unverified"}
    reported = body.get("memoryRoot") if isinstance(body, dict) else None
    if not isinstance(reported, str) or not reported.strip():
        return {"state": "unverified"}
    same = os.path.realpath(os.path.expanduser(reported)) == os.path.realpath(root)
    out = {"state": "confirmed" if same else "mismatch"}
    if isinstance(body.get("version"), str):
        out["version"] = body["version"]
    return out


def _backend_headers(environ=None) -> dict[str, str]:
    from api.services import runtime_layout

    environ = os.environ if environ is None else environ
    token = (environ.get("CICADA_API_TOKEN") or "").strip()
    if not token:
        try:
            token = (runtime_layout.cicada_home(environ) / "api_token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    return {"Authorization": f"Bearer {token}"} if token else {}


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

def _tool_context(boot: Boot):
    from api.services import mcp_tools

    path = boot.pin.path
    return mcp_tools.ToolContext(memory_path=lambda: path, session_id="", harness="unknown",
                                 read_surface="cli", available=cli_map.exposed_tools(),
                                 headers=lambda: {"Content-Type": "application/json", **_backend_headers()},
                                 backend_url=boot.backend_url)


def _vector_state(bank: Path) -> str:
    db = bank / "vector_index.db"
    if not db.exists():
        return "absent"
    try:
        from api.services.vector_index import SqliteVecIndexer

        return "present" if SqliteVecIndexer(bank).index_info() else "empty"
    except Exception:  # noqa: BLE001
        return "unreadable"


def _hints_data(text: str) -> dict:
    match = _HINTS.search(text)
    payload = {}
    if match:
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            payload = {}
    return {"suggested_entities": payload.get("suggested_entities", []),
            "relevant_hub": payload.get("relevant_hub"),
            "hub_members_preview": payload.get("hub_members_preview", []),
            "state": payload.get("state")}


def cmd_recall(boot: Boot, args) -> Result:
    from api.services import mcp_tools

    text = mcp_tools.recall(_tool_context(boot), args.query)
    warnings = _root_warnings(boot)
    if _vector_state(boot.pin.path) != "present":
        warnings.append("degraded:vector")
    return Result(text=text, data=_hints_data(text), warnings=warnings)


_VERIFIED_WORDS = {"confirmed": "matches the app's backend", "mismatch": "the app's backend uses a DIFFERENT folder",
                   "backend_down": "the app's backend is not running", "unverified": "the app's backend did not answer"}


def cmd_status(boot: Boot, args) -> Result:
    from api.services import agentic_write, demo_guard

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
    lines.append(f"cicada {__version__} ({boot.distribution})")
    return Result(text="\n".join(lines), data=data, warnings=_root_warnings(boot))


def cmd_commands(boot: Boot | None, args) -> Result:
    catalog = cli_map.catalog()
    exposed = [c for c in catalog if c["exposed"]]
    later = [c for c in catalog if not c["exposed"]]
    width = max(len(c["command"]) for c in catalog) + 2

    def line(c):
        return f"  {c['command']:<{width}}{(c['mirrors'] or '(CLI only)'):<26}{c['summary']}"

    text = "\n".join(["Commands:", *map(line, exposed), "", "Not in this command line yet (use the MCP tool):",
                      *map(line, later)])
    return Result(text=text, data={"commands": catalog})


#: name → (handler, needs a bank). A test may swap a handler.
COMMANDS: dict[str, Callable] = {"recall": cmd_recall, "status": cmd_status, "commands": cmd_commands}
_NO_BOOT = {"commands"}


# --- parsing ------------------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)

    def exit(self, status=0, message=None):
        if status:
            raise UsageError((message or "").strip() or "invalid command line")
        raise _HelpShown()


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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = _wants_json(argv)
    parser = build_parser()
    command: str | None = None
    try:
        try:
            args = parser.parse_args(argv)
        except _HelpShown:
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
        if command == "recall" and not args.query.strip():
            raise UsageError("the query is empty")
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
                except Exception as exc:  # noqa: BLE001
                    raise BootstrapError(type(exc).__name__) from None
                bank_name = boot.pin.name
                _check_bank(boot, args.bank if args.bank is not None else os.environ.get("CICADA_BANK"))
                boot.probe = probe_backend(boot.backend_url, boot.root)
                result = boot.ctx.run(handler, boot, args)
    except Refusal as exc:
        _emit(as_json, command=command, ok=False, code=exc.code, bank=bank_name, data=None, text=str(exc),
              warnings=[])
        return EXIT_CODES.get(exc.code, 1)
    except BootstrapError as exc:
        _emit(as_json, command=command, ok=False, code="bootstrap", bank=None, data=None,
              text=f"Could not open the memory ({exc}).", warnings=[])
        return EXIT_CODES["bootstrap"]
    except PermissionError as exc:
        where = f" ({exc.filename})" if getattr(exc, "filename", None) else ""
        _emit(as_json, command=command, ok=False, code="sandbox_denied", bank=bank_name, data=None,
              text=f"This shell may not use the memory folder{where}. Where the shell is sandboxed, "
                   "use Cicada's MCP tools instead.", warnings=[])
        return EXIT_CODES["sandbox_denied"]
    except Exception as exc:  # noqa: BLE001 - the class only: a message can carry memory text
        _emit(as_json, command=command, ok=False, code="internal", bank=bank_name, data=None,
              text=f"Internal error ({type(exc).__name__}).", warnings=[])
        return EXIT_CODES["internal"]
    _emit(as_json, command=command, ok=True, code=None, bank=bank_name, data=result.data, text=result.text,
          warnings=result.warnings)
    return 0


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
