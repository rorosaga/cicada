"""Where an item lives in the app it came from — an account and a collection (2026-11-04).

The owner, on the Sources pages of Apple Notes, Reminders, Contacts and Calendar: *"replicate this layout … starting
from those that are iCloud, those that are iPhone, or whatever, and then you go into it, and then you can see the notes
… or you can see folders"*, and *"they should be separate using the respective logos"*. Every source the app reads on
this Mac files its items the way its own app does: an **account** (iCloud, On My Mac, a Google or Exchange account) that
holds **collections** (a calendar, a Reminders list, a Notes folder), which hold the items. The Sources page browses
the same three levels (`channel_items.collections`).

What a sync names is kept here, beside the channel's last sync (`sync_state`): the calendars and ticked lists that hold
an item, each ``{id, title, account, provider}`` — the titles the episodes' bodies already carry, so nothing new about
the person enters the bank. A note's account and folder ride the Notes index instead (`notes_sync`). Pure apart from the
one read of `sync_state`; never raises.
"""

from __future__ import annotations

from pathlib import Path

from api.services import sync_state

#: The `sync_state` entry's key.
KEY = "collections"
#: The kinds of account the app names (`EKSource.sourceType` mapped on the Mac; Notes' account by its name). Anything
#: else is stored as ``other``.
PROVIDERS = frozenset({"icloud", "google", "exchange", "local", "subscribed", "other"})
#: At most this many collections are kept per channel (a sync's own cap on calendars is far below it).
MAX = 500
TITLE_CAP = 120


def _clip(value) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= TITLE_CAP else text[: TITLE_CAP - 1].rstrip() + "…"


def provider(value) -> str | None:
    """A posted provider word, or None when the app sent none (an older app)."""
    if value is None or not str(value).strip():
        return None
    word = str(value).strip().lower()
    return word if word in PROVIDERS else "other"


def stored(records: list[dict]) -> list[dict]:
    """The collections a sync named, as `sync_state` keeps them: id, title, account and provider, clipped."""
    out: list[dict] = []
    for record in records[:MAX]:
        if not isinstance(record, dict) or not str(record.get("id") or "").strip():
            continue
        out.append({"id": str(record["id"]), "title": _clip(record.get("title")),
                    "account": _clip(record.get("account")) or None, "provider": provider(record.get("provider"))})
    return out


def after_sync(memory_path: Path, channel_id: str, records: list[dict], with_items: set[str]) -> list[dict]:
    """What to keep after a sync: the collections holding an item (`with_items`, the ids this sync posted items for)
    and every name kept before, freshest first. An empty calendar's title stays out: no episode carries it, and the
    pickers read EventKit, not this. A list unticked later keeps its name, because its items stay in the bank."""
    past = known(memory_path, channel_id)
    now = stored([r for r in records if isinstance(r, dict) and (str(r.get("id")) in with_items or r.get("id") in past)])
    ids = {r["id"] for r in now}
    return (now + [r for cid, r in past.items() if cid not in ids])[:MAX]


def known(memory_path: Path, channel_id: str) -> dict[str, dict]:
    """Every collection kept for the channel, by id; empty when none was (an older sync)."""
    entry = sync_state.read_sync_state(memory_path).get(channel_id)
    records = entry.get(KEY) if isinstance(entry, dict) else None
    if not isinstance(records, list):
        return {}
    return {str(r["id"]): r for r in records if isinstance(r, dict) and r.get("id")}
