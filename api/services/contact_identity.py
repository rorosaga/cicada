"""One person, one page across every source (owner 2026-10-28): a chat participant reaches their page through Contacts.

The owner: "memory is good because it's supposed to track the same persons too, so if a friend said something on a
gc, when it all about him somewhere else, example Claude code, it should point to the same person. That's why syncing
contacts will be useful too."

**No second identity table.** Two links already exist and this module only reads them together:

* the APP knows which address-book card a chat's handle belongs to. Since this change it posts that card's id — the
  same opaque ``CNContact`` identifier the Contacts sync posts (`contacts_local`), never a phone number or address —
  beside a one-to-one chat (``conversation.contact``) and beside each group member (``members[].contact``), and only
  when exactly ONE card holds the handle. `messages_source` keeps it on the sitting's own records: the
  ``correspondent`` record and each ``participants`` row. A chat source to come (WhatsApp, Telegram) fills the same
  two records the same way;
* a page the Contacts sync matched carries that card's G61 sources, ``addressbook://<card id>`` (`contacts_local`).

So a participant names their page by card id: the one person page whose sources carry the card's ref. Below the
promotion bar nothing changes — a card still waits outside every bank (owner 2026-10-20) and is used only once the
usual rules promote the mention (2+ conversations, the person's own words, a link): then the page is born under the
card's name with its photo and sources, as a card's first mention always was (`entity_resolver`). Never the person's
own card (the app marks it ``is_me``; it belongs to the owner's page and never waits), never a page titled by a
relation (`role_people`), never a card two pages carry.

**What Stage 1 marks.** An entity extracted from a sitting whose name (or alias) folds to exactly one participant's
name, where that participant carries a card id, gets :data:`MARK` — the model may never set it. Stage 2 reads it
before any name match: a mention spelled differently in the chat ("Bobby") still lands on the card's page, and a
same-name page of someone else never takes it. A name-only mention elsewhere (a harness session, a chat export, a
note) carries no card and goes through the name rules; a one-word name is never joined on the given name alone —
Stage 2 asks (`entity_resolver._held_alias_questions`, worded by `inbox_wording`). No LLM here.
"""
from __future__ import annotations

import re

from api.services import agent_detectors

#: What Stage 1 stamps on an entity that is a chat participant with an address-book card (never the model's).
MARK = "contact_card"
REF_SCHEME = "addressbook://"
ID_CAP = 200
#: A card id as Contacts writes it: an opaque identifier. Anything shaped like a phone number or an address is refused
#: — a newer or buggier app can never make the bank keep a handle under this key.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
_PHONE = re.compile(r"^[\d\s()+\-.]{7,}$")
_ID = re.compile(r"^[A-Za-z0-9:_\-./]+$")
#: The chat sources whose sittings carry participants (`messages_source`; WhatsApp and Telegram to come).
CHAT_ORIGINS = frozenset({"imessage", "whatsapp", "telegram"})


def clean_card_id(value) -> str | None:
    """A posted card id, or ``None``: never a phone number, never an address, never longer than the sync allows."""
    text = str(value or "").strip()
    if not text or len(text) > ID_CAP or _EMAIL.search(text) or not _ID.match(text):
        return None
    if _PHONE.match(text) and sum(c.isdigit() for c in text) >= 7:
        return None
    return text


def ref(card_id: str) -> str:
    return f"{REF_SCHEME}{card_id}"


def card_pages(pages: list[dict]) -> dict[str, str]:
    """Card id -> the ONE person page whose sources carry ``addressbook://<id>``, never the owner's page (its card is
    the person's own). A card two pages carry names neither."""
    found: dict[str, set[str]] = {}
    for page in pages or []:
        fm = page.get("frontmatter") or {}
        if str(fm.get("type") or "").lower() != "person" or fm.get("owner") is True or not page.get("id"):
            continue
        for source in fm.get("sources") or []:
            text = str(source.get("ref") or "") if isinstance(source, dict) else ""
            if text.startswith(REF_SCHEME) and (cid := clean_card_id(text[len(REF_SCHEME):])):
                found.setdefault(cid, set()).add(str(page["id"]))
    return {cid: next(iter(ids)) for cid, ids in found.items() if len(ids) == 1}


def participants(episode: dict | None) -> dict[str, str]:
    """Folded name -> card id for the people of one sitting who carry a card: a one-to-one chat's correspondent (a
    person, never an agent) and a group's members. A name two of them share names nobody."""
    episode = episode or {}
    rows: list[tuple[str, str | None]] = []
    record = episode.get("correspondent")
    if isinstance(record, dict) and record.get("kind") == agent_detectors.PERSON:
        rows.append((str(record.get("name") or ""), clean_card_id(record.get("contact"))))
    for row in episode.get("participants") or []:
        if isinstance(row, dict) and row.get("kind") != agent_detectors.AGENT:
            rows.append((str(row.get("name") or ""), clean_card_id(row.get("contact"))))
    seen: dict[str, set] = {}
    for name, cid in rows:
        key = agent_detectors.fold(name)
        if key:
            seen.setdefault(key, set()).add(cid)
    return {key: next(iter(ids)) for key, ids in seen.items() if len(ids) == 1 and None not in ids}


def mark(result: dict, episode: dict | None) -> int:
    """Stage 1: stamp every ``person`` entity of this sitting's extraction that names exactly one participant with a
    card. Strips what the model may never set first. Returns how many it marked."""
    for item in result.get("entities") or []:
        if isinstance(item, dict):
            item.pop(MARK, None)
    people = participants(episode)
    if not people:
        return 0
    marked = 0
    for entity in result.get("entities") or []:
        if not isinstance(entity, dict) or str(entity.get("type") or "").lower() != "person":
            continue
        names = [entity.get("name"), *(entity.get("aliases") or [] if isinstance(entity.get("aliases"), list) else [])]
        hits = {people[k] for k in (agent_detectors.fold(str(n or "")) for n in names if n) if k in people}
        if len(hits) == 1:
            entity[MARK] = next(iter(hits))
            marked += 1
    return marked


def card_of(entity: dict, siblings=()) -> str | None:
    """The card every marked mention of one name agrees on, or ``None`` (none marked, or two cards: a name two
    people in two chats share is decided by the usual rules)."""
    cards = {clean_card_id(e.get(MARK)) for e in (entity, *siblings) if isinstance(e, dict) and e.get(MARK)}
    cards.discard(None)
    return next(iter(cards)) if len(cards) == 1 else None
