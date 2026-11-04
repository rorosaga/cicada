"""A book's status from what the person said in a conversation (TODO ruling 61, owner 2026-11-04, G233).

"Yes, change the book status in that case. But it has to be in the context, we can always go back and correct that's
what cicada is about." A book's status used to come only from the person's explicit acts (a scan's tap, Apple Books,
Goodreads). Now the person saying "I finished X" changes it. **The judgement is Stage 1's model, reading the
conversation** — there is no keyword list here, on the owner's word. What this module checks is what a model cannot
be trusted to report about itself, each from the conversation's own record:

* **whose words:** the model's quote is located (``evidence.locate``: exact → whitespace → case, never fuzzy) inside a
  turn that is the person's own (``user``; a meeting's other speaker, an agent's reply, a saved record, an agent's
  saved note never are, ``authorship``). A quote that cannot be located there changes nothing;
* **the title is on the record:** the name is said somewhere in the conversation, so it is never the model's memory;
* **a date to file it under:** an undated conversation is no time signal and sets no status (ruling 39);
* **not a door's own record:** an Apple Books or Goodreads episode carries its status already.

**Dated by the conversation** (read on time, 2026-10-16), or by the day it states (``on``), never after it. The chain
in ``books.set_status`` orders by that day, so a late read never overrides a newer status: it lands closed, as history.

**The right work** (:meth:`TitleIndex.clear_page`): one book page whose name, title or alias is the name said, else one
whose title without its subtitle or series note is, else the book page Stage 2 joined this name to (the identity rails'
own decision). Two such pages (a copy with no shared identifier keeps its own page, B1): nothing is guessed, and Stage
2's same-title question is the way out. **What is said about a name with no page yet is held** — on the episode's own
frontmatter (``book_said``, derived from the bank like ``book_applied``) — and applied by :func:`apply_waiting` when a
door makes the page or an answer settles the name, dated as it was said. A first mention of a book stays under the
promotion rules: Stage 1 never produces ``media``, so a page the normal rule makes from a chat is an ordinary page with
no status record.

**One writer:** the status goes through ``books.set_status`` and the happening through ``books.record_happening`` →
``progress.record_happening``, the one event writer. A finish is a "Finished reading" dated by the conversation or the
day it states; a reading is a "Started reading" only on a day the conversation states (review of #600, B2).

**Said again** (a later day, nothing changed between): only its episode joins the record as evidence, no second record
and no second happening (``books.set_status``, ``ranked``). A record's happening is only written when the page holds none.

**A real conflict** — the same day, and the person's words say less than a record already holds (they say "still
reading" on the day the library says finished) — keeps the record's status open and asks once, the existing conflict
path. Undo: ``books.undo_status`` ("Not right" on the page); a held row, once applied, never applies twice: it is known by the
words it rests on, never its day (a re-read may date them differently), and keeps only their hash, never a copy.

Rails: no model and no network here; the caller holds Sleep's window or the bank's admission; this holds the page lock
(lock order: page, then episode); nothing here logs a title.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import authorship, bank_index, books, episode_ids, evidence, markdown_parser, page_lock
from api.services.text_fold import fold

#: What the model writes on an entity at Stage 1 (consumed there, never reaches a page), and where a checked mark
#: lives: on the extraction's result, then in the episode's frontmatter until it lands on a page.
MODEL_KEY = "reading_status"
KEY = "book_said"
#: A person's own turn. A meeting's ``speaker`` is someone else, whatever ``promotion.PERSON_KINDS`` counts for a page.
OWN_KIND = "user"
MAX_QUOTE = 240


def own_span(text: str, quote: str, *, episode_id: str, override: str | None, gaps=()) -> evidence.Evidence | None:
    """``quote`` as a span inside one of the person's own turns, or None. Every turn of theirs is tried, so the same
    words in an agent's reply first never hide the person's."""
    for turn in evidence.turns(text, override=override, gaps=gaps):
        if turn.role != OWN_KIND:
            continue
        window = (turn.content_start, turn.end)
        hit = evidence.locate(text, quote, window=window)
        if hit is None or hit[0] < window[0] or hit[1] > window[1] or evidence.touches_gap(hit[0], hit[1], gaps):
            continue
        return evidence.Evidence(episode=episode_id, start=hit[0], end=hit[1], kind=OWN_KIND,
                                 hash=evidence.body_hash(text))
    return None


def _stated_day(raw, day: str) -> str | None:
    """The day the conversation states for the act (``on``), never one after the conversation, or None."""
    try:
        stated = date.fromisoformat(str(raw or "").strip()[:10]).isoformat()
    except ValueError:
        return None
    return stated if stated <= day else None


def at_extraction(entity: dict, *, episode_id: str, frontmatter: dict, text: str, day: str | None,
                  override: str | None = None, gaps=()) -> dict | None:
    """The mark this conversation gives the entity, or None (module docstring). Takes the model's field off the
    entity: nothing of it reaches a page."""
    from api.services.project_birth import _name_pattern

    raw = entity.pop(MODEL_KEY, None)
    if not isinstance(raw, dict) or not day or str(frontmatter.get("origin") or "") in books.DOORS:
        return None
    status = str(raw.get("status") or "").strip().lower()
    quote = " ".join(str(raw.get("quote") or "").split())[:MAX_QUOTE]
    name = " ".join(str(entity.get("name") or "").split())
    pattern = _name_pattern(entity)
    if status not in books.STATUSES or not quote or not name or pattern is None or not pattern.search(text or ""):
        return None
    if own_span(text, quote, episode_id=episode_id, override=override, gaps=gaps) is None:
        return None
    stated = _stated_day(raw.get("on"), day)
    return {"name": name, "aliases": [str(a) for a in entity.get("aliases") or [] if isinstance(a, str)][:6],
            "status": status, "day": stated or day, "stated": bool(stated), "quote": quote}


# --------------------------------------------------------------------------- #
# the right work
# --------------------------------------------------------------------------- #


def _plain_title(title: str) -> str:
    """A title without a series note or a subtitle: "<Title> (Series, #1)", "<Title>: A Novel"."""
    plain = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*", " ", title).strip()
    return plain.split(":", 1)[0].strip()


class TitleIndex:
    """Every book page by what it is called: exactly (name, title, each alias), then by its title alone."""

    def __init__(self, memory_path: Path):
        self.exact: dict[str, set[str]] = {}
        self.plain: dict[str, set[str]] = {}
        self.ids: set[str] = set()
        for f in bank_index.files(Path(memory_path), "entities"):
            fm = f.frontmatter or {}
            if not books.is_book(fm) or str(fm.get("status") or "active") == "dropped":
                continue
            stem = Path(f.path).stem
            self.ids.add(stem)
            block = fm.get("book") if isinstance(fm.get("book"), dict) else {}
            for value in (fm.get("name"), block.get("title"), *(fm.get("aliases") or [])):
                if isinstance(value, str) and value.strip():
                    self.exact.setdefault(fold(value), set()).add(stem)
                    plain = _plain_title(value)
                    if plain:
                        self.plain.setdefault(fold(plain), set()).add(stem)

    def clear_page(self, names, *, joined: str | None = None) -> str | None:
        """The one page these names mean, or None: never a guess between two. The exact tier is read first, so "<Title>"
        finds that book and not "<Title>: <Another book's subtitle>"."""
        keys = [fold(n) for n in names if isinstance(n, str) and n.strip()]
        for tier in (self.exact, self.plain):
            found = set().union(*(tier.get(k, set()) for k in keys)) if keys else set()
            if len(found) == 1:
                return next(iter(found))
            if len(found) > 1:
                return None
        return joined if joined in self.ids else None


# --------------------------------------------------------------------------- #
# held on the episode, applied when the page is clear
# --------------------------------------------------------------------------- #


def _said(quote) -> str:
    return hashlib.sha256(fold(str(quote or "")).encode()).hexdigest()[:16]


def _row_key(row: dict) -> tuple:
    """Who said what about which name, never when: a re-read that dates the same words differently is the same row."""
    return fold(str(row.get("name") or "")), row.get("status"), row.get("said") or _said(row.get("quote"))


def _stamp(memory_path: Path, episode_id: str, marks: list[dict]) -> bool:
    """Add this read's marks to the episode, once each: re-reading the same words adds nothing, and a row already
    applied stays as it is. Under the episode lock, re-read first (capture runs during Sleep)."""
    path = evidence.source_path(memory_path, episode_id)
    if path is None or not path.is_file():
        return False
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        rows = [r for r in parsed.frontmatter.get(KEY) or [] if isinstance(r, dict)]
        seen = {_row_key(r) for r in rows}
        new = []
        for mark in marks:
            if _row_key(mark) not in seen:
                seen.add(_row_key(mark))
                new.append(mark)
        if not new:
            return False
        parsed.frontmatter[KEY] = rows + new
        markdown_parser.write(path, parsed.frontmatter, parsed.body)
    return True


def _waiting_rows(memory_path: Path) -> list[tuple[str, dict]]:
    out = []
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        rows = fm.get(KEY)
        if not isinstance(rows, list) or fm.get("source_deleted_at"):
            continue
        out += [(str(fm.get("id") or Path(f.path).stem), r) for r in rows if isinstance(r, dict) and not r.get("page")]
    return out


def waiting(memory_path: Path) -> bool:
    return bool(_waiting_rows(memory_path))


def _settle_row(memory_path: Path, episode_id: str, row: dict, *, page: str | None) -> str | None:
    """Mark the row applied to ``page``, its words kept only as their hash (the span on the record is the evidence), or
    take it away (``page`` None: its words are gone)."""
    path = evidence.source_path(memory_path, episode_id)
    if path is None or not path.is_file():
        return None
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        rows = [r for r in parsed.frontmatter.get(KEY) or [] if isinstance(r, dict)]
        key = _row_key(row)
        rows = [{**{k: v for k, v in r.items() if k != "quote"}, "page": page, "said": key[2]}
                if _row_key(r) == key else r for r in rows] if page else [r for r in rows if _row_key(r) != key]
        if rows:
            parsed.frontmatter[KEY] = rows
        else:
            parsed.frontmatter.pop(KEY, None)
        markdown_parser.write(path, parsed.frontmatter, parsed.body)
    return f"episodes/{path.name}"


def _ask_if_clash(memory_path: Path, page: str, day: str, status: str, *, today: str) -> list[str]:
    """Same day, and these words say less than a record already holds: the record stays open, one question (the
    existing conflict path: its answer closes the loser, and ``books.set_status`` keeps that order)."""
    from api.services import inbox_generator
    from api.services.claim_reconciler import _conflict_nudge
    from api.services.claims import parse_claims

    parsed = markdown_parser.parse(Path(memory_path) / "entities" / f"{page}.md")
    claims = books.live_status_claims(parse_claims(parsed.body))
    new = next((c for c in claims if c.object == status and (c.valid_from or "") == day), None)
    held = next((c for c in claims if not c.valid_to and c.object != status and (c.valid_from or "") == day), None)
    if new is None or held is None:
        return []
    inbox_generator.write_claim_nudges([_conflict_nudge(held, new, today)], Path(memory_path))
    asked = inbox_generator.find_open(Path(memory_path), "conflict", page, books.STATUS_PREDICATE)
    return [Path(asked).relative_to(Path(memory_path)).as_posix()] if asked else []


def apply_waiting(memory_path: Path, *, today: date | None = None) -> list[str]:
    """Every held mark whose page is now clear, oldest first: the status, then the happening. Returns memory-relative
    paths for the caller's commit. A row whose words a revision removed goes away with them."""
    memory_path = Path(memory_path)
    rows = _waiting_rows(memory_path)
    if not rows:
        return []
    today_s = (today or date.today()).isoformat()
    paths: list[str] = []
    with page_lock.page_lock(memory_path):
        titles = TitleIndex(memory_path)
        observer = books._owner(memory_path)
        for episode_id, row in sorted(rows, key=lambda r: (str(r[1].get("day") or ""), r[0])):
            try:
                doc = evidence.source_document(memory_path, episode_id)
                if doc is None:
                    continue
                fm, text = doc
                span = own_span(text, str(row.get("quote") or ""), episode_id=episode_id, override=authorship.of(fm),
                                gaps=evidence.gap_ranges(fm, text))
                if span is None:
                    # The conversation no longer says it (edited, G104): nothing to act on.
                    if (done := _settle_row(memory_path, episode_id, row, page=None)) is not None:
                        paths.append(done)
                    continue
                page = titles.clear_page([row.get("name"), *(row.get("aliases") or [])], joined=row.get("joined"))
                if page is None:
                    continue
                status, day, quote = str(row["status"]), str(row["day"]), text[span.start:span.end]
                has_it = books.happening_stands(memory_path, page, status, day)
                wrote = books.set_status(memory_path, page, status=status, day=day, episode_id=episode_id,
                                         quote=quote, observer=observer, today=today_s, span=span, ranked=True)
                if wrote:
                    paths.append(f"entities/{page}.md")
                    paths += _ask_if_clash(memory_path, page, day, status, today=today_s)
                # A finish said is dated by what said it; a reading only by a day the conversation states (B2).
                if wrote and not has_it and (status == books.FINISHED
                                             or (status == books.READING and row.get("stated"))):
                    paths += books.record_happening(memory_path, page, status=status, day=day, episode_id=episode_id,
                                                    quote=quote, span=span, observer=observer,
                                                    basis="stated" if row.get("stated") else "episode")
                if (done := _settle_row(memory_path, episode_id, row, page=page)) is not None:
                    paths.append(done)
            except Exception as exc:  # noqa: BLE001 — one bad row never stops the rest
                from api.services import tool_contract

                logger.warning(f"a status said in a conversation was not applied: {tool_contract.where(exc)}")
    bank_index.invalidate(memory_path)
    return list(dict.fromkeys(paths))


def settle(memory_path: Path, extracted: list, *, name_to_id: dict | None = None,
           today: date | None = None) -> list[str]:
    """Stage 5's step: hold this batch's marks on their episodes, then apply what is clear. Runs inside Sleep's window;
    the batch's commit carries what it wrote. ``name_to_id`` is Stage 2's own map (a page it joined the name to)."""
    memory_path = Path(memory_path)
    stamped = 0
    for result in extracted or []:
        marks = [m for m in (result.get(KEY) or []) if isinstance(m, dict)] if isinstance(result, dict) else []
        if not marks:
            continue
        for mark in marks:
            joined = (name_to_id or {}).get(str(mark.get("name") or "").strip().lower())
            if joined:
                mark["joined"] = joined
        if _stamp(memory_path, str(result.get("episode_id") or ""), marks):
            stamped += 1
    if not stamped:
        return []
    bank_index.invalidate(memory_path)
    return apply_waiting(memory_path, today=today)
