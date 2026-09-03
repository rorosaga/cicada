#!/usr/bin/env python3
"""Cicada session-capture hook (G105 R1, R2, R8, R14).

Registered by ``install.sh`` under ``hooks.Stop`` in ``~/.claude/settings.json``
(and ``~/.codex/hooks.json`` when Codex is installed) as::

    "<venv python>" "<repo>/api/hooks/capture.py" --harness claude-code

The harness pipes its hook JSON to stdin (``session_id``, ``transcript_path``,
``cwd``, ``hook_event_name``); this script POSTs exactly those fields to
``POST /capture/transcript`` and exits 0 — always, within 3 s, printing
nothing to stdout (a Stop hook's stdout is parsed by the harness). It never
opens the transcript: the backend validates the path against the harness
root and does the one read (R2).

Why ``Stop`` and not ``SessionEnd`` (R1): ``SessionEnd`` only fires on a
graceful exit and shares a 1.5 s budget with every other SessionEnd hook; a
closed terminal or a killed process never reaches it. ``Stop`` fires after
every reply, and the endpoint is idempotent by content hash (R3), so the LAST
Stop of a session is the session's end however it ended — volume is cost,
never noise.

Stdlib only, run by path: a hook has no cwd guarantee and no venv on its
``sys.path``, so nothing here imports ``api.*`` (R14).

``CICADA_CAPTURE=off`` in the environment exits before any request: every
CLI Cicada itself spawns (Sleep's ``claude -p`` engine, doctor probes) runs
under ``connections/base.scrubbed_env()`` which sets it, so Cicada's own
extraction prompts are never captured back into the bank (R8) — without it a
Sleep cycle on a plan engine would fire this hook on its own prompts and
write them back as episodes, a feedback loop.

Codex (R9): its Stop payload is unverified, so a payload without
``transcript_path`` is logged as ``skipped: no transcript_path`` and exits 0
— nothing breaks, and that log line is the verification signal.

One line per firing goes to ``~/.cicada/logs/capture.log`` (0600): a
timestamp, the harness, the first 8 characters of the session id, and the
outcome — never a path, never content. The token comes from
``~/.cicada/api_token``, never from an env-embedded key.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_S = 3.0
LOG_MAX_BYTES = 1024 * 1024


def _default_post(url: str, body: bytes, token: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - loopback only
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx is an outcome to log (the endpoint's enum refusal reason
        # rides in ``detail``), not a hook failure.
        return exc.code, exc.read().decode("utf-8", "replace")


def _log(path: Path, message: str) -> None:
    """Append one line, 0600, rotating once past :data:`LOG_MAX_BYTES`.
    A log failure must never become a hook failure — swallow ``OSError``."""
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


def main(argv=None, *, stdin=None, environ=None, post=None, log_path=None, token_path=None) -> int:
    """Forward the harness payload; return 0 unconditionally.

    Every collaborator is injectable (``stdin``, ``environ``, ``post``,
    ``log_path``, ``token_path``) so the tests exercise the whole path with no
    network and no real home directory (R14).
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    stdin = sys.stdin if stdin is None else stdin
    post = _default_post if post is None else post
    home = Path(environ.get("CICADA_HOME") or (Path.home() / ".cicada"))
    log_path = log_path or home / "logs" / "capture.log"
    token_path = token_path or home / "api_token"

    harness = "claude-code"
    if "--harness" in argv:
        try:
            harness = argv[argv.index("--harness") + 1]
        except IndexError:
            pass
    tag = f"{harness} ?"
    try:
        if str(environ.get("CICADA_CAPTURE", "")).strip().lower() == "off":
            _log(log_path, f"{tag} skipped: CICADA_CAPTURE=off")
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
        transcript_path = payload.get("transcript_path")
        if not session_id or not transcript_path:
            _log(log_path, f"{tag} skipped: no transcript_path")
            return 0
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if not token:
            _log(log_path, f"{tag} skipped: no api_token at {token_path.name}")
            return 0
        port = str(environ.get("CICADA_PORT") or "8000")
        url = f"http://127.0.0.1:{port}/capture/transcript"
        body = json.dumps({
            "harness": harness,
            "session_id": session_id,
            "transcript_path": str(transcript_path),
            "cwd": payload.get("cwd"),
            "hook_event": payload.get("hook_event_name"),
        }).encode("utf-8")
        status, text = post(url, body, token, TIMEOUT_S)
        outcome = ""
        try:
            parsed = json.loads(text)
            outcome = str(parsed.get("status") or parsed.get("detail") or "")
        except (ValueError, AttributeError):
            pass
        _log(log_path, f"{tag} http {status} {outcome}".rstrip())
    except Exception as exc:  # noqa: BLE001 - the harness must never see a failure
        _log(log_path, f"{tag} error: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
