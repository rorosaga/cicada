"""What a split leaves on the old page: prose nobody sourced that still states the person who left (2026-11-24).

`same_name_tend.moving` moves a leaving conversation's beliefs and the Key Facts whose provenance names only it. A page's
Summary, its History bullets, its Open Questions and its tags carry no per-sentence provenance: they were written when
the page was a blend of two people and they stay, so an agent reading the staying page is told the leaving person's
facts as the staying person's (found on a real bank: a retired neighbour's jam on the architect's page, nobody in the
record to say otherwise).

This is the plan half (a model call, outside the write window, by the same main-model judge the split was read with).
It numbers the old page's unsourced items and asks, for each, whose it is, **and only acts on what it can locate**:
a line moves only when the words the judge copies from a leaving conversation's description are there word for word
and in none of the staying ones, and the part of the line that moves is a stretch of the line itself, copied exactly,
at a clause boundary (``leave_text``). Nothing is invented: a cut is removed from the old page and appended to the new
page as it was written, in the same commit as the split (`page_join.split(cuts=...)`), so the person's undo of the split
takes it back byte for byte. What the judge cannot locate, a line both people's conversations state, a passage a person
or an agent wrote (git blame, `revision_prose._hand_lines`) or pinned (`page_edits.corrections`), and a Summary the
person wrote, stay where they are. Engine-free apart from the injected ``judge(system, prompt)``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.services import engine_errors, same_name_people as snp

Judge = Callable[[str, str], Awaitable[object]]

SECTIONS = ("Summary", "Key Facts", "History", "Related", "Open Questions")
#: Items one call reads: the old page's unsourced sentences and tags, the oldest first (a page past this is read again by
#: the next split; nothing is lost).
MAX_ITEMS = 60
ITEM_CHARS = 420
TAGS = "tags"
#: Letters, beyond the name, a stretch of words must have to tie a line to a leaving description: a place or a word alone is no tie.
TIE_CHARS = 12

SYSTEM = ("You decide, from the descriptions you are given, which of two people sharing one name a line on their shared "
          "page is about, and you answer in JSON.")

PROMPT = """One page in a person's memory held two people called "{name}", and has just been split. Everything the record says about each, conversation by conversation:

STAYS (the person this page keeps)
{stays}

LEAVES (the person who moves to a page of their own)
{leaves}

These lines are still on the page and have no recorded source (a summary, a bullet, a tag). For each, say whose it is:
- "stays": it is about the STAYS person, or says nothing about either of them, or both descriptions say it.
- "leaves": it states something only the LEAVES person's descriptions say. Copy in "from", word for word, the words of a LEAVES description it states, and in "leave_text" the whole line.
- "mixed": it states something of both. In "leave_text" copy, word for word, the one stretch of the line (a clause, between its own punctuation) that states what only the LEAVES person's descriptions say, and in "from" the words of the LEAVES description it states.
When unsure, say "stays": a line is moved only when you can copy the words that prove it.

LINES
{lines}

Answer in JSON only: {{"lines": [{{"n": 1, "about": "stays" | "leaves" | "mixed", "leave_text": "words copied from the line", "from": "words copied from a LEAVES description"}}]}}
"""


@dataclass(frozen=True)
class Cut:
    """A stretch of one of the old page's unsourced lines that is the leaving person's, copied exactly. ``section`` is
    the heading it sits under, or ``tags`` for one of the page's tags."""

    section: str
    text: str
    sentence: str = ""   # the sentence the judge saw, of which ``text`` is a stretch at offset ``at``
    at: int = -1

    def as_tuple(self) -> tuple:
        return (self.section, self.text, self.sentence, self.at) if self.sentence else (self.section, self.text)


@dataclass
class Item:
    n: int
    section: str
    text: str


def _items(memory_path: Path, page_id: str) -> tuple[str, list[Item], set[str], bool]:
    """``(name, the old page's unsourced items, the lines a person or an agent wrote or pinned, whether the page has
    human prose)``."""
    from api.services import entity_body, markdown_parser, page_edits, revision_prose, same_name_split, section_provenance
    from api.services.claims import strip_claims_block

    path = Path(memory_path) / "entities" / f"{page_id}.md"
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter or {}
    prose = strip_claims_block(parsed.body or "")
    sections = entity_body.parse_sections(prose)
    sourced: set[str] = set()
    scanned = section_provenance.scan(prose)
    for section, matched in section_provenance.matched(fm, parsed.body).items():
        by_key = {item.key: item for item in scanned.get(section, [])}
        sourced |= {" ".join(by_key[key].text.split()) for key in matched if key in by_key}
    hand = revision_prose._hand_lines(Path(memory_path), f"entities/{page_id}.md")
    if hand is None:
        return str(fm.get("name") or page_id), [], set(), True   # git cannot say who wrote what: nothing is touched
    pinned = [str(row.get("new") or "") for row in page_edits.corrections(fm) if row.get("new")]
    held = set(hand)
    human = entity_body.has_human_prose(fm, sections)
    items: list[Item] = []
    for title in SECTIONS:
        if title == "Summary" and human:
            continue
        content = sections.get(title) or ""
        for raw in content.splitlines():
            line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", raw).strip()
            if not line or " ".join(line.split()) in sourced or revision_prose._line_key(raw) in held:
                continue
            if any(p and p in line for p in pinned):
                continue
            for piece in same_name_split._SPLIT.split(line):
                piece = piece.strip()
                if len(piece) >= 12 and re.search(r"\w", piece):
                    items.append(Item(len(items) + 1, title, piece))
    for tag in fm.get("tags") or []:
        tag = str(tag).strip()
        if tag:
            items.append(Item(len(items) + 1, TAGS, tag))
    return str(fm.get("name") or page_id), items[:MAX_ITEMS], held, human


def still_placeable(memory_path: Path, page_id: str, cuts: list[tuple]) -> list[tuple]:
    """The cuts that are still there to make, read again on the page as it is now (inside the write window, by
    `page_join.split`): a cut with its sentence stays only when that sentence is still, exactly once under its heading, an
    unsourced line nobody wrote or pinned since. A tag, or a short sourced line, is placed by `page_join` itself."""
    sentences = [c for c in cuts if len(c) >= 4 and c[0] != TAGS]
    if not sentences:
        return list(cuts)
    try:
        _name, items, _held, _human = _items(memory_path, page_id)
    except Exception as exc:  # noqa: BLE001 - what cannot be read again is not cut
        logger.debug(f"same-name leftovers: page unreadable at apply ({type(exc).__name__})")
        items = []
    held = [(i.section, i.text) for i in items]
    return [c for c in cuts if len(c) < 4 or c[0] == TAGS or held.count((c[0], c[2])) == 1]


_LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def _words(text: object) -> list[str]:
    return re.findall(r"\w+", str(text or "").lower())


def _has_run(run: list[str], texts: list[str]) -> bool:
    """The words ``run`` occur one after the other, whole words, in one of ``texts``."""
    needle = f" {' '.join(run)} "
    return bool(run) and any(needle in f" {' '.join(_words(t))} " for t in texts)


def _longest_shared(a: list[str], b: list[str]) -> list[str]:
    """The longest stretch of whole words both lists hold one after the other."""
    best: tuple[int, int] = (0, 0)
    last = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        now = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                now[j] = last[j - 1] + 1
                if now[j] > best[0]:
                    best = (now[j], i)
        last = now
    return a[best[1] - best[0]:best[1]]


def _tied(name: str, text: str, leaves: list[str], stays: list[str], *, tag: bool) -> bool:
    """The line's OWN words are tied to the leaving conversations, not just the judge's number for it.

    A line is tied when it shares with a leaving description a stretch of whole words, word for word, of at least
    `TIE_CHARS` letters beyond the name, and shares no stretch of that size with any staying description (a name the two
    people's conversations both carry, "Mira Kolar", is never enough either way); or a line that links a page ``[[Name]]``
    only a leaving description names (a Related bullet states little else) and no page only a staying one names. A tag has no sentence: its words are tied
    by the record alone (a leaving description holds them, no staying one does). The rule is exact words, so it does not
    follow a paraphrase ("studies in Glasgow" for "a student in Glasgow"): the line then stays where it is, the safe side. It
    also fails when a line and a staying description share an ordinary phrase of that size, likewise safe. The judge's own
    proof is no part of it: a number it gets wrong, or a proof for another fact of the same line, moves nothing."""
    mine = _words(text)
    if tag:
        return bool(mine) and snp._says(" ".join(mine), name) and _has_run(mine, leaves) and not _has_run(mine, stays)
    named = set(_words(name))

    def size(run: list[str]) -> int:
        return sum(len(w) for w in run if w not in named)

    links = [w for w in (_words(m.group(1)) for m in _LINK.finditer(text)) if w]
    only_leaving = [w for w in links if _has_run(w, leaves) and not _has_run(w, stays)]
    only_staying = [w for w in links if _has_run(w, stays) and not _has_run(w, leaves)]
    shared_with = lambda texts: any(size(_longest_shared(mine, _words(t))) >= TIE_CHARS for t in texts)  # noqa: E731
    if only_staying or shared_with(stays):
        return False
    return shared_with(leaves) or bool(only_leaving)


async def plan(memory_path: Path, page_id: str, leaving: frozenset[str], judge: Judge) -> list[Cut]:
    """The old page's unsourced stretches that are the leaving person's, located. ``[]`` when there is nothing to read, the
    judge cannot answer, or nothing it says is there to be found. Never raises but for an engine failure."""
    import asyncio

    from api.services import page_join, same_name_tend

    try:   # git blame and the page read are blocking: off the event loop
        name, items, _held, _human = await asyncio.to_thread(_items, memory_path, page_id)
        _name, said, _order = await asyncio.to_thread(same_name_tend.page_conversations, memory_path, page_id)
    except Exception as exc:  # noqa: BLE001 - leftovers are never worth failing a split
        logger.debug(f"same-name leftovers: page unreadable ({type(exc).__name__})")
        return []
    stays = [t for ep, texts in said.items() if ep not in leaving for t in texts]
    leaves = [t for ep, texts in said.items() if ep in leaving for t in texts]
    if not items or not stays or not leaves:
        return []

    def block(texts: list[str]) -> str:
        return "\n".join(f"- {t[:ITEM_CHARS]}" for t in texts[:24])

    lines = "\n".join(f"{i.n}. [{i.section}] {i.text[:ITEM_CHARS]}" for i in items)
    prompt = PROMPT.format(name=name, stays=block(stays), leaves=block(leaves), lines=lines)
    try:
        parsed = await judge(SYSTEM, prompt)
    except engine_errors.EngineError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"same-name leftovers: judge failed ({type(exc).__name__})")
        return []
    answers = parsed.get("lines") if isinstance(parsed, dict) else None
    if not isinstance(answers, list):
        return []
    by_n = {i.n: i for i in items}
    cuts: list[Cut] = []
    for row in answers:
        if not isinstance(row, dict):
            continue
        try:
            item = by_n.get(int(row.get("n")))
        except (TypeError, ValueError):
            continue
        about = str(row.get("about") or "").strip().lower()
        if item is None or about not in ("leaves", "mixed"):
            continue
        proof = row.get("from")
        if not (snp._located(proof, leaves) and snp._says(proof, name) and not snp._located(proof, stays)):
            continue   # nothing to point at in the leaving person's conversations alone: the line stays
        sentence, at = item.text, 0
        if item.section == TAGS:
            text, sentence, at = item.text, "", -1
        elif about == "leaves":
            text = item.text
        else:
            text = " ".join(str(row.get("leave_text") or "").split())
            at = item.text.find(text) if text else -1
            if at < 0 or (text != item.text and (item.text.find(text, at + 1) >= 0
                                                 or not page_join.cut_edges_clean(item.text, at, at + len(text)))):
                continue   # not on the line exactly once, or not between clause edges: the line stays whole
        if item.section != TAGS and snp._located(text, stays):
            continue   # the staying person's conversations say these very words too: shared, never moved
        if not _tied(name, text, leaves, stays, tag=item.section == TAGS):
            continue   # the line itself is not tied to the leaving conversations, whatever number the judge gave it
        cuts.append(Cut(item.section, text, sentence, at))
    return cuts
