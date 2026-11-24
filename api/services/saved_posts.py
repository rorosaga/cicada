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
"""
from __future__ import annotations

import hashlib
import itertools
import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from api.services import bank_index, episode_time, history_index, promotion, quiet_pages, saved_lists, video_urls

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


_CLAIMS: dict[tuple, bool] = {}


def _lit_by_claims(entry, kind_of) -> bool:
    """Does a claim on the page cite the person's words or a conversation? Reads the page's body, so once per file stamp:
    a capture moves the folders' generations, and a post's body is no different for it."""
    from api.services.claims import parse_claims

    key = (str(entry.path), entry.mtime_ns, entry.size)
    with _OLD_SHAPE_LOCK:
        if key in _CLAIMS:
            return _CLAIMS[key]
    try:
        found = quiet_pages.lit_by_claims(parse_claims(entry.body()), kind_of)
    except Exception:  # noqa: BLE001 - an unreadable page has no claim signs
        found = False
    with _OLD_SHAPE_LOCK:
        if len(_CLAIMS) >= _OLD_SHAPE_MAX:
            _CLAIMS.clear()
        _CLAIMS[key] = found
    return found


def _saves_by_page(episodes) -> dict[str, list]:
    """``{page id: its save episodes}`` by the ``media_entity_id`` each carries. A note given on a link that is already
    saved is written as a new episode (``media_ingestor.write_note_episode``) that names its page but is listed in the
    page's ``source_episodes`` only when a later Sleep touches the page, so the page's own list alone misses it."""
    out: dict[str, list] = {}
    for episode in episodes:
        fm = episode.frontmatter
        page = str(fm.get(quiet_pages.SAVE_KEY) or "").strip() if isinstance(fm, dict) else ""
        if page:
            out.setdefault(page, []).append(episode)
    return out


def _page_signs(entry, episodes: dict, kind_of, saves: dict | None = None) -> set[str]:
    """The signs from a post's own frontmatter, its own episodes and its own claims. Its own episodes are the ones its
    ``source_episodes`` lists and the ones that name it (``saves``, by ``media_entity_id``)."""
    fm = entry.frontmatter
    out: set[str] = set()
    if fm.get("human_edited") is True or fm.get("corrections"):
        out.add("edited")
    owned = list(dict.fromkeys(quiet_pages.episode_ids(fm.get("source_episodes")
                                                       if isinstance(fm.get("source_episodes"), list) else [])))
    mine = [episodes.get(episode_id) for episode_id in owned]
    mine += [e for e in (saves or {}).get(entry.stem, []) if e.stem not in owned]
    for found in mine:
        if found is not None and found.frontmatter.get(quiet_pages.SAVE_KEY):
            out |= episode_signs(found)
    if quiet_pages.lit_by_episodes(fm, kind_of):
        out.add("conversation")
    elif _lit_by_claims(entry, kind_of):
        out.add("claim")
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


@dataclass(frozen=True)
class State:
    """What the entity and episode headers say, kept until either folder's cached headers change."""

    token: int
    #: every page the rule calls a post, by id
    posts: frozenset
    #: ``{post id: signs}`` from the page, its episodes and its claims, and from links the person made in other pages'
    #: frontmatter (a project's list, a taken source)
    signs: dict = field(default_factory=dict)
    #: ``{folded name: ids}`` for every page that shares a name with a post (a wikilink resolves by name)
    names: dict = field(default_factory=dict)
    #: ``{post id: site}`` and ``{post id: origin}`` for the report
    sites: dict = field(default_factory=dict)
    origins: dict = field(default_factory=dict)


_TOKENS = itertools.count(1)


def _build(entities, episodes) -> State:
    by_episode = {e.stem: e for e in episodes}
    kind_of = lambda eid: quiet_pages.episode_kind(  # noqa: E731
        by_episode[eid].frontmatter if eid in by_episode else None) if eid else None
    posts = {e.stem: e for e in entities if is_post(e.frontmatter)}
    saves = _saves_by_page(episodes)
    signs: dict[str, set[str]] = {pid: _page_signs(entry, by_episode, kind_of, saves) for pid, entry in posts.items()}
    for e in entities:
        fm = e.frontmatter
        if not isinstance(fm, dict):
            continue
        for target in _tied(fm) & posts.keys():
            signs[target].add("project")
        for target in _taken_sources(fm) & posts.keys():
            signs[target].add("source")
    wanted = {_fold(entry.frontmatter.get("name") or pid.replace("-", " ").title()) for pid, entry in posts.items()}
    names: dict[str, set[str]] = {}
    for e in entities:
        name = _fold(e.frontmatter.get("name") or e.stem.replace("-", " ").title()) if isinstance(e.frontmatter, dict) \
            else ""
        if name in wanted:
            names.setdefault(name, set()).add(e.stem)
    return State(
        token=next(_TOKENS), posts=frozenset(posts),
        signs={pid: frozenset(s) for pid, s in signs.items()},
        names={n: frozenset(ids) for n, ids in names.items()},
        sites={pid: site_of(entry.frontmatter) for pid, entry in posts.items()},
        origins={pid: str(entry.frontmatter.get("origin") or "") for pid, entry in posts.items()},
    )


def state(memory_path: Path) -> State:
    """The state for this bank, incremental over the cached headers (``bank_index.derived_over``): a capture re-runs one
    pass over cached frontmatter, and the answer moves only when a post, a sign or a name did."""
    return bank_index.derived_over(Path(memory_path), ("entities", "episodes"), "saved_posts.state", _build)


# The signs graph_edges.yaml adds: an edge a claim of the person's backs. Memoised on the file's stamp and the state.
_EDGES: dict[str, tuple[tuple, dict]] = {}


def _edge_signs(memory_path: Path, st: State) -> tuple[tuple, dict[str, frozenset]]:
    """``(stamp, {post id: {"edge"}})``: a post one end of an edge that is not a machine label's, that a claim cites the
    person's words for (the claim sits on the edge's source page; ``claim_id`` ties them)."""
    from api.services.claims import parse_claims
    from api.services.markdown_parser import load_yaml_file

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
    try:
        rows = (load_yaml_file(edges) or {}).get("edges", []) or []
    except Exception:  # noqa: BLE001 - an unreadable edge file earns nothing
        rows = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("claim_id"):
            continue
        source, target = str(row.get("source") or ""), str(row.get("target") or "")
        if source == target or str(row.get("label") or "").strip().lower() in MACHINE_LABELS:
            continue
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
            if getattr(claim, "id", None) == row["claim_id"] and promotion.claim_cites_person(claim, located=False):
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
