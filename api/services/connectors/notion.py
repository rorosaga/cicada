"""Notion — the pages the person shared with their own connection, live (ruling 47 tier 2; G219's API slice).

The export (``notion_export``, G219 slice 1) is a one-time move; this is the live path. The person creates an
*internal connection* in Notion's developer portal with **Read content** only, shares the pages and databases they
choose with it ("Add connections" on a page), and pastes its token in Settings → Sources → Notion. An internal
connection is its own bot that sees only what was shared with it — never the workspace, never the person's other
pages. A personal access token acts as the person with everything they can open, so it is refused at Save
(``check``: ``GET /v1/users/me`` must answer a bot). Notion's guides describe exactly this use ("Internal connections
are ideal for … syncing data from external tools"); its request limits (180 requests a minute per connection outside
Business plans) are honoured through a 429's ``Retry-After``.

What is read, only with ``GET`` and ``POST /v1/search`` (a read):

* ``POST /v1/search`` for pages, newest edit first, stopping at the last sync's high-water mark; then for each page
  that changed, ``GET /v1/pages/{id}/markdown`` (the page's own Markdown) and, for a database row, its database's
  title once (``GET /v1/data_sources/{id}``, kept in the cursor).
* No query text is ever sent: search names no person and no subject (ruling 44's guard).

Each page is one episode keyed ``notion:<32-hex id>`` — the export's key, so an export and the live sync never double a
page; the API's later read rewrites the export's episode in place — or, when long, one per H2 section
(``notion:<id>#<slug>``, the export's split). An edit rewrites it in place and re-queues it; a section that went is
tombstoned; a page moved to the trash is tombstoned and kept. A page unshared from the connection is no longer read
and is kept as it was (unsharing deletes nothing). A database row is one episode with its properties as facts, dated
when it was created (read on time); a plain page likewise.

Whose words: a page is the person's own (``user``) only when Notion says who owns the connection
(``GET /v1/users/me``: ``bot.owner`` of type ``user``) and that user created the page. Otherwise — an internal
connection is usually owned by the workspace, and a page's single creator may be a colleague — no page is credited to
the person on a guess: it is ``assistant`` with ``notion_by_other`` (someone's words, not certainly theirs), and the
Sources row says so. A page stored as someone else's is never moved back to the person's words by a later read
(``tier2._stage``), whichever door stored it. Only ids are compared; no name is read or sent.

The first sync walks every shared page, newest edit first, ``MAX_PAGES_PER_SYNC`` at a time, carrying on from Notion's
own cursor (``walk``); the high-water mark moves only when the walk is done, to the newest edit seen when it began, so
nothing older is ever skipped. After that a sync lists the pages edited since the mark; if more changed than one
listing holds, it walks everything again rather than miss any.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from api.services import episode_ids, episode_staging, notion_export
from api.services.connectors import base, tier2

CHANNEL_ID = "notion-api"
LABEL = "Notion"
LOGIN_MODE = "credentials"
CHANNEL_NOUN = "page"
TIER = tier2.TIER
ORIGIN = "notion-api"
SOURCE_PREFIX = notion_export.SOURCE_PREFIX
SCRUB_WRITER = notion_export.SCRUB_WRITER
TOKEN_ENV = "CICADA_NOTION_TOKEN"
FIELDS: tuple[dict, ...] = ({"name": TOKEN_ENV, "label": "Notion internal connection token", "secret": True},)
SECRET_NAMES: tuple[str, ...] = (TOKEN_ENV,)
API_BASE = "https://api.notion.com/v1/"
NOTION_VERSION = "2026-03-11"
TOKEN_HELP = "notion.so/profile/integrations"
READS = ("Reads only the Notion pages and databases you share with your own connection (Add connections on a page), "
         "as text, with each row's properties. Give the connection Read content only; Cicada never changes anything "
         "in Notion. Disconnect forgets the token; you can also delete the connection in Notion.")
REFUSED_WORDS = ("Notion refused the token. Check the connection in Notion's developer portal (it may have been "
                 "deleted or lost access), then paste its token again in Settings → Sources → Notion.")
PERSONAL_TOKEN_WORDS = ("That token acts as you, with every page you can open. Cicada reads only what you choose to "
                        "share: create an internal connection with Read content only, share pages with it, and paste "
                        "its token instead. Nothing was saved.")
UNKNOWN_AUTHOR_WORDS = ("Notion does not say which of these pages you wrote, so they are kept as pages you shared, "
                        "not as your own words.")

PAGE_SIZE = 100
MAX_LIST_PAGES = 20
MAX_PAGES_PER_SYNC = 150
TITLE_CAP = 300
PROPERTY_CAP = 2000
#: Notion's enhanced-Markdown tags that carry no text of their own; their inner text stays.
_TAG = re.compile(r"</?(?:page|database|data-source|unknown|mention-[a-z-]+|callout|details|summary|columns|column|"
                  r"table_of_contents|synced_block|empty-block|span|color)\b[^>]*?/?>", re.IGNORECASE)


def _self():
    return sys.modules[__name__]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION, "Accept": "application/json"}


def is_connected() -> bool:
    return tier2.is_connected(_self())


def credential_fields() -> list[dict]:
    return tier2.credential_fields(_self())


def forget() -> None:
    tier2.forget(_self())


async def check(client: tier2.Client) -> None:
    """The token must be an internal connection (a bot that sees only what was shared), never a personal token."""
    me = await client.get("users/me") or {}
    if str(me.get("type") or "") != "bot":
        raise tier2.Refused(PERSONAL_TOKEN_WORDS, kind="sign-in")


async def sync(memory_path: Path, *, http_fn=None, allow_fetch=None, scheduled: bool = False) -> dict:
    return await tier2.run(_self(), memory_path, http_fn=http_fn, allow_fetch=allow_fetch, scheduled=scheduled)


# --- reading ---------------------------------------------------------------------------------------------------------


def _hex(page_id) -> str:
    return str(page_id or "").replace("-", "").lower()


def _when(value) -> datetime | None:
    if not value:
        return None
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else None


def _trashed(page: dict) -> bool:
    return bool(page.get("in_trash") or page.get("archived") or page.get("is_archived"))


def _search_body(start: str | None) -> dict:
    body = {"filter": {"property": "object", "value": "page"}, "page_size": PAGE_SIZE,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
    if start:
        body["start_cursor"] = start
    return body


def _pages_of(listing: dict) -> list[dict]:
    return [p for p in (listing.get("results") or []) if isinstance(p, dict) and p.get("object") == "page"]


async def _changed_pages(client: tier2.Client, high_water: str) -> list[dict] | None:
    """Pages edited since ``high_water``, oldest first — or ``None`` when ``MAX_LIST_PAGES`` listing pages did not
    reach it (more changed than one listing holds: the caller walks the whole history instead, never skipping)."""
    out: list[dict] = []
    start = None
    for _ in range(MAX_LIST_PAGES):
        listing = await client.post("search", _search_body(start)) or {}
        for item in _pages_of(listing):
            if str(item.get("last_edited_time") or "") < high_water:
                return sorted(out, key=lambda p: (str(p.get("last_edited_time") or ""), _hex(p.get("id"))))
            out.append(item)
        start = listing.get("next_cursor")
        if not listing.get("has_more") or not start:
            return sorted(out, key=lambda p: (str(p.get("last_edited_time") or ""), _hex(p.get("id"))))
    return None


async def _walk(client: tier2.Client, walk: dict) -> tuple[list[dict], dict, bool]:
    """The next part of a walk through every shared page, newest edit first, whole listing pages at a time until
    ``MAX_PAGES_PER_SYNC`` are in hand. ``walk`` is ``{"next": Notion's start_cursor, "top": the newest edit time when
    the walk began, "read": pages so far}``. Returns (pages, the walk to resume, finished). A cursor Notion no longer
    takes restarts the walk from the top (pages already read are a hash skip)."""
    walk = dict(walk)
    pages: list[dict] = []
    while len(pages) < MAX_PAGES_PER_SYNC:
        try:
            listing = await client.post("search", _search_body(walk.get("next"))) or {}
        except tier2.Refused:
            raise
        except base.ConnectorError:
            if not walk.get("next"):
                raise
            walk = {"next": None, "top": None, "read": 0}      # an expired cursor: start again from the top
            continue
        found = _pages_of(listing)
        if walk.get("top") is None and found:
            walk["top"] = str(found[0].get("last_edited_time") or "") or None
        pages.extend(found)
        walk["read"] = int(walk.get("read") or 0) + len(found)
        walk["next"] = listing.get("next_cursor") if listing.get("has_more") else None
        if not walk["next"]:
            return pages, walk, True
    return pages, walk, False


async def _trashed_pages(client: tier2.Client) -> list[dict]:
    body = {"filter": {"property": "object", "value": "page", "in_trash": True}, "page_size": PAGE_SIZE,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
    try:
        page = await client.post("search", body) or {}
    except tier2.Refused:
        raise
    except Exception:   # noqa: BLE001 — a trash read Notion does not take is no reason to lose the sync
        return []
    return [p for p in (page.get("results") or []) if isinstance(p, dict) and _trashed(p)]


def _database_of(page: dict) -> str | None:
    parent = page.get("parent") or {}
    for key in ("data_source_id", "database_id"):
        if parent.get("type") == key and parent.get(key):
            return str(parent[key])
    return None


async def _database_title(client: tier2.Client, db_id: str, cache: dict) -> str:
    if db_id in cache:
        return cache[db_id]
    title = "A database"
    for path in (f"data_sources/{db_id}", f"databases/{db_id}"):
        try:
            body = await client.get(path) or {}
        except tier2.Refused:
            raise
        except Exception:   # noqa: BLE001 — a title Notion will not give stays a plain word
            continue
        if text := _plain(body.get("title")):
            title = text
            break
    cache[db_id] = title
    return title


def owner_of(me: dict) -> str | None:
    """The Notion user who owns this connection, when Notion says so (``bot.owner`` of type ``user``). An internal
    connection is usually owned by the workspace, and then nobody is known to be the person."""
    owner = ((me or {}).get("bot") or {}).get("owner") or {}
    if owner.get("type") == "user":
        return str((owner.get("user") or {}).get("id") or "") or None
    return None


async def fetch(client: tier2.Client, cursor: dict, memory_path: Path) -> tier2.Batch:
    db_titles: dict = dict(cursor.get("databases") or {})
    high_water = cursor.get("high_water")
    walk = cursor.get("walk")
    owner = owner_of(await client.get("users/me") or {})
    finished = True
    if high_water and not walk:
        todo = await _changed_pages(client, high_water)
        if todo is None:
            walk = {"next": None, "top": None, "read": 0}     # too many changed to list: walk everything instead
        elif len(todo) > MAX_PAGES_PER_SYNC:
            todo = todo[:MAX_PAGES_PER_SYNC]
            finished = False
    if walk is not None or not high_water:
        todo, walk, finished = await _walk(client, walk or {"next": None, "top": None, "read": 0})
    batch = tier2.Batch()
    unreadable = 0
    for page in todo:
        sid = SOURCE_PREFIX + _hex(page.get("id"))
        if _trashed(page):
            batch.deleted.append(sid)
            continue
        try:
            md = await client.get(f"pages/{page['id']}/markdown") or {}
        except tier2.Refused:
            raise
        except Exception:   # noqa: BLE001 — one page the connection cannot read is skipped, never the sync
            unreadable += 1
            continue
        db_id = _database_of(page)
        db_title = await _database_title(client, db_id, db_titles) if db_id else None
        mine = owner is not None and str((page.get("created_by") or {}).get("id") or "") == owner
        batch.drafts.extend(drafts_for(page, md, db_title=db_title, mine=mine))
        batch.replaced.append(sid)
        batch.seen += 1
    for page in await _trashed_pages(client):
        batch.deleted.append(SOURCE_PREFIX + _hex(page.get("id")))
    words = []
    if walk is not None:
        # A walk through the whole history: the high-water mark moves only once nothing older is left to read.
        if finished:
            batch.cursor = {"high_water": walk.get("top") or high_water, "databases": db_titles}
        else:
            batch.cursor = {"high_water": high_water, "walk": walk, "databases": db_titles}
            words.append(f"Reading your shared pages: {walk.get('read', 0)} so far; the next sync carries on.")
    else:
        if finished:
            new_high = max([str(p.get("last_edited_time") or "") for p in todo] + [high_water or ""]) or None
        else:
            new_high = str(todo[-1].get("last_edited_time") or "") or high_water
            words.append("Part of your edited pages came in; the next sync brings the rest.")
        batch.cursor = {"high_water": new_high, "databases": db_titles}
    if owner is None:
        words.append(UNKNOWN_AUTHOR_WORDS)
    if unreadable:
        words.append(f"{unreadable} page(s) could not be read; share them with the connection again.")
    batch.words = " ".join(words) or None
    return batch


# --- one page as episodes ------------------------------------------------------------------------------------------


def _plain(rich) -> str:
    if isinstance(rich, list):
        return "".join(str((r or {}).get("plain_text") or "") for r in rich if isinstance(r, dict)).strip()
    return str(rich or "").strip()


def _clip(text, cap: int = TITLE_CAP) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= cap else value[: cap - 1].rstrip() + "…"


def _value(prop: dict) -> str:
    """One property as words. People and relations are ids or names Notion holds; only their names (people) or
    nothing (relations) are kept — nothing is looked up."""
    kind = str(prop.get("type") or "")
    v = prop.get(kind)
    if kind in ("title", "rich_text"):
        return _plain(v)
    if kind in ("select", "status"):
        return str((v or {}).get("name") or "")
    if kind == "multi_select":
        return ", ".join(str(o.get("name") or "") for o in (v or []) if isinstance(o, dict))
    if kind == "date":
        if not v:
            return ""
        return str(v.get("start") or "") + (f" → {v['end']}" if v.get("end") else "")
    if kind in ("number", "url", "email", "phone_number", "created_time", "last_edited_time"):
        return "" if v is None else str(v)
    if kind == "checkbox":
        return "Yes" if v else "No"
    if kind == "people":
        return ", ".join(str(p.get("name") or "") for p in (v or []) if isinstance(p, dict) and p.get("name"))
    if kind == "files":
        return ", ".join(str(f.get("name") or "") for f in (v or []) if isinstance(f, dict))
    if kind == "formula":
        inner = v or {}
        return str(inner.get(inner.get("type") or "") or "")
    if kind == "unique_id":
        return f"{(v or {}).get('prefix') or ''}{(v or {}).get('number') or ''}"
    return ""


def title_of(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _clip(_plain(prop.get("title"))) or "Untitled"
    return "Untitled"


def page_text(md: dict) -> str:
    text = str(md.get("markdown") or md.get("page_markdown") or "")
    if isinstance(md.get("page_markdown"), dict):
        text = str(md["page_markdown"].get("markdown") or "")
    text = _TAG.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return notion_export._links(text)


def drafts_for(page: dict, md: dict, *, db_title: str | None, mine: bool) -> list[episode_staging.EpisodeDraft]:
    hex_id = _hex(page.get("id"))
    sid = SOURCE_PREFIX + hex_id
    title = title_of(page)
    when = _when(page.get("created_time")) or _when(page.get("last_edited_time"))
    if db_title is not None:
        lines = [f"# {title}", "", f"**Database:** {_clip(db_title)}"]
        for key, prop in (page.get("properties") or {}).items():
            if not isinstance(prop, dict) or prop.get("type") == "title":
                continue
            if value := _clip(_value(prop), PROPERTY_CAP):
                lines.append(f"**{_clip(key, 60)}:** {value}")
        head = "\n".join(lines)
    else:
        head = f"# {title}"
    content = page_text(md)
    if md.get("truncated"):
        content += "\n\n(Part of this page could not be read.)"
    extra = {"notion_kind": "row" if db_title is not None else "page", "notion_by_other": not mine,
             "evidence_kind": "user" if mine else "assistant",
             "notion_last_edited": str(page.get("last_edited_time") or "") or None}
    episodes = notion_export._sections(sid, title, head, content, when, extra)
    out = []
    for ep in episodes:
        ep["origin"] = ORIGIN
        ep["source"] = ORIGIN
        ep["extra"] = {**ep.get("extra", {}), "source": ORIGIN}
        ep["source_updated_at"] = str(page.get("last_edited_time") or "") or None
        if when is not None:
            ep["original_date"] = episode_ids.id_day(when.astimezone(timezone.utc))
        draft = episode_staging.draft_from_export(ep)
        draft.redate = False
        out.append(draft)
    return out


__all__ = ["CHANNEL_ID", "LABEL", "ORIGIN", "drafts_for", "fetch", "page_text", "sync", "title_of"]
