"""Telegram capture connector (Wave B ingestion).

Turns a Telegram message the user forwards/sends to their own bot into a
staged episode or media item in Cicada's queue — the same "episode inbox"
the Awake cycle writes to (see ``mcp/server.py::handle_save_episode``) and the
same media-save path bookmarks/URLs go through (``media_ingestor.ingest_one``,
as used by ``POST /sources/save``).

Two-stage, deliberately separated so the parsing/routing logic is testable
without a live bot, a webhook, or the network:

1. ``parse_telegram_update`` — pure parse of a Telegram Bot API ``update``
   object into ``{text, urls, date, from_self}``. No I/O, no side effects.
2. ``ingest_telegram_update`` — routes the parsed message: a URL present ->
   saved as media (``origin="telegram"``); otherwise the text is staged as an
   episode (``origin="telegram"``, ``processed: false``). Both writer calls
   are injectable (``save_url_fn`` / ``save_episode_fn``) so tests never touch
   the real filesystem, network, or a live bot — the defaults are the only
   code path that does.

Token-gating lives one layer up, in ``api/routers/capture.py`` /
``Settings.telegram_enabled`` — this module has no opinion on whether the
connector is "activated"; it just parses+emits whatever update it is given.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import markdown_parser

# Telegram doesn't ship its own "find URLs in free text" primitive, and
# media_ingestor's URL handling assumes a URL is already the whole field
# (bookmark hrefs, one-URL-per-line lists) — none of it applies to "a URL
# embedded somewhere in a sentence", so this connector owns a small regex.
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

# `/save`, `/note`, `/remind` — with or without the `@botname` suffix Telegram
# appends in group chats. Stripped before the reason is read so the command
# token never becomes part of the reason.
_COMMAND_RE = re.compile(r"^/(save|note|remind)(?:@\w+)?\b\s*", re.IGNORECASE)

SaveUrlFn = Callable[..., Any]
SaveEpisodeFn = Callable[..., Any]


def extract_reason(text: str, urls: list[str]) -> str | None:
    """Everything the user typed *around* the URL — the reason they saved it.

    The bot command and every URL are removed, whitespace is collapsed, and a
    leading separator ("— ", ": ", "- ") is trimmed so "https://x — worth
    rereading" yields "worth rereading". Returns ``None`` when nothing is left,
    and always ``None`` for a message with no URL at all (there the whole text
    IS the note, staged as an episode, and calling it a "reason" would double
    it into a claim about nothing).
    """
    if not urls:
        return None
    body = _COMMAND_RE.sub("", text or "", count=1)
    for url in urls:
        body = body.replace(url, " ")
    body = re.sub(r"\s+", " ", body).strip()
    body = body.lstrip("-–—:;,. ").strip()
    return body or None


# --- Stage 1: pure parse ----------------------------------------------------


def _extract_urls(text: str, entities: list[dict] | None) -> list[str]:
    """URLs from Telegram ``entities`` (``text_link`` hyperlinks, whose visible
    text may not be the URL itself) plus a regex scan of the raw text, deduped
    in encounter order.
    """
    urls: list[str] = []
    for e in entities or []:
        if isinstance(e, dict) and e.get("type") == "text_link" and e.get("url"):
            urls.append(e["url"])
    if text:
        urls.extend(_URL_RE.findall(text))

    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_telegram_update(update: dict) -> dict | None:
    """Extract ``{text, urls, date, from_self}`` from a Telegram Bot API
    ``update`` object, or ``None`` if there's nothing capturable here.

    ``None`` for: non-dict input, updates with no ``message``/``channel_post``
    (edited messages, callback queries, poll answers, ...), and messages with
    no text/caption and no URL (a bare photo, a sticker, ...) — nothing to
    stage.

    ``from_self`` is best-effort provenance, not an identity check (a personal
    capture bot has no notion of "other users" to check against): ``True``
    when the message has a human (non-bot) sender and carries no forward
    metadata, i.e. it reads as something the owner typed themselves rather
    than something they forwarded from elsewhere. Forwarded posts are still
    parsed and returned — the task explicitly includes them — just with
    ``from_self=False``.
    """
    if not isinstance(update, dict):
        return None

    message = update.get("message") or update.get("channel_post")
    if not isinstance(message, dict):
        return None

    text = (message.get("text") or message.get("caption") or "").strip()
    entities = message.get("entities") or message.get("caption_entities") or []
    urls = _extract_urls(text, entities)

    if not text and not urls:
        return None

    date_ts = message.get("date")
    date_iso = None
    if isinstance(date_ts, (int, float)):
        try:
            date_iso = datetime.fromtimestamp(date_ts, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            date_iso = None

    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    is_forwarded = bool(
        message.get("forward_date")
        or message.get("forward_origin")
        or message.get("forward_from")
        or message.get("forward_from_chat")
    )
    from_self = bool(sender) and not sender.get("is_bot", False) and not is_forwarded

    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}

    return {
        "text": text,
        "urls": urls,
        "date": date_iso,
        "from_self": from_self,
        "reason": extract_reason(text, urls),
        "chat_id": chat.get("id"),
    }


# --- Stage 2: routing + emit -------------------------------------------------


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def ingest_telegram_update(
    memory_path: Path,
    update: dict,
    *,
    save_url_fn: SaveUrlFn | None = None,
    save_episode_fn: SaveEpisodeFn | None = None,
) -> dict:
    """Parse + route a Telegram update into the episode/media queue.

    Returns ``{"kind": "url" | "note" | "skipped", ...}``. Never raises —
    any parse or writer failure degrades to ``{"kind": "skipped", ...}`` with
    a reason, matching the rest of the ingestion pipeline's "never crash the
    webhook" contract (``media_ingestor.ingest_batch`` does the same).

    ``save_url_fn(memory_path, url, note=..., reason=...)`` / ``save_episode_fn(
    memory_path, text, title=...)`` may be sync or async.
    """
    try:
        parsed = parse_telegram_update(update)
    except Exception as e:  # pragma: no cover - parse_telegram_update doesn't raise
        logger.warning(f"telegram parse failed: {type(e).__name__}: {e}")
        return {"kind": "skipped", "reason": f"parse error: {e}", "ack": None, "chat_id": None}

    if parsed is None:
        return {"kind": "skipped", "reason": "not a capturable message", "ack": None, "chat_id": None}

    text = parsed["text"]
    urls = parsed["urls"]
    reason = parsed["reason"]
    chat_id = parsed["chat_id"]

    try:
        if urls:
            fn = save_url_fn or _default_save_url
            result = await _maybe_await(
                fn(memory_path, urls[0], note=text or None, reason=reason)
            )
            status = (result or {}).get("status") if isinstance(result, dict) else None
            if status == "duplicate":
                # L3 (final review): a reason on a repeat save still gets
                # written (see _default_save_url) — the ACK must say so
                # rather than implying the reason was silently dropped.
                ack = "Already saved — note updated." if reason else "Already saved."
            elif reason:
                ack = f"Saved with note: {reason}"
            else:
                ack = "Saved."
            return {"kind": "url", "url": urls[0], "result": result,
                    "ack": ack, "chat_id": chat_id}

        fn = save_episode_fn or _default_save_episode
        result = await _maybe_await(fn(memory_path, text, title=None))
        return {"kind": "note", "result": result, "ack": "Noted.", "chat_id": chat_id}
    except Exception as e:
        logger.warning(f"telegram ingest failed: {type(e).__name__}: {e}")
        return {"kind": "skipped", "reason": f"{type(e).__name__}: {e}",
                "ack": None, "chat_id": chat_id}


# --- Default writers (the only code path touching real I/O) -----------------


def _tag_episode_origin(memory_path: Path, episode_id: str, origin: str) -> None:
    """Best-effort: stamp ``origin=<origin>`` onto an already-written episode.

    ``media_ingestor.write_media_episode`` has no ``origin`` field of its own
    (it's used by non-Telegram sources too), so we patch it in after the fact
    rather than growing that shared writer's signature for one caller. Never
    raises — a failed stamp degrades to an un-tagged (still perfectly usable)
    episode.
    """
    if not episode_id:
        return
    filepath = memory_path / "episodes" / f"{episode_id}.md"
    try:
        parsed = markdown_parser.parse(filepath)
        fm = dict(parsed.frontmatter or {})
        fm["origin"] = origin
        markdown_parser.write(filepath, fm, parsed.body)
    except Exception as e:
        logger.debug(f"Could not tag origin={origin} on {episode_id}: {type(e).__name__}: {e}")


def _write_saved_because_claim(
    memory_path: Path, media_entity_id: str, reason: str, episode_id: str
) -> None:
    """The reason, as a first-class ``saved-because`` claim on the media page.

    ``object_kind="literal"`` on purpose: Stage 5.7's
    ``regenerate_edges_from_claims`` projects only node-object claims, so a
    free-text reason must never become a graph edge — it stays prose the Feed
    card can show and Stage 1 can mine for concepts. ``origin="telegram"`` keeps
    the claim honest: user-stated, but not the manual-assertion channel, so it
    does not inherit ``claim_reconciler.is_human`` overwrite protection.

    Never raises — ``write_claim`` returns an error dict rather than throwing,
    and a failed claim must never lose the save that already succeeded.
    """
    from api.services.agentic_write import write_claim

    result = write_claim(
        memory_path,
        media_entity_id,
        "saved-because",
        reason,
        observer="rodrigo",
        object_kind="literal",
        confidence=0.9,
        source_episode=episode_id or None,
        origin="telegram",
    )
    if result.get("action") in {"error", "ambiguous_subject", "corrupt_claims_block"}:
        logger.warning(
            f"saved-because claim not written for {media_entity_id}: "
            f"{result.get('action')} — {result.get('error')}"
        )


def _append_saved_because_section_if_absent(
    memory_path: Path, episode_id: str, reason: str
) -> None:
    """Append a ``## Saved because`` section to an EXISTING episode on a
    repeat ``/save`` with a new reason (final-review L3).

    A brand-new save gets this section baked in by ``_episode_body`` at
    write time; a duplicate never re-writes the episode at all, so an
    already-saved URL that gets a reason for the FIRST time on a later save
    would otherwise never gain the section a fresh save with a reason gets
    for free. Only appends when the episode doesn't already carry one — a
    changed reason on a THIRD save still updates the claim (claim history is
    append-only and versioned; this section is prose on a single file, not
    a ledger, so it is written once). Never raises — the same "the save
    already succeeded, a missed annotation must not undo it" contract as
    ``_tag_episode_origin``.
    """
    if not episode_id:
        return
    filepath = memory_path / "episodes" / f"{episode_id}.md"
    try:
        parsed = markdown_parser.parse(filepath)
        if "## Saved because" in parsed.body:
            return
        body = parsed.body.rstrip("\n") + f"\n\n## Saved because\n{reason}\n"
        markdown_parser.write(filepath, dict(parsed.frontmatter or {}), body)
    except Exception as e:
        logger.debug(
            f"Could not append Saved-because section to {episode_id}: "
            f"{type(e).__name__}: {e}"
        )


async def _commit_saved_because_update(memory_path: Path, media_entity_id: str) -> None:
    """Commit a ``saved-because`` claim (+ episode section) written on a
    REPEAT save of an already-saved URL (final-review L3) — a distinct,
    honestly-worded commit from ``_commit_media``'s "N media item(s) saved",
    since no new media item was created here.
    """
    from api.services import git_service

    date_str = datetime.now().strftime("%Y-%m-%d")
    message = git_service.build_commit_message(
        f"Sources ingest {date_str}",
        [
            f"entities/{media_entity_id}.md: updated (trigger: user/media_save)",
            "saved-because note updated on a repeat save (trigger: user/media_save)",
        ],
        authors=["user"],
    )
    await git_service.commit_changes(memory_path, message)


async def _default_save_url(
    memory_path: Path, url: str, *, note: str | None = None, reason: str | None = None
) -> dict:
    """Real default for ``save_url_fn`` — the same path as ``POST /sources/save``."""
    import httpx

    from api.services import media_ingestor

    item = media_ingestor.RawItem(url=url, note=note, reason=reason)
    idx = media_ingestor.load_url_index(memory_path)
    async with httpx.AsyncClient() as client:
        result = await media_ingestor.ingest_one(item, memory_path, client, idx)
    media_ingestor.save_url_index(memory_path, idx)

    if result.status == "created":
        _tag_episode_origin(memory_path, result.episode_id, "telegram")
        if reason:
            _write_saved_because_claim(
                memory_path, result.media_entity_id, reason, result.episode_id
            )
        try:
            await media_ingestor._commit_media(memory_path, 1)
        except Exception as e:
            logger.warning(f"Telegram media commit failed: {type(e).__name__}: {e}")
    elif reason and result.media_entity_id:
        # L3 (final review): a repeat /save of an already-saved URL WITH a
        # new reason must not silently drop it — update/write the
        # saved-because claim and append the episode section if it doesn't
        # have one yet, same as a brand-new save would.
        _write_saved_because_claim(
            memory_path, result.media_entity_id, reason, result.episode_id
        )
        _append_saved_because_section_if_absent(memory_path, result.episode_id, reason)
        try:
            await _commit_saved_because_update(memory_path, result.media_entity_id)
        except Exception as e:
            logger.warning(f"Telegram saved-because commit failed: {type(e).__name__}: {e}")

    return {
        "status": result.status,
        "media_entity_id": result.media_entity_id,
        "episode_id": result.episode_id,
        "title": result.title,
    }


def _default_save_episode(memory_path: Path, text: str, *, title: str | None = None) -> dict:
    """Real default for ``save_episode_fn`` — mirrors
    ``mcp/server.py::handle_save_episode`` (same id scheme, same content-hash
    dedup) with ``source``/``origin`` stamped ``"telegram"`` instead of ``"mcp"``.
    """
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    for filepath in episodes_dir.glob("*.md"):
        try:
            if f"content_hash: {content_hash}" in filepath.read_text(encoding="utf-8"):
                return {"status": "duplicate", "episode_id": filepath.stem}
        except OSError:
            continue

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    max_num = 0
    for filepath in episodes_dir.glob(f"ep_{today}_*.md"):
        suffix = filepath.stem.rsplit("_", 1)[-1]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    episode_id = f"ep_{today}_{max_num + 1:03d}"

    frontmatter = {
        "id": episode_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "telegram",
        "origin": "telegram",
        "title": title or "Telegram capture",
        "processed": False,
        "content_hash": content_hash,
    }
    markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, text)
    return {"status": "created", "episode_id": episode_id}


# --- Webhook secret auto-provisioning (G57 / Wave-1 1.5 round 2) ------------

# CICADA_TELEGRAM_WEBHOOK_SECRET — the per-request secret Telegram echoes
# back on ``X-Telegram-Bot-Api-Secret-Token``, stored in the same
# ``~/.cicada/secrets.env`` seam as every other Cicada-held credential (never
# through ``Settings``, which is constructed and cached in ``main.py``'s
# lifespan BEFORE that seam is projected into the environment). Defined here
# rather than in ``api/routers/capture.py`` so this module's own
# ``ensure_webhook_secret`` can reference it without an import cycle (the
# router already imports FROM this module) — the router re-exports it.
TELEGRAM_WEBHOOK_SECRET_ENV = "CICADA_TELEGRAM_WEBHOOK_SECRET"


async def ensure_webhook_secret(bot_token: str) -> tuple[bool, str]:
    """Make the secure per-request webhook secret the AUTOMATIC default
    rather than something the operator has to opt into by hand (Devin PR #24
    round 1, finding 5: "bot token configured" is not per-request
    authentication — anyone who finds the public webhook URL can write to
    memory until a secret is set).

    A no-op (returns ``(False, "already configured")``) if
    ``CICADA_TELEGRAM_WEBHOOK_SECRET`` is already set. Otherwise:

    1. Generate a new random secret.
    2. Discover the CURRENTLY REGISTERED webhook url via ``getWebhookInfo`` —
       Cicada never stores its own public URL (the user's tunnel is out of
       its control, per the module docstring above), so this is the only
       way to learn it without asking the user.
    3. Re-register that SAME url with the new secret via ``setWebhook`` —
       Telegram then starts sending ``X-Telegram-Bot-Api-Secret-Token`` on
       every subsequent request.
    4. Only on success is the secret persisted (``connections.secrets``).
       An unregistered secret would just reject every real request from
       Telegram — exactly the "lock out a working bot" failure mode this
       feature exists to avoid.

    Returns ``(provisioned, detail)``: ``provisioned`` is True only when a
    new secret was generated, registered with Telegram, AND persisted this
    call; ``detail`` is a short human-readable reason it wasn't (e.g. "no
    webhook currently registered yet", a Telegram API error, a network
    error). Never raises — any failure degrades to "not provisioned" so the
    caller can fall back to today's behavior with its own warning.
    """
    import os
    import secrets as secrets_mod

    from api.services.connections import secrets as connection_secrets

    if (os.environ.get(TELEGRAM_WEBHOOK_SECRET_ENV) or "").strip():
        return False, "already configured"

    import httpx

    api_base = f"https://api.telegram.org/bot{bot_token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            info_resp = await client.get(f"{api_base}/getWebhookInfo")
            info_resp.raise_for_status()
            info = info_resp.json()
            if not info.get("ok"):
                return False, f"getWebhookInfo failed: {info.get('description', 'unknown error')}"
            url = (info.get("result") or {}).get("url") or ""
            if not url:
                return False, "no webhook currently registered yet"

            new_secret = secrets_mod.token_urlsafe(32)
            set_resp = await client.get(
                f"{api_base}/setWebhook", params={"url": url, "secret_token": new_secret}
            )
            set_resp.raise_for_status()
            result = set_resp.json()
            if not result.get("ok"):
                return False, f"setWebhook failed: {result.get('description', 'unknown error')}"
    except Exception as exc:  # network error, timeout, bad JSON, etc.
        return False, f"{type(exc).__name__}: {exc}"

    connection_secrets.set_secret(TELEGRAM_WEBHOOK_SECRET_ENV, new_secret)
    return True, "provisioned"
