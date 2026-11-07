"""Sentences about a different thing with the same name: a per-sentence repair plan, never applied here (G227).

#539 found one page — a tool called <name-a> — whose prose also carried a program called <name-a>: about 10 of its
182 sentences were about the program, written there by joins on the name alone before Stage 2 judged same-titled
pages (G227). That is a class, not a case: any page whose title another thing shares may hold sentences about that
other thing. This module finds them and says, per sentence, where each would go — an existing page with the same name
(by id) or ``new`` (a thing with no page yet) — with the reason. **It writes nothing.** The owner reads the plan and
OKs it before anything is applied (owner 2026-10-29); applying is a separate, reviewed step.

**Which pages** (:func:`targets`): every page that is not a saved link and not dropped whose title another page shares
(`same_name`), plus any page id the caller names (a page whose same-named twin has no page yet is invisible to the
collision map — the case #539 found).

**Which sentences** (:func:`sentences`): the page's prose only — the claims fence, headings, link-only lines and
fragments under :data:`MIN_CHARS` are skipped — numbered in reading order with their section.

**The judge** is injected (``judge(prompt) -> dict``, async): the caller binds it to an engine (the dry run uses the
Claude plan with haiku). One call per page, in chunks of :data:`CHUNK` sentences, each chunk with the page's own first
sentence and every same-named page's (id, type, qualifier, first sentence). It lists only sentences *clearly* about a
different thing; anything it is unsure of stays where it is — never a guess. A target that is neither a listed page id
nor ``new`` is dropped. Engine-free apart from the judge; pure apart from the page reads.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

MIN_CHARS = 25
CHUNK = 60
NEW = "new"

Judge = Callable[[str], Awaitable[dict]]


@dataclass(frozen=True)
class Sentence:
    n: int
    section: str
    text: str


@dataclass(frozen=True)
class Move:
    page_id: str
    n: int
    section: str
    sentence: str
    target: str      # a page id, or ``new``
    reason: str


_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(\[])")
_LINK_ONLY = re.compile(r"^\s*(?:[-*]\s*)?(?:\[[^\]]*\]\([^)]*\)|\[\[[^\]]*\]\]|https?://\S+)\s*[.,;]?\s*$")


def sentences(body: str) -> list[Sentence]:
    """The page's prose as numbered sentences (reading order), each with the heading it sits under."""
    from api.services.claims import strip_claims_block

    out: list[Sentence] = []
    section = ""
    in_fence = False
    for raw in strip_claims_block(body or "").splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            continue
        if _LINK_ONLY.match(line) or line.startswith("|"):
            continue
        line = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line)
        for piece in _SPLIT.split(line):
            piece = piece.strip()
            if len(piece) >= MIN_CHARS and re.search(r"[A-Za-z]", piece):
                out.append(Sentence(len(out) + 1, section, piece))
    return out


def targets(memory_path, extra_ids=()) -> list[tuple[str, list[str]]]:
    """``[(page id, [same-named page ids])]`` to read: every page in a same-name group that is not a saved link, then
    the ids the caller names (with whatever pages share their title, often none)."""
    from api.services import bank_index, same_name

    memory_path = Path(memory_path)
    same_name.qualifiers(memory_path)   # warms the map
    groups = same_name._current(memory_path)[1]
    out: dict[str, list[str]] = {}
    for ids in groups.values():
        for pid in ids:
            f = bank_index.file(memory_path, "entities", f"{pid}.md")
            if f is None or str((f.frontmatter or {}).get("type") or "") == "media":
                continue
            out[pid] = [o for o in ids if o != pid]
    for pid in extra_ids:
        f = bank_index.file(memory_path, "entities", f"{pid}.md")
        if f is None:
            continue
        others = same_name.pages_titled(memory_path, (f.frontmatter or {}).get("name") or pid)
        out.setdefault(pid, [o for o in others if o != pid])
    return list(out.items())


def _describe(memory_path: Path, pid: str) -> dict:
    from api.services import bank_index, graph_builder, same_name

    f = bank_index.file(memory_path, "entities", f"{pid}.md")
    fm = (f.frontmatter if f is not None else {}) or {}
    try:
        summary = graph_builder.summarize(f.body()) if f is not None else ""
    except Exception:  # noqa: BLE001 — an unreadable body is described by its type alone
        summary = ""
    first = re.split(r"(?<=[.!?])\s", " ".join(str(summary or "").split()), maxsplit=1)[0][:300]
    return {"id": pid, "name": str(fm.get("name") or pid), "type": str(fm.get("type") or ""),
            "qualifier": same_name.qualifier(memory_path, pid), "says": first}


PROMPT = """You are checking one page of a personal knowledge base for sentences about a DIFFERENT thing that happens to
share its name.

The page: {page}
Other pages with exactly the same name (may be empty): {others}

Below are numbered sentences from the page. Most are about the page's own thing. List ONLY the sentences that are
clearly about a different thing with the same name (for example a program, a company or a person, on a page about a
software tool). For each, say where it belongs: the id of one of the other pages above, or "new" when it is about a
thing that has no page here. If a sentence could be about either, or you are not sure, leave it out.

Sentences:
{sentences}

Respond with JSON only:
{{"moves": [{{"n": <sentence number>, "target": "<page id or new>", "reason": "<one short sentence>"}}]}}
"""


def _prompt(page: dict, others: list[dict], chunk: list[Sentence]) -> str:
    def one(p: dict) -> str:
        return json.dumps({k: p[k] for k in ("id", "name", "type", "qualifier", "says") if p.get(k)},
                          ensure_ascii=False)

    return PROMPT.format(page=one(page), others="[" + ", ".join(one(o) for o in others) + "]",
                         sentences="\n".join(f"{s.n}. {s.text}" for s in chunk))


async def plan_page(memory_path, page_id: str, others: list[str], judge: Judge) -> list[Move]:
    """The moves one page's judge proposes — only listed sentence numbers, only a listed page id or ``new``."""
    from api.services import bank_index

    memory_path = Path(memory_path)
    f = bank_index.file(memory_path, "entities", f"{page_id}.md")
    if f is None:
        return []
    found = sentences(f.body())
    if not found:
        return []
    page = _describe(memory_path, page_id)
    described = [_describe(memory_path, o) for o in others]
    allowed = {o for o in others} | {NEW}
    by_n = {s.n: s for s in found}
    moves: list[Move] = []
    for start in range(0, len(found), CHUNK):
        chunk = found[start:start + CHUNK]
        answer = await judge(_prompt(page, described, chunk)) or {}
        for row in answer.get("moves") or []:
            if not isinstance(row, dict):
                continue
            try:
                n = int(row.get("n"))
            except (TypeError, ValueError):
                continue
            target = str(row.get("target") or "").strip()
            if n not in by_n or by_n[n] not in chunk or target not in allowed or target == page_id:
                continue
            s = by_n[n]
            moves.append(Move(page_id, n, s.section, s.text, target, " ".join(str(row.get("reason") or "").split())))
    return moves


async def plan(memory_path, judge: Judge, extra_ids=()) -> tuple[list[tuple[str, int]], list[Move]]:
    """Every target page's moves: ``([(page id, sentences read)], moves)``. Writes nothing."""
    from api.services import bank_index

    read: list[tuple[str, int]] = []
    moves: list[Move] = []
    for pid, others in targets(memory_path, extra_ids):
        f = bank_index.file(Path(memory_path), "entities", f"{pid}.md")
        read.append((pid, len(sentences(f.body())) if f is not None else 0))
        moves.extend(await plan_page(memory_path, pid, others, judge))
    return read, moves
