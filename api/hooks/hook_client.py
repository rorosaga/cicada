"""A hook on a client machine: where it sends, with which token, and what it does when the server is away (G181 phase 2).

Only when ``CICADA_API_BASE`` is set, or the app's ``$CICADA_HOME/api_base`` names a server (``runtime_layout.is_client``,
G181 phase 3). Unset, every hook keeps its loopback request,
its ``api_token`` read and its log lines byte for byte, and nothing here runs.

* **Where:** ``runtime_layout.api_base`` (https, or http only to a loopback address) — the one rule the stdio MCP
  server and the `cicada` command read too. An invalid value is logged as the rule it broke, never as the value.
* **Token:** this device's own (``CICADA_API_TOKEN``, else ``$CICADA_HOME/device_token``), never the server's master
  token (owner ruling 1, 2026-10-16).
* **Away:** a post that does not land (refused connection, timeout, 401/403/409/5xx) goes to the spool
  (``hook_spool.py``) under ``$CICADA_HOME``, and the next firing flushes it, oldest first, inside the hook's own time
  budget. A resend is safe: the server dedupes a session by its content hash and refuses a stale snapshot as
  ``superseded``; a per-turn post is kept in order behind anything already waiting.
* **Whose:** each waiting post names the server (and, once heard, the bank) it was captured for, and goes only there
  (D1, G202: ``hook_spool``). Besides a hook's firing, a successful MCP or command-line call from this machine flushes
  what waits for the server it reached (:func:`flush_waiting`, D3).

Stdlib at import. ``runtime_layout`` (stdlib only) and, for a session, Cicada's own extractor (``session_post``) are
imported from this checkout by path only in client mode — the transcript rail, amended: the session is read here, on
the machine it lives on, and only what the extractor keeps is sent.
"""
from __future__ import annotations

import json
import os
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


def raw_base(environ) -> str:
    """``CICADA_API_BASE``, else the app's ``$CICADA_HOME/api_base`` (G181 phase 3: the person chose *A server* in the
    app), else "" — ``runtime_layout._raw_base``'s rule restated in stdlib so a hook on one machine decides without
    importing the backend (``test_headless_app`` pins the two equal). A bare dict that names no ``CICADA_HOME`` never
    reaches the person's home."""
    import os

    raw = str(environ.get("CICADA_API_BASE") or "").strip()
    if raw:
        return raw
    home = str(environ.get("CICADA_HOME") or "").strip()
    if environ is not os.environ and not home:
        return ""
    folder = Path(home).expanduser() if home else Path.home() / ".cicada"
    try:
        return (folder / "api_base").read_bytes().decode("utf-8", "replace").strip()
    except OSError:
        return ""


def is_client(environ) -> bool:
    return bool(raw_base(environ))


def spool_module():
    """``hook_spool``: the sibling a hook already imported by path, else the package module (the backend's side — the
    stdio MCP server and the `cicada` command flush through here too). Both are the same file; its state is on disk."""
    mod = sys.modules.get("hook_spool")
    if mod is not None:
        return mod
    try:
        from api.hooks import hook_spool as mod
    except ImportError:
        import hook_spool as mod
    return mod


def bank_in(text: str) -> str | None:
    """The bank a capture answer says it filed the post in (``bankId``, additive since G202), or None."""
    try:
        value = json.loads(text).get("bankId")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is never followed. urllib re-sends a redirected POST as a GET, with the ``Authorization`` header, to
    wherever ``Location`` points (another host, plain http), and that GET's 200 would read as delivered. The 3xx is the
    answer instead: the token stays with the server it was meant for, and the post is kept for a resend."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def opener():
    """The person's own server, straight: no proxy from the environment, no redirect followed."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def send(url: str, body: bytes, token: str, timeout: float) -> tuple[int | None, str]:
    """POST; ``(None, "")`` when no answer came (refused, unreachable, timed out) — the spool's signal."""
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with opener().open(req, timeout=timeout) as resp:  # noqa: S310 - the person's own server
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        return None, ""


def landed(status: int | None) -> bool:
    return status is not None and 200 <= status < 300


def why(status: int | None) -> str:
    """The log phrase for a post that was kept: a status or an enum, never content. A 3xx says what to change."""
    if status is None:
        return "no answer"
    if 300 <= status < 400:
        return (f"http {status} (a redirect, never followed with the token: "
                "set CICADA_API_BASE to the server's own address)")
    return f"http {status}"


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


def utc_offset_minutes(stamp=None) -> int | None:
    """This machine's UTC offset in minutes (east positive) at ``stamp`` — an ISO time, the conversation's first turn —
    or now (ruling 34): the server elsewhere mints the episode id, and the day it carries is the person's, here. Rides
    on a ``/capture/session`` or ``/capture/turn`` post as ``utc_offset_minutes`` (additive; a server that predates it
    ignores it). ``None`` when the zone cannot be read."""
    from datetime import datetime, timezone

    moment = None
    if isinstance(stamp, str) and stamp.strip():
        try:
            moment = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
        except ValueError:
            moment = None
    if moment is None or moment.tzinfo is None:
        moment = datetime.now(timezone.utc)
    try:
        offset = moment.astimezone().utcoffset()
    except (ValueError, OverflowError, OSError):
        return None
    return None if offset is None else int(offset.total_seconds() // 60)


def first_stamp(conversation) -> str | None:
    """The first kept turn's time in a session's wire (``session_post.to_wire``), or ``None``."""
    turns = conversation.get("kept") if isinstance(conversation, dict) else None
    for turn in turns if isinstance(turns, list) else []:
        if isinstance(turn, dict) and isinstance(turn.get("ts"), str) and turn["ts"]:
            return turn["ts"]
    return None


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

    spool = spool_module()
    post = post or send
    started = time.monotonic()
    base, token, problem = target(environ)
    meant = spool.target_for(home, base)
    if problem:
        spool.put(home, route, body, target=meant)
        return f"spooled: {problem}"

    def one(r: str, b: dict, t: float) -> tuple[int | None, str]:
        try:
            return post(base + r, json.dumps(b).encode("utf-8"), token, t)
        except Exception:  # noqa: BLE001 - no answer
            return None, ""

    def size_of(_path, fallback: int) -> int:
        return fallback

    flushed = ""
    if spool.has_turns(home, base):
        if flush_budget <= 0:
            spool.put(home, route, body, target=meant)
            return "queued behind waiting turns"
        # The waiting turns go first; this one is sent after them, or waits behind those that still cannot land. It
        # is stamped only after the flush, so a bank the server just refused is never written onto it (#408 review).
        deadline = started + flush_budget
        sent, _final, left = spool.flush(home, lambda r, b: one(r, b, max(0.1, min(timeout, deadline -
                                                                                    time.monotonic() - 0.1))),
                                         deadline=deadline, keep=keep, size_of=size_of, base=base)
        meant = spool.target_for(home, base)
        if spool.has_turns(home, base):
            spool.put(home, route, body, target=meant)
            return f"queued behind waiting turns: sent {sent}, {left} waiting" + elsewhere_note(home, base)
        flushed = f"; spool: sent {sent}, 0 waiting" + elsewhere_note(home, base)
        timeout = max(0.1, min(timeout, deadline - time.monotonic() - 0.1))
    try:
        status, text = post(base + route, json.dumps(body).encode("utf-8"), token, timeout)
    except Exception:  # noqa: BLE001 - no answer
        status, text = None, ""
    if landed(status):
        spool.remember_bank(home, base, bank_in(text))
        return f"http {status}" + flushed
    if keep(status):
        spool.put(home, route, body, target=meant)
        return "spooled: " + why(status) + flushed
    return f"http {status}" + flushed


def elsewhere_note(home: Path, base: str | None) -> str:
    """``"; 2 wait for another server (host)"`` when posts meant for a server this machine no longer points at are
    waiting (D1, G202) — said, never sent here, never dropped. "" when there are none."""
    try:
        other = spool_module().waiting(home, base)["elsewhere"]
    except Exception:  # noqa: BLE001 - a log phrase is never worth a failed hook
        return ""
    total = sum(other.values())
    if not total:
        return ""
    hosts = ", ".join(sorted(h for h in other if h)) or "a server this machine no longer names"
    return f"; {total} wait{'s' if total == 1 else ''} for another server ({hosts})"


#: How long a flush after a tool call or a command may take (D3): the call already answered, so this is spare time.
FLUSH_AFTER_CALL_S = 4.0


def flush_waiting(home: Path, environ, *, budget: float = FLUSH_AFTER_CALL_S, post=None, surface: str = "call"):
    """D3 (G202): this machine just reached its server through MCP or the command line, so the captures waiting for
    that server go now, not only when a hook next fires. ``(sent, left)`` or None when nothing waited for it. Only
    entries meant for this server are sent (``hook_spool.flush`` with its address); one line in the capture log says
    what happened — counts only."""
    import time

    spool = spool_module()
    if not spool.pending(home):
        return None
    base, token, problem = target(environ)
    if problem or not spool.pending_for(home, base):
        return None
    post = post or send
    deadline = time.monotonic() + budget

    def one(r: str, b: dict) -> tuple[int | None, str]:
        remaining = deadline - time.monotonic()
        if remaining <= 0.2:
            return None, ""
        try:
            return post(base + r, json.dumps(b).encode("utf-8"), token, min(3.0, remaining - 0.1))
        except Exception:  # noqa: BLE001 - no answer
            return None, ""

    def size_of(path, fallback: int) -> int:
        try:
            return Path(path or "").stat().st_size
        except (OSError, ValueError):
            return fallback

    sent, _final, left = spool.flush(home, one, deadline=deadline, keep=keep, size_of=size_of, base=base)
    _log_line(home, f"{surface} flush: sent {sent}, {left} waiting" + elsewhere_note(home, base))
    return sent, left


def _log_line(home: Path, message: str) -> None:
    """One line in the capture log (``$CICADA_HOME/logs/capture.log``, 0600) — the hook's own log, so every flush is
    read in one place. Never raises; skipped past 1 MB (the hook rotates it)."""
    import time

    path = Path(home) / "logs" / "capture.log"
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 1024 * 1024:
            return
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n".encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass
