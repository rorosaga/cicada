"""One standard for "this part of this source" (ROR-16, G118).

The owner: *"entities and projects can point at the exact part of a source and show it highlighted. If there's nothing
to highlight, that's fine, but provenance should prioritize it."*

A claim stores coordinates (``claims.Evidence``); whether those coordinates may be drawn is decided when they are read,
against the source as it is now. :class:`Source` is that one decision, and :class:`~api.models.schemas.SourceSpan` is the
one shape it answers in, wherever a span travels: the Reader's focus (``/episodes/{id}/text``), a conversation's noted
rows (``/citations``), a popover's quote (``ProvenanceSpan``) and "every span pointing into this source, grouped by
page" (``/episodes/{id}/spans``, :func:`for_source`).

**A span's status**, and only a ``current``, ``grown`` or ``derived`` one carries an ``at``:

* ``current`` / ``grown``: the offsets hold (``evidence.span_status``);
* ``derived``: a name match found at read, never written and never a quote;
* ``stale``: the source changed under the span, so there is nothing true to highlight;
* ``held``: the words are what ``sensitive_text`` is sure is a secret (G235), so neither they nor their neighbourhood
  are drawn as evidence. The person can still open the source, and read it as stored: that is what the review opens;
* ``unlocated``: an inference, or Cicada's own gap line. The citation still opens the source, with nothing to apologise
  for.

**``at`` leaves room for other media without building it.** ``{"type": "text", "start", "end"}`` is the only type today:
code points into the document ``/text`` serves. A recording's ``{"type": "time", ...}`` or a PDF's ``{"type": "pdf",
"page": ...}`` is a new ``type`` here; a client that does not know one draws no highlight and still opens the source.

Rails held here: engine-free; never fuzzy (nothing here locates a quote, it judges stored offsets); no value is kept, the
held cache holds offsets and never words; a locked note's kept file is unreachable, because every document comes from
``evidence.source_document``, which reads its record as no document at all. Not on a remote door: this is the app's read
(``/episodes/{id}/spans`` is not on the G135 listener), so the ``sources`` scope has nothing new to gate.

**The index** (:func:`pages_citing`): which pages name which source, kept per page file and its ledger's stamp. The first
read of a bank reads every page's raw text once, off the loop (no YAML, no claim parsed); after that a changed page is
re-read alone. A page's coordinates are parsed the first time a read needs them and kept until its stamp moves, so a
read costs the spans of that one source.
"""
from __future__ import annotations

import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from api.models.schemas import SourceSpan, SourceSpanGroup, SourceSpans, SpanAt
from api.services import authorship, bank_index, evidence, markdown_parser
from api.services.claims import Claim, is_current, is_event, is_record, parse_claims, current_day

CURRENT, GROWN, STALE, DERIVED, HELD, UNLOCATED = "current", "grown", "stale", "derived", "held", "unlocated"
#: Rides each route's ETag ``extra``: what these fields mean moved.
SHAPE = "spans1"

#: What a source is, for the words a citation opens it with and for the layout that draws it.
CONVERSATION, NOTE, MEETING, BOOK, SAVE, PAGE, WEB, VIDEO, ITEM = (
    "conversation", "note", "meeting", "book", "save", "page", "web", "video", "item")
_NOTE_ORIGINS = frozenset({"apple-notes", "folder"})
_ITEM_ORIGINS = frozenset({"rss", "calendar", "calendar-local"})
_PAGE_READ = "page-read"   # `page_read.SOURCE`


def kind_of(doc_id: str, fm: dict | None) -> str:
    """What this source is, from its id and its own record: never a guess from its words."""
    from api.services import books, video_state, web_settle

    if not evidence.is_episode_id(doc_id):
        return PAGE
    fm = fm or {}
    origin = str(fm.get("origin") or fm.get("source") or "")
    source = str(fm.get("source") or "")
    if fm.get("meeting"):
        return MEETING
    if fm.get(books.EPISODE_KEY):
        return BOOK
    if source == web_settle.SOURCE:
        return WEB
    if source == video_state.WATCH_SOURCE:
        return VIDEO
    if source == _PAGE_READ:
        return PAGE
    if origin in _ITEM_ORIGINS:
        return ITEM
    if authorship.is_saved(fm):
        return SAVE
    if origin in _NOTE_ORIGINS or authorship.agent_saved(fm):
        return NOTE
    return CONVERSATION


# ---- what may not be drawn (G235) -------------------------------------------------------------------------------------

_HELD_CAP = 256
_held_lock = threading.Lock()
#: (document, body hash, what the person left) -> the confident hits' offsets. Offsets only, never a value (ruling 60).
_HELD: OrderedDict[tuple, tuple[tuple[int, int], ...]] = OrderedDict()


def forget() -> None:
    """Every held offset and the citing index go (a bank switch, a test)."""
    with _held_lock:
        _HELD.clear()
    with _index_lock:
        _INDEX.clear()


def held_ranges(doc_id: str, fm: dict | None, text: str, *, override: str | None = None, gaps: tuple = ()) -> tuple:
    """The offsets in an episode the detector is sure hold a secret and the person has not left. A page's stored text is
    a page's, not a conversation: only an episode is read. A failure of the detector holds nothing back from the person's
    own view of their own source, and never stops a citation opening."""
    from api.services import sensitive_flags, sensitive_text

    if not evidence.is_episode_id(doc_id) or not text:
        return ()
    fm = fm or {}
    sensitive = fm.get("sensitive") if isinstance(fm.get("sensitive"), dict) else {}
    key = (doc_id, evidence.body_hash(text), str(sensitive.get("kept") or ""))
    with _held_lock:
        if key in _HELD:
            _HELD.move_to_end(key)
            return _HELD[key]
    try:
        harness = bool(fm.get("harness") or fm.get("capture_kind") == "transcript")
        hits = sensitive_text.find(text, harness=harness, override=override, gaps=gaps)
        ranges = tuple((h.start, h.end) for h in sensitive_flags.not_left(fm, hits) if h.sure)
    except Exception:  # noqa: BLE001 - a detector failure never stops a citation opening
        ranges = ()
    with _held_lock:
        _HELD[key] = ranges
        while len(_HELD) > _HELD_CAP:
            _HELD.popitem(last=False)
    return ranges


def overlaps_held(start: int, end: int, held: tuple) -> bool:
    return any(s < end and e > start for s, e in held)


# ---- one source, one judge --------------------------------------------------------------------------------------------

@dataclass
class Source:
    """A document as it is now, and the one judgement of a span against it."""
    id: str
    fm: dict
    text: str
    is_episode: bool
    override: str | None
    gaps: tuple
    held: tuple

    @classmethod
    def of(cls, doc_id: str, fm: dict | None, text: str) -> "Source":
        is_episode = evidence.is_episode_id(doc_id)
        fm = fm or {}
        override = authorship.of(fm) if is_episode else None
        gaps = evidence.gap_ranges(fm, text) if is_episode else ()
        return cls(doc_id, fm, text, is_episode, override, gaps,
                   held_ranges(doc_id, fm, text, override=override, gaps=gaps))

    @classmethod
    def open(cls, memory_path: Path | None, doc_id: str) -> "Source | None":
        doc = evidence.source_document(memory_path, doc_id)
        return None if doc is None else cls.of(doc_id, doc[0], doc[1])

    def status(self, start: int, end: int, hash: str | None) -> str:  # noqa: A002 - the field's own name
        """The one decision (order matters): a gap line is nobody's words; a span past the text or under a changed hash
        says so; then the secret check, so a stale span never asks about words it no longer points at."""
        if start < 0 or end <= start:
            return UNLOCATED
        if end > len(self.text):
            return STALE
        if evidence.touches_gap(start, end, self.gaps):
            return UNLOCATED
        stored = evidence.span_status(self.text, end=end, hash=hash, appendable=self.is_episode)
        if stored == evidence.SPAN_STALE:
            return STALE
        if overlaps_held(start, end, self.held):
            return HELD
        return GROWN if stored == evidence.SPAN_GROWN else CURRENT

    def span(self, start: int, end: int, hash: str | None, kind: str, *,  # noqa: A002
             claim_id: str | None = None, current: bool = True) -> SourceSpan:
        """The wire shape of a stored span. Only what may be drawn carries an ``at``."""
        status = self.status(start, end, hash)
        return SourceSpan(source=self.id, status=status, kind=kind, hash=hash or "", claim_id=claim_id, current=current,
                          at=SpanAt(start=start, end=end) if status in (CURRENT, GROWN) else None)

    def derived(self, start: int, end: int) -> SourceSpan:
        """A name match found at read (R-PB9). A secret is not a name, but the same door holds it."""
        status = HELD if overlaps_held(start, end, self.held) else DERIVED
        return SourceSpan(source=self.id, status=status, kind="derived",
                          at=SpanAt(start=start, end=end) if status == DERIVED else None)

    def nothing(self, kind: str = "reasoning", *, claim_id: str | None = None, current: bool = True) -> SourceSpan:
        """A citation with nothing to locate: it opens the source."""
        return SourceSpan(source=self.id, status=UNLOCATED, kind=kind, claim_id=claim_id, current=current)


# ---- which pages cite which source ------------------------------------------------------------------------------------

#: A document a page names: an evidence entry's, or any episode or media id in its text (`source_episodes`, in the fence
#: or the frontmatter). A false positive costs one parse; a miss would lose a citation.
_DOC_RE = re.compile(r'"episode":\s*"([^"]+)"|\b(ep_\d{4}-\d{2}-\d{2}_\d+|media-[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*)')


@dataclass(frozen=True)
class Row:
    """A claim's stored coordinates into one source: what the index keeps, with no words."""
    claim_id: str
    start: int
    end: int
    hash: str
    kind: str
    current: bool


@dataclass
class _Page:
    stamp: tuple
    docs: frozenset
    #: Parsed on the first read that needs this page's claims, then kept until its stamp moves.
    rows: dict[str, tuple[Row, ...]] | None = None
    name: str = ""
    type: str = ""


@dataclass
class _Bank:
    key: tuple = ()
    pages: dict | None = None
    citing: dict | None = None


_index_lock = threading.Lock()
_INDEX: dict[str, _Bank] = {}


def _current(claim: Claim) -> bool:
    return not bool(claim.superseded_by) if is_event(claim) else is_current(claim)


def _read_page(path: Path, stamp: tuple) -> _Page | None:
    """Which sources this page names, from its raw text and ledger: no YAML and no claim parsed, so a first read of the
    whole bank costs the file reads the old per-call scan paid on every call."""
    try:
        raw = path.read_text(encoding="utf-8")
        ledger = path.with_suffix(".claims.jsonl")
        if ledger.exists():
            raw += ledger.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None   # one unreadable page is left out, as the citations route always has
    return _Page(stamp, frozenset(a or b for a, b in _DOC_RE.findall(raw)))


def _parse_rows(page: _Page, path: Path) -> None:
    """A page's coordinates, by source. An unreadable page cites nothing."""
    rows: dict[str, list[Row]] = {}
    name, kind = path.stem, ""
    try:
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter or {}
        name, kind = str(fm.get("name") or path.stem), str(fm.get("type") or "")
        for claim in parse_claims(parsed.body):
            if is_record(claim):
                continue
            for ev in claim.evidence:
                if ev.episode and ev.is_span():
                    rows.setdefault(ev.episode, []).append(
                        Row(claim.id, ev.start, ev.end, ev.hash, ev.kind, _current(claim)))
    except Exception:  # noqa: BLE001
        rows = {}
    page.name, page.type = name, kind
    page.rows = {d: tuple(r) for d, r in rows.items()}


def _bank(memory_path: Path) -> _Bank:
    """The bank's index, brought up to date: a page is re-read only when it, its ledger or the day moved."""
    directory = Path(memory_path) / "entities"
    day = current_day()
    key = (bank_index.dir_fingerprint(directory), bank_index.ledger_fingerprint(directory), day)
    with _index_lock:
        bank = _INDEX.setdefault(str(memory_path), _Bank())
        if bank.key == key and bank.citing is not None:
            return bank
        old = bank.pages or {}
        fresh: dict[str, _Page] = {}
        for name in sorted(n for n in bank_index.stamps(memory_path, "entities") if n.endswith(".md")):
            path = directory / name
            try:
                st = path.stat()
                ledger = path.with_suffix(".claims.jsonl")
                led = ledger.stat() if ledger.exists() else None
            except OSError:
                continue
            stamp = (st.st_mtime_ns, st.st_size, led.st_mtime_ns if led else 0, led.st_size if led else 0, day)
            seen = old.get(name)
            page = seen if seen is not None and seen.stamp == stamp else _read_page(path, stamp)
            if page is not None:
                fresh[name] = page
        citing: dict[str, list[str]] = {}
        for name, page in fresh.items():
            for doc in page.docs:
                citing.setdefault(doc, []).append(name)
        bank.key, bank.pages, bank.citing = key, fresh, citing
        return bank


def pages_citing(memory_path: Path, doc_id: str) -> list[str]:
    """The page files naming ``doc_id`` in their claims or frontmatter, ledgers included, in filename order."""
    return list(_bank(Path(memory_path)).citing.get(doc_id, ()))


def for_source(memory_path: Path, doc_id: str) -> SourceSpans | None:
    """Every span pointing into ``doc_id``, grouped by page, each page's in document order, the pages by where they first
    point. ``None`` for an unknown or locked document. What cannot be drawn stays in its group with no ``at``: the page
    still cites this source."""
    source = Source.open(memory_path, doc_id)
    if source is None:
        return None
    bank = _bank(Path(memory_path))
    groups: list[SourceSpanGroup] = []
    directory = Path(memory_path) / "entities"
    for name in bank.citing.get(doc_id, ()):
        page = bank.pages[name]
        if page.rows is None:
            _parse_rows(page, directory / name)
        rows = page.rows.get(doc_id)
        if not rows:
            continue
        spans = [source.span(r.start, r.end, r.hash, r.kind, claim_id=r.claim_id, current=r.current) for r in rows]
        spans.sort(key=lambda s: (s.at is None, s.at.start if s.at else 0, s.claim_id or ""))
        groups.append(SourceSpanGroup(page=name[:-3], name=page.name, type=page.type, spans=spans))
    groups.sort(key=lambda g: (g.spans[0].at is None, g.spans[0].at.start if g.spans[0].at else 0, g.page))
    return SourceSpans(source=doc_id, source_kind=kind_of(doc_id, source.fm), hash=evidence.body_hash(source.text),
                       length=len(source.text), groups=groups)
