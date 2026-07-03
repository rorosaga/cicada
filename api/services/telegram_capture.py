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

SaveUrlFn = Callable[..., Any]
SaveEpisodeFn = Callable[..., Any]


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

    return {
        "text": text,
        "urls": urls,
        "date": date_iso,
        "from_self": from_self,
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

    ``save_url_fn(memory_path, url, note=...)`` / ``save_episode_fn(memory_path,
    text, title=...)`` may be sync or async — injected test doubles can be
    plain functions; the real defaults are async (they call ``media_ingestor``
    over ``httpx``).
    """
    try:
        parsed = parse_telegram_update(update)
    except Exception as e:  # pragma: no cover - parse_telegram_update doesn't raise
        logger.warning(f"telegram parse failed: {type(e).__name__}: {e}")
        return {"kind": "skipped", "reason": f"parse error: {e}"}

    if parsed is None:
        return {"kind": "skipped", "reason": "not a capturable message"}

    text = parsed["text"]
    urls = parsed["urls"]

    try:
        if urls:
            fn = save_url_fn or _default_save_url
            result = await _maybe_await(fn(memory_path, urls[0], note=text or None))
            return {"kind": "url", "url": urls[0], "result": result}

        fn = save_episode_fn or _default_save_episode
        result = await _maybe_await(fn(memory_path, text, title=None))
        return {"kind": "note", "result": result}
    except Exception as e:
        logger.warning(f"telegram ingest failed: {type(e).__name__}: {e}")
        return {"kind": "skipped", "reason": f"{type(e).__name__}: {e}"}


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


async def _default_save_url(memory_path: Path, url: str, *, note: str | None = None) -> dict:
    """Real default for ``save_url_fn`` — the same path as ``POST /sources/save``."""
    import httpx

    from api.services import media_ingestor

    item = media_ingestor.RawItem(url=url, note=note)
    idx = media_ingestor.load_url_index(memory_path)
    async with httpx.AsyncClient() as client:
        result = await media_ingestor.ingest_one(item, memory_path, client, idx)
    media_ingestor.save_url_index(memory_path, idx)

    if result.status == "created":
        _tag_episode_origin(memory_path, result.episode_id, "telegram")
        try:
            await media_ingestor._commit_media(memory_path, 1)
        except Exception as e:
            logger.warning(f"Telegram media commit failed: {type(e).__name__}: {e}")

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
