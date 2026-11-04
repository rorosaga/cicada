"""Real-time capture for apps with no hooks (rulings 32 and 57; amends G105 for those apps only).

Owner: "Exports should only be a starter seed for users; the usual should always be real-time captures." claude.ai,
ChatGPT, their phone apps and the Claude desktop app run no hook Cicada can install, so the remote connector's contract
and the desktop app's local primer (ruling 57, :func:`local_relay_allowed`) ask the app's
model to call ``cicada_capture_turns`` on every turn with the person's message, verbatim, and its own previous reply.
This module is that tool's body; the words go through the same writer as a Cursor or Gemini CLI hook
(``turn_capture.capture_turns``): cleaned and scrubbed like a transcript turn, 16k for the first person message and
2k for every other turn, the session cap, one episode per conversation (G104) keyed by the conversation handle the
handshake minted, a re-sent turn changing nothing.

What differs from a hook, and why (the coordinator's conservative default until the owner says otherwise):

* **Relayed, not heard.** A model relayed the words and may paraphrase, so the episode declares
  ``evidence_kind: assistant`` and carries ``relay: {app, connector, channel, first}``. Its words are stored,
  searchable and read by Sleep, but never counted as the person's own — not for promotion's own-words rung and not
  for ruling 29's settling.
* **An export upgrades it.** ``relay.first`` is the match key of the first person message
  (``turn_capture.relay_match_key``); importing the same conversation from the app's export rewrites this episode in
  place with the export's words, which are the person's (``episode_staging``), instead of adding a second copy.
* **Like a hook, not like a remote write:** no commit of its own (as every captured session) and no Sleep gate —
  an episode written while Sleep runs is read by the next one, exactly as a Stop hook's is. The demo guard holds.

No LLM anywhere; nothing here logs a word of the conversation.
"""
from __future__ import annotations

import dataclasses
import os
import re
import secrets
from datetime import date

from api.services import mcp_tools, session_identity, turn_capture

TOOL = "cicada_capture_turns"
CHANNEL = "remote"
#: Ruling 57: the Claude desktop app's own local server. One stdio process serves all its chats, so a chat's handle
#: comes from this tool (``conversation="new"``), never from the process. Its chats are claude.ai's, so ``app`` is the
#: remote connector's, and that account's export upgrades them.
LOCAL_CHANNEL = "local"
LOCAL_APP = "claude"
LOCAL_HARNESS = "claude-desktop"
NEW_CONVERSATION = "new"
LOCAL_HANDLE_RE = re.compile(r"^lc_\d{4}-\d{2}-\d{2}_[0-9a-f]{8}$")
#: The most one call may carry per turn: the same request bound ``/capture/turn`` holds.
TEXT_MAX_CHARS = turn_capture.TEXT_MAX_CHARS

_REPLIES = {
    # Said once per conversation, so the person sees it in words (ruling 57): connecting an app is no consent to a
    # tool they never saw named.
    "created": "Captured. Keep calling this every turn. Say once, in a few words, that this chat is being kept in "
               "their Cicada memory.",
    "updated": "Captured.",
    "unchanged": "Already captured.",
    "metadata": "Captured.",
    "empty": "Nothing to capture in that turn.",
    "upgraded": "This conversation is already in Cicada from the app's export; nothing to add.",
    "elsewhere": "This conversation is already being kept through this app's other Cicada connection. Stop calling "
                 "this tool here.",
}


def local_relay_allowed(client_name: str | None, harness: str | None, *, env=None) -> bool:
    """Ruling 57: whether a stdio client is offered, and asked for, ``cicada_capture_turns``. An allow-list that fails
    closed: only a client whose ``clientInfo.name`` is exactly the desktop app's (``handshake.CLIENT_VARIANTS``), and
    only while nothing says it is a harness with a hook. ``clientInfo`` is self-reported, so Claude Code calling itself
    ``claude-ai`` is still told apart by the session id it injects (``session_identity``), and any session a harness
    named for itself counts the same: a second copy of a hook-captured turn is the failure this exists to prevent. An
    unknown or unnamed client is not offered it. ``CICADA_CAPTURE=off`` in the server's environment is the capture
    switch every hook already answers to. ``env={}`` for a caller whose environment is another machine's (the door)."""
    from api.services import handshake

    if handshake.variant_for(client_name) != "desktop" or str(harness or "unknown").strip().lower() != "unknown":
        return False
    env = os.environ if env is None else env
    named = session_identity.parse(env)
    return not (named.session_id or named.harness) and str(env.get("CICADA_CAPTURE", "")).strip().lower() != "off"


def _keep_replies() -> bool:
    try:
        from api.config import get_settings

        return bool(get_settings().capture_assistant_replies)
    except Exception:  # noqa: BLE001 — the setting's default
        return True


#: The one zone hint a hookless app is documented to send with a tool call (ruling 34): ChatGPT's Apps SDK puts a coarse
#: ``openai/userLocation`` object in the request's ``_meta``, whose ``timezone`` is an IANA name. claude.ai sends none.
ZONE_HINT_KEY = "openai/userLocation"


def offset_from_meta(meta) -> int | None:
    """The person's UTC offset in minutes now, from a tool call's ``_meta`` zone hint; ``None`` without one.

    Only the zone name is read — never the city, region or coordinates beside it — and nothing of it is stored or
    logged: it decides which day a new relayed episode's id carries and nothing else. A hint, never a reason to refuse
    a capture: an unknown zone is ``None`` and the id takes this server's zone, as before."""
    from api.services import episode_ids

    if not isinstance(meta, dict):
        return None
    hint = meta.get(ZONE_HINT_KEY)
    return episode_ids.zone_offset_minutes(hint.get("timezone")) if isinstance(hint, dict) else None


def _project_word(value) -> str | None:
    text = " ".join(value.split()) if isinstance(value, str) else ""
    return text[:120] or None


def capture_turns(ctx: mcp_tools.ToolContext, message, previous_reply=None, *, app: str | None = None,
                  utc_offset_minutes: int | None = None, project=None, channel: str = CHANNEL,
                  queue_index: bool = True) -> str:
    """``utc_offset_minutes`` (ruling 34): the person's offset when the app sent a zone hint (:func:`offset_from_meta`),
    so a new relayed episode's id carries their day; without one (claude.ai sends none, and a model's guess is never
    taken) the id takes this server's zone. ``project`` (ruling 45 addendum): the relaying app's own word on which
    project the conversation is in — kept on the episode as the app said it (``relay.project``), a conversation signal
    labelled "the app said", never the person's words. ``queue_index=False``: a stdio process with no backend to
    index it; Sleep's own sync covers the conversation, and no process but the backend runs that worker."""
    memory_path = ctx.memory_path()
    text = message if isinstance(message, str) else ""
    if not text.strip():
        return mcp_tools.Reply("Nothing captured: `message` must be the person's message, word for word.",
                               code="empty")
    reply = previous_reply if isinstance(previous_reply, str) and previous_reply.strip() else None
    turns = ([turn_capture.Posted("assistant", reply[:TEXT_MAX_CHARS])] if reply else []) + [
        turn_capture.Posted("user", text[:TEXT_MAX_CHARS])]
    result = turn_capture.capture_turns(
        memory_path, harness=ctx.harness, session_id=ctx.session_id, turns=turns,
        keep_assistant=_keep_replies(), bank=memory_path.name,
        bank_paths=None,  # a relayed conversation is no workspace session: the continuity registry stays out
        relay={"app": app, "connector": ctx.connector_id, "channel": channel, "project": _project_word(project),
               "device": ctx.device_id},
        utc_offset_minutes=utc_offset_minutes)
    if result.status == "refused":
        reason = result.reason or "refused"
        if reason == "demo_bank":
            from api.services import demo_guard

            return mcp_tools.Reply(demo_guard.AGENT_REFUSAL, code="demo_bank")
        return mcp_tools.Reply(f"Not captured ({reason}).", code=reason)
    # G207: a relayed conversation has no end event — its quick read waits for the quiet window.
    from api.services import awake_read

    if queue_index:
        awake_read.after_capture(memory_path, result.episode_id, status=result.status)
    return mcp_tools.Reply(_REPLIES.get(result.status, "Captured."), code=None,
                           data={"status": result.status, "episode_id": result.episode_id})


def capture_local(ctx: mcp_tools.ToolContext, message, previous_reply=None, conversation=None, project=None,
                  *, queue_index: bool = True) -> str:
    """Ruling 57: one turn from the Claude desktop app's local connection, as ``claude-desktop``, never the process's
    own ``unknown`` session. ``conversation`` is ``"new"`` on a chat's first call and the handle the reply gave after,
    so one process's chats stay one episode each and a chat outlives the process (G104)."""
    raw = conversation.strip() if isinstance(conversation, str) else ""
    started = raw == NEW_CONVERSATION
    if not started and not LOCAL_HANDLE_RE.match(raw):
        return mcp_tools.Reply('Nothing captured: pass conversation="new" on this chat\'s first call, then the handle '
                               "the reply gives.", code="invalid_arguments")
    handle = f"lc_{date.today().isoformat()}_{secrets.token_hex(4)}" if started else raw
    relayed = dataclasses.replace(ctx, harness=LOCAL_HARNESS, session_id=handle)
    reply = capture_turns(relayed, message, previous_reply, app=LOCAL_APP, project=project, channel=LOCAL_CHANNEL,
                          queue_index=queue_index)
    data = getattr(reply, "data", None)
    if started and isinstance(data, dict) and data.get("status") in ("created", "updated", "unchanged", "metadata"):
        return mcp_tools.Reply(f'{reply} Pass conversation="{handle}" on every later turn of this chat.', code=None,
                               data={**data, "conversation": handle})
    return reply


