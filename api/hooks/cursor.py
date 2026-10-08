#!/usr/bin/env python3
"""Local interactive Cursor sessionStart adapter (docs/hooks v1, 2026-10-08).

Stdlib, run by path. Only startup context: no transcript reads, stop/prompt/
response capture or tool events. User-hook cwd is ~/.cursor, not workspace cwd.
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

INPUT_BYTES = 64 * 1024
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}")


def _cwd(roots):
    if not isinstance(roots, list) or len(roots) != 1:
        return None
    value = roots[0]
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 4096 \
            or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    return value


def main(argv=None, *, stdin=None, stdout=None, environ=None, post=None):
    environ = os.environ if environ is None else environ
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    post = _default_post if post is None else post
    home = Path(environ.get("CICADA_HOME") or (Path(environ.get("HOME") or str(Path.home())) / ".cicada"))
    log = home / "logs" / "recall.log"
    out = {}
    reason = "skipped"
    try:
        if any(_off(environ, key) for key in ("CICADA_CAPTURE", "CICADA_RECALL")) \
                or str(environ.get("CURSOR_CODE_REMOTE", "")).lower() == "true":
            return 0
        raw = stdin.read(INPUT_BYTES + 1)
        if len(raw.encode("utf-8")) > INPUT_BYTES:
            return 0
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("hook_event_name") != "sessionStart" \
                or payload.get("is_background_agent") is not False:
            return 0
        sid = payload.get("conversation_id")
        if not isinstance(sid, str) or not SESSION.fullmatch(sid) or payload.get("session_id") != sid:
            return 0
        token = str(environ.get("CICADA_API_TOKEN") or "").strip()
        if not token:
            try:
                token = (home / "api_token").read_text(encoding="utf-8").strip()
            except OSError:
                pass
        if not token:
            return 0
        cwd = _cwd(payload.get("workspace_roots"))
        body = {"event": "session_start", "harness": "cursor", "session_id": sid, "cwd": cwd, "source": "startup"}
        workspace = observe_if_needed(cwd, home=home, environ=environ, harness="cursor", session_id=sid,
                                      startup=True) if cwd else None
        if workspace is not None:
            body["workspace"] = workspace
        port = str(environ.get("CICADA_PORT") or "8000")
        status, text = post(f"http://127.0.0.1:{port}/capture/hook-context", json.dumps(body).encode(), token, TIMEOUT_S)
        reason = "http_error"
        if status == 200:
            remember(home, "cursor", sid, workspace, environ=environ)
            parsed = json.loads(text)
            context = parsed.get("additionalContext") if isinstance(parsed, dict) else None
            if isinstance(context, str) and context.strip() and len(context) <= 7200:
                out = {"additional_context": context}
                reason = "delivered"
            else:
                reason = "empty"
    except Exception as exc:  # fail open; exception messages can contain private input
        reason = type(exc).__name__
    finally:
        _log(log, f"cursor startup_adapter {reason}")
        stdout.write(json.dumps(out) + "\n")
        stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
