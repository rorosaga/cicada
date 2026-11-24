"""Quiet pages — a page that exists only because of an import, until the person mentions it (owner ruling 2026-10-20).

Saving a link, a video or a playlist item mints a ``media`` page at once (the save is a deliberate signal, so it skips
promotion), and a large import mints hundreds. Those pages are real, but nobody has *talked* about them yet. The
ruling: they are drawn dimmed until the person mentions them, the first mention lights them up, and the inbox never
asks about a quiet page.

**Quiet is derived, never stored.** It is read from what the record already holds — the page's ``source_episodes``
and the evidence its claims cite — every time a page is read, so the first conversation that mentions the page (Sleep
appends that conversation to ``source_episodes`` and its claims cite it) ends it with nothing to write or undo.

The rule. A page is quiet when

1. it has **import evidence** on the page itself: it is a saved page (``media:`` frontmatter, written only by the
   save, playlist and paper writers — Stage 1 never extracts ``media``), or one of its own ``source_episodes`` is a
   save (an episode carrying ``media_entity_id``: a saved link, video or playlist item, or a note on one; or a tab
   group, which holds no page link: G245) or a watch
   (a recorded watch, a day or month of watch history); and
2. it has **no conversation evidence**: none of its episodes, and no episode its claims cite, is anything else, and no
   claim on it cites the words of a person (``user`` / ``speaker`` evidence, :data:`promotion.PERSON_KINDS`).
   Cicada's own reading — a source check, a source re-check, a web check, a LinkedIn profile an agent read — is
   neither: it never lights a page and never makes one quiet. An episode id that no longer resolves says nothing
   either way.

**A book the person marked is never quiet (owner 2026-11-04, ruling 64):** a book's record that holds a highlight or a
note (:func:`marked_record`) is their own act, whatever the words' kind, so it counts as a conversation: it lights the
book's page, and a theme page Sleep drew from it. A library entry with nothing marked stays quiet, and a record whose
marks were all removed goes back to being one. The owner's page is never quiet. A page with no recorded episode at all (written by the person, an agent or a seed) has
no import evidence, so it is never quiet either: the rule dims what an import made, not what nobody wrote down.

Decay is untouched (decay classes, rulings 1 and 30): quiet is a presentation and an inbox gate, not a confidence.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from api.services import bank_index, promotion

#: A save: the media writer stamps every save episode (and a note on a save) with the page it made.
SAVE_KEY = "media_entity_id"
#: A watch: a recorded watch (``watch_record.SOURCE``), a day and a month of watch history
#: (``watch_history.SOURCE``, ``history_index.MONTH_SOURCE``).
WATCH_SOURCES = frozenset({"video-watch", "watch-history", "watch-history-month"})
#: A tab group (``tab_groups``, ``history_index.SAVE_SOURCES``) is one record of the tabs the person kept together: a
#: save with no page of its own, so it carries no ``media_entity_id``. It is an import all the same — a page only a tab
#: group named is quiet, and the group is no conversation for the 2+ rule or a person's own words (G245).
TAB_GROUP_SOURCES = frozenset({"tab-group"})
#: Cicada's own reading, or an agent's on the person's behalf — never the person mentioning anything:
#: ``check_record.SOURCE``, ``source_refresh.ORIGIN``, ``web_settle.SOURCE``, ``linkedin_people.PROFILE_SOURCE``.
CHECK_SOURCES = frozenset({"source-check", "source-refresh", "web-check", "profile-read"})

IMPORT = "import"
CHECK = "check"
CONVERSATION = "conversation"


def marked_record(fm: dict) -> bool:
    """A book's record (``books.EPISODE_KEY``) that says it holds a highlight, a note or a review (ruling 64)."""
    book = fm.get("book")
    return isinstance(book, dict) and bool(book.get("highlights") or book.get("notes") or book.get("reviewed"))


def episode_kind(fm: dict | None) -> str | None:
    """``import`` (a save or a watch), ``check`` (Cicada's or an agent's reading) or ``conversation`` (anything else
    the person or their agents said) — or None for an episode that does not resolve."""
    if fm is None:
        return None
    if marked_record(fm):
        return CONVERSATION
    if fm.get(SAVE_KEY):
        return IMPORT
    source = str(fm.get("source") or "")
    if source in TAB_GROUP_SOURCES:
        return IMPORT   # a saved group of tabs holds no page link (ruling 80, G245), but it is a save all the same
    if source in WATCH_SOURCES:
        return IMPORT
    if source in CHECK_SOURCES:
        return CHECK
    return CONVERSATION


def episode_lookup(memory_path: Path) -> Callable[[str], str | None]:
    """One episode's kind by id, through ``bank_index`` (mtime-gated, one parse per episode per process), memoised for
    the reader that holds it."""
    memo: dict[str, str | None] = {}

    def kind(episode_id: str) -> str | None:
        if episode_id not in memo:
            entry = bank_index.file(memory_path, "episodes", f"{episode_id}.md") if episode_id else None
            memo[episode_id] = episode_kind(entry.frontmatter if entry is not None else None)
        return memo[episode_id]

    return kind


def episode_ids(values: Iterable) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text.startswith("ep_"):
            out.append(text.split("#", 1)[0])
    return out


def _imported_and_unmentioned(fm: dict, kind_of: Callable[[str], str | None]) -> bool:
    """The frontmatter half of the rule, which reads no body: import evidence on the page itself (its ``media:`` block
    or one of its own episodes a save or a watch), and none of its own episodes a conversation."""
    if not isinstance(fm, dict) or fm.get("owner") is True:
        return False
    if isinstance(fm.get("media"), dict) and fm["media"].get("kind") == "list":
        return False   # a list's own page (G246) is never quiet: it is what a person sees their saves through
    imported = isinstance(fm.get("media"), dict)
    for episode_id in dict.fromkeys(episode_ids(fm.get("source_episodes")
                                                 if isinstance(fm.get("source_episodes"), list) else [])):
        found = kind_of(episode_id)
        if found == CONVERSATION:
            return False
        imported = imported or found == IMPORT
    return imported


def lit_by_episodes(fm: dict, kind_of: Callable[[str], str | None]) -> bool:
    """A media page one of whose own episodes is a conversation: the first way a page stops being quiet."""
    return isinstance(fm, dict) and isinstance(fm.get("media"), dict) and not _imported_and_unmentioned(fm, kind_of)


def lit_by_claims(claims: Iterable, kind_of: Callable[[str], str | None]) -> bool:
    """A claim on the page that cites a person's own words or a conversation: the second way. Never someone else's claim
    (``external:``, a group member's, #499 review)."""
    for claim in claims or []:
        # A person's own words wake it — never someone else's claim (`external:`, a group member's, #499 review).
        if promotion.claim_cites_person(claim, located=False):
            return True
        if str(getattr(claim, "observer", "") or "").startswith("external:"):
            continue
        for ev in getattr(claim, "evidence", None) or []:
            if any(kind_of(e) == CONVERSATION for e in episode_ids([getattr(ev, "episode", "")])):
                return True
    return False


def is_quiet(fm: dict, claims: Iterable, kind_of: Callable[[str], str | None]) -> bool:
    """The rule (module docstring) over one page's frontmatter and claims: the frontmatter half first, then no claim
    citing a person's own words or a conversation."""
    if not _imported_and_unmentioned(fm, kind_of):
        return False
    return not lit_by_claims(claims, kind_of)


def dimmed(quiet: bool, entity_id: str, earned: Iterable[str]) -> bool:
    """What a page's ``quiet`` reads once the person gave a reason to a saved post (G246, ``saved_posts``): a post that
    earned its page is drawn like any page — never dimmed, asked about like any page. ``earned`` is empty while
    ``saved_posts.HIDE_POSTS`` is off, so nothing changes until the flip."""
    return quiet and entity_id not in earned


def page_is_quiet(memory_path: Path, entity_id: str, *, kind_of: Callable[[str], str | None] | None = None) -> bool:
    """Is this one page quiet right now? A missing or unreadable page is not (fail open: a read error never hides a
    question). Most pages are settled by their frontmatter alone — a conversation among their episodes — and only an
    imported page's body is read."""
    from api.services.claims import parse_claims

    if not entity_id:
        return False
    entry = bank_index.file(memory_path, "entities", f"{entity_id}.md")
    if entry is None:
        return False
    kind_of = kind_of or episode_lookup(memory_path)
    if not _imported_and_unmentioned(entry.frontmatter, kind_of):
        return False
    try:
        claims = parse_claims(entry.body())
    except Exception:
        return False
    return is_quiet(entry.frontmatter, claims, kind_of)


def page_is_dimmed(memory_path: Path, entity_id: str, *, kind_of: Callable[[str], str | None] | None = None) -> bool:
    """:func:`page_is_quiet` as a person sees it: a saved post that earned its page (``saved_posts``, G246) is not
    dimmed and the inbox may ask about it. The mention readers keep :func:`page_is_quiet` — a note a person gave a post
    is not a conversation that lit its page. Identical to :func:`page_is_quiet` while ``HIDE_POSTS`` is off."""
    from api.services import saved_posts

    quiet = page_is_quiet(memory_path, entity_id, kind_of=kind_of)
    return quiet and dimmed(quiet, entity_id, saved_posts.earned_ids(memory_path))


def survey(memory_path: Path) -> dict[str, int]:
    """Counts over a bank — how many pages are quiet, of how many carry import evidence — for the measurement the PR
    reports. Ids and counts only, never a title."""
    kind_of = episode_lookup(memory_path)
    pages = imported = quiet = 0
    for entry in bank_index.files(memory_path, "entities"):
        pages += 1
        fm = entry.frontmatter
        episodes = episode_ids(fm.get("source_episodes") if isinstance(fm.get("source_episodes"), list) else [])
        if isinstance(fm.get("media"), dict) or any(kind_of(e) == IMPORT for e in episodes):
            imported += 1
        if page_is_quiet(memory_path, entry.stem, kind_of=kind_of):
            quiet += 1
    return {"pages": pages, "imported": imported, "quiet": quiet}
