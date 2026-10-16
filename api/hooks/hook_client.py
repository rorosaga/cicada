"""A hook on a client machine: where it sends, with which token, and what it does when the server is away (G181 phase 2).

Only when ``CICADA_API_BASE`` is set (``runtime_layout.is_client``). Unset, every hook keeps its loopback request,
its ``api_token`` read and its log lines byte for byte, and nothing here runs.

* **Where:** ``runtime_layout.api_base`` (https, or http only to a loopback address) — the one rule the stdio MCP
  server and the `cicada` command read too. An invalid value is logged as the rule it broke, never as the value.
* **Token:** this device's own (``CICADA_API_TOKEN``, else ``$CICADA_HOME/device_token``), never the server's master
  token (owner ruling 1, 2026-10-16).
* **Away:** a post that does not land (refused connection, timeout, 401/403/409/5xx) goes to the spool
  (``hook_spool.py``) under ``$CICADA_HOME``, and the next firing flushes it, oldest first, inside the hook's own time
  budget. A resend is safe: the server dedupes a session by its content hash and refuses a stale snapshot as
  ``superseded``; a per-turn post is kept in order behind anything already waiting.

Stdlib at import. ``runtime_layout`` (stdlib only) and, for a session, Cicada's own extractor (``session_post``) are
imported from this checkout by path only in client mode — the transcript rail, amended: the session is read here, on
the machine it lives on, and only what the extractor keeps is sent.
"""
from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Statuses a resend can never fix: the request itself is wrong. Anything else (a refused connection, a timeout,
#: 401/403 while a token is being replaced, a 409 while only the demo is open, a 5xx) is kept for later.
FINAL_STATUSES = frozenset({400, 404, 405, 413, 422})


def _import_api():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))


def layout():
    _import_api()
    from api.services import runtime_layout

    return runtime_layout


def is_client(environ) -> bool:
    return bool(str(environ.get("CICADA_API_BASE") or "").strip())


def target(environ) -> tuple[str | None, str, str | None]:
    """``(base, token, problem)``: ``problem`` is a short log phrase (never a value) when nothing can be sent now."""
    rl = layout()
    try:
        base = rl.api_base(environ)
    except ValueError as exc:
        return None, "", f"bad CICADA_API_BASE ({exc})"
    token = rl.client_token(environ)
    if not token:
        return base, "", f"no device token (CICADA_API_TOKEN or {rl.DEVICE_TOKEN_FILE})"
    return base, token, None


def send(url: str, body: bytes, token: str, timeout: float) -> tuple[int | None, str]:
    """POST; ``(None, "")`` when no answer came (refused, unreachable, timed out) — the spool's signal."""
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:  # noqa: S310 - the person's own server
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        return None, ""


def landed(status: int | None) -> bool:
    return status is not None and 200 <= status < 300


def keep(status: int | None) -> bool:
    """Should a post that did not land be kept for a resend?"""
    return not landed(status) and status not in FINAL_STATUSES


def read_session(harness: str, session_id: str, transcript_path: str) -> tuple[dict | None, int, str | None]:
    """Cicada's own extractor on this machine's transcript: ``(conversation, bytes read, refusal)``. A refusal is the
    backend's own enum (``outside_root``, ``stem_mismatch``…): the path is not the harness's file for this session,
    and nothing was read."""
    _import_api()
    from api.services import session_post
    from api.services.transcript_capture import TranscriptRefused

    try:
        wire, read_bytes = session_post.read_local(harness, session_id, transcript_path)
    except TranscriptRefused as exc:
        return None, 0, exc.reason
    return wire, read_bytes, None


def outcome(text: str) -> str:
    try:
        parsed = json.loads(text)
        value = parsed.get("status") or parsed.get("detail") or ""
        return value if isinstance(value, str) else "invalid request"
    except (ValueError, AttributeError):
        return ""


def deliver_turn(home: Path, route: str, body: dict, *, environ, post=None, timeout: float,
                 flush_budget: float = 0.0) -> str:
    """A per-turn post from a client (Cursor's hook): in order behind any turn already waiting, spooled when the
    server does not answer, flushed only when ``flush_budget`` allows it (a prompt hook holds the person's message,
    so it never waits on a flush). Returns the log line's outcome — an enum or a status, never content."""
    import time

    import hook_spool as spool

    post = post or send
    started = time.monotonic()
    base, token, problem = target(environ)
    if problem:
        spool.put(home, route, body)
        return f"spooled: {problem}"

    def one(r: str, b: dict, t: float) -> int | None:
        try:
            return post(base + r, json.dumps(b).encode("utf-8"), token, t)[0]
        except Exception:  # noqa: BLE001 - no answer
            return None

    def size_of(_path, fallback: int) -> int:
        return fallback

    if spool.has_turns(home):
        spool.put(home, route, body)
        if flush_budget > 0:
            deadline = started + flush_budget
            sent, _final, left = spool.flush(home, lambda r, b: one(r, b, max(0.1, min(timeout, deadline -
                                                                                        time.monotonic() - 0.1))),
                                             deadline=deadline, keep=keep, size_of=size_of)
            return f"queued behind waiting turns: sent {sent}, {left} waiting"
        return "queued behind waiting turns"
    status = one(route, body, timeout)
    if landed(status):
        return f"http {status}"
    if keep(status):
        spool.put(home, route, body)
        return "spooled: " + ("no answer" if status is None else f"http {status}")
    return f"http {status}"
