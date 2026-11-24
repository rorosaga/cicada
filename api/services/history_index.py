"""Watch history and platform-export saves are indexed, not consolidated (owner ruling 2026-10-18; G71, G94).

The owner imported a YouTube Takeout with its watch history: 45,879 watches became 2,532 day episodes and 3,156
playlist saves became saved videos, and every one of them was queued for a full Stage-1 model read. Owner: "maybe
overanalyzing the watch history is too much … Maybe just have it there and then maybe the metadata has it as
embeddings or something." So these are a record to look up, never a conversation to read:

* **What is index-only** (:func:`kind`). A watch-history day (``source: watch-history``), the month summary built
  from those days (``source: watch-history-month``, :func:`watch_history.rollup`), and a save that came in from a
  platform's saved LIST — a Takeout playlist (Watch later included, whichever door read it), Instagram saves and
  likes, TikTok likes and favourites, an X archive's likes and bookmarks, Reddit's and LinkedIn's export CSVs. A link
  the person bookmarked in a browser, a single URL save, a connector poll (Reddit's ``r/<sub>`` folders, X's API
  bookmarks) and a save carrying the person's own note keep being read by Sleep: none of those has an index-only
  origin, no list door carries the person's words (the parsers never set ``note`` or ``reason``), and a list save
  that ever did is stamped ``has_note`` and queued like any save.
* **Read without a model.** Capture writes them already read — ``processed: true``, ``processed_by: index`` — and
  Sleep retires the ones a bank queued before this ruling (:func:`retire`) at the start of every run, before a
  drain freezes its ids, in its own ``cicada`` commit. :func:`waits_for_model` is the one predicate every "waiting
  for Sleep" count uses, so an index-only episode never enters a model batch, a drain's frozen list or its progress.
* **Found by lookup.** They stay files in ``episodes/``: the lexical and vector indexes cover every episode, so
  recall's excerpts, search and the timeline find them; a saved video stays in Saved with its media page.

**The lean pass (ruling 62, owner 2026-11-04):** "a leaner initial pass for consolidation on those things who have no
reason/user intent attached, but enough info so that it can come up in a relevant conversation and an agent can look
further into it." So every other bare save is index-only too (:func:`kind` ``saved``): a browser bookmark, a tab group,
a single saved link, a feed item, a connector poll, with no note and no reason. No model reads it; it makes no claim, no
page and no question; its title, link, site and date stay findable (``saved_lookup``). A save carrying a reason, or one
the person later talks about, is read once like any conversation (:func:`wake`, ``saved_mentions``). A save a model
already read keeps what it made and stays as it was: ``saved`` never names it.

**Ruling 80 (owner 2026-11-24, G246): "if i save it already has a reason."** Saving is the reason, so Sleep reads a save
after his conversations (:data:`SAVES_READ`). Ruling 62's lean pass is withdrawn for what he saves, and what is left of
it is the *pile*: a save that arrived in bulk (a first whole list read, an export, an import), one received long after
the day it was saved, and every save a bank already kept, waits its turn. Stored ``processed: true, processed_by: index``
(the old pair, so a bank written before this ruling needs no migration), it is released
:data:`SAVES_PER_DAY` a local day, newest first, after everything else (:func:`take_turns`), and put back when a night
ends before it was read (:func:`return_to_pile`). :func:`kind` therefore names a save only while it is in the pile; a
save written waiting (``processed: false``: a click, a paste, a notch or site save, a small poll), one a model read, and
one that holds nothing to read (:data:`NO_WORDS_BY`) are ordinary episodes to every reader that asks "is this
index-only". Watch history, a month's summary, activity traces, reading and listening days, a locked note and the
*records* (:func:`is_record`: his own repositories, joined communities, an open tab on another device) are not saves and
stay index-only exactly as before. ``SAVES_READ = False`` restores ruling 62 whole: capture writes every save
index-only, :func:`take_turns` releases nothing and :func:`retire` retires a queued save again.

Rails: no model and no fetch here; frontmatter only for the predicate (the cached ``bank_index`` scan); every write
under the bank's episode lock, re-checked before it flips; nothing here logs a title or a query.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from api.services import evidence as _evidence

#: ``processed_by`` of an episode read by the index, never by a model.
INDEXED_BY = "index"
#: ``source`` of a watch-history day (``watch_history.SOURCE``) and of a month's summary.
HISTORY_SOURCE = "watch-history"
HISTORY_PREFIX = "watch-history:"
MONTH_SOURCE = "watch-history-month"
MONTH_PREFIX = "watch-history-month:"
#: ``source`` of an activity-traces day summary (G218, ``trace_memory``): counted, index-only unless the person turned
#: on "Learn from traces" when it was written (``learn_from_traces`` in its frontmatter) — the one model read traces get.
TRACES_SOURCE = "traces-day"
TRACES_PREFIX = "traces-day:"
#: ``source`` of a reading day (G218, 2026-10-28, ``trace_memory.write_reading``): the pages activity traces saw read
#: on any site that day — index-only like a watched day (ruling 30), never read by a model. G89 (2026-11-04): the posts
#: the person's Substack History showed, ``reading-history:substack:<day>`` (``substack_reads``), are the same kind.
READING_SOURCE = "reading-history"
READING_PREFIX = "reading-history:"
#: ``source`` of a listening day (G32, ``listening_history``): what was played on Spotify that day, from the person's own
#: export — index-only like a watched day (ruling 30), never read by a model, never a mention.
LISTENING_SOURCE = "listening-history"
LISTENING_PREFIX = "listening-history:"
#: Origins only a platform's saved list writes (an export archive, or the person's agent reading Watch later or,
#: G206, a saved list on X, Instagram or LinkedIn — ``saved_lists``, which files X under the archive's ``Bookmarks``).
#: G230: GitHub's own lists, read with the person's token — the repositories they starred (a save each) and the ones
#: they own (a record GitHub keeps, offered as a project, never the person's words).
#: G232: Pinterest's saved pins, read by the person's agent in their browser.
#: G89 (2026-11-04): ``substack-saved`` — the posts the person's agent read off their Substack Saved list.
LIST_ORIGINS = frozenset({"youtube-playlist", "instagram-saved", "tiktok-saved", "x-likes", "x-reposts", "linkedin-saved",
                          "spotify-saved", "github-starred", "github-owned", "pinterest-saved", "substack-saved"})
#: Origins a connector shares with an export: the export's rows are told apart by the folder its reader names
#: (the Reddit connector files under ``r/<sub>``, the X connector under no folder).
LIST_FOLDERS: dict[str, frozenset[str]] = {
    # G232: an upvote (a like) and a joined community (a follow), from the connector or the export, are index-only
    # like Instagram's likes; a connector save (``r/<sub>``) is still a connector poll Sleep reads (ruling 30).
    "reddit-saved": frozenset({"Saved posts", "Saved comments", "Upvoted", "Joined communities"}),
    "x-bookmarks": frozenset({"Bookmarks"}),
}
#: Ruling 62: what a bare save is, by its own record, beside the saving door's page link (``media_entity_id``, ``url``):
#: a tab group holds no page link, and an older bookmark episode may not.
SAVE_SUFFIXES = ("-bookmark", "-tab-group")
SAVE_SOURCES = frozenset({"tab-group"})
#: Ruling 62: an episode carrying a saved page's link that is NOT a save: an agent's report of what it read or watched,
#: or Cicada's own check. Each is written read, or read on its own terms.
NOT_A_SAVE = frozenset({"video-watch", "page-read", "profile-read", "web-check", "source-check", "source-refresh"})
#: A book's record (``books.EPISODE_KEY``): read for its notes, on its own terms.
BOOK_KEY = "book"
#: Frontmatter flag on a list save that carries the person's own note or reason: their words are read by Sleep.
NOTE_KEY = "has_note"
#: Ruling 62: why a bare save gets its one real read (``{why, at}``): the person mentioned it. Stamped by :func:`wake`,
#: it takes the episode out of :func:`kind` for good, so the read happens once and says why.
WOKEN_KEY = "read_asked"
#: G221 (2026-11-23): a save filed in a folder the person gave a reason to inherits it, and that makes it readable
#: (``save_folders``): ``{at, folders}``, stamped by that module alone when the folder's reason is set or the save is
#: filed, removed when neither holds. The reason itself is never copied here — it is read from the folder's own record.
FOLDER_READ_KEY = "readable_by_folder"
#: Frontmatter a list save carries once the person said why they saved it (``saved_why``'s answer, its earlier
#: answers) or a note, or once its folder carries a reason of theirs (:data:`FOLDER_READ_KEY`, G221): any of them makes
#: the save readable, never index-only (review of #340).
PERSON_KEYS = (NOTE_KEY, "saved_why", "saved_why_earlier", FOLDER_READ_KEY)
#: Body sections only the person's own words fill: ``saved_why``'s, a save's reason (Telegram, ``/save``), a note —
#: ``evidence``'s one list, which also makes them the only ``user`` words in a save.
PERSON_SECTIONS = _evidence.PERSON_SECTIONS
#: Ruling 62: an agent's note on a save (``## Note``) is not the person's words, and it still says why the link matters:
#: a save that has one is read like a save with a reason.
REASON_SECTIONS = (*PERSON_SECTIONS, "## Note")
#: Paths per retirement commit: a commit names each path three times on git's command line.
COMMIT_STEP = 500

#: Ruling 80 (owner 2026-11-24): saving is the reason, so Sleep reads a save. ``False`` is the kill switch: ruling 62's
#: lean pass whole (:func:`kind`, :func:`take_turns`, :func:`retire`, capture's stamp in ``media_ingestor``).
SAVES_READ = True
#: How many saves leave the pile for Sleep a local day (the one number; ruling 80 (c), the owner's cost answer pending).
#: Newest first, after every conversation and every talked-about save.
SAVES_PER_DAY = 100
#: More than this many new saves in one door (an import, an export, a first whole list read) is a bulk: each waits its
#: turn in the pile whatever its dates.
BULK_ITEMS = 10
#: A save received more than this many days after the day it was saved waits its turn too (a browser import of old
#: bookmarks, an archive): whatever the door.
LATE_DAYS = 30
#: ``processed_by`` of a save that holds nothing for a model to read (a title and a link on a site Sleep never reads a
#: page of): written at capture, read when the person talks about it or their agent opens it.
NO_WORDS_BY = "no-words"
#: The local day a save left the pile (``YYYY-MM-DD``): stamped by :func:`take_turns`, kept by :func:`return_to_pile`
#: so a night that stopped early does not spend the day's number twice.
TURN_KEY = "turn_released_on"
#: Records another service keeps for the person, never something they saved (ruling 80 (e) (i)): never read, never
#: released, never woken by a mention. ``github-owned`` and the joined communities are in :data:`LIST_ORIGINS` /
#: :data:`LIST_FOLDERS` as before; an open tab on another device is a bookmark-shaped record of its own.
RECORD_ORIGINS = frozenset({"github-owned", "safari-tab"})
RECORD_FOLDERS = {"reddit-saved": frozenset({"Joined communities"})}


def kind(fm: dict | None) -> str | None:
    """``history`` (a watched day), ``month`` (a month's summary), ``list`` (a save from a platform's saved list),
    ``traces`` (an index-only trace day written before 2026-10-28), ``reading`` (a reading day), ``listening``
    (a listening day, G32), ``locked`` (a retired locked note, G234: never read, never indexed), ``saved`` (a bare
    save), or ``None`` — an episode Sleep reads with a model.

    Ruling 80: ``saved`` and ``list`` name a save only while it is index-only — in the pile (``processed: true``,
    ``processed_by: index``) or a record (:func:`is_record`). A save waiting for Sleep, one a model read and one with
    nothing to read are ``None``, like any episode (:func:`save_state` says which)."""
    k = shape(fm)
    if k not in ("saved", "list") or not SAVES_READ:
        return k
    return k if is_record(fm) or in_pile(fm) else None


def in_pile(fm: dict | None) -> bool:
    """Is this save stored waiting its turn (ruling 80): read by the index alone so far, not by a model."""
    return isinstance(fm, dict) and bool(fm.get("processed", False)) and fm.get("processed_by") == INDEXED_BY


def is_record(fm: dict | None) -> bool:
    """A record another service keeps for the person (ruling 80 (e) (i)): his own repository, a joined community, an
    open tab on another device. Index-only for good: never read, released or woken."""
    origin = str((fm or {}).get("origin") or "")
    return origin in RECORD_ORIGINS or str((fm or {}).get("folder") or "") in RECORD_FOLDERS.get(origin, ())


def save_shaped(fm: dict | None) -> str | None:
    """Is this episode a save by its own record — ``saved`` (a bookmark, a saved link, a tab group) or ``list`` (a post
    from a platform's saved list) — whoever has since read it, woken it or given it a reason? ``None`` for everything
    else: a conversation, a book's record, an agent's report, a watched day, a feed item that is no page."""
    if not isinstance(fm, dict) or fm.get(_evidence.LOCKED_NOTE_KEY):
        return None
    source = str(fm.get("source") or "")
    sid = str(fm.get("source_id") or "")
    for src, prefix in ((HISTORY_SOURCE, HISTORY_PREFIX), (MONTH_SOURCE, MONTH_PREFIX), (TRACES_SOURCE, TRACES_PREFIX),
                        (READING_SOURCE, READING_PREFIX), (LISTENING_SOURCE, LISTENING_PREFIX)):
        if source == src or sid.startswith(prefix):
            return None
    origin = str(fm.get("origin") or "")
    if origin in LIST_ORIGINS:
        return "list"
    folders = LIST_FOLDERS.get(origin)
    if folders is not None and str(fm.get("folder") or "") in folders:
        return "list"
    if fm.get(BOOK_KEY) or source in NOT_A_SAVE:
        return None
    if source in SAVE_SOURCES or origin.endswith(SAVE_SUFFIXES):
        return "saved"
    return "saved" if (fm.get("media_entity_id") and fm.get("url")) else None


def save_state(fm: dict | None) -> str | None:
    """Where a save stands (ruling 80): ``record`` (another service's record, never read), ``pile`` (waiting its turn),
    ``waiting`` (for Sleep tonight), ``no-words`` (nothing for a model to read), ``read`` (a model or agent read it), or
    ``None`` when the episode is no save."""
    if save_shaped(fm) is None:
        return None
    if is_record(fm):
        return "record"
    if not fm.get("processed", False):
        return "waiting"
    by = fm.get("processed_by")
    if by == INDEXED_BY:
        return "pile"
    return "no-words" if by == NO_WORDS_BY else "read"


def not_read(fm: dict | None) -> bool:
    """The one place "not read yet" comes from: a save no model has read — waiting for tonight, waiting its turn in the
    pile, or holding nothing to read. A record is no save and is never "not read yet"."""
    return save_state(fm) in ("waiting", "pile", "no-words")


def shape(fm: dict | None) -> str | None:
    """What :func:`kind` said before ruling 80, by the record's own shape and whatever has happened to it since: the
    save kinds (``saved``, ``list``) say nothing about whether a model has read it."""
    if not isinstance(fm, dict):
        return None
    if fm.get(_evidence.LOCKED_NOTE_KEY):
        return "locked"
    source = str(fm.get("source") or "")
    sid = str(fm.get("source_id") or "")
    if source == HISTORY_SOURCE or sid.startswith(HISTORY_PREFIX):
        return "history"
    if source == MONTH_SOURCE or sid.startswith(MONTH_PREFIX):
        return "month"
    if source == TRACES_SOURCE or sid.startswith(TRACES_PREFIX):
        return None if fm.get("learn_from_traces") is True else "traces"
    if source == READING_SOURCE or sid.startswith(READING_PREFIX):
        return "reading"
    if source == LISTENING_SOURCE or sid.startswith(LISTENING_PREFIX):
        return "listening"
    origin = str(fm.get("origin") or "")
    if any(fm.get(key) for key in PERSON_KEYS):
        return None
    if fm.get(WOKEN_KEY):
        # Ruling 78 (e): the person talked about this save, so its one real read is owed or done, whatever list it
        # came from. (A bare save is judged the same way in `_is_bare_save`.)
        return None
    if origin in LIST_ORIGINS:
        return "list"
    folders = LIST_FOLDERS.get(origin)
    if folders is not None and str(fm.get("folder") or "") in folders:
        return "list"
    return "saved" if _is_bare_save(fm, origin, source) else None


def _is_bare_save(fm: dict, origin: str, source: str) -> bool:
    """Ruling 62: a save nobody has said anything about yet, by its own record, never by what its body says. Not one a
    model or an agent already read (a save read before this ruling keeps what it made, and every reader goes on
    treating it as read), not one woken for its read, not a book's record, not an agent's report."""
    if fm.get(WOKEN_KEY) or fm.get(BOOK_KEY) or source in NOT_A_SAVE:
        return False
    if fm.get("processed", False) and fm.get("processed_by") != INDEXED_BY:
        return False
    if source in SAVE_SOURCES or origin.endswith(SAVE_SUFFIXES):
        return True
    return bool(fm.get("media_entity_id") and fm.get("url"))


#: Ruling 78 (e): the list saves a mention does NOT wake — a repository the person owns is a record GitHub keeps
#: (ruling 53), and a joined community is a follow: neither is something they could be talking about as a save.
NOT_MENTIONABLE_ORIGINS = frozenset({"github-owned"})
NOT_MENTIONABLE_FOLDERS = {"reddit-saved": frozenset({"Joined communities"})}


def mentionable(fm: dict | None) -> bool:
    """Ruling 78 (e), 80: may the person's own words about this save get it read first? A save waiting for Sleep or in
    the pile and not already asked for. Not a record (a repository he owns, a joined community, an open tab is not
    something he could be talking about as a save), not one a model read, not one with nothing to read: those leave
    only the ask (``saved_mentions``)."""
    if not SAVES_READ:
        return kind(fm) in ("saved", "list") and not is_record(fm)
    return save_state(fm) in ("pile", "waiting") and not (fm or {}).get(WOKEN_KEY)


def is_list_origin(fm: dict | None) -> bool:
    """Does this record's own origin (and folder) say it came from a platform's list? True whether or not it has since
    been woken or given a reason (which take it out of :func:`kind`)."""
    origin = str((fm or {}).get("origin") or "")
    if origin in LIST_ORIGINS:
        return True
    folders = LIST_FOLDERS.get(origin)
    return folders is not None and str((fm or {}).get("folder") or "") in folders


def is_index_only(fm: dict | None) -> bool:
    return kind(fm) is not None


def owes_a_read(fm: dict | None) -> bool:
    """Ruling 62: a save queued for its real read that no model has taken yet: woken, or given a reason. A later sync
    re-stages it as a bare save; that never takes the read back (``episode_staging``)."""
    return (isinstance(fm, dict) and not fm.get("processed", False) and kind(fm) is None
            and (bool(fm.get(WOKEN_KEY)) or any(fm.get(key) for key in PERSON_KEYS)))


def is_unread_save(fm: dict | None) -> bool:
    """A save no claim holds yet, so only ``saved_lookup`` can bring it up: one in the pile, one waiting for Sleep (kept
    by its own words until tonight), or one with nothing to read."""
    if kind(fm) == "saved":
        return True
    return SAVES_READ and save_shaped(fm) == "saved" and not_read(fm)


def is_pageless_save(fm: dict | None) -> bool:
    """A save with no page of its own (a tab group) that the saved-item finder serves from its passages: unread ones, and,
    since ruling 80, one a model read too — it has no page, so no other leg is promised to hold what its tabs said."""
    if is_unread_save(fm):
        return True
    return SAVES_READ and save_shaped(fm) == "saved" and save_state(fm) == "read" and not (fm or {}).get("media_entity_id")


def has_person_words(body: str | None) -> bool:
    """Does a save's body hold a section the person wrote (why they saved it, a reason, a note)?"""
    lines = {ln.strip() for ln in (body or "").splitlines()}
    return any(h in lines for h in PERSON_SECTIONS)


def has_a_reason(body: str | None) -> bool:
    """Ruling 62: does a save's body say why it was saved, in the person's words or an agent's note?"""
    lines = {ln.strip() for ln in (body or "").splitlines()}
    return any(h in lines for h in REASON_SECTIONS)


def mark_person_words(fm: dict) -> bool:
    """A list save just gained the person's own words: stamp it theirs (``has_note``) and, when the index had read it,
    queue it for Sleep again. Mutates ``fm``; ``True`` when it changed. The caller writes under the episode lock."""
    if not (save_state(fm) in ("pile", "waiting", "no-words") if SAVES_READ else kind(fm) in ("list", "saved")):
        return False
    fm[NOTE_KEY] = True
    if fm.get("processed_by") in (INDEXED_BY, NO_WORDS_BY):   # its words are something to read now
        fm["processed"] = False
        fm.pop("processed_by", None)   # G114 R6: written only beside processed: true
    return True


def wake(memory_path: Path, episode_id: str, why: str, at: str) -> str | None:
    """Ruling 62, 78 (e), 80: the person talked about this save, so it is read first. Stamps :data:`WOKEN_KEY` (which puts
    it ahead of every other save at the next freeze, ``saved_order``); a save in the pile is also queued for the next run,
    one already waiting needs no more than the stamp. Under the episode lock, re-checked. The memory-relative path, or
    ``None`` when it is no longer such a save (read meanwhile, removed from its source, a record, holding nothing to
    read). Only ``saved_mentions`` calls this: a retrieval hit never does."""
    from api.services import episode_ids, markdown_parser, saved_mentions

    episodes_dir = Path(memory_path) / "episodes"
    path = episodes_dir / f"{episode_id}.md"
    with episode_ids.episode_lock(episodes_dir):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — a missing or malformed file wakes nothing
            return None
        fm = dict(parsed.frontmatter)
        if not mentionable(fm) or fm.get("source_deleted_at"):
            return None
        if save_shaped(fm) == "list" and why not in (saved_mentions.WHY_LINK, saved_mentions.WHY_TITLE):
            return None   # ruling 78 (e): a list save wakes only for the person's own located words, never a lit page
        fm[WOKEN_KEY] = {"why": why, "at": at}
        fm["processed"] = False
        fm.pop("processed_by", None)   # G114 R6: written only beside processed: true
        markdown_parser.write(path, fm, parsed.body)
    return f"episodes/{episode_id}.md"


def waits_for_model(fm: dict | None) -> bool:
    """Is this episode waiting for Sleep's model read? Not when it is read, and never when it is index-only."""
    if not isinstance(fm, dict) or fm.get("processed", False):
        return False
    return not is_index_only(fm)


def _now() -> str:
    from api.services import episode_ids

    return episode_ids.utc_now_iso()


def _origin(fm: dict) -> str:
    return str(fm.get("origin") or fm.get("source") or "unknown")


@dataclass
class Count:
    """What :func:`retire` would do: counts and enums only (never a title)."""

    waiting: int = 0                     # every episode with processed: false
    for_model: int = 0                   # what Sleep's model would still read
    index_only: Counter = field(default_factory=Counter)      # kind -> queued episodes
    by_origin: Counter = field(default_factory=Counter)       # origin -> queued index-only episodes
    already_indexed: Counter = field(default_factory=Counter)  # kind -> episodes read by the index

    def as_dict(self) -> dict:
        return {"waiting": self.waiting, "for_model": self.for_model,
                "index_only_queued": sum(self.index_only.values()),
                "index_only_by_kind": dict(sorted(self.index_only.items())),
                "index_only_by_origin": dict(sorted(self.by_origin.items())),
                "already_indexed_by_kind": dict(sorted(self.already_indexed.items()))}


def count(memory_path: Path) -> Count:
    """The dry run: one cached frontmatter pass, writes nothing."""
    from api.services import bank_index

    out = Count()
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        k = kind(fm)
        if fm.get("processed", False):
            if k is not None and fm.get("processed_by") == INDEXED_BY:
                out.already_indexed[k] += 1
            continue
        out.waiting += 1
        if k is None:
            out.for_model += 1
        else:
            out.index_only[k] += 1
            out.by_origin[_origin(fm)] += 1
    return out


@dataclass
class Retired:
    paths: list[str] = field(default_factory=list)     # memory-relative
    by_kind: Counter = field(default_factory=Counter)
    skipped_dirty: int = 0
    #: list saves whose body holds the person's own words: stamped theirs and left for the model
    returned: int = 0
    #: the ``paths`` left queued for a read rather than marked read (the manifest's word for them)
    queued: list[str] = field(default_factory=list)


def retire(memory_path: Path, *, skip: frozenset[str] = frozenset()) -> Retired:
    """Mark every queued index-only episode read, ``processed_by: index``. Pure files; the caller commits
    ``paths``. ``skip``: memory-relative paths dirty in git before this ran — an uncommitted capture keeps its own
    author (its writer's commit, or the next run, takes it); it stays out of every model batch meanwhile
    (:func:`waits_for_model`). Each file is re-read under the episode lock and flipped only if it is still queued
    and still index-only, exactly as Sleep retires what it read (audit A01)."""
    from api.services import bank_index, episode_ids, markdown_parser, saved_mentions

    memory_path = Path(memory_path)
    out = Retired()
    queued = [f for f in bank_index.files(memory_path, "episodes")
              if not (f.frontmatter or {}).get("processed", False) and is_index_only(f.frontmatter)]
    if not queued:
        return out
    episodes_dir = memory_path / "episodes"
    for f in queued:
        rel = f"episodes/{f.path.name}"
        if rel in skip:
            out.skipped_dirty += 1
            continue
        with episode_ids.episode_lock(episodes_dir):
            try:
                parsed = markdown_parser.parse(f.path)
            except Exception:  # noqa: BLE001 — one malformed file never stops the rest
                continue
            fm = dict(parsed.frontmatter)
            k = kind(fm)
            if fm.get("processed", False) or k is None:
                continue
            if (k == "list" and has_person_words(parsed.body)) or (k == "saved" and has_a_reason(parsed.body)):
                # The person's words reached it by a door that did not stamp it (an older writer): theirs to read.
                # Ruling 62: an agent's note on a save too, the one kind of reason no frontmatter ever said.
                mark_person_words(fm)
                markdown_parser.write(f.path, fm, parsed.body)
                out.paths.append(rel)
                out.queued.append(rel)
                out.returned += 1
                continue
            if k == "saved" and saved_mentions.page_lit(memory_path, fm):
                # Ruling 62: a conversation already tied to this page, before the save was ever indexed.
                fm[WOKEN_KEY] = {"why": saved_mentions.WHY_LIT, "at": _now()}
                markdown_parser.write(f.path, fm, parsed.body)
                out.paths.append(rel)
                out.queued.append(rel)
                out.returned += 1
                continue
            fm["processed"] = True
            fm["processed_by"] = INDEXED_BY
            markdown_parser.write(f.path, fm, parsed.body)
        out.paths.append(rel)
        out.by_kind[k] += 1
    return out



# ---- ruling 80: how a save is kept, released from the pile, and put back ---------------------------------------------


def entry_stamp(fm: dict, *, has_words: bool, walled: bool, bulk: bool, late: bool) -> str | None:
    """How capture stores a save it has just built (``fm`` as :func:`media_ingestor.write_media_episode` assembled it, not
    yet carrying the person's own note): ``None`` — waiting for Sleep tonight, ``processed: false`` — or the
    ``processed_by`` of a save written already settled: :data:`INDEXED_BY` (the pile: a bulk door, a save received long
    after it was saved, or a record), :data:`NO_WORDS_BY` (a title and a link on a site no page is read from).
    A feed item and everything that is no save: ``None``, as before. File I/O only: no model, no fetch."""
    if save_shaped(fm) is None:
        return None
    if not SAVES_READ:
        return INDEXED_BY       # ruling 62, whole: every save is index-only
    if is_record(fm):
        return INDEXED_BY
    if walled and not has_words:
        return NO_WORDS_BY
    return INDEXED_BY if (bulk or late) else None


def _saved_day(fm: dict) -> str:
    """The day the person saved it, for ordering the pile: the save's recorded day or instant, else the post's, else the
    day Cicada received it (``timestamp`` is that for a save written before the recorded day was kept)."""
    for key in ("saved_at", "added_at", "posted"):
        value = str(fm.get(key) or "")[:10]
        if len(value) == 10:
            return value
    return str(fm.get("received_at") or fm.get("timestamp") or "")[:10]


def _local_today() -> str:
    from datetime import date

    return date.today().isoformat()


@dataclass
class Turns:
    """What :func:`take_turns` did: memory-relative paths and counts, never a title."""

    released: list[str] = field(default_factory=list)    # left the pile: waiting for tonight
    emptied: list[str] = field(default_factory=list)     # stamped ``no-words`` instead: nothing to read, no turn used
    skipped_dirty: int = 0
    budget: int = 0                                      # the day's number still unspent when this began
    pile: int = 0                                        # saves in the pile when this began

    @property
    def paths(self) -> list[str]:
        return [*self.released, *self.emptied]


def nothing_to_read(fm: dict, body: str, url: str | None = None) -> bool:
    """Does this save, as stored, hold nothing for a model to read and no page Sleep reads for it? A title, a link, a
    site and a day on a link of a site no page is read from (a login-walled site, a video, a paper). A save with any
    words of the person's, or a text the page or post gave, has something to read."""
    from api.services import link_enrichment, saved_reading

    if fm.get("source") in SAVE_SOURCES or any(fm.get(key) for key in PERSON_KEYS):
        return False
    return saved_reading.holds_no_words(body) and link_enrichment._excluded_media(
        url or str(fm.get("url") or ""), str(fm.get("source") or ""))


def take_turns(memory_path: Path, *, skip: frozenset[str] = frozenset(), today: str | None = None,
               per_day: int | None = None) -> Turns:
    """Once a local day, release a fixed number of the pile for Sleep to read (ruling 80 (c)): the day's number less what
    was released today already (:data:`TURN_KEY`), newest saved day first (ties by id). A released save is written
    ``processed: false`` and stamped with the day; Sleep then reads it after every conversation and every save the person
    talked about (``saved_order``). A pile save that holds nothing to read is stamped :data:`NO_WORDS_BY` and costs no
    turn. A file dirty in git (``skip``), a save removed from its source and a record are left. Pure files under the
    episode lock, re-checked; the caller commits ``paths``. A no-op under ``SAVES_READ = False``."""
    from api.services import bank_index, episode_ids, markdown_parser

    memory_path = Path(memory_path)
    out = Turns()
    if not SAVES_READ:
        return out
    day = today or _local_today()
    limit = SAVES_PER_DAY if per_day is None else per_day
    files = bank_index.files(memory_path, "episodes")
    spent = sum(1 for f in files if (f.frontmatter or {}).get(TURN_KEY) == day)
    out.budget = max(0, limit - spent)
    pile = [f for f in files if kind(f.frontmatter) in ("saved", "list") and not is_record(f.frontmatter)
            and not (f.frontmatter or {}).get("source_deleted_at")]
    out.pile = len(pile)
    # A save that had today's turn and was put back (a night that ended at its line) waits for tomorrow's.
    pile = [f for f in pile if (f.frontmatter or {}).get(TURN_KEY) != day]
    if out.budget <= 0 or not pile:
        return out
    pile.sort(key=lambda f: (_saved_day(f.frontmatter or {}), str((f.frontmatter or {}).get("id") or f.stem)), reverse=True)
    episodes_dir = memory_path / "episodes"
    left = out.budget
    for f in pile:
        if left <= 0:
            break
        rel = f"episodes/{f.path.name}"
        if rel in skip:
            out.skipped_dirty += 1
            continue
        with episode_ids.episode_lock(episodes_dir):
            try:
                parsed = markdown_parser.parse(f.path)
            except Exception:  # noqa: BLE001 — one malformed file never stops the rest
                continue
            fm = dict(parsed.frontmatter)
            if kind(fm) not in ("saved", "list") or is_record(fm) or fm.get("source_deleted_at"):
                continue
            if nothing_to_read(fm, parsed.body):
                fm["processed_by"] = NO_WORDS_BY
                markdown_parser.write(f.path, fm, parsed.body)
                out.emptied.append(rel)
                continue
            fm["processed"] = False
            fm.pop("processed_by", None)   # G114 R6: written only beside processed: true
            fm[TURN_KEY] = day
            markdown_parser.write(f.path, fm, parsed.body)
        out.released.append(rel)
        left -= 1
    return out


def turns_due(memory_path: Path, *, today: str | None = None) -> bool:
    """Would :func:`take_turns` release something today: saves in the pile and some of the day's number unspent. The
    scheduled catch-up asks it, so a missed night with only the pile left still reads its share."""
    from api.services import bank_index

    if not SAVES_READ:
        return False
    day = today or _local_today()
    files = bank_index.files(Path(memory_path), "episodes")
    spent = sum(1 for f in files if (f.frontmatter or {}).get(TURN_KEY) == day)
    return spent < SAVES_PER_DAY and any(
        kind(f.frontmatter) in ("saved", "list") and not is_record(f.frontmatter)
        and not (f.frontmatter or {}).get("source_deleted_at") for f in files)


def pile_report(memory_path: Path, *, today: str | None = None) -> dict:
    """What the next run would do with the saves, as counts and enums only (never an id, a title or a link): where every
    save stands (:func:`save_state`), what leaves the pile tonight by origin (the day's number less what was released
    today, newest first, the pile's nothing-to-read saves costing none), what holds nothing to read, and how many nights
    the readable pile takes at the day's number. One cached frontmatter pass plus one body read per save in the pile;
    writes nothing. For ``api.scripts.history_index_dry_run``."""
    import math

    from api.services import bank_index, link_enrichment, saved_reading

    day = today or _local_today()
    files = bank_index.files(Path(memory_path), "episodes")
    states: Counter = Counter()
    spent = 0
    pile = []
    for f in files:
        fm = f.frontmatter or {}
        if fm.get(TURN_KEY) == day:
            spent += 1
        st = save_state(fm)
        if st is not None and not fm.get("source_deleted_at"):
            states[st] += 1
        if st == "pile":
            pile.append(f)
    pile.sort(key=lambda f: (_saved_day(f.frontmatter or {}), str((f.frontmatter or {}).get("id") or f.stem)), reverse=True)
    budget = max(0, SAVES_PER_DAY - spent)
    readable = Counter()
    nothing = Counter()
    public_title_only = 0
    tonight: Counter = Counter()
    left = budget
    n_readable = 0
    for f in pile:
        fm = f.frontmatter or {}
        origin = _origin(fm)
        try:
            body = f.body()
        except OSError:
            body = ""
        empty = saved_reading.holds_no_words(body) and fm.get("source") not in SAVE_SOURCES \
            and not any(fm.get(k) for k in PERSON_KEYS)
        if empty and link_enrichment._excluded_media(str(fm.get("url") or ""), str(fm.get("source") or "")):
            nothing[origin] += 1
            continue
        n_readable += 1
        readable[origin] += 1
        public_title_only += int(empty)
        if left > 0:
            tonight[origin] += 1
            left -= 1
    return {"per_day": SAVES_PER_DAY, "released_today": spent, "budget_today": budget,
            "saves_by_state": dict(sorted(states.items())),
            "pile": len(pile), "pile_readable": n_readable, "pile_nothing_to_read": sum(nothing.values()),
            "pile_public_title_only": public_title_only,
            "released_tonight": sum(tonight.values()), "released_tonight_by_origin": dict(sorted(tonight.items())),
            "readable_by_origin": dict(sorted(readable.items())), "nothing_to_read_by_origin": dict(sorted(nothing.items())),
            "nights_for_the_pile": math.ceil(n_readable / SAVES_PER_DAY) if SAVES_PER_DAY > 0 else None}


def return_to_pile(memory_path: Path, ids: list[str], *, skip: frozenset[str] = frozenset()) -> list[str]:
    """Put released saves nobody read back in the pile (a night that ended before it reached them, or the revert of a
    day's release): ``processed: true, processed_by: index``, :data:`TURN_KEY` kept so the day's number stays spent. Only
    a save still waiting, released by :func:`take_turns`, with no word of the person's and not talked about; each
    re-checked under the episode lock. The memory-relative paths changed."""
    from api.services import episode_ids, markdown_parser

    out: list[str] = []
    episodes_dir = Path(memory_path) / "episodes"
    for episode_id in ids:
        rel = f"episodes/{episode_id}.md"
        if rel in skip:
            continue
        path = episodes_dir / f"{episode_id}.md"
        with episode_ids.episode_lock(episodes_dir):
            try:
                parsed = markdown_parser.parse(path)
            except Exception:  # noqa: BLE001
                continue
            fm = dict(parsed.frontmatter)
            if save_state(fm) != "waiting" or not fm.get(TURN_KEY) or fm.get(WOKEN_KEY) \
                    or any(fm.get(key) for key in PERSON_KEYS):
                continue
            fm["processed"] = True
            fm["processed_by"] = INDEXED_BY
            markdown_parser.write(path, fm, parsed.body)
        out.append(rel)
    return out


def released_unread(memory_path: Path, day: str) -> list[str]:
    """The ids released on ``day`` that no model has read yet: what reverting that day's release puts back."""
    from api.services import bank_index

    return [str((f.frontmatter or {}).get("id") or f.stem) for f in bank_index.files(Path(memory_path), "episodes")
            if (f.frontmatter or {}).get(TURN_KEY) == day and save_state(f.frontmatter) == "waiting"]

TRIGGER = "sleep/index"
AUTHOR = "cicada"


def commit_message(paths: list[str], day: str, *, part: int = 1, parts: int = 1,
                   queued: frozenset[str] = frozenset()) -> str:
    """``Indexed without a model <date>``: one manifest line per file, ``Cicada-Author: cicada``, no engine trailer
    (no model ran — the G85 shape). ``queued``: files this left waiting for a read, which were not indexed."""
    from api.services import git_service

    suffix = f" (part {part} of {parts})" if parts > 1 else ""
    return git_service.build_commit_message(
        f"Indexed without a model {day}{suffix}",
        [f"{p}: {'queued' if p in queued else 'indexed'} (source: n/a, trigger: {TRIGGER})" for p in paths],
        authors=[AUTHOR],
    )


def restore(memory_path: Path, paths: list[str]) -> None:
    """Put files back as HEAD has them after a failed commit; an untracked one (a month summary born this run) is
    removed. Through the bank's one write lock. Re-derived on the next run."""
    from api.services import git_service

    memory_path = Path(memory_path)
    if not paths or not (memory_path / ".git").exists():
        return
    tracked: list[str] = []
    for p in paths:
        try:
            known = bool(git_service.run_git_write_sync(memory_path, "ls-files", "--", p).strip())
        except git_service.GitError:
            known = True
        if known:
            tracked.append(p)
        else:
            try:
                (memory_path / p).unlink()
            except OSError:
                pass
    if tracked:
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "--", *tracked)
        except git_service.GitError:
            pass


__all__ = ["AUTHOR", "BULK_ITEMS", "COMMIT_STEP", "Count", "HISTORY_SOURCE", "INDEXED_BY", "LATE_DAYS", "LIST_FOLDERS",
           "LIST_ORIGINS", "MONTH_SOURCE", "NOTE_KEY", "NO_WORDS_BY", "PERSON_KEYS", "PERSON_SECTIONS", "RECORD_FOLDERS",
           "RECORD_ORIGINS", "Retired", "SAVES_PER_DAY", "SAVES_READ", "TURN_KEY", "Turns", "WOKEN_KEY", "has_a_reason",
           "is_pageless_save", "is_unread_save", "owes_a_read", "pile_report", "has_person_words", "mark_person_words", "TRIGGER", "commit_message", "count",
           "entry_stamp", "in_pile", "is_index_only", "is_record", "kind", "not_read", "nothing_to_read", "released_unread",
           "restore", "retire", "return_to_pile", "save_shaped", "save_state", "take_turns", "turns_due", "waits_for_model",
           "wake"]
