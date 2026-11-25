"""A hook that still posts a transcript PATH to a computer that keeps a copy (B3, 2026-11-24).

On a copy the hook sends its home the session itself (``hook_client.captures_elsewhere``: it reads the transcript on
the machine that holds it and posts the capped turns to ``/capture/session``). But a hook that cannot tell it runs on a
copy — its ``$CICADA_HOME`` is not the folder the backend keeps ``replica_of`` in, or the copy was configured only in
the backend's own environment — posts the old way, ``/capture/transcript`` with a path, to this computer's own backend.
The home cannot read that path, and a copy refuses every bank write, so the answer was ``409 replica_read_only`` and the
hook (which keeps only a 5xx) let the session go. Here the backend does the hook's client half instead: it validates
the path against the harness root and reads the one transcript (the same rails as the home's own read, ruling 28), and
keeps the session as the hook would have — one entry per session in ``$CICADA_HOME/spool/capture``, the newest — for the
follower to send (``replica._flush_hook_spool``). The answer is ``200 queued``: nothing is lost by the hook not waiting,
and the home still writes one episode per session, stamped with this device.
"""
from __future__ import annotations

import json
from pathlib import Path


class Refused(Exception):
    """The request is not a session of this computer (a ``TranscriptRefused`` reason, or a malformed body)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def keep_session(raw: bytes) -> dict:
    """Read the session ``raw`` (a ``/capture/transcript`` body) names and keep it for the home. ``{"status":
    "queued", ...}`` — ``Refused`` when nothing was read."""
    from api.hooks import hook_client
    from api.services import replica, runtime_layout

    try:
        fields = json.loads(raw or b"{}")
    except ValueError:
        raise Refused("bad_request") from None
    if not isinstance(fields, dict):
        raise Refused("bad_request")
    harness, session_id = fields.get("harness"), fields.get("session_id")
    path = fields.get("transcript_path")
    if harness not in ("claude-code", "codex") or not isinstance(session_id, str) or not session_id.strip() \
            or not isinstance(path, str) or not path:
        raise Refused("bad_request")
    host = fields.get("host") if isinstance(fields.get("host"), str) else None
    conversation, read_bytes, refused = hook_client.read_session(harness, session_id, path, host=host)
    if refused:
        raise Refused(refused)
    if not (conversation or {}).get("kept"):
        # Nothing worth keeping (an empty transcript): the home writes nothing for it either, so nothing is queued —
        # the answer says so and the caller finishes (``local_spool`` counts it; the hook just logs it).
        return {"status": "empty", "episodeId": None}
    body = {"harness": harness, "session_id": session_id, "conversation": conversation,
            "transcript_bytes": read_bytes, "cwd": fields.get("cwd"), "hook_event": fields.get("hook_event")}
    try:
        body["transcript_size"] = max(read_bytes, Path(path).stat().st_size)
    except OSError:
        body["transcript_size"] = read_bytes
    offset = hook_client.utc_offset_minutes(hook_client.first_stamp(conversation))
    if offset is not None:
        body["utc_offset_minutes"] = offset
    if isinstance(fields.get("effort"), str) and fields["effort"].strip():
        body["effort"] = fields["effort"].strip()[:32]
    if fields.get("workspace") is not None:
        body["workspace"] = fields["workspace"]
    if host:
        body["host"] = host
    home = runtime_layout.cicada_home()
    spool = hook_client.spool_module()
    try:
        base = runtime_layout.replica_of()
    except ValueError:
        base = None
    spool.put(home, "/capture/session", body, key=f"{harness}:{session_id}", transcript_path=path,
              target=spool.target_for(home, base))
    replica.wake()                  # the follower sends it now, not on its next poll
    return {"status": "queued", "episodeId": None}
