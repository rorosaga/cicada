#!/usr/bin/env python3
"""Cicada implicit-recall hook (G149): the read side of G105's Stop hook.

Registered by ``install.sh`` (and by the app's Settings → Agents → Remembers
automatically) under ``hooks.SessionStart`` AND ``hooks.UserPromptSubmit`` in
``~/.claude/settings.json`` and ``~/.codex/hooks.json`` as::

    "<venv python>" "<repo>/api/hooks/recall.py" --harness claude-code

One command for both events: the harness's own stdin names the event
(``hook_event_name``, a common input field in Claude Code; Codex's
``SessionStartCommandInput`` / ``UserPromptSubmitCommandInput``, openai/codex
``codex-rs/hooks/src/schema.rs`` @ c098f97). This script POSTs the event, the
session id and, for UserPromptSubmit only, the prompt (``prompt`` in both
harnesses, windowed exactly as ``hook_recall.prompt_window`` reads it) to
``POST /capture/hook-context`` as a JSON body, never a query string. It
prints ``{"hookSpecificOutput": {"hookEventName": …, "additionalContext": …}}``
when the backend has something to say, the one output shape both harnesses
parse (Claude Code's hook reference, read 2026-09-24; Codex's
``output_parser.rs``). Otherwise it prints nothing.

It never blocks and never erases a prompt: exit 0 always, never 2 (exit 2 on
UserPromptSubmit blocks the prompt and erases it). The one request has a
0.9 s timeout, so the whole script stays under about a second; the backend
holds itself to 300 ms and answers "nothing" past that (R-H6).

``CICADA_CAPTURE=off`` (every CLI Cicada itself spawns, G105 R8) and
``CICADA_RECALL=off`` (the person's switch) exit before any request. A Codex
sub-agent's prompt (``agent_id`` set) is the parent agent talking, not the
person, and is skipped (R-H15).

One line per firing goes to ``~/.cicada/logs/recall.log`` (0600, rotated at
1 MB): the time, the harness, the session id's first 8 characters, the event,
the HTTP status, the backend's reason enum, the number of pages and the
latency. It NEVER holds the prompt, a page id or a response body (FastAPI's
422 echoes its input). An error line names the exception class only, because
a message can carry the input (R-H10).

Stdlib only, run by path: a hook has no cwd guarantee and no venv on its
``sys.path``, so nothing here imports ``api.*`` (G105 R14).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_S = 0.9
LOG_MAX_BYTES = 1024 * 1024
HEAD_CHARS = 6000
TAIL_CHARS = 2000
EVENTS = {"SessionStart": "session_start", "UserPromptSubmit": "user_prompt_submit"}
_REASON_RE = re.compile(r"[a-z_]{1,32}")


def _default_post(url: str, body: bytes, token: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - loopback only
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # A 4xx body can echo the prompt back (FastAPI's 422): never read it.
        return exc.code, ""


def _log(path: Path, message: str) -> None:
    """Append one line, 0600, rotating once past :data:`LOG_MAX_BYTES`.
    A log failure must never become a hook failure, so ``OSError`` is swallowed."""
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_suffix(".log.1"))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n".encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


def _window(prompt: str) -> str:
    """``hook_recall.prompt_window``'s rule, restated because this script
    imports nothing: a 1 MB paste never crosses the loopback."""
    if len(prompt) <= HEAD_CHARS + TAIL_CHARS:
        return prompt
    return prompt[:HEAD_CHARS] + "\n" + prompt[-TAIL_CHARS:]


def _off(environ, key: str) -> bool:
    return str(environ.get(key, "")).strip().lower() == "off"


def main(argv=None, *, stdin=None, stdout=None, environ=None, post=None, log_path=None, token_path=None) -> int:
    """Ask the backend for a note and print it; return 0 unconditionally.
    Every collaborator is injectable so the tests run the whole path with no
    network and no real home directory."""
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    post = _default_post if post is None else post
    home = Path(environ.get("CICADA_HOME") or (Path.home() / ".cicada"))
    log_path = log_path or home / "logs" / "recall.log"
    token_path = token_path or home / "api_token"

    harness = "claude-code"
    if "--harness" in argv:
        try:
            harness = argv[argv.index("--harness") + 1]
        except IndexError:
            pass
    tag = f"{harness} ?"
    try:
        for key in ("CICADA_CAPTURE", "CICADA_RECALL"):
            if _off(environ, key):
                _log(log_path, f"{tag} skipped: {key}=off")
                return 0
        try:
            payload = json.loads(stdin.read() or "{}")
        except ValueError:
            _log(log_path, f"{tag} skipped: stdin is not JSON")
            return 0
        if not isinstance(payload, dict):
            _log(log_path, f"{tag} skipped: stdin is not an object")
            return 0
        session_id = str(payload.get("session_id") or "")
        tag = f"{harness} {session_id[:8] or '?'}"
        hook_event = str(payload.get("hook_event_name") or "")
        event = EVENTS.get(hook_event)
        if event is None or not session_id:
            _log(log_path, f"{tag} skipped: not a recall event")
            return 0
        if event == "user_prompt_submit" and payload.get("agent_id"):
            _log(log_path, f"{tag} {event} skipped: a sub-agent's prompt")
            return 0
        token = str(environ.get("CICADA_API_TOKEN") or "").strip()
        if not token:
            try:
                token = token_path.read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
        if not token:
            _log(log_path, f"{tag} {event} skipped: no api_token at {token_path.name}")
            return 0
        prompt = payload.get("prompt")
        body = {
            "event": event,
            "harness": harness,
            "session_id": session_id,
            "cwd": payload.get("cwd") if isinstance(payload.get("cwd"), str) else None,
            "model": payload.get("model") if isinstance(payload.get("model"), str) else None,
            "prompt": _window(prompt) if event == "user_prompt_submit" and isinstance(prompt, str) else None,
        }
        port = str(environ.get("CICADA_PORT") or "8000")
        started = time.monotonic()
        status, text = post(f"http://127.0.0.1:{port}/capture/hook-context", json.dumps(body).encode("utf-8"),
                            token, TIMEOUT_S)
        ms = int((time.monotonic() - started) * 1000)
        reason, pages, context = "-", 0, None
        if status == 200:
            try:
                parsed = json.loads(text)
                raw = str(parsed.get("reason") or "")
                reason = raw if _REASON_RE.fullmatch(raw) else "other"
                pages = len(parsed.get("injected") or [])
                context = parsed.get("additionalContext")
            except (ValueError, AttributeError, TypeError):
                reason = "unparseable"
        if isinstance(context, str) and context.strip():
            stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": hook_event,
                                                            "additionalContext": context}}))
            stdout.flush()
        _log(log_path, f"{tag} {event} http {status} {reason} pages={pages} {ms}ms")
    except Exception as exc:  # noqa: BLE001 - the harness must never see a failure
        _log(log_path, f"{tag} error: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
