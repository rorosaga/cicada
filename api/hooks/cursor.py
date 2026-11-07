#!/usr/bin/env python3
"""Local interactive Cursor hook: startup context and turn capture (docs/hooks v1).

Stdlib, run by path; one command registered under three events of the user's
``~/.cursor/hooks.json`` (``cursor_registry``):

* ``sessionStart`` — startup context (G149): asks ``POST /capture/hook-context``
  and prints ``{"additional_context": …}``. User-hook cwd is ~/.cursor, not the
  workspace, so the workspace is the one ``workspace_roots`` entry or nothing.
* ``beforeSubmitPrompt`` — the person's turn: ``prompt`` is posted to
  ``POST /capture/turn``. Every output of this script carries
  ``{"continue": true}`` — whatever the event, and even when the payload could
  not be read at all — so a prompt is never held back by Cicada; Cursor ignores
  the key on the other events.
* ``afterAgentResponse`` — the agent's reply: ``text`` is posted the same way.

Capture posts the turn's words, the ``conversation_id`` (the session) and the
``generation_id`` (which run the turn belongs to, so a re-fire is idempotent and
only a run's final reply is kept) — never ``transcript_path``, attachments,
``user_email`` or a thought. Cursor's docs list a ``transcript_path`` on every
hook, but it may be null and nothing documents its format, a confined root or
where the final reply sits in it, while ``prompt`` and ``text`` already are the
two things kept — so it is never forwarded and the backend opens nothing (the
transcripts rail). ``stop``, thoughts and tool events
are never registered. ``CICADA_CAPTURE=off`` stops capture and ``CICADA_RECALL=off``
the startup note (separate switches since 2026-10-23; Cicada's own spawns set both), and a
remote or cloud session (``CURSOR_CODE_REMOTE``) posts nothing. Fails open: every path
exits 0 with valid JSON on stdout, and an exception's message is never logged.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from recall import _default_post, _log, _off, TIMEOUT_S
from workspace_identity import observe_if_needed, remember
import hook_client as remote_client  # G181 phase 2: a client of a server elsewhere (CICADA_API_BASE)
import host_identity  # G228: the app that launched this harness, if any

INPUT_BYTES = 64 * 1024
#: A capture payload carries the person's prompt, which can be a long paste.
CAPTURE_INPUT_BYTES = 1024 * 1024
#: What one turn may post (the backend's ``turn_capture.TEXT_MAX_CHARS``); it keeps ≤16k / ≤2k.
TEXT_MAX_CHARS = 256 * 1024
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}")
TURN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
#: event -> (speaker, the payload field holding the words)
CAPTURE = {"beforeSubmitPrompt": ("user", "prompt"), "afterAgentResponse": ("assistant", "text")}
#: beforeSubmitPrompt holds the person's message until it answers; the reply hook does not.
CAPTURE_TIMEOUT_S = {"beforeSubmitPrompt": 1.2, "afterAgentResponse": 3.0}
#: Only for a payload too large to parse: a quoted key inside a JSON string is escaped, so it never matches.
#: Only for a payload too large to parse; a key quoted inside a JSON string is escaped, so it never matches.
_EVENT_SNIFF = re.compile(r'"hook_event_name"\s*:\s*"(beforeSubmitPrompt|afterAgentResponse|sessionStart)"')


def _cwd(roots):
    if not isinstance(roots, list) or len(roots) != 1:
        return None
    value = roots[0]
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 4096 \
            or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    return value


def _token(environ, home):
    token = str(environ.get("CICADA_API_TOKEN") or "").strip()
    if not token:
        try:
            token = (home / "api_token").read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return token


def _capture(payload, event, *, environ, home, post):
    """Post one turn; return the log line's outcome (an enum or an HTTP status, never content)."""
    speaker, field = CAPTURE[event]
    sid = payload.get("conversation_id")
    if not isinstance(sid, str) or not SESSION.fullmatch(sid):
        return "?", "skipped: no conversation_id"
    text = payload.get(field)
    if not isinstance(text, str) or not text.strip():
        return sid, f"skipped: no {field}"
    client = remote_client.captures_elsewhere(environ)   # a client's server, or a copy's home (G132 phase 1 B)
    token = "" if client else _token(environ, home)
    if not token and not client:
        return sid, "skipped: no api_token"
    gen = payload.get("generation_id")
    body = {"harness": "cursor", "session_id": sid, "hook_event": event,
            "messages": [{"speaker": speaker, "text": text[:TEXT_MAX_CHARS]}],
            "turn_id": gen if isinstance(gen, str) and TURN.fullmatch(gen) else None,
            "cwd": _cwd(payload.get("workspace_roots"))}
    model = payload.get("model")
    if speaker == "assistant" and isinstance(model, str) and model.strip():
        body["model"] = model.strip()[:200]
    host = host_identity.detect(environ)
    if host:
        body["host"] = host
    if client:
        # G181 phase 2: the server is elsewhere; a turn it does not take now waits in the spool, in order. Only the
        # reply hook flushes: the prompt hook holds the person's message.
        offset = remote_client.utc_offset_minutes()
        if offset is not None:
            body["utc_offset_minutes"] = offset   # ruling 34: the id's day is this machine's, not the server's
        return sid, remote_client.deliver_turn(
            home, "/capture/turn", body, environ=environ, post=None if post is _default_post else post,
            timeout=CAPTURE_TIMEOUT_S[event], flush_budget=3.5 if event == "afterAgentResponse" else 0.0)
    port = str(environ.get("CICADA_PORT") or "8000")
    status, answer = post(f"http://127.0.0.1:{port}/capture/turn", json.dumps(body).encode("utf-8"), token,
                          CAPTURE_TIMEOUT_S[event])
    outcome = ""
    try:
        parsed = json.loads(answer)
        detail = parsed.get("status") or parsed.get("detail")
        outcome = str(detail) if isinstance(detail, str) and re.fullmatch(r"[a-z_]{1,32}", detail) else ""
        if parsed.get("redirectedFrom"):
            outcome += f" into {parsed.get('bank')} (the demo memory is open)"
    except (ValueError, AttributeError):
        pass
    return sid, f"http {status} {outcome}".rstrip()


def _startup(payload, *, environ, home, post):
    if payload.get("is_background_agent") is not False:
        return {}, "skipped"
    sid = payload.get("conversation_id")
    if not isinstance(sid, str) or not SESSION.fullmatch(sid) or payload.get("session_id") != sid:
        return {}, "skipped"
    if remote_client.is_client(environ):
        base, token, problem = remote_client.target(environ)
        url = None if problem else f"{base}/capture/hook-context"
    else:
        token = _token(environ, home)
        port = str(environ.get("CICADA_PORT") or "8000")
        url = f"http://127.0.0.1:{port}/capture/hook-context"
    if not token or not url:
        return {}, "skipped"
    cwd = _cwd(payload.get("workspace_roots"))
    body = {"event": "session_start", "harness": "cursor", "session_id": sid, "cwd": cwd, "source": "startup"}
    workspace = observe_if_needed(cwd, home=home, environ=environ, harness="cursor", session_id=sid,
                                  startup=True) if cwd else None
    if workspace is not None:
        body["workspace"] = workspace
    status, text = post(url, json.dumps(body).encode(), token, TIMEOUT_S)
    if status != 200:
        return {}, "http_error"
    remember(home, "cursor", sid, workspace, environ=environ)
    parsed = json.loads(text)
    context = parsed.get("additionalContext") if isinstance(parsed, dict) else None
    if isinstance(context, str) and context.strip() and len(context) <= 7200:
        return {"additional_context": context}, "delivered"
    return {}, "empty"


def main(argv=None, *, stdin=None, stdout=None, environ=None, post=None):
    environ = os.environ if environ is None else environ
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    post = _default_post if post is None else post
    home = Path(environ.get("CICADA_HOME") or (Path(environ.get("HOME") or str(Path.home())) / ".cicada"))
    # Whatever happens below, a prompt is never blocked: an event that cannot be
    # read (oversized prompt-first JSON, bad UTF-8, a list) still answers continue.
    out = {"continue": True}
    event = None
    reason = "skipped"
    sid, outcome = "?", "skipped"
    try:
        raw = stdin.read(CAPTURE_INPUT_BYTES + 1)
        size = len(raw.encode("utf-8"))
        payload = None
        if size <= CAPTURE_INPUT_BYTES:
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = None
        if isinstance(payload, dict):
            event = payload.get("hook_event_name") if isinstance(payload.get("hook_event_name"), str) else None
        elif size > CAPTURE_INPUT_BYTES:
            # Too large to read whole: the event name is still found, so the prompt
            # hook answers ``continue`` and the log says why nothing was saved.
            sniffed = _EVENT_SNIFF.search(raw)
            event = sniffed.group(1) if sniffed else None
        remote = str(environ.get("CURSOR_CODE_REMOTE", "")).lower() == "true"
        if event in CAPTURE:
            if _off(environ, "CICADA_CAPTURE"):
                outcome = "skipped: CICADA_CAPTURE=off"
            elif remote:
                outcome = "skipped: remote session"
            elif not isinstance(payload, dict):
                outcome = "skipped: payload too large"
            else:
                sid, outcome = _capture(payload, event, environ=environ, home=home, post=post)
            return 0
        if _off(environ, "CICADA_RECALL") or remote or size > INPUT_BYTES:
            return 0
        if not isinstance(payload, dict) or event != "sessionStart":
            return 0
        startup_out, reason = _startup(payload, environ=environ, home=home, post=post)
        out = {"continue": True, **startup_out}
    except Exception as exc:  # fail open; exception messages can contain private input
        reason = outcome = f"error: {type(exc).__name__}" if event in CAPTURE else type(exc).__name__
    finally:
        if event in CAPTURE:
            # capture.py's line shape: harness, session prefix, event, outcome — never content.
            _log(home / "logs" / "capture.log", f"cursor {sid[:8]} {event} {outcome}")
        else:
            _log(home / "logs" / "recall.log", f"cursor startup_adapter {reason}")
        stdout.write(json.dumps(out) + "\n")
        stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
