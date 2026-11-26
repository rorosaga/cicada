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
from pathlib import Path
from typing import Callable

from api.services import bank_index, described_landing as dl, evidence, markdown_parser, pending_store
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims
from api.services.id_utils import sanitize_id

RULE = "which_one_filed"
#: The rule of the question Sleep closes once every conversation of it was filed and only leftovers with no conversation remain.
ANSWERED = "which_one_answered"
REASON = "Read where you said it: what each conversation said went to the person that conversation meant."
UNDONE_KEY = "which_one_undone"
SCOPE_KEY = "scope_episodes"
FILED = "filed_to"
PROSE_FIELDS = ("summary", "description", "key_facts")


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


def prose_rows(line: pending_store.PendingEntity) -> list[dict]:
    """The G118 rows of the line's summary, description and key facts that are still on it, one per (field, text)."""
    out, seen = [], set()
    for row in line.item_inputs:
        field_name, text = str(row.get("field") or ""), str(row.get("text") or "").strip()
        if field_name not in PROSE_FIELDS or not text or (field_name, text) in seen:
            continue
        here = (field_name == "key_facts" and text in [str(f).strip() for f in line.key_facts]) or \
               (field_name != "key_facts" and str(getattr(line, field_name) or "").strip() == text)
        if here and row_episodes(row):
            seen.add((field_name, text))
            out.append(row)
    return out


def open_episodes(line: pending_store.PendingEntity) -> list[str]:
    """The conversations the line still holds something of that nobody filed: the line's own, then the ones its claims cite."""
    done = filed(line)
    out = [e for e in line.episodes() if e not in done]
    for data in line.held_claims:
        for ep in sorted(claim_episodes(data)):
            if ep not in out and ep not in done:
                out.append(ep)
    return out


def _page_of(eps: set[str], verdict: dict[str, str]) -> str | None:
    pages = {verdict.get(e) for e in eps}
    return next(iter(pages)) if eps and len(pages) == 1 and None not in pages else None


@dataclass
class Plan:
    page: str
    episodes: list[str]
    claims: list[dict] = field(default_factory=list)
    prose: list[dict] = field(default_factory=list)


def plan(line: pending_store.PendingEntity, verdict: dict[str, str]) -> dict[str, Plan]:
    """``{page: what goes there}`` from ``verdict`` (``{conversation: page}`` of the conversations that were read and decided)."""
    slug = sanitize_id(line.name)
    out: dict[str, Plan] = {}
    for page in dict.fromkeys(verdict.values()):
        out[page] = Plan(page, [e for e, p in verdict.items() if p == page])
    for data in line.held_claims:
        if str(data.get("subject") or "") != slug:   # a claim about another page that has the mention as its object stays held
            continue
        page = _page_of(claim_episodes(data), verdict)
        if page:
            out[page].claims.append(data)
    for row in prose_rows(line):
        page = _page_of(row_episodes(row), verdict)
        if page:
            out[page].prose.append(row)
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


def _mark(line: pending_store.PendingEntity, episodes: list[str], page: str | None) -> bool:
    changed = False
    rows = {str(r["episode"]): r for r in line.heard_in if isinstance(r, dict) and r.get("episode")}
    for ep in episodes:
        row = rows.get(ep)
        if row is None:
            if page is None:
                continue
            row = {"episode": ep}
            line.heard_in.append(row)
        if page is None and FILED in row:
            row.pop(FILED)
            changed = True
        elif page is not None and row.get(FILED) != page:
            row[FILED] = page
            changed = True
    return changed


def _take_prose(line: pending_store.PendingEntity, rows: list[dict]) -> bool:
    changed = False
    for row in rows:
        field_name, text = str(row.get("field")), str(row.get("text") or "").strip()
        if field_name == "key_facts":
            kept = [f for f in line.key_facts if str(f).strip() != text]
            changed |= len(kept) != len(line.key_facts)
            line.key_facts = kept
        elif str(getattr(line, field_name, "") or "").strip() == text:
            setattr(line, field_name, "")
            changed = True
        line.item_inputs = [r for r in line.item_inputs
                            if (r.get("field"), str(r.get("text") or "").strip()) != (field_name, text)]
    return changed


def _give_prose(line: pending_store.PendingEntity, rows: list[dict]) -> bool:
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
        if row not in line.item_inputs:
            line.item_inputs.append(dict(row))
    return changed


def empty(line: pending_store.PendingEntity | None) -> bool:
    """Nothing left to keep: no claim, summary, description, fact, history entry, link or question (aliases and tags alone are not)."""
    return line is None or not (line.held_claims or line.summary or line.description or line.key_facts or line.history_entries
                                or line.links or line.open_questions)


def remove_prose(memory_path: Path, name: str, rows: list[dict]) -> bool:
    return edit_line(memory_path, name, lambda line: _take_prose(line, rows))


def mark_filed(memory_path: Path, name: str, episodes: list[str], page: str | None) -> bool:
    return edit_line(memory_path, name, lambda line: _mark(line, episodes, page))


# --------------------------------------------------------------------------- the question


def scope_of(fm: dict) -> list[str]:
    return [str(e) for e in (fm or {}).get(SCOPE_KEY) or [] if str(e).strip()]


def undone_of(fm: dict) -> set[str]:
    return {str(e) for e in (fm or {}).get(UNDONE_KEY) or [] if str(e).strip()}


def narrowed(fm: dict, open_eps: list[str], *, undone: set[str] | None = None) -> dict:
    """The question's frontmatter about the conversations in ``open_eps`` only: they are what it names; when two or more are open
    it is about the first alone (its pick files that conversation's words). One open conversation is the whole-line question."""
    out = dict(fm)
    if open_eps:
        out["source_episode"], out["source_episodes"] = open_eps[0], list(open_eps)
    out.pop(SCOPE_KEY, None)
    if len(open_eps) > 1:
        out[SCOPE_KEY] = [open_eps[0]]
    if undone is not None:
        if undone:
            out[UNDONE_KEY] = sorted(undone)
        else:
            out.pop(UNDONE_KEY, None)
    return out


def rewrite_question(path: Path, open_eps: list[str], *, undone: set[str] | None = None) -> bool:
    """Write the question about ``open_eps`` only (:func:`narrowed`). True when its file changed."""
    parsed = markdown_parser.parse(path)
    fm = narrowed(dict(parsed.frontmatter), open_eps, undone=undone)
    if fm == dict(parsed.frontmatter):
        return False
    markdown_parser.write(path, fm, parsed.body)
    return True


def after_tap(memory_path: Path, path: Path, mention: str, scope: list[str], page: str) -> bool:
    """The person's pick of ``page`` for ``scope`` was just landed (`inbox_service._release_answered`, scoped): mark those
    conversations filed and, when other conversations are still open, keep the question about the next one. False when none is
    (the caller closes the question as every pick does)."""
    mark_filed(memory_path, mention, scope, page)
    line = pending_store.held_line(memory_path, mention)
    left = open_episodes(line) if line is not None else []
    if not left:
        return False
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, narrowed(dict(parsed.frontmatter), left), parsed.body)
    return True


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
    """File ``part`` on ``page_id``: its claims by `described_landing.land_page`, its prose by the writer a pick uses, the line
    edited, the question narrowed, one record. ``reads``: ``{conversation: ConvRead}`` (the located sentence, its kind). ``None``
    when no claim lands (everything is already there or would clash: nothing is written). The caller commits ``paths`` and puts
    every path back when anything raises."""
    memory_path = Path(memory_path)
    line = pending_store.held_line(memory_path, mention)
    if line is None:
        return None
    items: list[tuple[dl.Item, dl.Pick]] = []
    for data in part.claims:
        eps = sorted(claim_episodes(data))
        r = reads[eps[0]]
        claim = Claim.from_dict(data)
        pick = dl.Pick(page=page_id, scope="", start=r.start, end=r.end, turn=r.kind,
                       hash=_hash_of(memory_path, r.episode, r.sentence, r.start, r.end))
        items.append((dl.Item(line.name, claim, r.episode, r.start, r.end, pick.hash, r.kind, -1, rule=RULE), pick))
    extra = {"item_id": item_path.stem, "mention": line.name, "which_page": page_id, "filed_episodes": list(part.episodes),
             "prose": [dict(r) for r in part.prose]}
    done = dl.land_page(memory_path, page_id, items, by=by, engine=engine, today=today, rule=RULE, reason=REASON, extra=extra,
                        close_empty=False)
    if done is None or not done.record_id:
        return None
    page_rel = f"entities/{page_id}.md"
    # The prose the landed claims' conversations said (every conversation of a row is one this page was named for).
    if part.prose and _apply_prose(memory_path, page_id, part.prose, part.episodes) and page_rel not in done.paths:
        done.paths.append(page_rel)
    remove_prose(memory_path, line.name, part.prose)
    mark_filed(memory_path, line.name, part.episodes, page_id)
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
        if rewrite_question(item_path, open_episodes(after) if after is not None else []):
            done.paths.append(item_path.relative_to(memory_path).as_posix())
            done.lines.append(f"{done.paths[-1]}: updated (source: {done.record_id}, trigger: sleep/which-one-filed)")
    bank_index.invalidate(memory_path)
    return done


# --------------------------------------------------------------------------- the undo


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
    kept = parsed = restore = None
    if path.is_file():
        parsed = markdown_parser.parse(path)
        try:
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            raise dl.NotLandable("The page's claims could not be read; nothing was changed.") from exc
        if prose:
            # The prose cannot be taken out by id: the page must still be exactly what the landing's commit wrote.
            sha = inbox_tend._commit_of(memory_path, record_rel)
            if not sha:
                raise dl.NotLandable("The settle's commit could not be found; nothing was changed.")
            restore = {}
            for rel in (page_rel, ledger_rel):
                if not rel:
                    continue
                after, before = inbox_tend._git_bytes(memory_path, f"{sha}:{rel}"), inbox_tend._git_bytes(memory_path, f"{sha}^:{rel}")
                current = dl._bytes(memory_path / rel)
                if current != after:
                    raise dl.NotLandable("The page changed since this was filed; nothing was changed.")
                restore[rel] = before
        else:
            for c in claims:
                if c.id in landed and not dl.as_written(c, landed[c.id]):
                    raise dl.NotLandable("A fact this settle wrote was changed since; nothing was changed.")
            kept = [c for c in claims if c.id not in landed]
            if len(kept) == len(claims):
                kept = None
    dl._places(memory_path, [name], held, {str(d["name"]).lower() for d in closed})
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
        mine = [c for c in held if c.subject == sanitize_id(name)]
        if mine:
            pending_store.hold(memory_path, {sanitize_id(name): mine})
        line = pending_store.held_line(memory_path, name)
        if mine and (line is None or not {c.id for c in mine} <= {d.get("id") for d in line.held_claims}):
            raise dl._gone()
        if prose:
            edit_line(memory_path, name, lambda ln: _give_prose(ln, prose))
        mark_filed(memory_path, name, episodes, None)
        if restore is not None:
            for rel, data in restore.items():
                target = memory_path / rel
                if data is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(data)
                paths.append(rel)
            lines.append(f"{page_rel}: updated (source: {record_id}, trigger: sleep/which-one-filed/undone)")
        elif kept is not None and parsed is not None:
            markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, kept))
            paths += [rel for rel in (page_rel, ledger_rel) if rel and ((memory_path / rel).exists() or snapshot.get(rel) is not None)]
            lines.append(f"{page_rel}: updated (source: {record_id}, trigger: sleep/which-one-filed/undone)")
        if question is not None:
            after = pending_store.held_line(memory_path, name)
            qfm = markdown_parser.parse(question).frontmatter
            if rewrite_question(question, open_episodes(after) if after is not None else episodes,
                                undone=undone_of(qfm) | set(episodes)):
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


def _open_question(memory_path: Path, item_id: str, mention: str) -> list[Path]:
    """The question the filing was about, if it is still open: its own file, else the open which-one question of the mention."""
    own = Path(memory_path) / "inbox" / f"{item_id}.md"
    if item_id and own.is_file():
        return [own]
    from api.services import which_one

    found = which_one.open_question(memory_path, mention)
    return [found] if found is not None else []
