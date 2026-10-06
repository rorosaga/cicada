"""Reading with an agent, the app's half (G166): the read state on a link, and asking.

Two functions the REST router and ``GET /sources`` share, so the wire and the
mint rule live in one place:

* :func:`read_state` — the ``read`` block on a saved link: what happened the
  last time an agent read (or was asked to read) it, merged from the page's own
  ``read:`` stamp (a successful read is memory, on the page) and the ask store
  (every outcome, and "waiting", outside the bank). The newest wins and a tie
  goes to the ask. It also carries whether "Ask an agent" is on offer and, when
  not, the sentence why — so the app holds no host table of its own. When
  Cicada's own reader could not read the page it also names the wall and the
  site (``reading_walls``, ``reading_hosts.site_of``), so the detail column can
  offer the site's switch.
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

from api.services import media_ingestor, reading_asks, reading_hosts, reading_prompt, reading_settings, write_admission


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


def read_state(url: str, fm_read, ask_row, *, enabled: bool, wall: str | None = None,
               allowed_sites=(), paused_sites=()) -> dict | None:
    """The ``read`` wire block for one link, or ``None`` for a link that is not a
    page to read (a video, a paper, or a class an agent is never offered) and has
    nothing recorded. Pure: no file is opened here.

    ``wall`` is the page's wall kind when Cicada's reader could not read it and
    it holds no words (``reading_walls``); ``allowed_sites`` / ``paused_sites``
    are the person's permissions and the sites an agent was not signed in to
    (``reading_queue.paused_sites``). ``askable`` is the structural verdict plus
    the master switch, nothing about the site: "Ask an agent" on one page is the
    person's own consent for it. A wall page of an allowed site with no ask of
    its own reads ``waiting`` with ``queuedBy: site``."""
    verdict = reading_hosts.agent_may_read(url, enabled=enabled)
    stamp = fm_read if isinstance(fm_read, dict) and fm_read.get("by") == "agent" else None
    if not verdict.ok and verdict.cls != "off" and stamp is None and ask_row is None:
        return None
    state: dict = {"status": "none", "host": reading_hosts.display_host(verdict.host) or None,
                   "askable": verdict.ok, "reason": None if verdict.ok else verdict.reason}
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
    if wall and (verdict.ok or verdict.cls == "off"):
        site = verdict.site
        allowed = bool(enabled and site in set(allowed_sites or ()))
        state.update(wall=wall, siteKey=site, siteLabel=reading_hosts.site_label(site), siteAllowed=allowed)
        icon = reading_hosts.icon_host(site)
        if icon:
            state["siteIconHost"] = icon
        if state["status"] == "none" and allowed and site not in set(paused_sites or ()):
            state.update(status="waiting", queuedBy="site")
    return {k: v for k, v in state.items() if v is not None or k == "reason"}


async def ask(memory_path: Path, url: str) -> dict:
    """The person's "Ask an agent". Returns ``{ask, mediaEntityId, saved, prompt}``
    or raises :class:`AskRefused` with a sentence the person can read."""
    memory_path = Path(memory_path)
    url = (url or "").strip()
    enabled = reading_settings.agent_enabled()
    verdict = reading_hosts.agent_may_read(url, enabled=enabled)
    if not verdict.ok:
        # The link's own class is a 422; the person's master switch is a 409.
        raise AskRefused(409 if verdict.cls == "off" else 422, verdict.reason)
    h = media_ingestor.url_hash(url)
    idx = media_ingestor.load_url_index(memory_path)
    entry = idx.get(h)
    saved = False
    if not (isinstance(entry, dict) and entry.get("media_entity_id")):
        # No fetch (``defer_enrich``): the save and its commit are one held admission (G183 round 1), never refused —
        # like ``POST /sources/save``.
        async def save():
            item = media_ingestor.RawItem(url=url, origin="saved-link", defer_enrich=True)
            index = media_ingestor.load_url_index(memory_path)
            result = await media_ingestor.ingest_one(item, memory_path, None, index)
            media_ingestor.save_url_index(memory_path, index)
            if result.status == "created":
                paths = ["sources/url_index.json", f"entities/{result.media_entity_id}.md",
                         f"episodes/{result.episode_id}.md"]
                try:
                    await media_ingestor._commit_media(
                        memory_path, 1, paths, author="user", trigger="user/media_save")
                except Exception as exc:  # noqa: BLE001 — the save stands; the next writer's commit takes it
                    logger.warning(f"Reading ask: save commit failed: {type(exc).__name__}")
            return result

        result = await write_admission.run_admitted(memory_path, save)
        entity_id = result.media_entity_id
        saved = result.status == "created"
    else:
        entity_id = str(entry["media_entity_id"])
    row = reading_asks.ask(memory_path, h, host=reading_hosts.display_host(verdict.host),
                           host_class=verdict.host_class)
    return {"ask": row, "mediaEntityId": entity_id, "saved": saved, "prompt": reading_prompt.ask_prompt(url)}
