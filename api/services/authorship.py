"""Whose words an episode holds, read from its own record — the ONE value every evidence reader passes as ``override``.

Two answers existed before this module, and every reader read only the first:

* **Declared** (R-F2 / R-LS7): an episode's ``evidence_kind`` — ``user`` (a watched folder's own files, a reminder, a
  Notion page of the person's) or ``assistant`` (someone else's words: a shared list, a relayed app's turn, an agent's
  memory note, a day of traces). It wins.
* **A saved item** (2026-10-29, :data:`evidence.SAVE_KIND`): a bookmark, a saved link, a saved-list post, a feed item,
  a watched day, a tab group, a calendar entry. Its body is the page's own words — the title, the site, the
  description Cicada fetched — with the person's own reason or note in its own section (``evidence.PERSON_SECTIONS``).
  A save carries no turn marker, so before this R4's default read the WHOLE save as the person's writing: a fetched
  description of four paragraphs was four "exchanges in the person's own words" (promotion), and a span in it was
  labelled ``user`` (``evidence.speaker_kind``) — which ruling 42, the Contacts-card rule and ``web_context``'s
  protection all read as the person's. Derived on read, never stored, so no existing episode is rewritten and every
  reader agrees from its next read.

What makes an episode a saved item is the episode's own record, never what a line says: the saving door's
``media_entity_id`` or ``url``, or a saving door's ``origin``/``source`` (:func:`saved_origin`, the list
``inbox_tend`` already used to keep a saved page's title from counting as the person's words).
"""
from __future__ import annotations

import functools

from api.services.evidence import SAVE_KIND

#: Where something saved comes from (a bookmark, a saved post, a feed, a watch or web history, a read page): its text
#: is the page's, not the person's — a name in its title, link or byline is never "their own words".
SAVED_ORIGINS = frozenset({"bookmark", "saved-link", "media", "rss", "pdf", "ingest", "watch-history",
                           "watch-history-month", "video-watch", "page-read", "profile-read", "web-check",
                           "source-check", "web-history", "safari-tab", "chrome-tab-group", "tab-group"})
SAVED_SUFFIXES = ("-bookmark", "-bookmarks", "-saved", "-history", "-likes", "-playlist", "-tab", "-tabs")


@functools.cache
def _saving_doors() -> frozenset[str]:
    from api.services import source_overview   # the catalog is fixed at import; read once

    return SAVED_ORIGINS | {o for spec in source_overview.CATALOG if spec.kind in ("browser", "social", "feed")
                            for o in spec.origins}


def saved_origin(tag) -> bool:
    """Whether an episode's ``origin`` or ``source`` is a saving door (a bookmark, a saved post, a feed, a history):
    what came through it is the saved page's text, not something the person said."""
    t = str(tag or "").strip().lower()
    if not t:
        return False
    return t in _saving_doors() or t.endswith(SAVED_SUFFIXES)


def is_saved(fm: dict | None) -> bool:
    """A saved item, by its own record: the saving door's page link (``media_entity_id``, ``url``) or a saving door's
    ``origin``/``source``."""
    if not isinstance(fm, dict):
        return False
    if fm.get("media_entity_id") or fm.get("url"):
        return True
    return any(saved_origin(fm.get(k)) for k in ("origin", "source"))


def of(fm: dict | None) -> str | None:
    """The ``override`` for an episode: its declared ``evidence_kind``, else :data:`evidence.SAVE_KIND` for a saved
    item, else ``None`` (the turn markers decide, R4)."""
    if not isinstance(fm, dict):
        return None
    declared = str(fm.get("evidence_kind") or "").strip()
    if declared:
        return declared
    return SAVE_KIND if is_saved(fm) else None


#: The key Sleep's episode dict carries :func:`of` under (``sleep_cycle``), read from the whole frontmatter.
KEY = "words_of"


def of_episode(episode: dict | None) -> str | None:
    """:func:`of` for an episode dict (Sleep's, an ``inbox_tend`` conversation): the value Sleep read from the whole
    frontmatter when it carries one, else what the dict itself holds."""
    if isinstance(episode, dict) and KEY in episode:
        return episode[KEY]
    return of(episode)
