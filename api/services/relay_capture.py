"""Real-time capture for apps with no hooks (ruling 32, owner 2026-10-19; amends G105 for hookless apps).

Owner: "Exports should only be a starter seed for users; the usual should always be real-time captures." claude.ai,
ChatGPT and their phone apps run no hook Cicada can install, so the remote connector's instructions ask the app's
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

from api.services import mcp_tools, turn_capture

CHANNEL = "remote"
#: The most one call may carry per turn: the same request bound ``/capture/turn`` holds.
TEXT_MAX_CHARS = turn_capture.TEXT_MAX_CHARS

_REPLIES = {
    "created": "Captured. Keep calling this every turn.",
    "updated": "Captured.",
    "unchanged": "Already captured.",
    "metadata": "Captured.",
    "empty": "Nothing to capture in that turn.",
    "upgraded": "This conversation is already in Cicada from the app's export; nothing to add.",
}


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


def capture_turns(ctx: mcp_tools.ToolContext, message, previous_reply=None, *, app: str | None = None,
                  utc_offset_minutes: int | None = None) -> str:
    """``utc_offset_minutes`` (ruling 34): the person's offset when the app sent a zone hint (:func:`offset_from_meta`),
    so a new relayed episode's id carries their day; without one (claude.ai sends none, and a model's guess is never
    taken) the id takes this server's zone."""
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
        relay={"app": app, "connector": ctx.connector_id, "channel": CHANNEL},
        utc_offset_minutes=utc_offset_minutes)
    if result.status == "refused":
        reason = result.reason or "refused"
        if reason == "demo_bank":
            from api.services import demo_guard

            return mcp_tools.Reply(demo_guard.AGENT_REFUSAL, code="demo_bank")
        return mcp_tools.Reply(f"Not captured ({reason}).", code=reason)
    return mcp_tools.Reply(_REPLIES.get(result.status, "Captured."), code=None,
                           data={"status": result.status, "episode_id": result.episode_id})


