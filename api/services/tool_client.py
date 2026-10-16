"""The client half of the tool door (G181 phase 2): an MCP tool call from this machine, run on the server.

When ``CICADA_API_BASE`` names a backend on another machine, the stdio MCP server never touches a local bank: every
tool goes to ``POST /tools/call`` (``api/routers/tools.py``, ``tool_door``) with this device's token, carrying the
caller's identity (the G48 session, the client's name) and the stdio process's own per-session state (skipped inbox
ids, the once-per-conversation now-view, the revisions ``cicada_pending`` listed), and gets back the same text a local
call would have produced plus the updated state. One body per tool still: the server runs the same ``mcp_tools`` body
a stdio process on the server would.

What stays on this machine is only what lives here: a picture or screenshot an agent saved is read here and sent as
base64 (the server never opens a path a client names), and ``cicada_repo_context`` probes git here, where the
repository is.
"""
from __future__ import annotations

import base64
import json
import os
import socket
from pathlib import Path

from api.services import runtime_layout

DEFAULT_TIMEOUT_S = 60.0
#: Tools that may wait on a model or a fetch on the server.
SLOW_TOOLS = {"cicada_ask": 120.0, "cicada_save_url": 30.0, "cicada_record_watch": 30.0, "cicada_save_design": 60.0}


class ToolClientError(RuntimeError):
    """The server did not run the call. The message is a sentence for the agent; never a token or a body."""


def _read_picture(raw_path, cap: int) -> bytes | str:
    """An agent's own file, read on this machine by the same rule a local call uses (``mcp_tools._design_read_file``:
    refused folders by identity, a regular PNG or JPEG under the cap)."""
    from api.services import mcp_tools

    given = Path(os.path.expanduser(str(raw_path)))
    if not given.is_absolute():
        return "Not saved: give the screenshot's absolute path."
    return mcp_tools._design_read_file(given, runtime_layout.cicada_home(), cap)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _inline_specimens(holder) -> None:
    if not isinstance(holder, dict) or not isinstance(holder.get("specimens"), list):
        return
    from api.services import design_refs

    for item in holder["specimens"]:
        if isinstance(item, dict) and item.get("path") and not item.get("base64"):
            got = _read_picture(item["path"], design_refs.MAX_SPECIMEN_BYTES)
            item.pop("path", None)
            if isinstance(got, bytes):
                item["base64"] = _b64(got)


def _inline_shots(shots) -> str | None:
    from api.services import site_captures

    for shot in shots if isinstance(shots, list) else []:
        if isinstance(shot, dict) and shot.get("path") and not shot.get("base64"):
            got = _read_picture(shot["path"], site_captures.MAX_SHOT_BYTES)
            if isinstance(got, str):
                return got
            shot.pop("path", None)
            shot["base64"] = _b64(got)
    return None


def inline_files(tool: str, arguments: dict) -> dict | str:
    """The arguments with every file the agent named read here and carried as base64; a refusal sentence when a file
    cannot be read (the same sentence a local call gives)."""
    args = json.loads(json.dumps(arguments or {}))      # a deep copy of plain JSON
    if tool in ("cicada_save_design", "cicada_design_search") and args.get("image_path") \
            and not args.get("image_base64"):
        from api.services import design_refs

        got = _read_picture(args.pop("image_path"), design_refs.MAX_IMAGE_BYTES)
        if isinstance(got, str):
            return got
        args["image_base64"] = _b64(got)
    if tool == "cicada_save_design":
        _inline_specimens(args.get("tokens"))
    if tool == "cicada_record_capture":
        refusal = _inline_shots(args.get("shots"))
        if refusal:
            return f"Not recorded: {refusal.removeprefix('Not saved: ').rstrip('.')}."
        _inline_specimens(args.get("design"))
        for page in args.get("pages") if isinstance(args.get("pages"), list) else []:
            if isinstance(page, dict):
                if _inline_shots(page.get("shots")):
                    page["shots"] = []          # one unreadable page drops its pictures, never the visit
                _inline_specimens(page.get("design"))
    return args


def call(tool: str, arguments: dict, *, caller: dict, state: dict, surface: str = "mcp", options: dict | None = None,
         environ=os.environ, timeout: float | None = None) -> dict:
    """POST one call to the server's tool door; the decoded answer ``{text, code, data, state, error}``."""
    import urllib.error
    import urllib.request

    try:
        base = runtime_layout.api_base(environ)
    except ValueError as exc:
        raise ToolClientError(f"Cicada's server address is not usable: {exc}.") from None
    token = runtime_layout.client_token(environ)
    if not token:
        raise ToolClientError("This device has no Cicada token (CICADA_API_TOKEN or ~/.cicada/device_token). "
                              "The person issues one on the server with `cicada device add`.")
    body = json.dumps({"tool": tool, "arguments": arguments or {}, "caller": caller, "state": state,
                       "surface": surface, "options": options or {}}).encode("utf-8")
    req = urllib.request.Request(f"{base}/tools/call", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout or SLOW_TOOLS.get(tool, DEFAULT_TIMEOUT_S)) as resp:
            answer = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ToolClientError("Cicada's server did not accept this device's token; the person may have "
                                  "revoked it (`cicada device list` on the server).") from None
        detail = ""
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
            detail = parsed.get("detail") if isinstance(parsed.get("detail"), str) else ""
        except Exception:  # noqa: BLE001
            pass
        raise ToolClientError(detail or f"Cicada's server could not run this (HTTP {exc.code}).") from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        raise ToolClientError("Cicada's server did not answer. Nothing was read or written; try again when it is "
                              "reachable.") from None
    except ValueError:
        raise ToolClientError("Cicada's server answered something that is not JSON.") from None
    if not isinstance(answer, dict):
        raise ToolClientError("Cicada's server answered something unexpected.")
    return answer
