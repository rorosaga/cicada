"""What the person marked in a book, word for word, with no model (ROR-95, G39, ruling 64).

A highlight is an act: the person chose that passage out of a whole book. Sleep's prose kept some of it as a paraphrase
and dropped the rest, and a library entry with nothing marked looked the same as a book the person worked through.
So every highlight and every note is a claim on the book's page, written here at the door with no model:

* ``highlighted`` — the passage in the book's words, its evidence a span of kind ``page``: the person's act, never the
  person's words or belief;
* ``noted`` — the person's note or review, its evidence a span of kind ``user``.

**One writer** (:func:`apply`, called by ``books.apply_pending``), keyed on the episode's own sections, so what it writes
is exactly what the body says: the same passage again is the same claim, a span follows the body when a status line or
an earlier section moves it, a passage removed from the record is closed (``valid_to``) and comes back open if the
person marks it again. Sleep's revision step never closes one (``episode_revision._closable``). One the person took back
(a ``retracts`` record) is never written again, and a re-sync reopens neither recovered history nor one a successor closed.

**The words stay private the way the person's own do:** :func:`claims.is_mark` makes each one ``is_persons_words``, so a
remote caller without ``sources`` is told a passage exists, never what it says. What the sensitive detector flags is
written as its typed mark, never repeated on the page (rail G235).

**The page draws them from the claims** (:func:`block`, ``page_blocks``): derived on read, no section in the prose, so no
merge carries a copy and no model reads them when it rewrites a page.

**What Sleep reads** (:func:`note`, :func:`plan_read`, :func:`of_a_read`). Since the words are safe, Stage 1 reads a book's record for what
the words alone cannot give: what the marked passages share. It is told so in a source note, it never sees the status
lines (:func:`mask_status`), and it reads one chunk at most per book: a book past :data:`READ_CHARS` is read as its notes
and passages spread evenly across it, so the cost is bounded by how many books the person marked, never by how much they
marked or how many books they own. A theme becomes a page through the normal rule: 2+ books naming it.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from loguru import logger

from api.services import evidence, markdown_parser
from api.services.claims import (HIGHLIGHTED, MARK_ORIGIN, NOTED, RETRACT_PREDICATE, Claim, Evidence,
                                 MalformedClaimsBlockError, is_mark, is_persons_words, is_recovered_history, parse_claims,
                                 write_claims)

#: The most marks one card carries (the claims hold them all, and search finds them all).
MAX_SHOWN = 500
#: One Stage 1 chunk (``entity_extractor.CHUNK_SIZE``): a book's read never needs a second call.
READ_CHARS = 12_000
#: A passage in a sampled read is cut here, so one long passage does not take the room of twenty.
SAMPLED_PASSAGE_CHARS = 700
#: Theme names told to Stage 1, so two books converge on one spelling and the 2+ rule can count them.
MAX_THEMES = 60
THEME_PREDICATE = "explores-theme"

_HEAD = re.compile(r"(?m)^## (?:Highlight, (?P<day>\d{4}-\d{2}-\d{2})|(?P<note>User note))[ \t]*$")
_NOT_KEPT = re.compile(r"(?m)^\*\*Not kept:\*\*")
#: The record's lines that are already claims, blanked for Stage 1 with their offsets kept.
_STATUS_LINE = re.compile(r"(?m)^\*\*(?:Status|Finished on|My rating):\*\*[^\n]*$")
_QUOTE_PREFIX = re.compile(r"(?m)^> ?")


@dataclass(frozen=True)
class Mark:
    """One section of a book's record: its offsets are the words' own, past the heading and the first ``> ``."""
    predicate: str
    text: str
    start: int
    end: int
    day: str | None = None


def _section(text: str, lo: int, hi: int) -> tuple[int, int]:
    while lo < hi and text[lo].isspace():
        lo += 1
    while hi > lo and text[hi - 1].isspace():
        hi -= 1
    return lo, hi


def parse(body: str) -> list[Mark]:
    """The record's highlights and notes, in order. A note's day is the highlight above it, else None."""
    body = body or ""
    tail = _NOT_KEPT.search(body)
    stop = tail.start() if tail else len(body)
    heads = [m for m in _HEAD.finditer(body) if m.start() < stop]
    out: list[Mark] = []
    day = None
    for i, head in enumerate(heads):
        lo, hi = _section(body, head.end(), heads[i + 1].start() if i + 1 < len(heads) else stop)
        if lo >= hi:
            continue
        if head.group("day"):
            day = head.group("day")
            if body.startswith(">", lo):
                lo = lo + 2 if body.startswith("> ", lo) else lo + 1
            out.append(Mark(HIGHLIGHTED, _QUOTE_PREFIX.sub("", body[lo:hi]).strip(), lo, hi, day))
        else:
            out.append(Mark(NOTED, body[lo:hi], lo, hi, day))
    return [m for m in out if m.text]


def is_book_record(episode: dict) -> bool:
    """A book's record, by its frontmatter block and door."""
    from api.services import books

    return isinstance(episode.get(books.EPISODE_KEY), dict) and str(episode.get("origin") or "") in books.DOORS


def holds_marks(episode: dict) -> bool:
    """A book's record with a highlight or a note in it."""
    return is_book_record(episode) and _HEAD.search(str(episode.get("content") or "")) is not None


def _digest(text: str) -> str:
    return hashlib.sha1(" ".join(text.split()).casefold().encode()).hexdigest()[:12]


def _claim_id(entity_id: str, predicate: str, text: str) -> str:
    return "clm_book_" + hashlib.sha1("\x00".join((entity_id, predicate, _digest(text))).encode()).hexdigest()[:10]


def _words(predicate: str, text: str) -> str:
    return f"{'Highlighted' if predicate == HIGHLIGHTED else 'Noted'}: {text}"


def words_of(claim) -> str:
    """The passage or note a mark holds, without its label."""
    return str(claim.text or "").split(": ", 1)[-1]


def _object(text: str) -> str:
    return " ".join(text.split())[:80]


def _held(body: str, mark: Mark, hits) -> str:
    """The mark's words as a page may repeat them: anything flagged is its typed mark (rail G235)."""
    from api.services import sensitive_text

    if not any(h.start < mark.end and h.end > mark.start for h in hits):
        return mark.text
    held = sensitive_text.held_text(body, mark.start, mark.end, hits)
    return _QUOTE_PREFIX.sub("", held).strip() if mark.predicate == HIGHLIGHTED else held


def _closes(claim, episode_id: str, here: set[str]) -> bool:
    """An open mark of this episode the body no longer says, and that no other door's record holds."""
    return (is_mark(claim) and claim.id not in here and not claim.valid_to and episode_id in claim.source_episodes
            and not [e for e in claim.source_episodes if e != episode_id])


def apply(memory_path: Path, entity_id: str, episode_id: str, *, observer: str, today: str) -> bool:
    """Make the page's marks from this episode match what the episode says. Returns whether the page changed. The caller
    holds the page lock and the bank's write admission (``books.apply_pending``). A failure of the sensitive check raises:
    nothing is written, rather than a value repeated, and the caller's next apply tries again."""
    from api.services import authorship, page_redirects, sensitive_flags, sensitive_text

    memory_path = Path(memory_path)
    doc = evidence.source_document(memory_path, episode_id)
    if doc is None:
        return False
    fm, body = doc
    marks = parse(body)
    path = memory_path / "entities" / f"{entity_id}.md"
    if not path.is_file():
        logger.warning("a book's marks have no page to go on; the record keeps them")
        return False
    parsed = markdown_parser.parse(path)
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError:
        logger.warning("book page has an unreadable claims block; its marks were not written")
        return False
    if not marks and not any(is_mark(c) and episode_id in c.source_episodes for c in claims):
        return False
    digest = evidence.body_hash(body)
    override = authorship.of(fm)
    gaps = evidence.gap_ranges(fm, body)
    hits = sensitive_flags.not_left(fm, sensitive_text.find(body, override=override, gaps=gaps))
    by_id = {c.id: c for c in claims}
    gone = {str(c.object) for c in claims if c.predicate == RETRACT_PREDICATE}
    default_day = str((fm.get("book") or {}).get("day") or "")[:10] or today
    changed = False
    here: set[str] = set()
    # A mark keeps its id through a merge or a rename, and that id was derived from the old page's: the same passage on
    # this page is any of them, and one the person took back under any of them stays taken back.
    pages = (entity_id, *page_redirects.former_ids(memory_path, entity_id))
    for mark in marks:
        ids = [_claim_id(eid, mark.predicate, mark.text) for eid in pages]
        if gone.intersection(ids) or here.intersection(ids):
            continue
        cid = next((i for i in ids if i in by_id), ids[0])
        here.add(cid)
        span = Evidence(episode=episode_id, start=mark.start, end=mark.end, hash=digest,
                        kind=evidence.kind_for(episode_id, body, mark.start, override, gaps))
        words = _held(body, mark, hits)
        text = _words(mark.predicate, words)
        old = by_id.get(cid)
        if old is None:
            claims.append(Claim(id=cid, text=text, subject=entity_id, predicate=mark.predicate, object=_object(words),
                                object_kind="literal", observer=observer, context="general", epistemic="explicit",
                                source_trust="user_stated", confidence=0.9, valid_from=mark.day or default_day,
                                recorded_at=today, source_episodes=[episode_id], origin=MARK_ORIGIN,
                                authored_by="user", evidence=[span]))
            changed = True
            continue
        # Marked again reopens only this writer's own close. Recovered history stays history (G148), and a mark closed in
        # favour of something else stays closed: the person's answer on a conflict is not undone by a re-sync.
        if is_recovered_history(old) or (old.valid_to and old.superseded_by):
            continue
        # Both merged pages held this passage: one mark, resting on what both rest on.
        twins = [by_id[i] for i in ids if i != cid and i in by_id and not by_id[i].valid_to]
        for twin in twins:
            twin.valid_to = today
            old.evidence = [*old.evidence, *(ev for ev in twin.evidence if ev not in old.evidence)]
            old.source_episodes = [*old.source_episodes, *(e for e in twin.source_episodes if e not in old.source_episodes)]
            changed = True
        evidence_now = [*(ev for ev in old.evidence if ev.episode != episode_id), span]
        now = (evidence_now, text, old.source_episodes + ([] if episode_id in old.source_episodes else [episode_id]))
        if (old.evidence, old.text, old.source_episodes) != now or old.valid_to:
            old.evidence, old.text, old.source_episodes = now
            old.object = _object(words)
            old.valid_to = None   # marked again after it was removed
            changed = True
    for claim in claims:
        if _closes(claim, episode_id, here):
            claim.valid_to = today   # the person removed it from the book: history, never deleted
            changed = True
    if changed:
        markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))
    return changed


# ---- the page's block ------------------------------------------------------------------------------------------------


def _order(claim) -> tuple:
    ev = next((e for e in claim.evidence if e.is_span()), None)
    return (ev.episode if ev else "", ev.start if ev else 1 << 40)


def block(claims) -> dict | None:
    """The page's marks in the order they were made, each note under its passage; ``None`` for a page with none. Withdrawn
    or removed marks are not drawn."""
    gone = {str(c.object) for c in claims or [] if c.predicate == RETRACT_PREDICATE}
    live = sorted((c for c in claims or [] if is_mark(c) and not c.valid_to and c.id not in gone), key=_order)
    if not live:
        return None
    items: list[dict] = []
    for c in live:
        if c.predicate == NOTED and items and items[-1]["note"] is None and items[-1]["text"]:
            items[-1]["note"] = words_of(c)
            continue
        passage = c.predicate == HIGHLIGHTED
        items.append({"claimId": c.id, "day": str(c.valid_from or "")[:10], "text": words_of(c) if passage else None,
                      "note": None if passage else words_of(c)})
    return {"items": items[:MAX_SHOWN], "total": len(items)}


def for_caller(marks: dict | None) -> dict | None:
    """A caller without ``sources``: how many, on which days, never the words."""
    if not marks:
        return marks
    return {"total": marks.get("total", 0),
            "items": [{"claimId": i["claimId"], "day": i["day"], "text": None, "note": None}
                      for i in marks.get("items") or []]}


#: What a claim in the person's own words reads as for a caller that may not see them: theirs, or a passage they chose.
HIDDEN = "(the person's own: this connection can't read it)"


def masked_page(text: str) -> str:
    """A page as an agent reads the file (fence and ledger lines), with the words of each claim gated like the person's
    own (`claims.is_persons_words`) taken out. A line that does not parse is left to the reader that already refuses it."""
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith('{"id": "') and '"origin": "' in line:
            try:
                row = json.loads(line)
            except ValueError:
                out.append(line)
                continue
            if isinstance(row, dict) and is_persons_words(SimpleNamespace(**row)):
                row["text"], row["object"] = HIDDEN, ""
                line = json.dumps(row, ensure_ascii=False) + ("\n" if line.endswith("\n") else "")
        out.append(line)
    return "".join(out)


def without_marks(body: str) -> str:
    """A page's body with its marks out of the claims block, for a reader that hands claims to a caller or a model on the
    behalf of a caller without ``sources``."""
    claims = parse_claims(body or "")
    return write_claims(body, [c for c in claims if not is_mark(c)]) if any(is_mark(c) for c in claims) else body


# ---- what Sleep reads ------------------------------------------------------------------------------------------------


def mask_status(text: str) -> str:
    """Blank the lines Sleep must not read again (a status, a finish date, a rating), keeping every offset."""
    return _STATUS_LINE.sub(lambda m: " " * len(m.group(0)), text)


def plan_read(body: str, windows=None, *, limit: int = READ_CHARS) -> tuple[list[tuple[int, int]], int, int] | None:
    """What one chunk of this record holds when the whole of it would not fit: ``(spans, sections shown, sections there
    are)``, or ``None`` when it fits as it stands. The header, then every note, then passages spread evenly across the
    book, each cut to :data:`SAMPLED_PASSAGE_CHARS`. With ``windows`` (a revision) only the sections it changed compete."""
    ranges = list(windows) if windows else [(0, len(body))]
    if len(ranges) == 1 and ranges[0][1] - ranges[0][0] <= limit:
        return None
    marks = [m for m in parse(body) if any(m.start < hi and m.end > lo for lo, hi in ranges)]
    first = _HEAD.search(body)
    header = (0, min(first.start() if first else len(body), 1000))
    room = limit - (header[1] - header[0])

    def size(mark: Mark) -> int:
        return min(mark.end - mark.start, SAMPLED_PASSAGE_CHARS) + 2

    picked: list[Mark] = []
    used = 0
    for mark in (m for m in marks if m.predicate == NOTED):
        if used + size(mark) > room:
            break
        picked.append(mark)
        used += size(mark)
    passages = [m for m in marks if m.predicate == HIGHLIGHTED]
    if passages and used < room:
        average = sum(size(m) for m in passages) / len(passages)
        fit = max(1, min(len(passages), int((room - used) / average)))
        for i in range(fit):
            mark = passages[i * len(passages) // fit]
            if used + size(mark) > room:
                continue
            picked.append(mark)
            used += size(mark)
    picked.sort(key=lambda m: m.start)
    spans = [header] + [(m.start, min(m.end, m.start + SAMPLED_PASSAGE_CHARS)) for m in picked]
    return spans, len(picked), len(marks)


def theme_hints(memory_path: Path) -> list[str]:
    """Theme names already on the record: concept pages a book page links to, and names held from a book's record waiting
    for their second book. Frontmatter and one small store only."""
    from api.services import bank_index, books, pending_store

    memory_path = Path(memory_path)
    names: list[str] = []
    try:
        pages = {Path(f.path).stem: f.frontmatter or {} for f in bank_index.files(memory_path, "entities")}
        for fm in pages.values():
            if not books.is_book(fm):
                continue
            for linked in fm.get("related") or []:
                other = pages.get(str(linked).strip("[]"))
                if other and other.get("type") == "concept" and other.get("name"):
                    names.append(str(other["name"]))
        for held in pending_store.load(memory_path):
            if held.type != "concept":
                continue
            header = bank_index.file(memory_path, "episodes", f"{held.source_episode}.md")
            if header is not None and isinstance((header.frontmatter or {}).get(books.EPISODE_KEY), dict):
                names.append(held.name)
    except Exception as exc:  # noqa: BLE001 — a hint is a convenience; its absence costs a spelling, never a read
        logger.warning(f"book theme hints skipped: {type(exc).__name__}")
    return list(dict.fromkeys(names))[:MAX_THEMES]


def owner_test(owner_fm: dict | None, entities=()):
    """Could a name be the owner's, as a read of a book must take it: a self-reference, a name made only of their page's
    words (`role_people.owner_names`: the name, its first word, its aliases) or a close spelling of one
    (`entity_resolver.fuzzy_same`). Only :func:`names_the_owner` is sure; a first name may be a friend's. A name this read
    itself types as no person keeps its own facts, as in G169: a concept "Hope" on the page of someone called Hope."""
    from api.services import entity_resolver, owner_identity, role_people, text_fold

    names = [text_fold.fold(n) for n in role_people.owner_names(owner_fm)]
    words = {w for n in names for w in n.split()}
    apart = {text_fold.fold(" ".join(str(e.get("name") or "").split())) for e in entities
             if isinstance(e, dict) and str(e.get("type") or "person").strip().lower() != "person"}

    def is_owner(name) -> bool:
        said = text_fold.fold(" ".join(str(name or "").split()))
        if not said or said in apart:
            return False
        return (owner_identity.is_self_reference(said) or set(said.split()) <= words
                or any(entity_resolver.fuzzy_same(said, n) for n in names))

    return is_owner


def _page_names(owner_fm: dict | None) -> set[str]:
    """The owner page's full name and aliases, folded: what names them with no doubt."""
    from api.services import text_fold

    fm = owner_fm or {}
    return {text_fold.fold(" ".join(str(n).split())) for n in [fm.get("name"), *(fm.get("aliases") or [])] if n}


def names_the_owner(name, owner_fm: dict | None) -> bool:
    """What Stage 2 joins to the owner's page on its own: a self-reference, the full name, an alias or a close spelling of
    those (`entity_resolver.endpoint_id`). Never a bare first name or surname: "Ada" in a note may be a friend, and the
    person's page takes only the person's own words naming themselves so."""
    from api.services import entity_resolver, owner_identity, text_fold

    said = text_fold.fold(" ".join(str(name or "").split()))
    return bool(said) and (owner_identity.is_self_reference(said) or said in _page_names(owner_fm)
                           or any(entity_resolver.fuzzy_same(said, n) for n in _page_names(owner_fm)))


def in_a_note(row: dict, content: str) -> bool:
    """A read's relationship or value whose evidence is located in the person's own note on this record: a ``user`` span
    inside a ``## User note`` section, never a passage, the header or someone else's words."""
    if str(row.get("observer") or "").startswith("external:"):
        return False
    notes = [m for m in parse(content) if m.predicate == NOTED]
    return any(isinstance(ev, dict) and ev.get("kind") == "user"
               and any(m.start <= int(ev.get("start", -1)) < m.end for m in notes) for ev in row.get("evidence") or [])


def of_a_read(entities: list, relationships: list, values: list, episode: dict,
              *, owner_fm: dict | None) -> tuple[list, list, list]:
    """What a read of a book's record may add (ruling 64): its themes and what the person's own notes say. Told not to, a
    small model still wrote "highlighted a passage saying …" onto the book's page and "practices sourdough baking" onto
    the owner's from a highlight about bread (haiku, 2026-11-05).

    The book's entry goes: the page exists and every word of that is held verbatim, and its links still land on it by name
    (an entry emptied instead was held as a new name beside its page). The owner's entry goes too, note or no note: a
    summary or a fact on it rests on no span. What reaches their page is a relationship or a value located in a note, and
    only that; a full name or an alias is written as their page's name. A bare first name or surname stays as written
    with its entry, located in a note: it may be a friend, and Stage 2 holds it or asks."""
    from api.services import text_fold
    from api.services.owner_identity import is_self_reference

    title = " ".join(str((episode.get("book") or {}).get("title") or "").split()).casefold()
    content = str(episode.get("content") or "")
    is_owner = owner_test(owner_fm, entities)
    own_name = str((owner_fm or {}).get("name") or "").strip()
    page_names = _page_names(owner_fm)
    folded = lambda name: text_fold.fold(" ".join(str(name or "").split()))  # noqa: E731
    noted: set[str] = set()   # the bare names a kept row says in a note: their entries stay beside it

    def kept(rows: list, keys: tuple[str, ...]) -> list:
        out = []
        for row in rows:
            theirs = [k for k in keys if is_owner(row.get(k))]
            if theirs and not in_a_note(row, content):
                continue
            noted.update(folded(row.get(k)) for k in theirs)
            out.append({**row, **{k: own_name for k in theirs if own_name and folded(row.get(k)) in page_names
                                  and not is_self_reference(str(row.get(k)))}})
        return out

    def restates(entity) -> bool:
        if not isinstance(entity, dict):
            return False
        name = " ".join(str(entity.get("name") or "").split()).casefold()
        if title and name and (name == title or title.startswith(f"{name}:") or name.startswith(f"{title}:")):
            return True
        return is_owner(entity.get("name")) and (names_the_owner(entity.get("name"), owner_fm)
                                                 or folded(entity.get("name")) not in noted)

    kept_rels, kept_vals = kept(relationships, ("source", "target")), kept(values, ("entity",))
    return [e for e in entities if not restates(e)], kept_rels, kept_vals


def new_themes(result: dict | None, known: list[str]) -> list[str]:
    """The concept names one book's read gave that the next book should hear, within :data:`MAX_THEMES`."""
    fresh = [str(e.get("name")) for e in (result or {}).get("entities") or []
             if isinstance(e, dict) and e.get("type") == "concept" and e.get("name")]
    fresh = [n for n in dict.fromkeys(fresh) if n not in known]
    return fresh[:max(0, MAX_THEMES - len(known))]


NOTE_PREFIX = "[Source: what the person marked in a book"


def note(episode: dict, *, themes=(), shown: tuple[int, int] | None = None) -> str | None:
    """Stage 1's note for a book's record with marks in it; ``None`` for every other episode."""
    if not holds_marks(episode):
        return None
    held = (f" Themes other books already hold; when one of yours means the same, even in other words, use its exact "
            f"name: {'; '.join(themes)}.") if themes else ""
    sample = f" This book holds {shown[1]} marked sections; {shown[0]} spread across it are shown." if shown else ""
    return (f'{NOTE_PREFIX}.{sample} Each line starting ">" is a passage from the book that the person chose to '
            'highlight: the book\'s words, never the person\'s, never what the person believes, and never a fact about '
            'their life. A "## User note" section is the person\'s own words: what one says about them goes in a '
            'relationship or a value whose evidence_quote is from that note, never in an entity for them. Every '
            "passage and note is already kept word for word on the book's page, and the book's reading status is "
            "recorded elsewhere, so give the book no history_entries, key_facts or summary about what was highlighted "
            "or when, and write no reading status, no value of a status, and no relationship saying the person read or "
            "finished the book. What this record is for: name the 1 to 3 themes these passages share, what the person "
            "keeps marking, each as a `concept` entity with decay_class durable and a general name of one to three "
            'words, the way a book\'s index names a topic ("Focus", "Fear of failure", "Grief"), never a phrase '
            f'particular to this book; and a relationship from the book to it with the label "{THEME_PREDICATE}" whose '
            "evidence_quote is a passage that shows it. Something only one passage touches is no theme unless the "
            f"person's own note names it.{held} Link to any other page only when a passage or a note names it.]\n\n")
