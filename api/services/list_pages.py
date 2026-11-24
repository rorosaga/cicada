"""One small page for each list of saved posts, and for each folder on a site that has them (G246, ruling 81, owner
2026-11-24: "maybe a small entity page that has all the saved posts would be good, no? i want to somehow see saved things
somewhere even if i haven't referred to them yet").

**This module is the one writer of these pages** (the way ``media_pages`` is the one writer of a recording's and
``github_repos`` of a repository's): a list of posts (a site's bookmarks, likes, reposts, saved posts) and each folder,
collection or board on a site that has them is a ``media`` page with ``media.kind: list``, born here by file and git work
alone — no model, nothing at capture time — when the list's **first item arrives and not before**. Stage 1 never produces
``media``; these pages are never projects (ruling 56).

**What the page holds, and what it does not.** It holds what the list *is*: its name, one fixed sentence (the list's kind
and its site, never a model's words), the site's mark, the day it was born, and the list's address (``list:``: its site,
its stream, its folder). It holds nothing that can go stale: **the count, the newest day, the rows, when the list was last
read and a folder's reason are read from the saves every time the page is served** (:func:`block`), newest first, as the
same rows the Sources page uses (``channel_items.items``), so the page cannot be out of date and no read of a list commits
a file. The page is written once, again only if the list's name changes (a name the person gave it stands), and when its
source is removed.

**A list page is not a saved item.** It has ``origin: list`` (never a list's own origin, or it would be a row of its own
list), an id that does not start with ``media-`` (``inject_media_edges``, ``link_enrichment`` and ``link_recon`` glob
``media-*.md``), no link, no ``tags`` and no ``member of`` edge — a list is never a hub (2026-10-19). It is never quiet and
never decays (a ``media`` page is evergreen), never merged (``entity_merge`` refuses), never a project, never asked about
(``inbox_service``), never given facts by Sleep (``entity_resolver`` treats it as a file page, whose name is no one's name),
and no member of any stream or hub. A browser's own bookmark folders get none, and neither do lists of works (a playlist, a
Substack list): those are a property of what they hold.

**Which lists.** Every stream of X, Instagram, LinkedIn, Reddit, Pinterest and TikTok that counts by membership
(``source_streams``), plus one page per folder those sites file saves into (``save_folders``). A list or folder with
nothing in it is not drawn and not counted (derived on read), so a renamed folder leaves no orphan node; a page the person
archived or dropped keeps its key and is never made again; turning a list off keeps its page; **removing a source retires
its pages undoably** (:func:`retire_source`: status ``archived`` in one commit, git keeps the rest).

**Ships dark.** While ``saved_posts.HIDE_POSTS`` is ``False`` this module **writes nothing**: no list page file is born, so
there is nothing for any reader of the pages folder — the status count, the search index, a hub, the graph — to show, and
nothing a person sees changes. The first sync after the flip makes every list's page at once. (The graph, Clusters and
find draw nothing of a list page that is not in :func:`state`, which is empty while dark.)

**Rails.** The writer runs only on the home (a replica refuses), never into a demo bank, inside ``write_admission`` and the
page lock, one commit per batch under ``cicada``, and a bank Sleep holds is tried again (``media_pages.RETRY_S``). The page
holds no per-Mac number (when the list was last read lives outside every bank), and every name comes from the tables
(``saved_lists.PLATFORMS``), never from a person: two computers over one bank make the same pages.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from loguru import logger

from api.services import (bank_index, decay_policy, demo_guard, git_service, markdown_parser, page_lock, replica_guard,
                          saved_posts, write_admission)
from api.services.id_utils import sanitize_id

KIND = "list"
#: The page's own origin: never a list's (``source_streams._build_members`` would count the page a member of its own list).
PAGE_ORIGIN = "list"
PREFIX = "list-"
TRIGGER_SYNC = "sync/list_pages"
TRIGGER_USER = "user/list_pages"
#: Pages written under one admission and one commit.
BATCH = 100
SETTLE_S = 3.0          # a burst of reads folds into one run
RETRY_S = 60.0          # Sleep held the pages: try again
SLUG_MAX = 40
#: How many of a list's newest rows ride in its block (the app draws its own five from the items route).
RECENT = 5
#: What a page of a list that left the table says it was retired for (``retired_by``).
RETIRED_SOURCE = "source-removed"

#: How a list's own name reads in "Posts you <verb> on <site>." Anything not here reads "Posts in your <label> on <site>."
_VERBS = {"bookmarks": "bookmarked", "likes": "liked", "liked posts": "liked", "reposts": "reposted", "saved": "saved",
          "saved posts": "saved", "upvoted": "upvoted", "favorites": "favorited", "pins": "pinned"}


# --------------------------------------------------------------------------- reading a page


def is_list(fm: dict | None) -> bool:
    """Is this page a list's own page (``media.kind: list``)? Pure: the one test every reader asks."""
    fm = fm or {}
    media = fm.get("media")
    return str(fm.get("type") or "").strip().lower() == "media" and isinstance(media, dict) \
        and str(media.get("kind") or "").strip().lower() == KIND


def list_of(fm: dict | None) -> dict | None:
    """The page's ``list:`` block (``{site, stream, folder, source, label}``), or None for any other page."""
    raw = (fm or {}).get("list") if is_list(fm) else None
    if not isinstance(raw, dict) or not str(raw.get("stream") or "").strip():
        return None
    folder = " ".join(str(raw.get("folder") or "").split())
    return {"site": str(raw.get("site") or ""), "stream": str(raw["stream"]).strip(), "folder": folder or None,
            "source": str(raw.get("source") or ""), "label": str(raw.get("label") or "")}


def _cf(text) -> str:
    return " ".join(str(text or "").split()).casefold()


# --------------------------------------------------------------------------- the lists there can be


@dataclass(frozen=True)
class Want:
    """One list a page may stand for."""
    id: str                  # the page's id
    site: str                # the source group (``x``)
    site_name: str           # "X"
    stream: str              # ``x.bookmarks``
    channel: str             # the items route's channel
    key: str                 # the saved-lists table key (``x``, ``x-likes``): where "last read" lives, per Mac
    origin: str              # the stream's own origin (the app's mark table has it: ``x-bookmarks``)
    label: str               # "Bookmarks"
    folder: str | None       # the folder's name as the site shows it, or None for the whole list
    folded: str              # the folder, folded, or ""
    name: str
    sentence: str


def _noun(label: str) -> str:
    folded = _cf(label)
    return "saved posts" if folded in ("saved", "saved posts") else folded or "list"


def sentence(site_name: str, label: str, folder: str | None = None) -> str:
    """The one fixed line a page says about itself — the list's kind and its site, no model's words."""
    if folder:
        return f"Posts in “{folder}”, a folder of your {_noun(label)} on {site_name}."
    verb = _VERBS.get(_cf(label))
    return f"Posts you {verb} on {site_name}." if verb else f"Posts in your {_noun(label)} on {site_name}."


def page_id(stream: str, folded_folder: str = "") -> str:
    """``list-<stream with dots as dashes>[--<folder slug>-<hash>]``: a pure function of the list, so two computers over one
    bank agree. A folder always carries a short hash of its folded name, so two folders that slug alike never share an id."""
    base = PREFIX + sanitize_id(stream.replace(".", "-"))
    if not folded_folder:
        return base
    slug = sanitize_id(folded_folder)[:SLUG_MAX].strip("-")
    digest = hashlib.sha1(folded_folder.encode("utf-8")).hexdigest()[:6]
    return f"{base}--{slug}-{digest}" if slug else f"{base}--{digest}"


def _name(site_name: str, label: str, folder: str | None) -> str:
    return f"{site_name}: {label}, {folder}" if folder else f"{site_name}: {label}"


def post_specs() -> list[tuple]:
    """``[(group, spec)]``: the streams of a site whose lists hold posts and count by membership."""
    from api.services import source_streams

    out = []
    for group in source_streams.groups():
        if not saved_posts.is_post_site(group.id):
            continue
        out.extend((group, spec) for spec in group.specs if spec.counts == "members" and spec.family == "saved")
    return out


def _want(group, spec, folder: str | None, folded: str) -> Want:
    from api.services import saved_lists

    site_name = group.label
    label = spec.label
    key = spec.key if spec.key in saved_lists.PLATFORMS else group.id
    return Want(id=page_id(spec.id, folded), site=group.id, site_name=site_name, stream=spec.id,
                channel=spec.channel or group.id, key=key, origin=spec.origin or "", label=label, folder=folder,
                folded=folded, name=_name(site_name, label, folder), sentence=sentence(site_name, label, folder))


def wanted(memory_path: Path) -> list[Want]:
    """Every list that could have a page right now and holds something: each post stream with a member, and each folder a
    save is filed in under a stream that files into folders. The count is the one the card shows (:func:`_read`)."""
    from api.services import source_streams

    memory_path = Path(memory_path)
    mem = source_streams.members(memory_path)
    eps = source_streams.episodes(memory_path)
    out: list[Want] = []
    for group, spec in post_specs():
        whole = _want(group, spec, None, "")
        if mem.members.get(spec.id):
            out.append(whole)
        if spec.folders != "save_folders" or not spec.origin:
            continue
        for (origin, folded), (name, saves) in sorted(eps.folder_names.items()):
            if origin == spec.origin and saves > 0 and folded:
                out.append(_want(group, spec, name, folded))
    return out


# --------------------------------------------------------------------------- what a list holds, read now


def _read(memory_path: Path, stream: str, folder: str | None, *, limit: int) -> dict | None:
    """The items route's own answer for one list (``{all, latest, items}``), so a page's count is the number its cards say."""
    from api.services import channel_items, source_streams

    spec = source_streams.spec_of(stream)
    if spec is None or not spec.channel:
        return None
    try:
        return channel_items.items(Path(memory_path), spec.channel, limit=limit, stream=stream, folder=folder)
    except channel_items.UnknownStream:
        return None


def _row(item: dict) -> dict:
    out = {"title": str(item.get("title") or "")}
    for key, src in (("author", "author"), ("posted", "posted"), ("saved", "day"), ("host", "host")):
        if item.get(src):
            out[key] = str(item[src])
    return out


def _why(memory_path: Path, origin: str, folder: str | None) -> dict | None:
    """The person's own reason for a whole folder (``save_folders``), read now: it belongs here and nowhere else."""
    if not folder or not origin:
        return None
    from api.services import save_folders

    record = save_folders.reason_for(memory_path, origin, folder)
    text = str((record or {}).get("text") or "").strip()
    return {"text": text, "at": str(record.get("at") or "")[:10] or None} if text else None


def _last_read(memory_path: Path, key: str) -> str | None:
    """When this Mac's list was last read, from outside the bank (per Mac): never stored on the page."""
    from api.services import saved_lists, source_streams

    try:
        return source_streams._z(saved_lists.last(Path(memory_path), key).get("read_at"))
    except Exception:  # noqa: BLE001 - a missing record is no read
        return None


def block(memory_path: Path, entity_id: str, fm: dict | None) -> dict | None:
    """The page's ``list`` block (``page_blocks``): what the list is, how many it holds, the newest day and the
    :data:`RECENT` newest rows, read from the saves now. None for any other page. Never raises."""
    info = list_of(fm)
    if info is None:
        return None
    memory_path = Path(memory_path)
    try:
        read = _read(memory_path, info["stream"], info["folder"], limit=RECENT) or {}
        spec = next((s for g, s in post_specs() if s.id == info["stream"]), None)
        key = (spec.key if spec is not None else None) or info["site"]
        return {
            "site": info["site"], "stream": info["stream"], "folder": info["folder"],
            "channel": spec.channel if spec is not None and spec.channel else info["site"],
            "label": info["label"], "source": info["source"],
            "count": int(read.get("all") or 0), "newest": read.get("latest"),
            "lastReadAt": _last_read(memory_path, key),
            "why": _why(memory_path, info["source"], info["folder"]),
            "recent": [_row(item) for item in (read.get("items") or [])[:RECENT]],
        }
    except Exception as exc:  # noqa: BLE001 - a derived block never fails a page read
        logger.debug(f"list pages: block skipped ({type(exc).__name__})")
        return None


# --------------------------------------------------------------------------- which pages are drawn


@dataclass(frozen=True)
class Drawn:
    stream: str
    folder: str | None
    count: int
    newest: str | None


@dataclass(frozen=True)
class State:
    """What the pages say about the lists that are on screen: the live list pages with their counts, and which folders each
    page's saves are filed in (for the read-time edges)."""
    drawn: dict = field(default_factory=dict)       # page id -> Drawn
    folders_of: dict = field(default_factory=dict)  # page id -> ((origin, folded folder), ...)
    stamp: str = ""


_EMPTY = State()


def _live(fm: dict) -> bool:
    return str(fm.get("status") or "active").strip().lower() not in ("archived", "dropped")


def _build(memory_path: Path, entities, episodes) -> State:
    from api.services import quiet_pages, save_folders

    drawn: dict[str, Drawn] = {}
    for entry in entities:
        fm = entry.frontmatter or {}
        info = list_of(fm)
        if info is None or not _live(fm):
            continue
        read = _read(memory_path, info["stream"], info["folder"], limit=1)
        count = int((read or {}).get("all") or 0)
        if count > 0:
            drawn[entry.stem] = Drawn(info["stream"], info["folder"], count, (read or {}).get("latest"))
    filed: dict[str, list] = {}
    for entry in episodes:
        fm = entry.frontmatter or {}
        page = str(fm.get(quiet_pages.SAVE_KEY) or "").strip()
        if not page or fm.get("source_deleted_at"):
            continue
        for origin, name in save_folders.folders_of(fm):
            pair = (origin, _cf(name))
            if pair not in filed.setdefault(page, []):
                filed[page].append(pair)
    stamp = hashlib.sha1("\x1f".join(f"{pid}:{d.count}:{d.newest}" for pid, d in sorted(drawn.items())).encode()
                         ).hexdigest()[:12] if drawn else ""
    return State(drawn=drawn, folders_of={p: tuple(v) for p, v in filed.items()}, stamp=stamp)


def state(memory_path: Path) -> State:
    """The lists that are drawn, kept until the pages' or the saves' cached headers change. Empty while
    ``saved_posts.HIDE_POSTS`` is off, so every reader behaves as before."""
    if not saved_posts.HIDE_POSTS:
        return _EMPTY
    memory_path = Path(memory_path)
    return bank_index.derived_over(memory_path, ("entities", "episodes"), "list_pages.state",
                                   lambda entities, episodes: _build(memory_path, entities, episodes))


def stamp(memory_path: Path) -> str:
    """Moves when a list is drawn or gone, or its count or newest day moves (a graph's cache key and a node's hash fold
    it in); empty while dark."""
    return state(memory_path).stamp


def drawn_ids(memory_path: Path) -> frozenset:
    return frozenset(state(memory_path).drawn)


def read_time_edges(memory_path: Path, entity_ids, earned) -> list[tuple[str, str, str]]:
    """``[(source, target, label)]`` for the graph, computed on read and never stored: each earned post that is a member of
    a drawn list is joined to that list's page, and each drawn folder's page to its list's page. Only between pages that
    are nodes (``entity_ids``). A list with no earned post has none, on purpose: a fake edge would be worse than none."""
    from api.services import source_streams

    st = state(memory_path)
    if not st.drawn:
        return []
    memory_path = Path(memory_path)
    out: list[tuple[str, str, str]] = []
    for pid, d in st.drawn.items():
        if d.folder and pid in entity_ids:
            whole = page_id(d.stream)
            if whole in st.drawn and whole in entity_ids:
                out.append((pid, whole, "part of"))
    streams_of = source_streams.members(memory_path).streams_of
    origin_of = {s.id: s.origin for _g, s in post_specs()}
    for post in sorted(set(earned) & set(entity_ids)):
        held = streams_of.get(post, ())
        for stream in held:
            whole = page_id(stream)
            if whole in st.drawn and whole in entity_ids:
                out.append((post, whole, "saved in"))
            for origin, folded in st.folders_of.get(post, ()):
                if origin and origin == origin_of.get(stream):
                    folder_page = page_id(stream, folded)
                    if folder_page in st.drawn and folder_page in entity_ids:
                        out.append((post, folder_page, "saved in"))
    return out


# --------------------------------------------------------------------------- the page


def _frontmatter(w: Want, today: str) -> dict:
    return {
        "name": w.name, "type": "media", "status": "active", "confidence": 0.8,
        "created": today, "last_referenced": today,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for("media", source="media")),
        "source_episodes": [], "aliases": [], "tags": [], "related": [], "version": 1, "origin": PAGE_ORIGIN,
        # Described by the list's own table, never a fetched page.
        "enrichment_attempted": True,
        "media": {"kind": KIND, "media_type": KIND},
        "list": _list_block(w),
    }


def _list_block(w: Want) -> dict:
    return {"site": w.site, "stream": w.stream, "folder": w.folder, "source": w.origin, "label": w.label,
            "named": w.name, "said": w.sentence}


def _body(w: Want) -> str:
    return w.sentence + "\n"


def _pages(memory_path: Path) -> dict[str, dict]:
    """Every list page, in any status, by id."""
    return {e.stem: e.frontmatter or {} for e in bank_index.files(memory_path, "entities")
            if is_list(e.frontmatter)}


# --------------------------------------------------------------------------- committing


def _commit(memory_path: Path, rows: list[tuple[str, str]], *, trigger: str, author: str) -> None:
    paths = [p for p, _ in rows]
    message = git_service.build_commit_message(
        f"Lists of saved posts {datetime.now(timezone.utc).date().isoformat()}",
        [f"{p}: {action} (source: n/a, trigger: {trigger})" for p, action in rows], authors=[author])
    git_service.commit_paths_sync(memory_path, message, paths)


# --------------------------------------------------------------------------- the sync


def _refused(memory_path: Path) -> bool:
    return not saved_posts.HIDE_POSTS or demo_guard.is_demo(memory_path) or replica_guard.blocks()


def sync(memory_path: Path) -> dict:
    """Make the page of every list that holds something and has none, bring a page's name up to its list's, and retire the
    pages of a list whose source is gone. Idempotent: a second run writes and commits nothing. Raises
    :class:`write_admission.SleepHolding` when Sleep holds the pages — the caller tries again, nothing is lost. A demo
    bank, a replica and (until the flip) every bank do nothing. ``{"created", "updated", "retired", "pending"}``."""
    memory_path = Path(memory_path)
    out = {"created": 0, "updated": 0, "retired": 0, "pending": 0}
    if _refused(memory_path):
        return out
    pages = _pages(memory_path)
    todo = wanted(memory_path)
    lists = {w.id: w for w in todo}
    have = set(pages)
    make = []
    for w in todo:
        if w.id in have:
            continue                                # exists in any status: its key is held
        count = (_read(memory_path, w.stream, w.folder, limit=1) or {}).get("all") or 0
        if count > 0:
            make.append(w)
    gone = _gone_streams(pages)
    changed = [pid for pid, fm in pages.items() if _live(fm) and pid in lists and _rename_due(fm, lists[pid])]
    retire = [pid for pid, fm in pages.items() if _live(fm) and (list_of(fm) or {}).get("stream") in gone]
    work = [("make", w) for w in make] + [("update", pid) for pid in changed] + [("retire", pid) for pid in retire]
    today = date.today().isoformat()
    for start in range(0, len(work), BATCH):
        chunk = work[start:start + BATCH]
        try:
            with write_admission.admitted(memory_path), page_lock.page_lock(memory_path):
                rows = _write_chunk(memory_path, chunk, lists, today, out)
                if rows:
                    _commit(memory_path, rows, trigger=TRIGGER_SYNC, author=git_service.CICADA_AUTHOR)
                bank_index.invalidate(memory_path)
        except write_admission.SleepHolding:
            out["pending"] = len(work) - start
            raise
    return out


def _gone_streams(pages: dict[str, dict]) -> set[str]:
    """The streams a page names that no longer exist in the table: their source was removed."""
    known = {spec.id for _g, spec in post_specs()}
    if not known:
        return set()           # a table that could not be read retires nothing
    return {info["stream"] for fm in pages.values() if (info := list_of(fm)) and info["stream"] not in known}


def _rename_due(fm: dict, w: Want) -> bool:
    """Has the list's own name changed since the page was written, and has the person left the page's name alone?"""
    info = fm.get("list") if isinstance(fm.get("list"), dict) else {}
    written = str(info.get("named") or "")
    return bool(written) and written != w.name and str(fm.get("name") or "") == written


def _write_chunk(memory_path: Path, chunk, lists: dict[str, Want], today: str, out: dict) -> list[tuple[str, str]]:
    entities = memory_path / "entities"
    rows: list[tuple[str, str]] = []
    for action, item in chunk:
        if action == "make":
            w: Want = item
            path = entities / f"{w.id}.md"
            if path.exists():
                continue                            # the id names another page: never overwritten
            try:
                markdown_parser.write_new(path, _frontmatter(w, today), _body(w))
            except FileExistsError:
                continue
            rows.append((f"entities/{w.id}.md", "created"))
            out["created"] += 1
            continue
        path = entities / f"{item}.md"
        if not path.is_file():
            continue
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter
        if not is_list(fm) or not _live(fm):
            continue
        if action == "update":
            w = lists[item]
            fm["name"] = w.name
            held = fm.get("list") if isinstance(fm.get("list"), dict) else {}
            # The words stay the person's when they edited them: only the sentence this writer wrote is replaced.
            body = _body(w) if parsed.body.strip() == str(held.get("said") or "").strip() else parsed.body
            fm["list"] = {**held, **_list_block(w)}
            markdown_parser.write(path, fm, body)
            rows.append((f"entities/{item}.md", "updated"))
            out["updated"] += 1
        else:
            _archive(path, fm, parsed.body)
            rows.append((f"entities/{item}.md", "archived"))
            out["retired"] += 1
    return rows


def _archive(path: Path, fm: dict, body: str) -> None:
    fm["status"] = "archived"
    fm["retired_by"] = RETIRED_SOURCE
    markdown_parser.write(path, fm, body)


def retire_source(memory_path: Path, site: str, *, by: str = git_service.USER_AUTHOR) -> int:
    """The person removed a source: archive each of its list pages in one commit under ``by`` (undoable: the page and its
    history stay, a revert brings it back, and ``sync`` never makes it again or wakes it). Raises
    :class:`write_admission.SleepHolding` while Sleep holds the pages. Returns how many pages were retired."""
    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path) or replica_guard.blocks():
        return 0
    rows: list[tuple[str, str]] = []
    with write_admission.admitted(memory_path), page_lock.page_lock(memory_path):
        for pid, fm in _pages(memory_path).items():
            info = list_of(fm)
            if info is None or info["site"] != site or not _live(fm):
                continue
            path = memory_path / "entities" / f"{pid}.md"
            parsed = markdown_parser.parse(path)
            _archive(path, parsed.frontmatter, parsed.body)
            rows.append((f"entities/{pid}.md", "archived"))
        if rows:
            _commit(memory_path, rows, trigger=TRIGGER_USER if by == git_service.USER_AUTHOR else TRIGGER_SYNC, author=by)
        bank_index.invalidate(memory_path)
    return len(rows)


# --------------------------------------------------------------------------- the background run


class _Runner:
    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.timer: threading.Timer | None = None
        self.again = False


_RUNNERS: dict[str, _Runner] = {}
_GUARD = threading.Lock()


def start_sync(memory_path, *, delay_s: float = 0.0) -> bool:
    """Make the pages in the background: one run per bank at a time (a trigger during a run runs once more after it), a
    short ``delay_s`` folding a burst into one run, and a bank Sleep holds tried again later. Never raises. A demo bank, a
    replica and a bank before the flip do nothing."""
    try:
        memory_path = Path(memory_path)
        if _refused(memory_path):
            return False
        key = str(memory_path.resolve())
        with _GUARD:
            runner = _RUNNERS.setdefault(key, _Runner())
            if runner.thread is not None and runner.thread.is_alive():
                runner.again = True
                return False
            if delay_s > 0:
                if runner.timer is not None and runner.timer.is_alive():
                    return False
                runner.timer = threading.Timer(delay_s, start_sync, args=(memory_path,))
                runner.timer.daemon = True
                runner.timer.start()
                return True
            runner.thread = threading.Thread(target=_run, args=(memory_path, runner), name="cicada-list-pages",
                                             daemon=True)
            runner.thread.start()
        return True
    except Exception as exc:  # noqa: BLE001 - a page is never a reason for a request to fail
        logger.debug(f"list pages: not started ({type(exc).__name__})")
        return False


def _run(memory_path: Path, runner: _Runner) -> None:
    while True:
        runner.again = False
        try:
            out = sync(memory_path)
            if out["created"] or out["updated"] or out["retired"]:
                logger.info(f"list pages: {out['created']} made, {out['updated']} updated, {out['retired']} retired")
        except write_admission.SleepHolding:
            _retry(memory_path)
            return
        except Exception as exc:  # noqa: BLE001 - the next trigger tries again
            logger.debug(f"list pages: skipped ({type(exc).__name__})")
            return
        if not runner.again:
            return


def _retry(memory_path: Path) -> None:
    with _GUARD:
        runner = _RUNNERS.setdefault(str(memory_path.resolve()), _Runner())
        if runner.timer is not None and runner.timer.is_alive():
            return
        runner.timer = threading.Timer(RETRY_S, start_sync, args=(memory_path,))
        runner.timer.daemon = True
        runner.timer.start()


__all__ = ["KIND", "PAGE_ORIGIN", "is_list", "list_of", "wanted", "block", "state", "stamp", "drawn_ids",
           "read_time_edges", "sync", "start_sync", "retire_source", "page_id", "sentence"]
