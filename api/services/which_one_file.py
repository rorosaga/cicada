"""A held mention is filed conversation by conversation (ruling 83, owner 2026-11-25/26).

The owner's case: two people share a first name and, in different conversations, the same nickname. In one the nickname stands
beside "my brother", in another beside a full name and "my teammate". The reader (`which_one_reader`) decides each conversation on
its own; until now it then refused to file anything unless every conversation named the same page, because a tap lifts the whole
held line. This module is what lets each conversation's words go to the page its own reading named, and nothing else.

**The unit is what a conversation said.** A held line holds, besides the claims, a summary, a description and key facts (each with
the G118 row that says which conversation it came from, `item_inputs`), dated history entries, links, open questions, aliases and
tags (these carry no conversation). A *unit* is a claim keyed to the mention, or a summary / description / key fact with its rows;
its conversations are the ones its evidence names. A unit goes to page P only when it has at least one conversation, every one of
them was read and named P (two conversations that disagree keep a shared fact held), and nothing else decides. Everything that
carries no conversation stays on the line, as does a claim about another page that has the mention as its object (`pending_store`
re-points it only for a whole-line answer). Nothing is guessed and nothing leaves the line except onto a page.

**The landing is the one a landing already uses** (`described_landing.land_page`): the claim as a claim of the page, its id,
predicate, object, source conversation, observer, trust and dates as they were held, its own evidence first and the sentence the
reader copied as one more span; a fact the page already says, or one that would clash with a single-valued belief, stays held. The
summary, description and key facts go through the writer a pick uses for the line's prose (`conflict_resolver.apply_changes`,
additive, never over a pinned passage). The name is never made an alias of either page. One settle record per page per run
(``inbox/settled/land-NNN.md``, rule :data:`RULE`, listed under what Sleep settled with each sentence), one Sleep commit of its own
paths.

**The undo** (:func:`undo`) puts that page's claims back on the line, takes the summary and key facts back to it, takes the
conversations' filed mark off, and tells the open question so: the reader never files those conversations again
(``which_one_undone``). A record that landed prose is undone only while the page is still exactly what the landing wrote (the prose
cannot be taken out of a page by id), otherwise nothing changes and it says so.

**The line's own bookkeeping** is one small writer here (:func:`edit_line`, through `pending_store.load`/`save` under its lock): a
conversation filed carries ``filed_to: <page>`` on its ``heard_in`` row, which is how the reader knows a conversation has nothing
left to be asked about. It never touches a held claim except through `pending_store.drop_released`.

**The question** follows the line. After a filing the question names only the conversations still open (``source_episode``,
``source_episodes``); when two or more are open and the reader could not decide them, it is about one at a time (``scope_episodes``:
the person's pick files that conversation's words only, :func:`after_tap`, and the next one is asked next). One conversation, or
every verdict agreeing, is the whole-line question as before.

Engine-free. The caller holds the bank (Sleep's window, or the person's answer under write admission).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from api.services import bank_index, described_landing as dl, evidence, markdown_parser, pending_store, which_one
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, strip_claims_block, write_claims
from api.services.id_utils import sanitize_id

RULE = "which_one_filed"
#: The rule of the question Sleep closes once nothing on the line can still be asked about (every conversation filed, nothing stranded).
ANSWERED = "which_one_answered"
REASON = "Read where you said it: what each conversation said went to the person that conversation meant."
UNDONE_KEY = "which_one_undone"
SCOPE_KEY = "scope_episodes"
FILED = "filed_to"
#: A conversation the person answered "someone else" about, for these pages, on its ``heard_in`` row (per conversation: the line's
#: own ``apart`` is per name and would take the candidate away from every other conversation).
APART = "apart_from"
PROSE_FIELDS = ("summary", "description", "key_facts")
#: The wire shape of ``scopeEpisodes`` on a served question; it rides the inbox ETag so every client takes one 200.
SHAPE = "scope1"


# --------------------------------------------------------------------------- what a unit says and where it was said


def claim_episodes(data: dict) -> set[str]:
    out = {str(e) for e in data.get("source_episodes") or [] if str(e)}
    for ev in data.get("evidence") or []:
        ep = str((ev or {}).get("episode") or "") if isinstance(ev, dict) else ""
        if ep:
            out.add(ep)
    return out


def row_episodes(row: dict) -> set[str]:
    return {str(r.get("episode")) for r in row.get("evidence") or [] if isinstance(r, dict) and r.get("episode")}


def filed(line: pending_store.PendingEntity) -> dict[str, str]:
    """``{conversation: page it was filed to}`` as the line's ``heard_in`` rows say."""
    return {str(r["episode"]): str(r[FILED]) for r in line.heard_in if isinstance(r, dict) and r.get("episode") and r.get(FILED)}


def said_not(line: pending_store.PendingEntity) -> dict[str, set[str]]:
    """``{conversation: pages}`` the person answered "someone else" about, for that conversation alone."""
    return {str(r["episode"]): {str(p) for p in r[APART] if str(p)} for r in line.heard_in
            if isinstance(r, dict) and r.get("episode") and r.get(APART)}


def split(line: pending_store.PendingEntity | None, target: str = "") -> bool:
    """Some conversation of the line was filed to a page other than ``target``, or answered "someone else": what the line holds that carries no conversation
    (history, links, questions, a description) is no longer one page's, and an answer lifts only what its conversations said."""
    return line is not None and (any(page != target for page in filed(line).values()) or bool(said_not(line)))


def counted(line: pending_store.PendingEntity | None) -> set[str]:
    """The conversations a line counts toward a page's birth: the ones nobody filed to a page already (a conversation filed is that
    page's, and a later mention of the name must not count it again)."""
    if line is None:
        return set()
    done = filed(line)
    return {e for e in line.episodes() if e not in done}


def _united(line: pending_store.PendingEntity) -> list[dict]:
    """The G118 rows of the line's summary, description and key facts that are still on it, one per (field, text), the evidence of
    every row of that text united (a fact two conversations stated has one row per conversation)."""
    order: list[tuple[str, str]] = []
    rows: dict[tuple[str, str], dict] = {}
    for row in line.item_inputs:
        field_name, text = str(row.get("field") or ""), str(row.get("text") or "").strip()
        if field_name not in PROSE_FIELDS or not text:
            continue
        here = (field_name == "key_facts" and text in [str(f).strip() for f in line.key_facts]) or \
               (field_name != "key_facts" and str(getattr(line, field_name) or "").strip() == text)
        if not here:
            continue
        key = (field_name, text)
        if key not in rows:
            rows[key] = {"field": field_name, "text": text, "evidence": []}
            order.append(key)
        for ev in row.get("evidence") or []:
            if isinstance(ev, dict) and ev not in rows[key]["evidence"]:
                rows[key]["evidence"].append(dict(ev))
    return [rows[k] for k in order if row_episodes(rows[k])]


def prose_rows(line: pending_store.PendingEntity) -> list[dict]:
    return _united(line)


def unfiled(line: pending_store.PendingEntity) -> list[str]:
    """The conversations the line still holds something of that nobody filed and nobody said "someone else" about: the line's own,
    then the ones its claims cite."""
    done, no = filed(line), said_not(line)
    out = [e for e in line.episodes() if e not in done and e not in no]
    for data in line.held_claims:
        for ep in sorted(claim_episodes(data)):
            if ep not in out and ep not in done and ep not in no:
                out.append(ep)
    return out


def stranded(line: pending_store.PendingEntity) -> list[str]:
    """The conversations of held claims about the mention that two or more conversations cite, every one filed, to two or more
    different pages: nothing lands such a claim (it is one fact, said where two people were meant), so it is asked, about those
    conversations, unless the person already said "someone else" for one of them."""
    slug, done, no = sanitize_id(line.name), filed(line), said_not(line)
    found: set[str] = set()
    for data in line.held_claims:
        eps = claim_episodes(data)
        if str(data.get("subject") or "") != slug or len(eps) < 2 or not eps <= set(done) or len({done[e] for e in eps}) < 2 \
                or eps & set(no):
            continue
        found |= eps
    order = line.episodes()
    return sorted(found, key=lambda e: (order.index(e) if e in order else len(order), e))


def asking(line: pending_store.PendingEntity | None) -> tuple[list[str], list[str]]:
    """``(the conversations the question is about, the conversations a pick files)``: the unfiled ones (a pick files the first alone
    when there are two or more, one conversation is the whole-line question), else the stranded claims' (a pick lands them)."""
    if line is None:
        return [], []
    eps = unfiled(line)
    if eps:
        return eps, ([eps[0]] if len(eps) > 1 else [])
    strand = stranded(line)
    return (strand, list(strand)) if strand else ([], [])


def open_episodes(line: pending_store.PendingEntity) -> list[str]:
    return asking(line)[0]


def _page_of(eps: set[str], verdict: dict[str, str]) -> str | None:
    pages = {verdict.get(e) for e in eps}
    return next(iter(pages)) if eps and len(pages) == 1 and None not in pages else None


def _parts_of(eps: set[str], verdict: dict[str, str]) -> dict[str, set[str]] | None:
    """``{page: its conversations}`` of ``eps`` when every one of them is in ``verdict``, else None (something is undecided)."""
    if not eps or not eps <= set(verdict):
        return None
    out: dict[str, set[str]] = {}
    for e in sorted(eps):
        out.setdefault(verdict[e], set()).add(e)
    return out


def _only(row: dict, eps: set[str]) -> dict:
    return {**row, "evidence": [dict(e) for e in row.get("evidence") or [] if isinstance(e, dict) and e.get("episode") in eps]}


@dataclass
class Plan:
    """What goes to ``page``. ``episodes``: the conversations whose words land there (they credit the page and nothing else
    does). ``filed``: the conversations decided for the page this time, marked filed on the line."""
    page: str
    episodes: list[str]
    claims: list[dict] = field(default_factory=list)
    prose: list[dict] = field(default_factory=list)
    filed: list[str] = field(default_factory=list)


def plan(line: pending_store.PendingEntity, verdict: dict[str, str], decided: set[str] | None = None) -> dict[str, Plan]:
    """``{page: what goes there}``. ``verdict``: ``{conversation: page}`` of every conversation whose page is known (the ones decided
    now and the ones filed before); ``decided``: the ones decided now (default all). A claim about the mention goes to page P only
    when it cites a conversation decided now and every conversation it cites is known and names P. A fact (key fact, summary,
    description) is split by conversation: each page gets it with its own conversations' evidence, and only when every page it
    names lands facts in this plan (else it stays whole on the line). Nothing that carries no conversation moves."""
    slug = sanitize_id(line.name)
    decided = set(verdict if decided is None else decided) & set(verdict)
    out: dict[str, Plan] = {}
    for e in verdict:
        if e in decided:
            out.setdefault(verdict[e], Plan(verdict[e], [], filed=[])).filed.append(e)
    for data in line.held_claims:
        if str(data.get("subject") or "") != slug:   # a claim about another page that has the mention as its object stays held
            continue
        eps = claim_episodes(data)
        page = _page_of(eps, verdict)
        if page and page in out and eps & decided:
            out[page].claims.append(data)
            out[page].episodes += [e for e in sorted(eps) if e not in out[page].episodes]
    ok = {p for p, v in out.items() if v.claims}
    for row in prose_rows(line):
        parts = _parts_of(row_episodes(row), verdict)
        if parts and set(parts) <= ok and set().union(*parts.values()) & decided:
            for page, eps in parts.items():
                out[page].prose.append(_only(row, eps))
                out[page].episodes += [e for e in sorted(eps) if e not in out[page].episodes]
    return {p: v for p, v in out.items() if v.claims}   # prose goes only with a landing of facts


# --------------------------------------------------------------------------- the line's own bookkeeping


def edit_line(memory_path: Path, name: str, change: Callable[[pending_store.PendingEntity], bool]) -> bool:
    """One read-modify-write of the line named ``name`` under the store's lock; ``change`` returns whether it changed."""
    key = (name or "").strip().lower()
    with pending_store._LOCK:
        entries = pending_store.load(memory_path)
        hit = False
        for line in entries:
            if line.name.lower() == key and change(line):
                hit = True
        if hit:
            pending_store.save(memory_path, entries)
        return hit


def _mark(line: pending_store.PendingEntity, episodes: list[str], page: str | None, *, taking_back: str | None = None) -> bool:
    """Mark ``episodes`` filed to ``page`` (a conversation already filed to a page keeps that page: it is never moved), or, with
    ``taking_back``, take the mark off the ones filed to that page."""
    changed = False
    rows = {str(r["episode"]): r for r in line.heard_in if isinstance(r, dict) and r.get("episode")}
    for ep in episodes:
        row = rows.get(ep)
        if page is None:
            if row is not None and FILED in row and (taking_back is None or row[FILED] == taking_back):
                row.pop(FILED)
                changed = True
            continue
        if row is None:
            row = {"episode": ep}
            line.heard_in.append(row)
            rows[ep] = row
        if FILED not in row:
            row[FILED] = page
            changed = True
    return changed


def _take_prose(line: pending_store.PendingEntity, rows: list[dict]) -> bool:
    """What landed leaves the line, conversation by conversation: the evidence of each landed row goes, and the text itself only
    once no conversation's evidence is left for it (a fact two conversations stated stays for the one not landed yet)."""
    changed = False
    for row in rows:
        field_name, text = str(row.get("field")), str(row.get("text") or "").strip()
        eps = row_episodes(row)
        inputs, left = [], False
        for r in line.item_inputs:
            if (r.get("field"), str(r.get("text") or "").strip()) != (field_name, text):
                inputs.append(r)
                continue
            evidence_rows = [e for e in r.get("evidence") or [] if not (isinstance(e, dict) and e.get("episode") in eps)]
            if len(evidence_rows) != len(r.get("evidence") or []):
                changed = True
            if evidence_rows:
                left = True
                inputs.append({**r, "evidence": evidence_rows})
        line.item_inputs = inputs
        if left:
            continue
        if field_name == "key_facts":
            kept = [f for f in line.key_facts if str(f).strip() != text]
            changed |= len(kept) != len(line.key_facts)
            line.key_facts = kept
        elif str(getattr(line, field_name, "") or "").strip() == text:
            setattr(line, field_name, "")
            changed = True
    return changed


def _give_prose(line: pending_store.PendingEntity, rows: list[dict]) -> bool:
    """:func:`_take_prose` undone: the text back, its evidence back on the row of that text."""
    changed = False
    for row in rows:
        field_name, text = str(row.get("field")), str(row.get("text") or "").strip()
        if field_name == "key_facts":
            if text not in [str(f).strip() for f in line.key_facts]:
                line.key_facts.append(text)
                changed = True
        elif not str(getattr(line, field_name, "") or "").strip():
            setattr(line, field_name, text)
            changed = True
        mine = next((r for r in line.item_inputs if (r.get("field"), str(r.get("text") or "").strip()) == (field_name, text)), None)
        if mine is None:
            line.item_inputs.append(dict(row))
            changed = True
            continue
        have = [e for e in mine.get("evidence") or []]
        add = [dict(e) for e in row.get("evidence") or [] if e not in have]
        if add:
            mine["evidence"] = [*have, *add]
            changed = True
    return changed


def empty(line: pending_store.PendingEntity | None) -> bool:
    """Nothing left to keep: no claim, summary, description, fact, history entry, link or question (aliases and tags alone are not)."""
    return line is None or not (line.held_claims or line.summary or line.description or line.key_facts or line.history_entries
                                or line.links or line.open_questions)


def remove_prose(memory_path: Path, name: str, rows: list[dict]) -> bool:
    return edit_line(memory_path, name, lambda line: _take_prose(line, rows))


def mark_filed(memory_path: Path, name: str, episodes: list[str], page: str | None, *, taking_back: str | None = None) -> bool:
    return edit_line(memory_path, name, lambda line: _mark(line, episodes, page, taking_back=taking_back))


def _say_not(line: pending_store.PendingEntity, episodes: list[str], pages: list[str]) -> bool:
    changed = False
    rows = {str(r["episode"]): r for r in line.heard_in if isinstance(r, dict) and r.get("episode")}
    for ep in episodes:
        row = rows.get(ep)
        if row is None:
            row = {"episode": ep}
            line.heard_in.append(row)
            rows[ep] = row
        merged = sorted({*[str(p) for p in row.get(APART) or []], *pages})
        if merged != row.get(APART):
            row[APART] = merged
            changed = True
    return changed


def keep_apart(memory_path: Path, name: str, pages: list[str], episodes: list[str]) -> bool:
    """The person said the mention, in ``episodes`` only, is none of ``pages``: recorded on those conversations' own rows (the
    candidate stays a candidate for every other conversation). False when no line holds the name."""
    return edit_line(memory_path, name, lambda line: _say_not(line, episodes, [str(p) for p in pages if str(p)]))


def scope_for(fm: dict, line: pending_store.PendingEntity | None, target: str, covered: set[str] | None = None) -> list[str] | None:
    """The conversations an answer that puts the mention on ``target`` files, or ``[]`` for the whole line (as before ruling 83's
    per-conversation filing), or ``None``: refused, nothing may be written.

    The whole line when the question is not about one conversation and no conversation of the line was filed to another page.
    Otherwise the question's own scope (``scope_episodes``), or, on a line already filed in part, the conversations the question
    names. ``covered`` is set for Sleep's own settle (the conversations its evidence is from): it files only those, and only when
    that leaves nothing of the question open (a settle that would leave the question standing is refused: Sleep's settle always
    closes the question, `inbox_tend.apply`), else it is left for the person."""
    scoped = scope_of(fm)
    if not scoped and not split(line, target):
        return []
    every = which_one.episodes_of(fm)
    if covered is None:
        return scoped or every
    mine = [e for e in every if e in covered]
    if line is None or not mine or (set(unfiled(line)) | set(stranded(line))) - set(mine):
        return None
    return mine if split(line, target) else []


def covered_by(actor) -> set[str]:
    """The conversations the evidence of a Sleep settle is from (its record's quote and spans); empty for a person's own answer."""
    record = getattr(actor, "record", None)
    rec = (record[1].get("settled") if record and isinstance(record[1], dict) else None) or {}
    out = {str(s.get("episode")) for s in rec.get("evidence_spans") or [] if isinstance(s, dict) and s.get("episode")}
    ev = rec.get("evidence")
    if isinstance(ev, dict) and ev.get("episode"):
        out.add(str(ev["episode"]))
    return out


# --------------------------------------------------------------------------- the question


def scope_of(fm: dict) -> list[str]:
    return [str(e) for e in (fm or {}).get(SCOPE_KEY) or [] if str(e).strip()]


def undone_of(fm: dict) -> set[str]:
    return {str(e) for e in (fm or {}).get(UNDONE_KEY) or [] if str(e).strip()}


def narrowed(fm: dict, eps: list[str], scope: list[str], *, undone: set[str] | None = None) -> dict:
    """The question's frontmatter about the conversations in ``eps`` only (what it names), a pick filing ``scope`` (none: the whole
    line, as when one conversation is open)."""
    out = dict(fm)
    if eps:
        out["source_episode"], out["source_episodes"] = eps[0], list(eps)
    out.pop(SCOPE_KEY, None)
    if scope:
        out[SCOPE_KEY] = list(scope)
    if undone is not None:
        if undone:
            out[UNDONE_KEY] = sorted(undone)
        else:
            out.pop(UNDONE_KEY, None)
    return out


def rewrite_question(path: Path, line: pending_store.PendingEntity | None, *, undone: set[str] | None = None,
                     fallback: list[str] | None = None) -> bool:
    """Write the question about what the line still holds to be asked (:func:`asking`; ``fallback`` when the line is gone).
    True when its file changed."""
    eps, scope = asking(line)
    if not eps and fallback:
        eps, scope = list(fallback), []
    parsed = markdown_parser.parse(path)
    fm = narrowed(dict(parsed.frontmatter), eps, scope, undone=undone)
    if fm == dict(parsed.frontmatter):
        return False
    markdown_parser.write(path, fm, parsed.body)
    return True


def after_tap(memory_path: Path, path: Path, mention: str, scope: list[str], page: str) -> bool:
    """The person's pick of ``page`` for ``scope`` was just landed (`inbox_service._release_answered`, scoped): mark those
    conversations filed and, while something of the line can still be asked (other conversations, or a claim stranded between two
    pages), keep the question about that. False when nothing can (the caller closes the question as every pick does)."""
    mark_filed(memory_path, mention, scope, page)
    line = pending_store.held_line(memory_path, mention)
    if not asking(line)[0]:
        return False
    rewrite_question(path, line)
    return True


def apart_scoped(memory_path: Path, path: Path, fm: dict, pages: list[str]) -> list[str] | None:
    """"Someone else" (or a dismissal) on a question about one conversation: it is the answer for that conversation only (its row
    on the line says so), and the question moves on to what is still open, or goes when nothing is. ``None`` when the question is
    not scoped (the caller keeps the mention apart on the whole line, as before)."""
    mention = str(fm.get("entity_name") or fm.get("entity_mention") or "").strip()
    if str(fm.get("detected") or "") != which_one.DETECTED:
        return None
    line = pending_store.held_line(memory_path, mention) if mention else None
    scope = scope_of(fm) or (which_one.episodes_of(fm) if split(line) else [])
    if not scope or line is None:
        return None
    keep_apart(memory_path, mention, pages, scope)
    line = pending_store.held_line(memory_path, mention)
    if asking(line)[0]:
        rewrite_question(path, line)
    else:
        path.unlink(missing_ok=True)
    return [f"{pending_store.PENDING_STORE_FILE}: updated (trigger: inbox/merge_suggestion/rejected)"]


def land_prose(memory_path: Path, mention: str, verdict: dict[str, str]) -> list[str]:
    """The person's pick (`inbox_service._land_held_prose`, scoped): every summary, description and key fact whose conversations
    are all known (``verdict``: the ones filed before and the ones this answer files) goes to the page each conversation named, with
    that conversation's evidence only; what landed leaves the line. Pages written, as memory-relative paths."""
    line = pending_store.held_line(memory_path, mention)
    if line is None:
        return []
    by_page: dict[str, list[dict]] = {}
    for row in prose_rows(line):
        parts = _parts_of(row_episodes(row), verdict)
        if parts and all((Path(memory_path) / "entities" / f"{p}.md").is_file() for p in parts):
            for page, eps in parts.items():
                by_page.setdefault(page, []).append(_only(row, eps))
    written, landed = [], []
    for page, rows in by_page.items():
        eps = sorted({e for r in rows for e in row_episodes(r)})
        if _apply_prose(memory_path, page, rows, eps):
            written.append(f"entities/{page}.md")
        landed += rows
    if landed:
        remove_prose(memory_path, mention, landed)
    return written


# --------------------------------------------------------------------------- the landing


def _apply_prose(memory_path: Path, page_id: str, rows: list[dict], episodes: list[str]) -> bool:
    """The summary, description and key facts of ``rows`` onto the page by the writer a pick uses for a line's prose. True when
    the page changed."""
    from api.services import conflict_resolver, section_provenance

    facts = [str(r.get("text")).strip() for r in rows]
    if not facts:
        return False
    path = Path(memory_path) / "entities" / f"{page_id}.md"
    entity = {"summary": "", "description": "", "key_facts": facts, "history_entries": [], "links": [], "open_questions": [],
              "aliases": [], "tags": [], section_provenance.INPUTS: [dict(r) for r in rows]}
    before = path.read_bytes()
    conflict_resolver.apply_changes([{"id": page_id, "action": "update", "entity": entity, "source_episodes": list(episodes),
                                      "untimed": True, "trigger": "inbox/held-prose"}], Path(memory_path))
    return path.read_bytes() != before


def _hash_of(memory_path: Path, episode: str, text: str, start: int, end: int) -> str:
    ev = evidence.verify(Path(memory_path), episode, text, window=(start, end))
    return ev.hash if ev is not None and getattr(ev, "hash", None) else ""


def land(memory_path: Path, item_path: Path, page_id: str, part: Plan, reads: dict, *, by: str, engine: str | None,
         mention: str, today: str | None = None) -> dl.Landed | None:
    """File ``part`` on ``page_id``: its claims by `described_landing.land_page`, its prose by the writer a pick uses, the page
    credited with the conversations whose words landed on it (``part.episodes``) and no other, the line edited, the question
    narrowed (or, when nothing on the line can be asked about any more, closed in this same landing), one record. ``reads``:
    ``{conversation: ConvRead}`` (the located sentence, its kind). ``None`` when no claim lands (everything is already there or
    would clash: nothing is written). The caller commits ``paths`` and puts every path back when anything raises."""
    memory_path = Path(memory_path)
    line = pending_store.held_line(memory_path, mention)
    if line is None:
        return None
    items: list[tuple[dl.Item, dl.Pick]] = []
    for data in part.claims:
        eps = sorted(claim_episodes(data))
        r = reads[next(e for e in eps if e in reads)]
        claim = Claim.from_dict(data)
        pick = dl.Pick(page=page_id, scope="", start=r.start, end=r.end, turn=r.kind,
                       hash=_hash_of(memory_path, r.episode, r.sentence, r.start, r.end))
        items.append((dl.Item(line.name, claim, r.episode, r.start, r.end, pick.hash, r.kind, -1, rule=RULE), pick))
    extra = {"item_id": item_path.stem, "mention": line.name, "which_page": page_id, "filed_episodes": list(part.filed),
             "prose": [dict(r) for r in part.prose]}
    done = dl.land_page(memory_path, page_id, items, by=by, engine=engine, today=today, rule=RULE, reason=REASON, extra=extra,
                        close_empty=False)
    if done is None or not done.record_id:
        return None
    page_rel = f"entities/{page_id}.md"
    page_path = memory_path / page_rel
    from api.services import claim_pipeline

    parsed = markdown_parser.parse(page_path)
    if claim_pipeline._credit_episodes(parsed.frontmatter, part.episodes):   # the conversations whose words landed here, no others
        markdown_parser.write(page_path, parsed.frontmatter, parsed.body)
    # The prose the landed claims' conversations said (every conversation of a row is one this page was named for).
    if part.prose and _apply_prose(memory_path, page_id, part.prose, part.episodes) and page_rel not in done.paths:
        done.paths.append(page_rel)
    remove_prose(memory_path, line.name, part.prose)
    mark_filed(memory_path, line.name, part.filed, page_id)
    left = pending_store.held_line(memory_path, line.name)
    closed: list[dict] = []
    if left is not None and empty(left):
        closed.append(left.to_dict())
        pending_store.release(memory_path, [line.name])
    rec_path = memory_path / "inbox" / dl.SETTLED_DIR / f"{done.record_id}.md"
    parsed = markdown_parser.parse(rec_path)
    settled = dict(parsed.frontmatter.get("settled") or {})
    settled["closed_lines"] = closed
    markdown_parser.write(rec_path, {**parsed.frontmatter, "settled": settled}, parsed.body)
    if item_path.is_file():
        after = pending_store.held_line(memory_path, line.name)
        if asking(after)[0]:
            if rewrite_question(item_path, after):
                done.paths.append(item_path.relative_to(memory_path).as_posix())
                done.lines.append(f"{done.paths[-1]}: updated (source: {done.record_id}, trigger: sleep/which-one-filed)")
        else:
            # Nothing on the line can be asked about any more (the last conversation was filed, or the line itself is gone): the
            # question is answered, in this same commit, and undoable with the filing (`undo` reopens it).
            paths, lines = _retire(memory_path, item_path, by)
            done.paths += paths
            done.lines += lines
    bank_index.invalidate(memory_path)
    return done


def _retire(memory_path: Path, item_path: Path, by: str) -> tuple[list[str], list[str]]:
    """The question moved to its settled shelf as Sleep's closed question (rule :data:`ANSWERED`), exactly as `inbox_tend._retire`
    leaves it, so the settled list and the question's own undo read it. ``([], [])`` when a record of that number is already there."""
    from api.services import inbox_tend

    rec_rel = f"inbox/{dl.SETTLED_DIR}/{item_path.stem}.md"
    rec_path = Path(memory_path) / rec_rel
    if rec_path.exists():
        return [], []
    parsed = markdown_parser.parse(item_path)
    fm = dict(parsed.frontmatter)
    d = inbox_tend.Decision(item_path.stem, "merge_suggestion", ANSWERED, None,
                            answer="Each conversation was filed under the one it meant", model=by or None, reason=REASON)
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(rec_path, {**fm, "settled": inbox_tend._record(fm, d, by or "cicada", None)}, parsed.body)
    item_path.unlink()
    rel = item_path.relative_to(memory_path).as_posix()
    trigger = f"{inbox_tend.TRIGGER}:{ANSWERED}"
    return [rel, rec_rel], [f"{rel}: settled (source: {item_path.stem}, trigger: {trigger})",
                            f"{rec_rel}: created (source: {item_path.stem}, trigger: {trigger})"]


def is_record(memory_path: Path, record_id: str) -> bool:
    if not dl.is_record_id(record_id):
        return False
    path = Path(memory_path) / "inbox" / dl.SETTLED_DIR / f"{record_id}.md"
    try:
        rec = markdown_parser.parse(path).frontmatter.get("settled") if path.is_file() else None
    except Exception:  # noqa: BLE001 - an unreadable record is no record
        return False
    return isinstance(rec, dict) and rec.get("rule") == RULE


def undo(memory_path: Path, record_id: str) -> tuple[list[str], list[str], dict]:
    """Take one filing back: its claims leave the page (each only while it is as the landing wrote it) and go back to the line, its
    summary and key facts go back too, the conversations are no longer marked filed, and the open question is told the reader must
    not file them again. :class:`described_landing.NotLandable` and nothing written when the page changed under a claim, or under
    prose the landing added; a held count that comes up short puts every path back as it was."""
    from api.services import claims_ledger, inbox_tend

    memory_path = Path(memory_path)
    if not is_record(memory_path, record_id):
        raise dl.NotLandable("No such settled landing.")
    record_rel = f"inbox/{dl.SETTLED_DIR}/{record_id}.md"
    rec = markdown_parser.parse(memory_path / record_rel).frontmatter["settled"]
    page_id = str(rec.get("entity_id") or "")
    page_rel = f"entities/{page_id}.md"
    path = memory_path / page_rel
    landed = {str(d.get("id")): d for d in rec.get("landed") or [] if isinstance(d, dict)}
    held = [Claim.from_dict(d) for d in rec.get("held") or [] if isinstance(d, dict)]
    closed = [d for d in rec.get("closed_lines") or [] if isinstance(d, dict) and d.get("name")]
    prose = [r for r in rec.get("prose") or [] if isinstance(r, dict)]
    name = str(rec.get("mention") or "")
    episodes = [str(e) for e in rec.get("filed_episodes") or []]
    ledger_rel = claims_ledger.rel_for(page_rel) or ""
    kept = parsed = new_prose = fm_after = None
    if path.is_file():
        parsed = markdown_parser.parse(path)
        try:
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            raise dl.NotLandable("The page's claims could not be read; nothing was changed.") from exc
        for c in claims:
            if c.id in landed and not dl.as_written(c, landed[c.id]):
                raise dl.NotLandable("A fact this settle wrote was changed since; nothing was changed.")
        kept = [c for c in claims if c.id not in landed]
        new_prose = strip_claims_block(parsed.body)
        fm_after = dict(parsed.frontmatter)
        # What the landing wrote besides claims (the credited conversations, the section's provenance, the prose) is taken back the
        # way the claims are: only while it is still what the landing wrote. Sleep's own bookkeeping since (a claim's confidence and
        # decay watermark, a version, a day) is not a change to it; the page's words and a changed field are.
        sha = inbox_tend._commit_of(memory_path, record_rel)
        before_page = _split_bytes(inbox_tend._git_bytes(memory_path, f"{sha}^:{page_rel}")) if sha else None
        after_page = _split_bytes(inbox_tend._git_bytes(memory_path, f"{sha}:{page_rel}")) if sha else None
        if prose and (before_page is None or after_page is None):
            raise dl.NotLandable("The settle's commit could not be found; nothing was changed.")
        if before_page is not None and after_page is not None:
            if prose:
                if strip_claims_block(after_page[1]) != new_prose:
                    raise dl.NotLandable("The page's words changed since this was filed; nothing was changed.")
                new_prose = strip_claims_block(before_page[1])
            for key in set(after_page[0]) | set(before_page[0]):
                if after_page[0].get(key) != before_page[0].get(key) and fm_after.get(key) == after_page[0].get(key):
                    if key in before_page[0]:
                        fm_after[key] = before_page[0][key]
                    else:
                        fm_after.pop(key, None)
    names = {str(d["name"]).lower() for d in closed}
    mine = [c for c in held if c.subject == sanitize_id(name)]
    skeleton = None
    if mine and name.lower() not in names and pending_store.held_line(memory_path, name) is None:
        # The line left when a later filing emptied it: this filing's claims come back to a line of their own.
        marks = {e: "" for e in episodes}
        for other in sorted((memory_path / "inbox" / dl.SETTLED_DIR).glob(f"{dl.RECORD_PREFIX}*.md")):
            if other.stem == record_id:
                continue
            try:
                theirs = markdown_parser.parse(other).frontmatter.get("settled")
            except Exception:  # noqa: BLE001 - an unreadable record marks nothing
                continue
            if isinstance(theirs, dict) and theirs.get("rule") == RULE and str(theirs.get("mention") or "").lower() == name.lower():
                marks.update({str(e): str(theirs.get("entity_id") or "") for e in theirs.get("filed_episodes") or []})   # still filed
        skeleton = pending_store.PendingEntity(name=name, type="person", description="", source_episode=episodes[0] if episodes else "",
                                               confidence=0.7, tags=[], history_entries=[], held_claims=[],
                                               heard_in=[{"episode": e, **({FILED: page} if page else {})} for e, page in marks.items()])
    else:
        dl._places(memory_path, [name], held, names)
    item_id = str(rec.get("item_id") or "")
    question = next(iter(_open_question(memory_path, item_id, name)), None)
    # The question was closed when its last conversation was filed (`which_one_reader._close_answered`): taking a filing back asks it again.
    retired = memory_path / "inbox" / dl.SETTLED_DIR / f"{item_id}.md"
    reopen = None
    if question is None and item_id and retired.is_file() and not (memory_path / "inbox" / f"{item_id}.md").exists():
        shelf = markdown_parser.parse(retired)
        if isinstance(shelf.frontmatter.get("settled"), dict) and shelf.frontmatter["settled"].get("rule") == ANSWERED:
            reopen = ({k: v for k, v in shelf.frontmatter.items() if k != "settled"}, shelf.body)
            question = memory_path / "inbox" / f"{item_id}.md"
    snapshot = {rel: dl._bytes(memory_path / rel) for rel in
                (page_rel, ledger_rel, pending_store.PENDING_STORE_FILE, question.relative_to(memory_path).as_posix() if question else "",
                 retired.relative_to(memory_path).as_posix() if reopen else "")
                if rel}
    paths: list[str] = []
    lines: list[str] = []
    try:
        if reopen is not None and question is not None:
            markdown_parser.write(question, reopen[0], reopen[1])
            retired.unlink()
            for rel in (question.relative_to(memory_path).as_posix(), retired.relative_to(memory_path).as_posix()):
                paths.append(rel)
            lines.append(f"inbox/{item_id}.md: reopened (source: {record_id}, trigger: sleep/which-one-filed/undone)")
        for d in closed:
            pending_store.upsert(memory_path, pending_store.PendingEntity.from_dict(d))
        if skeleton is not None:
            pending_store.upsert(memory_path, skeleton)
        if mine:
            pending_store.hold(memory_path, {sanitize_id(name): mine})
        line = pending_store.held_line(memory_path, name)
        if mine and (line is None or not {c.id for c in mine} <= {d.get("id") for d in line.held_claims}):
            raise dl._gone()
        if prose:
            edit_line(memory_path, name, lambda ln: _give_prose(ln, prose))
        mark_filed(memory_path, name, episodes, None, taking_back=page_id)
        if parsed is not None:
            body = write_claims(new_prose or "", kept or [])
            if fm_after != dict(parsed.frontmatter) or body != parsed.body:
                markdown_parser.write(path, fm_after, body)
                paths += [rel for rel in (page_rel, ledger_rel) if rel and ((memory_path / rel).exists() or snapshot.get(rel) is not None)]
                lines.append(f"{page_rel}: updated (source: {record_id}, trigger: sleep/which-one-filed/undone)")
        if question is None:
            # No question is open and none can be reopened (the person answered the last one themselves): what the filing's
            # conversations hold is open again, so a question about it is raised, as Sleep raises any (`which_one.raise_question`).
            after = pending_store.held_line(memory_path, name)
            open_now = asking(after)[0] or episodes
            raised = which_one.raise_question(memory_path, name, open_now[0], which_one.candidates_for(memory_path, name, [page_id]),
                                              today=date.today()) if open_now else None
            if raised:
                question = memory_path / raised
                snapshot[raised] = None
                paths.append(raised)
                lines.append(f"{raised}: created (source: {record_id}, trigger: sleep/which-one-filed/undone)")
        if question is not None:
            after = pending_store.held_line(memory_path, name)
            qfm = markdown_parser.parse(question).frontmatter
            if rewrite_question(question, after, undone=undone_of(qfm) | set(episodes), fallback=episodes):
                rel = question.relative_to(memory_path).as_posix()
                if rel not in paths:
                    paths.append(rel)
                lines.append(f"{rel}: updated (source: {record_id}, trigger: sleep/which-one-filed/undone)")
        (memory_path / record_rel).unlink()
    except BaseException:
        dl._restore(memory_path, snapshot)
        raise
    paths.append(pending_store.PENDING_STORE_FILE)
    lines.append(f"{pending_store.PENDING_STORE_FILE}: updated (source: {record_id}, trigger: sleep/which-one-filed/undone)")
    paths.append(record_rel)
    lines.append(f"{record_rel}: removed (source: {record_id}, trigger: sleep/which-one-filed/undone)")
    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))
    return paths, lines, rec


def _split_bytes(data: bytes | None) -> tuple[dict, str] | None:
    """``(frontmatter, body)`` of a page as git holds it, or None."""
    if data is None:
        return None
    parts = markdown_parser.split_frontmatter(data.decode("utf-8", "replace"))
    if parts is None:
        return None
    try:
        fm = markdown_parser.load_yaml(parts[0].strip()) or {}
    except Exception:  # noqa: BLE001 - a page git holds that cannot be read is no basis for an undo
        return None
    return (fm, parts[1].strip()) if isinstance(fm, dict) else None


def _open_question(memory_path: Path, item_id: str, mention: str) -> list[Path]:
    """The question the filing was about, if it is still open: its own file, else the open which-one question of the mention."""
    own = Path(memory_path) / "inbox" / f"{item_id}.md"
    if item_id and own.is_file():
        return [own]
    found = which_one.open_question(memory_path, mention)
    return [found] if found is not None else []
