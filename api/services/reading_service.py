"""Reading with an agent, the app's half (G166): the read state on a link, and asking.

Two functions the REST router and ``GET /sources`` share, so the wire and the
mint rule live in one place:

* :func:`read_state` — the ``read`` block on a saved link: what happened the
  last time an agent read (or was asked to read) it, merged from the page's own
  ``read:`` stamp (a successful read is memory, on the page) and the ask store
  (every outcome, and "waiting", outside the bank). The newest wins and a tie
  goes to the ask. It also carries whether "Ask an agent" is on offer and, when
  not, the sentence why — so the app holds no host table of its own.
* :func:`ask` — the person's "Ask an agent" on a link. A link that is not saved
  yet is saved first, **without a fetch** (``RawItem.defer_enrich``), as the
  person's own save (``Cicada-Author: user``, ``user/media_save``) — asking must
  never make the backend request a page, least of all a walled one. The ask
  itself is a row in the machine-wide store, nothing more.

Nothing here reads a browser, holds a session or fetches anything.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from api.services import media_ingestor, reading_asks, reading_hosts, reading_prompt, reading_settings


class AskRefused(Exception):
    """An ask that cannot be made. ``status`` is the HTTP code the router uses:
    409 when the person's own switches are why, 422 when the link itself is."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def read_state(url: str, fm_read, ask_row, *, enabled: bool, allowed_hosts) -> dict | None:
    """The ``read`` wire block for one link, or ``None`` for a link that is not a
    page to read (a video, a paper, or a class an agent is never offered) and has
    nothing recorded. Pure: no file is opened here."""
    verdict = reading_hosts.agent_may_read(url, enabled=enabled, allowed_hosts=allowed_hosts)
    stamp = fm_read if isinstance(fm_read, dict) and fm_read.get("by") == "agent" else None
    if not verdict.ok and verdict.cls != "off" and stamp is None and ask_row is None:
        return None
    state: dict = {"status": "none", "host": reading_hosts.display_host(verdict.host) or None,
                   "hostKey": verdict.host_key, "askable": verdict.ok,
                   "reason": None if verdict.ok else verdict.reason}
    stamp_at = _parse(stamp.get("at")) if stamp else None
    ask_at = _parse((ask_row or {}).get("outcome_at") or (ask_row or {}).get("asked_at")) if ask_row else None
    use_ask = ask_row is not None and (stamp_at is None or (ask_at is not None and ask_at >= stamp_at))
    if use_ask:
        row_state = ask_row["state"]
        state.update(
            status="ok" if row_state == "read" else row_state,
            askedAt=ask_row.get("asked_at"), at=ask_row.get("outcome_at"),
            via=ask_row.get("via"), harness=ask_row.get("harness"), note=ask_row.get("note"))
        if row_state != "waiting":
            state.update(by="agent", tier="agent" if row_state == "read" else None)
    elif stamp is not None:
        state.update(status="ok", by="agent", tier=str(stamp.get("tier") or "agent"), at=stamp.get("at"),
                     via=stamp.get("via"), harness=stamp.get("harness"))
    return {k: v for k, v in state.items() if v is not None or k in ("hostKey", "reason")}


async def ask(memory_path: Path, url: str) -> dict:
    """The person's "Ask an agent". Returns ``{ask, mediaEntityId, saved, prompt}``
    or raises :class:`AskRefused` with a sentence the person can read."""
    memory_path = Path(memory_path)
    url = (url or "").strip()
    enabled = reading_settings.agent_enabled()
    verdict = reading_hosts.agent_may_read(
        url, enabled=enabled, allowed_hosts=reading_settings.allowed_hosts())
    if not verdict.ok:
        # The link's own class is a 422; the person's switches are a 409.
        raise AskRefused(409 if verdict.cls == "off" else 422, verdict.reason)
    h = media_ingestor.url_hash(url)
    idx = media_ingestor.load_url_index(memory_path)
    entry = idx.get(h)
    saved = False
    if not (isinstance(entry, dict) and entry.get("media_entity_id")):
        item = media_ingestor.RawItem(url=url, origin="saved-link", defer_enrich=True)
        result = await media_ingestor.ingest_one(item, memory_path, None, idx)
        media_ingestor.save_url_index(memory_path, idx)
        entity_id = result.media_entity_id
        saved = result.status == "created"
        if saved:
            paths = ["sources/url_index.json", f"entities/{result.media_entity_id}.md",
                     f"episodes/{result.episode_id}.md"]
            try:
                await media_ingestor._commit_media(
                    memory_path, 1, paths, author="user", trigger="user/media_save")
            except Exception as exc:  # noqa: BLE001 — the save stands; the next writer's commit takes it
                logger.warning(f"Reading ask: save commit failed: {type(exc).__name__}")
    else:
        entity_id = str(entry["media_entity_id"])
    row = reading_asks.ask(memory_path, h, host=reading_hosts.display_host(verdict.host),
                           host_class=verdict.host_class)
    return {"ask": row, "mediaEntityId": entity_id, "saved": saved, "prompt": reading_prompt.ask_prompt(url)}
