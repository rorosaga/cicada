"""Which saves are posts drawn as a row under their list, and which are works that keep a page (G246, ruling 81, owner
2026-11-24: "ok yes, but maye a small entity page that has all the saved posts would be good... i want to somehow see
saved things somewhere evn if i havent refer to them yet").

About half of a memory's pages are saved items, most of them short posts nobody referred to. A post is still stored,
searchable, found by recall and Ask and listed under its source; what changes is that, until the person gives a reason
to, it is not drawn as a page of its own: not a node in the graph, not a line in Clusters, not a member of the Media
hub, not a "Related" entry that opens nothing. **All of it is decided on read.** No file is rewritten, moved or deleted,
and no pass over an old bank exists: the same page is a row today and a page again the moment he talks about it.

**Ships dark.** :data:`HIDE_POSTS` is ``False``: every reader below returns what it returned before this module existed.
The coordinator sets it to ``True`` after reading a dry run on the real memory
(``python -m api.scripts.saved_posts_dry_run --bank <path>``, counts only) and after every door puts a post on a list —
the same pattern as ``connector_text.REPAIR``.

**The rule (:func:`is_post`) is a pure function of the page's own saved link**, never of the door it came through: the
same status bookmarked in a browser, saved from a click in the site, pasted, or read from the site's list gets the same
answer. A post is a link to X, Instagram, LinkedIn (not an article), Reddit, Pinterest or a TikTok photo post
(``saved_lists.canonical`` already says "this link is a post of that site"); an ordinary web bookmark, an article, a
paper, a book, a repository, a video (YouTube, a TikTok video), a track, a newsletter post and a recording are works and
keep their pages. A Reddit link post is a work: its page is the outbound link, never the permalink an alias carries.

**Earned (:func:`signs`).** A post is drawn as a page again when the person gave a reason to: a note or a why-answer on
the save; their own words naming it (``named``, which no re-stage pops); a conversation or a claim of theirs citing it;
an edit of its page; a link they made to it from a project or a source link they took or an edge one of their claims
backs; or "Keep as a page" (``kept_as_page``). Not earned, on purpose: Sleep's or an agent's reading (an ``external:``
claim, a page read, a watch), an agent's note on a save (an episode carrying an agent's session), a folder's reason (that
shows on the folder's page), a second list. An old-shape connector episode (the post's own text filed under the person's
note, ``connector_text``) is no words of theirs.

One predicate: the graph, Clusters, the hubs, the meaning neighbours, a page's Related lines, the quiet test and the inbox
all ask this module and nothing else (``test_saved_posts.py`` greps for a copy).

**The digest (the check stays cheap on a cold start).** Which posts are earned is asked before any graph is built — the
graph route's ETag, ``/graph/meaning``'s signature, the graph's cache key — and reading it out of every page and episode
header costs seconds in a fresh process. So the answer is decided from one small record per file (:func:`_entity_record`,
:func:`_episode_record`), kept under the file's own ``(mtime_ns, size)`` and, derived and disposable, stored outside every bank
(``derived_store``) for the next process: only a file that moved is read, and :func:`_resolve` is the one place a sign is
decided. See the "digest" section below.
"""
from __future__ import annotations

import hashlib
import itertools
import re
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from loguru import logger

from api.services import (bank_index, derived_store, episode_time, history_index, promotion, quiet_pages, saved_lists,
                          video_urls)
from api.version import __version__

#: **The flip.** ``False``: nothing a person sees changes — every reader returns what it did before this module. The
#: coordinator sets it to ``True`` after reading a dry run on the real memory (``api/scripts/saved_posts_dry_run.py``).
HIDE_POSTS = False

#: Question 2 of the plan, in one line. How a link saved from a browser's own bookmarks is judged. ``by-link``: like
#: every other door, by the link alone (an X status is a post, an ordinary web page a work). ``pages``: a bookmarked
#: link is always a work (a page). ``rows``: a bookmarked link is always a post, whatever it is (declared works, videos
#: and feed items still keep their pages).
BOOKMARKED_LINKS = "by-link"
_BOOKMARKED_LINKS = ("by-link", "pages", "rows")

#: The sites whose lists hold posts (``saved_lists.LIST_KINDS`` ``posts``). Not Spotify (tracks) or Goodreads (books).
POST_SITES = ("x", "instagram", "linkedin", "reddit", "pinterest", "tiktok")
#: The stream every post site gains once :data:`HIDE_POSTS` is on (Track 3): the posts of that site saved through any door
#: other than its own lists (a link pasted, the notch, a browser's bookmarks, an agent, a chat), which sit on none of its
#: streams. ``ANOTHER_WAY`` is the stream's name inside its id (``x.another-way``), ``ANOTHER_LABEL`` what the person reads.
ANOTHER_WAY = "another-way"
ANOTHER_LABEL = "Saved another way"
#: ``media.kind`` values a page declares for itself: never a post whatever its link says (``media_kinds.kind_of``).
DECLARED_WORKS = frozenset({"book", "paper", "repository", "file", "list"})

#: Episode keys. ``named``: the person's own words named the save — ``{why, at}``, stamped by the mention reader
#: (Track M) and never popped by a re-stage, unlike ``read_asked``. ``kept_as_page``: the person pressed "Keep as a page"
#: (Track K) — ``{at}``. Both are read here whether or not the writer exists yet.
NAMED_KEY = "named"
KEPT_KEY = "kept_as_page"
#: "This save carries the person's own words", from the one definition (``history_index.PERSON_KEYS``) minus a folder's
#: reason: that is the person's words about the list, so it reads as theirs to Sleep and the activity clock and as no
#: earn to the graph.
EARNED_KEYS = tuple(k for k in history_index.PERSON_KEYS if k != history_index.FOLDER_READ_KEY)

#: Page frontmatter that says the person edited it (``page_edits``).
_EDITED_KEYS = ("human_edited", "corrections")
#: Edge labels only Cicada's own readers write: never a link the person made.
MACHINE_LABELS = frozenset({"about", "describes", "mentions", "related to", "member of"})

#: The signs a post can hold, in the order a report lists them.
SIGNS = ("note", "why", "named", "kept", "edited", "conversation", "claim", "project", "source", "edge")

_LI_ARTICLE = "urn:li:article"
_BOOKMARK_SUFFIX = "-bookmark"


# --- the rule ---------------------------------------------------------------------------------------------------


@lru_cache(maxsize=32768)
def post_site(url: str) -> str | None:
    """The site (one of :data:`POST_SITES`) whose post this link is, else ``None``: a profile, a search, a LinkedIn
    article, another site. Of the link alone, never an alias or an origin."""
    for key in POST_SITES:
        if saved_lists.canonical(key, url) is not None:
            if key == "linkedin" and _LI_ARTICLE in url.lower():
                return None
            return key
    return None


def is_another_way(stream_id: str) -> bool:
    """Is this stream id a post site's "Saved another way" (``x.another-way``)? What the list pages and the rows ask."""
    return str(stream_id or "").endswith("." + ANOTHER_WAY)


def is_post_site(key: str) -> bool:
    """Is ``key`` (a source group's id: ``x``, ``instagram``…) a site whose lists hold posts? What ``list_pages`` asks."""
    return key in POST_SITES


def _media(fm: dict) -> dict:
    media = fm.get("media")
    return media if isinstance(media, dict) else {}


def is_browser_bookmark(fm: dict | None) -> bool:
    origin = str((fm or {}).get("origin") or "").strip().lower()
    return origin.endswith(_BOOKMARK_SUFFIX) or origin == "safari-tab"


def is_post(fm: dict | None) -> bool:
    """Is this page a saved post (drawn as a row until it earns a page), by its own record alone? ``type: media`` that
    declares no kind of its own, whose saved link is a post of one of :data:`POST_SITES` (not a LinkedIn article, not a
    video the video rail knows) and that is not a feed item. Pure, no I/O, the same for every door."""
    if not isinstance(fm, dict) or str(fm.get("type") or "").strip().lower() != "media":
        return False
    media = _media(fm)
    if not media or str(media.get("kind") or "").strip().lower() in DECLARED_WORKS:
        return False
    url = str(media.get("url") or "").strip()
    if not url or episode_time.is_feed_item(fm):
        return False
    bookmarked = is_browser_bookmark(fm)
    if bookmarked and BOOKMARKED_LINKS == "pages":
        return False
    if video_urls.resolve(url) is not None:
        return False
    if bookmarked and BOOKMARKED_LINKS == "rows":
        return True
    return post_site(url) is not None


def site_of(fm: dict | None) -> str | None:
    """The :data:`POST_SITES` key of a post page, else ``None`` (a link under ``rows`` that is no site's post too)."""
    return post_site(str(_media(fm or {}).get("url") or "").strip()) if isinstance(fm, dict) else None


# --- what earns a page -----------------------------------------------------------------------------------------

_OLD_SHAPE: dict[tuple, bool] = {}
_OLD_SHAPE_LOCK = threading.Lock()
_OLD_SHAPE_MAX = 200_000


def _old_shape(entry) -> bool:
    """Is this episode a connector post written the old way (``connector_text.old_shape``): the post's own text under
    the person's note? Reads the body, so only for a connector origin that carries ``has_note``, once per file stamp."""
    from api.services import connector_text, saved_reading

    fm = entry.frontmatter
    if str(fm.get("origin") or "") not in saved_reading.CONNECTOR_TEXT_ORIGINS or not fm.get("has_note"):
        return False
    if any(fm.get(k) for k in connector_text._THEIRS_KEYS):
        return False
    key = (str(entry.path), entry.mtime_ns, entry.size)
    with _OLD_SHAPE_LOCK:
        if key in _OLD_SHAPE:
            return _OLD_SHAPE[key]
    try:
        found = connector_text.old_shape(fm, entry.body())
    except Exception:  # noqa: BLE001 - an unreadable episode reads as no old shape: never hides a note
        found = False
    with _OLD_SHAPE_LOCK:
        if len(_OLD_SHAPE) >= _OLD_SHAPE_MAX:
            _OLD_SHAPE.clear()
        _OLD_SHAPE[key] = found
    return found


def episode_signs(entry) -> set[str]:
    """What one of a post's own saves (an episode carrying the page's link: the save, a repeat save's note, an agent's
    read) says about its page: ``note``, ``why``, ``named``, ``kept``. An agent's note (an episode with a session) and an
    old-shape connector text are not the person's words; a why-answer is theirs whoever saved it."""
    fm = entry.frontmatter
    out: set[str] = set()
    if fm.get("has_note") and not str(fm.get("session_id") or "").strip() and not _old_shape(entry):
        out.add("note")
    if fm.get("saved_why") or fm.get("saved_why_earlier"):
        out.add("why")
    if fm.get(NAMED_KEY) or fm.get(history_index.WOKEN_KEY):
        out.add("named")
    if fm.get(KEPT_KEY):
        out.add("kept")
    return out


def _tied(fm: dict) -> set[str]:
    """Pages a project lists by the person's own tie (or a trusted agent's on their ask), never a proposal."""
    from api.services import project_ownership

    out = set()
    for row in project_ownership.page_entries(fm, project_ownership.PAGES_ADDED_KEY):
        if isinstance(row, dict) and row.get("proposed"):
            continue
        page = row if isinstance(row, str) else row.get("entity")
        if isinstance(page, str) and page.strip():
            out.add(page.strip())
    return out


def _taken_sources(fm: dict) -> set[str]:
    """Pages a source link the person took points at (a proposal is no link until they take it, ruling 36 D5)."""
    from api.services import fact_sources

    out = set()
    raw = fm.get("sources")
    for src in raw if isinstance(raw, list) else []:
        if isinstance(src, dict) and not fact_sources.is_proposed(src):
            target = str(src.get("entity") or "").strip()
            if target:
                out.add(target)
    return out


def _fold(name) -> str:
    return " ".join(str(name or "").split()).casefold()


# --- the digest: what the verdict reads of each file, kept apart from the files --------------------------------------
#
# The verdict is a pure function of a few facts per file. Reading them out of ~19,000 headers costs seconds in a fresh
# process (3.7 s measured on a real memory, against 0.25 s for the ETag without the flip), and it is asked before any
# graph is built, on every request that carries an ETag. So each file's facts are kept as a small record keyed by the
# file's own ``(mtime_ns, size)``: warm, one listing of each folder decides nothing changed; cold, the records a previous
# process stored (``derived_store``, outside every bank) answer for every file that has not moved, and only a moved file
# is read. The records are made by the same functions the readers use (``is_post``, ``episode_signs``,
# ``quiet_pages``), and :func:`_resolve` is the only place a sign is decided, from records alone, so a warm answer, a
# cold answer and an answer from a stored record cannot differ.
#
# Records (JSON-able, ``0`` for a file nothing here reads):
#   a page   ``{"p": 1, "s": site, "o": origin, "e": 1 edited, "w": 1 owner, "x": [its own episodes],
#               "c": [person cited 0|1, [episodes its claims cite]], "t": [pages it ties], "u": [pages a source names]}``
#   an episode  ``[kind C|I|K, the page it names or None, its signs, the folders it is filed in]`` (the last only when
#               it is filed in one); ``0`` for a conversation naming no page and filed nowhere.

#: Bump when the shape of a stored record changes in a way no source edit shows. Everything else a record depends on is in
#: :func:`_tag` already: the release, and the source of this module and of every module a record is made with.
RECORD_VERSION = 1
#: A stored digest is rewritten at most this often once one exists, or at once after this many files changed.
PERSIST_EVERY_S = 30.0
PERSIST_AT_ONCE = 200
#: ``False``: this process neither reads nor writes a stored digest (the dry run, which changes nothing outside the bank
#: either, and a test of the cold path).
STORE_DIGEST = True
_STORE = "saved_posts"
_BAD = "!"          # a file that does not parse: no page, no episode
_KIND = {"C": quiet_pages.CONVERSATION, "I": quiet_pages.IMPORT, "K": quiet_pages.CHECK}
_KIND_CODE = {v: k for k, v in _KIND.items()}


#: The modules a record is made with besides this one: the page and save kinds, the folders a save is filed in, the claim
#: and evidence reading, the video and list rules, the feed test, the project and source ties, the connector's old shape,
#: the sign keys, and the readers of a file's header. A change to any of them makes a stored record untrustworthy.
RECORD_MODULES = ("saved_posts", "quiet_pages", "save_folders", "promotion", "video_urls", "saved_lists", "episode_time",
                  "project_ownership", "fact_sources", "connector_text", "saved_reading", "history_index", "claims",
                  "bank_index", "markdown_parser")


def _source_files() -> list[Path]:
    """The source file of each module in :data:`RECORD_MODULES`, found without importing it (a frozen build with no
    ``.py`` on disk has none: the release then stands alone in the tag)."""
    from importlib import util

    out: list[Path] = []
    for name in RECORD_MODULES:
        try:
            spec = util.find_spec(f"api.services.{name}")
        except (ImportError, ValueError):
            continue
        if spec is not None and spec.origin and spec.origin.endswith(".py"):
            out.append(Path(spec.origin))
    return out


@lru_cache(maxsize=1)
def _source_stamp() -> str:
    """A short hash of the source of every module a record is made with. A new release, a branch switch or an edit of any of
    them changes it, so a record made by older code is made again once; nothing has to remember to bump a number. A file
    that cannot be read stamps its name only."""
    digest = hashlib.sha1()
    for path in _source_files():
        digest.update(path.name.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"?")
    return digest.hexdigest()[:12]


def _tag() -> str:
    """What every stored record depends on besides the files: the record version, the bookmark knob (``is_post``), the
    release and the source of every module a record is made with (:data:`RECORD_MODULES`)."""
    return f"{RECORD_VERSION}:{BOOKMARKED_LINKS}:{__version__}:{_source_stamp()}"


def _claim_facts(entry):
    """What a page's claims say for the verdict: ``[1, []]`` when one of them cites the person's own words, else
    ``[0, the conversations it cites]`` (never a claim of someone else's: ``external:``), or None. Reads the page's body."""
    from api.services.claims import parse_claims

    try:
        parsed = parse_claims(entry.body())
    except Exception:  # noqa: BLE001 - an unreadable page has no claim signs
        return None
    cited: list[str] = []
    for claim in parsed or []:
        if promotion.claim_cites_person(claim, located=False):
            return [1, []]
        if str(getattr(claim, "observer", "") or "").startswith("external:"):
            continue
        for ev in getattr(claim, "evidence", None) or []:
            cited.extend(quiet_pages.episode_ids([getattr(ev, "episode", "")]))
    cited = list(dict.fromkeys(cited))
    return [0, cited] if cited else None


def _entity_record(entry):
    fm = entry.frontmatter
    if not isinstance(fm, dict):
        return 0
    rec: dict = {}
    if tied := sorted(_tied(fm)):
        rec["t"] = tied
    if taken := sorted(_taken_sources(fm)):
        rec["u"] = taken
    if is_post(fm):
        rec["p"] = 1
        rec["s"] = site_of(fm)
        rec["o"] = str(fm.get("origin") or "")
        if fm.get("human_edited") is True or fm.get("corrections"):
            rec["e"] = 1
        if fm.get("owner") is True:
            rec["w"] = 1
        rec["x"] = list(dict.fromkeys(quiet_pages.episode_ids(
            fm.get("source_episodes") if isinstance(fm.get("source_episodes"), list) else [])))
        if facts := _claim_facts(entry):
            rec["c"] = facts
    return rec or 0


def _episode_record(entry):
    from api.services import save_folders

    fm = entry.frontmatter
    if not isinstance(fm, dict):
        return _BAD
    kind = _KIND_CODE.get(quiet_pages.episode_kind(fm), "C")
    raw = fm.get(quiet_pages.SAVE_KEY)
    # The folders a save is filed in (a folder's own list is made of them, ``source_streams.episodes``): never a deleted save's.
    filed = [] if fm.get("source_deleted_at") else [[origin, name] for origin, name in save_folders.folders_of(fm)]
    if not raw and kind == "C" and not filed:
        return 0
    record = [kind, str(raw).strip() if raw else None, ",".join(sorted(episode_signs(entry))) if raw else ""]
    if filed:
        record.append(filed)
    return record


@dataclass(frozen=True)
class _Digest:
    """One bank's records, never mutated: a change makes a new one. ``ent`` / ``epi``: ``{file name: (mtime_ns, size,
    record)}``; ``*_stamps``: the listing they match (compared with a fresh listing in one step); ``*_rel``: the rows
    whose record is not ``0``."""
    gen: int
    ent: dict
    epi: dict
    ent_stamps: dict
    epi_stamps: dict
    ent_rel: dict
    epi_rel: dict


_GENS = itertools.count(1)


def _digest_of(ent: dict, epi: dict, prior: _Digest | None = None) -> _Digest:
    """A digest of these rows; a folder that is the prior digest's own (nothing in it moved) keeps its derived maps."""
    same_ent = prior is not None and ent is prior.ent
    same_epi = prior is not None and epi is prior.epi
    return _Digest(
        gen=next(_GENS), ent=ent, epi=epi,
        ent_stamps=prior.ent_stamps if same_ent else {n: (r[0], r[1]) for n, r in ent.items()},
        epi_stamps=prior.epi_stamps if same_epi else {n: (r[0], r[1]) for n, r in epi.items()},
        ent_rel=prior.ent_rel if same_ent else {n: r for n, r in ent.items() if r[2] != 0},
        epi_rel=prior.epi_rel if same_epi else {n: r for n, r in epi.items() if r[2] != 0})


_DIGESTS: dict[str, _Digest] = {}
#: ``{bank: (entities listing, episodes listing, the digest found to match them)}``: the same listings again need no comparison.
_SEEN: dict[str, tuple] = {}
_SLOT_LOCKS: dict[str, threading.Lock] = {}
_PERSISTED: dict[str, dict] = {}


def _slot_lock(slot: str) -> threading.Lock:
    with _OLD_SHAPE_LOCK:
        return _SLOT_LOCKS.setdefault(slot, threading.Lock())


def _fold_folder(memory_path: Path, subdir: str, held: dict, now: dict, make) -> tuple[dict, int]:
    """``({name: (mtime_ns, size, record)}, how many files were read)`` for the listing ``now``: a file that has not moved
    keeps its record; one that has is read (``bank_index.file``: that one file's header, never the folder's)."""
    out: dict = {}
    todo: list[str] = []
    for name, stamp in now.items():
        row = held.get(name)
        if row is not None and row[0] == stamp[0] and row[1] == stamp[1]:
            out[name] = row
        else:
            todo.append(name)
    # Most of a folder to read (nothing stored yet): its batch reader, which one caller at a time parses (``bank_index.files``).
    bulk = {e.path.name: e for e in bank_index.files(memory_path, subdir)} if len(todo) * 4 > len(now) else None
    for name in todo:
        entry = bulk.get(name) if bulk is not None else bank_index.file(memory_path, subdir, name)
        if entry is None:
            out[name] = (now[name][0], now[name][1], _BAD)
            continue
        try:
            record = make(entry)
        except Exception as exc:  # noqa: BLE001 - one unreadable file is no record, never an error for the bank
            logger.debug(f"saved posts: {subdir}/{name} read as no record ({type(exc).__name__})")
            record = _BAD
        out[name] = (entry.mtime_ns, entry.size, record)
    return out, len(todo)


def _load_digest(memory_path: Path) -> _Digest | None:
    if not STORE_DIGEST:
        return None
    data = derived_store.load(memory_path, _STORE, _tag())
    if not isinstance(data, dict):
        return None
    try:
        ent = {n: (r[0], r[1], r[2]) for n, r in data["ent"].items()}
        epi = {n: (r[0], r[1], r[2]) for n, r in data["epi"].items()}
        edges = data.get("edges")
        if isinstance(edges, list) and len(edges) == 3:
            _EDGE_ROWS.setdefault(str(memory_path), ((edges[0], edges[1]), edges[2]))
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    return _digest_of(ent, epi)


def _write_digest(memory_path: Path, home: Path | None = None) -> None:
    slot = str(memory_path)
    with _OLD_SHAPE_LOCK:
        digest = _DIGESTS.get(slot)
        edges = _EDGE_ROWS.get(slot)
    if digest is None:
        return
    data = {"ent": {n: list(r) for n, r in digest.ent.items()}, "epi": {n: list(r) for n, r in digest.epi.items()}}
    if edges is not None:
        data["edges"] = [edges[0][0], edges[0][1], edges[1]]
    derived_store.save(memory_path, _STORE, _tag(), data, home)


def _persist_later(memory_path: Path, changed: int) -> None:
    """Store the digest, in the background, when it is due: the first time, after a large change, or every
    :data:`PERSIST_EVERY_S` while it keeps changing. Never on the request's time, never an error."""
    if not STORE_DIGEST or not HIDE_POSTS:    # dark, nothing is stored: a call that asks the verdict anyway leaves no file
        return
    slot = str(memory_path)
    home = derived_store.home_or_none()
    with _OLD_SHAPE_LOCK:
        held = _PERSISTED.setdefault(slot, {"at": None, "dirty": 0, "busy": False})
        held["dirty"] += changed
        now = time.monotonic()
        due = held["at"] is None or held["dirty"] >= PERSIST_AT_ONCE or now - held["at"] >= PERSIST_EVERY_S
        if not due or held["busy"] or not held["dirty"]:
            return
        held.update(busy=True, dirty=0, at=now)

    def run() -> None:
        try:
            _write_digest(memory_path, home)
        finally:
            with _OLD_SHAPE_LOCK:
                held["busy"] = False

    threading.Thread(target=run, name="saved-posts-digest", daemon=True).start()


def persist_now(memory_path: Path) -> None:
    """Store the digest this process holds, now (tests, a clean exit). Waits for a store already under way."""
    slot = str(Path(memory_path))
    while True:
        with _OLD_SHAPE_LOCK:
            if not _PERSISTED.get(slot, {}).get("busy"):
                break
        time.sleep(0.005)
    _write_digest(Path(memory_path))


def forget(memory_path: Path, *, stored: bool = True) -> None:
    """Drop what this process holds for the bank and, with ``stored``, what it stored (tests; a deleted bank)."""
    slot = str(Path(memory_path))
    with _OLD_SHAPE_LOCK:
        for table in (_DIGESTS, _SEEN, _STATES, _EDGE_ROWS, _EDGES, _VERDICT, _PERSISTED):
            table.pop(slot, None)
    if stored:
        derived_store.forget(Path(memory_path), _STORE)


def _digest(memory_path: Path) -> _Digest:
    """The bank's records, current: from this process when one is held, else from the stored digest, else made from the
    files; a file that moved since is read again, nothing else is."""
    memory_path = Path(memory_path)
    slot = str(memory_path)
    ent_now = bank_index.listing(memory_path, "entities")
    epi_now = bank_index.listing(memory_path, "episodes")
    with _OLD_SHAPE_LOCK:
        cur = _DIGESTS.get(slot)
        seen = _SEEN.get(slot)
    if cur is not None and seen is not None and seen[0] is ent_now and seen[1] is epi_now and seen[2] is cur:
        return cur          # the very listings this digest was last found to match (a block's, the SSE tick's)
    if cur is not None and cur.ent_stamps == ent_now and cur.epi_stamps == epi_now:
        with _OLD_SHAPE_LOCK:
            _SEEN[slot] = (ent_now, epi_now, cur)
        return cur
    with _slot_lock(slot):
        with _OLD_SHAPE_LOCK:
            cur = _DIGESTS.get(slot)
        loaded = False
        if cur is None:
            cur = _load_digest(memory_path)
            loaded = cur is not None
        if cur is not None and cur.ent_stamps == ent_now and cur.epi_stamps == epi_now:
            with _OLD_SHAPE_LOCK:
                if loaded:
                    _DIGESTS[slot] = cur
                _SEEN[slot] = (ent_now, epi_now, cur)
            return cur
        if cur is not None and cur.ent_stamps == ent_now:
            ent, n_ent = cur.ent, 0                      # no page moved: its rows are this digest's own
        else:
            ent, n_ent = _fold_folder(memory_path, "entities", cur.ent if cur else {}, ent_now, _entity_record)
        if cur is not None and cur.epi_stamps == epi_now:
            epi, n_epi = cur.epi, 0
        else:
            epi, n_epi = _fold_folder(memory_path, "episodes", cur.epi if cur else {}, epi_now, _episode_record)
        new = _digest_of(ent, epi, cur)
        with _OLD_SHAPE_LOCK:
            _DIGESTS[slot] = new
            _SEEN[slot] = (ent_now, epi_now, new)
        _persist_later(memory_path, n_ent + n_epi)
        return new


@dataclass(frozen=True)
class State:
    """What the entity and episode records say, kept until either folder's files change."""

    token: int
    #: every page the rule calls a post, by id
    posts: frozenset
    #: ``{post id: signs}`` from the page, its episodes and its claims, and from links the person made in other pages'
    #: frontmatter (a project's list, a taken source)
    signs: dict = field(default_factory=dict)
    #: ``{post id: site}`` and ``{post id: origin}`` for the report
    sites: dict = field(default_factory=dict)
    origins: dict = field(default_factory=dict)
    #: moves when a save is filed in or out of a folder (a folder's list is made of the saves filed in it); "" for none
    filed: str = ""
    memory_path: Path | None = field(default=None, repr=False, compare=False)

    @property
    def names(self) -> dict:
        """``{folded name: ids}`` for every page (a wikilink resolves by name), read only by the Related filter, from the
        pages' own headers, so a request that asks only for the stamp never reads one."""
        if self.memory_path is None:
            return {}
        return bank_index.derived(self.memory_path, "entities", "saved_posts.names", _names_of)


def _names_of(entities) -> dict:
    out: dict[str, set[str]] = {}
    for e in entities:
        name = _fold(e.frontmatter.get("name") or e.stem.replace("-", " ").title()) if isinstance(e.frontmatter, dict) \
            else ""
        if name:
            out.setdefault(name, set()).add(e.stem)
    return {n: frozenset(ids) for n, ids in out.items()}


_TOKENS = itertools.count(1)
_STATES: dict[str, tuple[int, State]] = {}


def _resolve(memory_path: Path, digest: _Digest) -> State:
    """Every sign, decided from records alone."""
    epi = digest.epi

    def kind_of(episode_id: str):
        row = epi.get(f"{episode_id}.md") if episode_id else None
        if row is None or row[2] == _BAD:
            return None
        return _KIND["C"] if row[2] == 0 else _KIND[row[2][0]]

    saves: dict[str, list[str]] = {}
    for name, row in digest.epi_rel.items():
        record = row[2]
        if isinstance(record, list) and record[1]:
            saves.setdefault(record[1], []).append(name[:-3])
    posts = {name[:-3]: row[2] for name, row in digest.ent_rel.items() if isinstance(row[2], dict) and row[2].get("p")}
    signs: dict[str, set[str]] = {}
    for pid, rec in posts.items():
        out: set[str] = set()
        if rec.get("e"):
            out.add("edited")
        owned = rec.get("x") or []
        for stem in [*owned, *(s for s in saves.get(pid, []) if s not in owned)]:
            row = epi.get(f"{stem}.md")
            record = row[2] if row is not None else None
            if isinstance(record, list) and record[1] is not None and record[2]:
                out.update(record[2].split(","))
        lit = {"media": {}, "source_episodes": owned}
        if rec.get("w"):
            lit["owner"] = True
        if quiet_pages.lit_by_episodes(lit, kind_of):
            out.add("conversation")
        elif (facts := rec.get("c")) and (facts[0] or any(kind_of(e) == quiet_pages.CONVERSATION for e in facts[1])):
            out.add("claim")
        signs[pid] = out
    for row in digest.ent_rel.values():
        rec = row[2]
        if isinstance(rec, dict):
            for target in rec.get("t", ()):
                if target in posts:
                    signs[target].add("project")
            for target in rec.get("u", ()):
                if target in posts:
                    signs[target].add("source")
    filed = sorted((name[:-3], repr(row[2][3])) for name, row in digest.epi_rel.items()
                   if isinstance(row[2], list) and len(row[2]) > 3)
    return State(
        token=next(_TOKENS), posts=frozenset(posts), signs={pid: frozenset(s) for pid, s in signs.items()},
        filed=hashlib.sha1("\x1f".join(f"{a}\x1e{b}" for a, b in filed).encode()).hexdigest()[:12] if filed else "",
        sites={pid: rec.get("s") for pid, rec in posts.items()}, origins={pid: rec.get("o") or "" for pid, rec in posts.items()},
        memory_path=memory_path)


def state(memory_path: Path) -> State:
    """The state for this bank, incremental over the records: a capture reads the one file it wrote, and the answer moves
    only when a post, a sign or a name did."""
    memory_path = Path(memory_path)
    digest = _digest(memory_path)
    slot = str(memory_path)
    with _OLD_SHAPE_LOCK:
        hit = _STATES.get(slot)
    if hit is not None and hit[0] == digest.gen:
        return hit[1]
    out = _resolve(memory_path, digest)
    with _OLD_SHAPE_LOCK:
        _STATES[slot] = (digest.gen, out)
    return out


# The signs graph_edges.yaml adds: an edge a claim of the person's backs. Memoised on the file's stamp and the state.
_EDGES: dict[str, tuple[tuple, dict]] = {}
#: ``{bank: ((mtime_ns, size), [[source, target, claim id], ...])}``: the edges worth a look (a claim backs them, and no
#: machine label), read out of the file once per stamp and stored with the digest, so a fresh process never parses the file.
_EDGE_ROWS: dict[str, tuple[tuple, list]] = {}


def _edge_rows(memory_path: Path, stat) -> list:
    from api.services.markdown_parser import load_yaml_file

    slot = str(memory_path)
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _OLD_SHAPE_LOCK:
        hit = _EDGE_ROWS.get(slot)
    if hit is not None and tuple(hit[0]) == stamp:
        return hit[1]
    rows: list = []
    try:
        listed = (load_yaml_file(memory_path / "graph_edges.yaml") or {}).get("edges", []) or []
    except Exception:  # noqa: BLE001 - an unreadable edge file earns nothing
        listed = []
    for row in listed:
        if not isinstance(row, dict) or not row.get("claim_id"):
            continue
        source, target = str(row.get("source") or ""), str(row.get("target") or "")
        if source == target or str(row.get("label") or "").strip().lower() in MACHINE_LABELS:
            continue
        rows.append([source, target, row["claim_id"]])
    with _OLD_SHAPE_LOCK:
        _EDGE_ROWS[slot] = (stamp, rows)
    _persist_later(memory_path, 1)
    return rows


def _edge_signs(memory_path: Path, st: State) -> tuple[tuple, dict[str, frozenset]]:
    """``(stamp, {post id: {"edge"}})``: a post one end of an edge that is not a machine label's, that a claim cites the
    person's words for (the claim sits on the edge's source page; ``claim_id`` ties them)."""
    from api.services.claims import parse_claims

    edges = Path(memory_path) / "graph_edges.yaml"
    try:
        stat = edges.stat()
        stamp = (st.token, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return (st.token, 0, 0), {}
    slot = str(memory_path)
    with _OLD_SHAPE_LOCK:
        hit = _EDGES.get(slot)
    if hit is not None and hit[0] == stamp:
        return stamp, hit[1]
    out: dict[str, frozenset] = {}
    claims_of: dict[str, list] = {}
    for source, target, claim_id in _edge_rows(Path(memory_path), stat):
        ends = [x for x in dict.fromkeys((source, target)) if x in st.posts]
        if not ends:
            continue
        if source not in claims_of:
            entry = bank_index.file(Path(memory_path), "entities", f"{source}.md")
            try:
                claims_of[source] = parse_claims(entry.body()) if entry is not None else []
            except Exception:  # noqa: BLE001
                claims_of[source] = []
        for claim in claims_of[source]:
            if getattr(claim, "id", None) == claim_id and promotion.claim_cites_person(claim, located=False):
                for end in ends:
                    out[end] = frozenset({"edge"})
                break
    with _OLD_SHAPE_LOCK:
        _EDGES[slot] = (stamp, out)
    return stamp, out


@dataclass(frozen=True)
class Verdict:
    state: State
    #: every post's signs, edges included
    signs: dict
    #: posts that hold no sign: drawn as a row when :data:`HIDE_POSTS`
    rows: frozenset
    #: posts that hold one: an ordinary page
    earned: frozenset
    #: moves only when ``earned`` does
    stamp: str


_VERDICT: dict[str, tuple[tuple, Verdict]] = {}


def verdict(memory_path: Path) -> Verdict:
    """The rule over a bank, whatever :data:`HIDE_POSTS` says (the dry run and the tests read this; every reader goes
    through :func:`hidden_ids`)."""
    st = state(memory_path)
    edge_stamp, edge = _edge_signs(memory_path, st)
    slot = str(Path(memory_path))
    with _OLD_SHAPE_LOCK:
        hit = _VERDICT.get(slot)
    if hit is not None and hit[0] == edge_stamp:
        return hit[1]
    signs = {pid: frozenset(s | edge.get(pid, frozenset())) for pid, s in st.signs.items()}
    earned = frozenset(pid for pid, s in signs.items() if s)
    out = Verdict(state=st, signs=signs, rows=st.posts - earned, earned=earned,
                  stamp=hashlib.sha1("\x1f".join(sorted(earned)).encode()).hexdigest()[:12])
    with _OLD_SHAPE_LOCK:
        _VERDICT[slot] = (edge_stamp, out)
    return out


# --- what every reader asks ---------------------------------------------------------------------------------------

_NONE: frozenset = frozenset()


def hidden_ids(memory_path: Path) -> frozenset:
    """The pages drawn as a row, not as a page: posts with no sign. Empty while :data:`HIDE_POSTS` is off, so every
    reader behaves as before."""
    if not HIDE_POSTS:
        return _NONE
    return verdict(memory_path).rows


def earned_ids(memory_path: Path) -> frozenset:
    """Posts that earned their page: drawn like any page, never dimmed, asked about like any page. Empty while
    :data:`HIDE_POSTS` is off."""
    if not HIDE_POSTS:
        return _NONE
    return verdict(memory_path).earned


def is_hidden(memory_path: Path, entity_id: str) -> bool:
    return entity_id in hidden_ids(memory_path)


def stamp(memory_path: Path) -> str:
    """A token that moves only when the set of earned posts does (a reason stamped on an episode moves neither the pages
    folder's fingerprint nor the graph's cache key, so this is what carries it). Empty while :data:`HIDE_POSTS` is off,
    so the keys and ETags that fold it in are unchanged."""
    if not HIDE_POSTS:
        return ""
    return verdict(memory_path).stamp


def lists_stamp(memory_path: Path) -> str:
    """A token that moves when a save is filed in or out of a folder: a folder's list page (``list_pages``) is made of the
    saves filed in it, which only the saves' own records say, so neither the pages folder nor :func:`stamp` moves with it.
    Empty while :data:`HIDE_POSTS` is off, and for a bank whose saves are filed in no folder."""
    if not HIDE_POSTS:
        return ""
    return state(memory_path).filed


def drawn_as_page(memory_path: Path, entity_id: str, fm: dict | None) -> bool:
    """Is this page drawn as a page (not a row)? Everything that is no post; a post that earned one."""
    return not (is_post(fm) and entity_id in hidden_ids(memory_path))


# --- a page's Related lines ---------------------------------------------------------------------------------------

_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_HEADING = re.compile(r"^## .*$")


def _hidden_name(v: Verdict, name: str) -> bool:
    ids = v.state.names.get(_fold(name))
    return bool(ids) and ids <= v.rows


def _filter_line(v: Verdict, line: str) -> str | None:
    links = list(_LINK.finditer(line))
    gone = [m for m in links if _hidden_name(v, m.group(1))]
    if not gone:
        return line
    if len(gone) == len(links):
        return None
    out = line
    for m in reversed(gone):
        out = out[:m.start()] + out[m.end():]
    out = re.sub(r"(latest)\s*,\s*", r"\1 ", out)
    out = re.sub(r",\s*,", ",", out)
    out = re.sub(r",\s+(and\b)", r" \1", out)
    out = re.sub(r",\s*$", "", out)
    return out


def _filter(v: Verdict, text: str) -> tuple[str, int]:
    """``(text, how many lines were dropped or changed)``: the ``## Related`` entries naming only posts drawn as rows
    gone; a line that names several pages keeps the others; a section left empty goes."""
    out: list[str] = []
    inside = False
    kept, heading_at, changed = 0, -1, 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped == "## Related":
            inside, kept, heading_at = True, 0, len(out)
            out.append(line)
            continue
        if inside and (_HEADING.match(stripped) or stripped.startswith("```")):
            if kept == 0 and heading_at >= 0:
                changed += 1
                del out[heading_at:]
            inside = False
        if inside and stripped:
            filtered = _filter_line(v, line)
            if filtered is None:
                changed += 1
                continue
            if filtered != line:
                changed += 1
            kept += 1
            out.append(filtered)
            continue
        out.append(line)
    if inside and kept == 0 and heading_at >= 0:
        changed += 1
        del out[heading_at:]
    return "\n".join(out), changed


def filter_related(memory_path: Path, text: str) -> str:
    """``text`` (a page's prose) without the ``## Related`` entries that name only posts drawn as a row, so no link on a
    page opens nothing. Read time only: nothing is rewritten, and a post that earns its page shows again at once."""
    if not HIDE_POSTS or "## Related" not in (text or ""):
        return text
    v = verdict(memory_path)
    return _filter(v, text)[0] if v.rows else text


def related_changed(memory_path: Path, text: str) -> int:
    """How many lines of ``text`` the filter would drop or change, whatever :data:`HIDE_POSTS` says (the dry run)."""
    if "## Related" not in (text or ""):
        return 0
    return _filter(verdict(memory_path), text)[1]
