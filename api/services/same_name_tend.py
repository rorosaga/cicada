"""Acting on the second look at two people who share a first name (2026-11-23): the disk half of `same_name_review`.

`same_name_people.plan` (Stage 2) places a batch's mentions and, when its re-read shows that a page may hold two people
or that two people held in doubt may be one, flags the name (`same_name_doubts.flag`). After the batch has committed, in
the engine-independent tail, this module reads what the record says about each flagged person **conversation by
conversation** (a page's beliefs and facts each carry the conversations they came from) and asks the main model, which
acts only on what it copies from those descriptions (`same_name_review`):

* a page that holds two people, on a located contrast, is split: the conversations that leave, with their beliefs and
  facts, move to a new page through `page_join.split`, one commit the person can undo (`page_join.undo`), authored by
  Sleep; the pair is recorded as split, so nothing joins them again. **The person's word stands over it:** a page
  they folded another into (their merge, an answered question) is never split by Sleep, and a split of Sleep's that
  the person took back is never made again (`same_name_doubts.one`, `splits`);
* two people held in doubt that a located contrast shows to be two are kept apart for good (`merge_rejections`);
* two people held in doubt that a later conversation links (one fact both sides state, found by two reads of the whole
  record) are **joined by Sleep** through `page_join.merge`, one commit the person can undo (owner 2026-11-23: "cicada
  itself should do it automatically", ruling 74a). An undo is the person saying they are two: the pair is then kept
  apart for good and never joined or asked about again (`reconcile`). A page in two doubt pairs is never joined;
* two pages held in doubt that read like two different people (a relative and a colleague) and that nothing settles
  **wait apart and nobody is asked** (owner 2026-11-23: "the fewer the asks the better"). Only a pair that reads like
  one person, or like nothing either way, is asked about, **once**: "Are Marc (brother-in-law) and Marc (colleague) the
  same person?", an ordinary `merge_suggestion` between two pages (`fold_page`: yes folds one into the other, no keeps
  them apart for good, `merge_rejections`), with what each is known for in its reason. Never for a person held on a line
  (nothing rests on it yet), never a second time (`same_name_doubts.mark_asked`), never when the person already said,
  never over a question already open about the pair, and never when the read failed or its answer could not be stood
  on (that is not "the record does not say").

The sentences and beliefs that leave are exactly those whose every source is a leaving conversation; one a staying
conversation also supports stays, and so does the summary, which no one conversation owns. A page or passage the person
or an agent wrote or pinned is never rewritten (it has no provenance rows). Engine-free apart from the injected judge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import same_name_doubts, same_name_leftovers, same_name_people as snp, same_name_review as snr

TRIGGER = "sleep/same-name"
#: New questions about a doubt one drain may open (the inbox already holds hundreds): the rest wait for the next drain.
MAX_QUESTIONS = 3
#: Pairs and pages one tail step reads (each is a main-model call).
MAX_LOOKS = 8
#: Questions of this kind open at once: the inbox is the person's to read, and a doubt waits better than a pile.
MAX_OPEN = 10


@dataclass
class Report:
    looked: int = 0
    split: int = 0
    merged: int = 0
    apart: int = 0
    asked: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def _episode_day(memory_path: Path, episode: str) -> str:
    from api.services import bank_index

    entry = bank_index.file(memory_path, "episodes", f"{episode}.md")
    return str(((entry.frontmatter if entry is not None else None) or {}).get("timestamp") or "")[:10]


def page_conversations(memory_path: Path, page_id: str) -> tuple[str, dict[str, list[str]], list[str]]:
    """``(name, {conversation: what it says about the person}, the conversations in the order the page lists them)``.

    What a conversation says is each belief of the page it is a source of (`Claim.source_episodes`) and each Key Fact
    whose provenance names it (`section_provenance`); text a conversation shares with another is listed under both.
    Reads only."""
    from api.services import markdown_parser, section_provenance
    from api.services.claims import parse_claims, strip_claims_block

    path = Path(memory_path) / "entities" / f"{page_id}.md"
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter or {}
    order = [str(e) for e in fm.get("source_episodes") or [] if e]
    said: dict[str, list[str]] = {}

    def add(episode: str, text: str) -> None:
        text = " ".join(str(text or "").split())
        if text and text.casefold() not in {t.casefold() for t in said.setdefault(episode, [])}:
            said[episode].append(text)

    for claim in parse_claims(parsed.body):
        if claim.valid_to is not None and claim.superseded_by:
            continue
        for episode in claim.source_episodes or []:
            add(str(episode), claim.text)
    scanned = section_provenance.scan(strip_claims_block(parsed.body))
    for section, items in section_provenance.matched(fm, parsed.body).items():
        by_key = {item.key: item for item in scanned.get(section, [])}
        for key, (_guard, rows) in items.items():
            item = by_key.get(key)
            if item is not None:
                for episode in {ev.episode for ev in rows}:
                    add(str(episode), item.text)
    return str(fm.get("name") or page_id), said, order


def page_of(memory_path: Path, page_id: str) -> snr.Page | None:
    """The page as the judge reads it: one description per conversation (dated), the conversations nothing is recorded
    for left out. ``None`` for a page that is not there, or nothing to read."""
    try:
        _name, said, order = page_conversations(memory_path, page_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"same-name tend: page unreadable ({type(exc).__name__})")
        return None
    items = []
    for episode in [e for e in order if e in said] + [e for e in said if e not in order]:
        day = _episode_day(memory_path, episode)
        text = "; ".join(said[episode])
        items.append(snp.Item(f"({day}) {text}"[: snp.TEXT_CHARS] if day else text[: snp.TEXT_CHARS], (episode,)))
    items.sort(key=lambda i: i.text[:12])
    return snr.Page(page_id, tuple(items)) if items else None


def _leaving_items(memory_path: Path, page_id: str, episodes: frozenset[str]) -> list[tuple[str, str]]:
    """``(heading, text)`` of the page's sourced prose items whose every source is one of ``episodes``."""
    from api.services import markdown_parser, section_provenance
    from api.services.claims import strip_claims_block

    parsed = markdown_parser.parse(Path(memory_path) / "entities" / f"{page_id}.md")
    out: list[tuple[str, str]] = []
    scanned = section_provenance.scan(strip_claims_block(parsed.body))
    for section, items in section_provenance.matched(parsed.frontmatter or {}, parsed.body).items():
        by_key = {item.key: item for item in scanned.get(section, [])}
        for key, (_guard, rows) in items.items():
            sources = {ev.episode for ev in rows}
            if sources and sources <= episodes and key in by_key:
                out.append((section_provenance.TITLES.get(section, section), by_key[key].text))
    return out


def moving(memory_path: Path, page_id: str, episodes: frozenset[str]) -> tuple[list[str], list[int]]:
    """``(belief ids, sentence numbers)`` that leave with ``episodes``: those whose every source is one of them."""
    from api.services import markdown_parser, same_name_split
    from api.services.claims import parse_claims

    parsed = markdown_parser.parse(Path(memory_path) / "entities" / f"{page_id}.md")
    claim_ids = [c.id for c in parse_claims(parsed.body)
                 if c.source_episodes and {str(e) for e in c.source_episodes} <= episodes]
    leaving = [text for _heading, text in _leaving_items(memory_path, page_id, episodes)]
    numbers = [s.n for s in same_name_split.sentences(parsed.body) if any(s.text in text for text in leaving)]
    return claim_ids, numbers


def short_leaving(memory_path: Path, page_id: str, episodes: frozenset[str]) -> list[tuple[str, str]]:
    """The leaving conversations' own sourced lines that a sentence number cannot carry: the numbering skips anything under
    `same_name_split.MIN_CHARS` ("Dani is retired"), so on its own such a line would stay behind on the old page as the
    other person's fact. They move as exact cuts (`page_join.split(cuts=...)`), on their provenance alone."""
    from api.services import same_name_split

    return [(heading, text) for heading, text in _leaving_items(memory_path, page_id, episodes)
            if len(text) < same_name_split.MIN_CHARS and "\n" not in text]


def _author() -> list[str]:
    return ["cicada"]


def split_page(memory_path: Path, page_id: str, episodes: frozenset[str], split: snr.Split, *, before=None,
               cuts=()) -> dict | None:
    """The page's leaving conversations, with their beliefs and facts, to a new page: one commit (`page_join.split`).
    ``cuts``: the unsourced stretches of the old page that state the leaving person (`same_name_leftovers.plan`); they
    move in the same commit, so the person's undo takes them back with it. ``None`` when there is nothing to move (no
    belief or sentence is sourced only from them)."""
    from api.services import page_join

    claims, sentences = moving(memory_path, page_id, episodes)
    if not claims and not sentences:
        return None
    cuts = [*short_leaving(memory_path, page_id, episodes), *cuts]
    reason = f"Two people share this name: “{split.here}” cannot be true of the same person as “{split.there}”."
    try:
        # The commit holds the split and nothing else: `page_join.undo` reverses exactly this, and what Sleep remembers
        # about having made it (`same_name_doubts.note_split`) is written after, outside it.
        return page_join.split(
            memory_path, page_id, sentences=sentences, claims=claims, episodes=sorted(episodes), author=_author(),
            trigger=TRIGGER, reason=reason, before=before,
            cuts=[tuple(c) if isinstance(c, tuple) else c.as_tuple() for c in cuts], related_follows=True)
    except page_join.JoinError as exc:
        logger.info(f"same-name split not applied: {exc}")
        return None


def known_for(memory_path: Path, page_id: str) -> str:
    """What a page says its person is, in the page's own first sentence of its Summary, cut at a clause."""
    from api.services import entity_body, markdown_parser
    from api.services.claims import strip_claims_block

    try:
        parsed = markdown_parser.parse(Path(memory_path) / "entities" / f"{page_id}.md")
        sections = entity_body.parse_sections(strip_claims_block(parsed.body or ""))
    except Exception:  # noqa: BLE001
        return ""
    text = " ".join(str(sections.get("Summary") or next(iter(sections.values()), "") or "").split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0] if text else ""
    if len(first) > 110:   # cut at a clause, never in the middle of one
        cut = max(first.rfind(", ", 30, 110), first.rfind("; ", 30, 110), first.rfind(" who ", 30, 110),
                  first.rfind(" which ", 30, 110))
        first = first[:cut] if cut > 0 else first[:first.rfind(" ", 0, 110)]
    return first.rstrip(" .,;")


def question_open(memory_path: Path, a: str, b: str) -> bool:
    """A question about these two pages being one is already waiting, whoever asked it."""
    from api.services import bank_index

    pair = {a, b}
    for f in bank_index.files(Path(memory_path), "inbox"):
        fm = f.frontmatter or {}
        if str(fm.get("kind") or "") != "merge_suggestion" or str(fm.get("status") or "pending") != "pending":
            continue
        if {str(fm.get("entity_id") or ""), str(fm.get("merge_target_hint") or "")} == pair:
            return True
    return False


def ask_pair(memory_path: Path, a: str, b: str, *, today: date, link: tuple[str, str] | None = None) -> str | None:
    """One "Are <A> and <B> the same person?" question about two pages the record cannot tell apart: an ordinary
    ``merge_suggestion`` (the card's one-tap merge, its undo and every reader already work) marked ``detected:
    same_name_doubt``, asked about the less-used page, with what each page is known for in its reason. Answered by the
    person only: yes folds one into the other (``fold_page``), no keeps the two apart for good. ``link``: the one fact
    the read found on both sides, in each side's words, said in the question (never acted on). Files only; ``None``
    when either page is gone, the pair is already settled, or a question about the two is already open."""
    from api.services import bank_index, inbox_service, markdown_parser, merge_rejections, page_use

    memory_path = Path(memory_path)
    if merge_rejections.is_rejected(memory_path, a, b) or merge_rejections.is_split(memory_path, a, b):
        return None
    fa, fb = bank_index.file(memory_path, "entities", f"{a}.md"), bank_index.file(memory_path, "entities", f"{b}.md")
    if fa is None or fb is None or question_open(memory_path, a, b):
        return None
    use = page_use.scores(memory_path, today=today)
    asked, target = (a, b) if use.get(a, 0.0) <= use.get(b, 0.0) else (b, a)
    fm_asked, fm_target = (fa, fb) if asked == a else (fb, fa)
    name = str((fm_asked.frontmatter or {}).get("name") or asked)
    inbox = memory_path / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"inbox-{inbox_service.next_inbox_num(inbox):03d}.md"
    one, two = known_for(memory_path, asked), known_for(memory_path, target)
    markdown_parser.write(path, {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.5,
        "entity_id": asked, "entity_name": name, "title": f"Are these two {name} the same person?",
        "uncertainty_type": f"Possible duplicate of {name}", "suggested_classification": "person",
        "suggested_confidence": 0.5, "created_date": today.isoformat(), "merge_target_hint": target,
        "fold_page": True, "detected": "same_name_doubt",
        "known_for": {asked: one, target: two},
        **({"link": [str(link[0])[:200], str(link[1])[:200]]} if link and all(link) else {}),
    }, "Why this is asked: everything on record about both was read and does not say whether they are one person. "
       "Asked, never joined: only your answer joins them.")
    bank_index.invalidate(memory_path)
    return f"inbox/{path.name}"


def open_questions(memory_path: Path) -> int:
    from api.services import bank_index

    return sum(1 for f in bank_index.files(Path(memory_path), "inbox")
               if str((f.frontmatter or {}).get("detected") or "") == "same_name_doubt"
               and str((f.frontmatter or {}).get("status") or "pending") == "pending")


def _page_exists(memory_path: Path, ref: str) -> bool:
    return (Path(memory_path) / "entities" / f"{ref}.md").is_file()


def _winner(memory_path: Path, a: str, b: str, name_slug: str) -> tuple[str, str]:
    """``(loser, winner)``: the page the bare name reaches stays, else the one with more conversations."""
    if a == name_slug:
        return b, a
    if b == name_slug:
        return a, b
    na, nb = len(page_conversations(memory_path, a)[2]), len(page_conversations(memory_path, b)[2])
    return (b, a) if na >= nb else (a, b)


def _undone(memory_path: Path) -> set[str]:
    """Every join commit a later commit took back (`page_join.undo` writes ``Undoes: <sha>``), in one git call."""
    import subprocess

    from api.services import page_join

    out = subprocess.run(["git", "-C", str(memory_path), "log", "--format=%b", "-F", f"--grep={page_join.UNDOES}", "HEAD"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return set()
    return {line[len(page_join.UNDOES):].strip() for line in out.stdout.splitlines() if line.startswith(page_join.UNDOES)}


def reconcile(memory_path: Path) -> dict[str, int]:
    """The person's word over Sleep's own joins, with no engine: a split of Sleep's they took back makes the page one
    Sleep never splits again (`same_name_doubts.one`), and a join of Sleep's they took back makes the pair two people for
    good (`merge_rejections.add_split`), never joined or asked about again. Writes files only (the caller commits);
    ``{"one": n, "apart": n}``. Nothing recorded: no git call."""
    from api.services import merge_rejections

    memory_path = Path(memory_path)
    made, joined = same_name_doubts.splits(memory_path), same_name_doubts.joins(memory_path)
    out = {"one": 0, "apart": 0}
    if not made and not joined:
        return out
    undone = _undone(memory_path)
    if not undone:
        return out
    for page, commit in made.items():
        if commit in undone:
            same_name_doubts.mark_one(memory_path, page)
            same_name_doubts.forget_split(memory_path, page)
            same_name_doubts.clear_flags(memory_path, pages=[page])
            out["one"] += 1
    for (a, b), commit in joined.items():
        if commit in undone:
            merge_rejections.add_split(memory_path, a, b)
            same_name_doubts.remove_pairs(memory_path, [(a, b)])
            same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
            same_name_doubts.forget_join(memory_path, a, b)
            out["apart"] += 1
    return out


async def _commit_store(memory_path: Path, rest: list[str], before0) -> None:
    """One `cicada` commit of the store and what else this step wrote outside a join's own commit; nothing when clean."""
    import asyncio

    from api.services import git_service, merge_rejections, page_join

    try:
        dirty = bool(await asyncio.to_thread(git_service.dirty_paths_sync, memory_path, same_name_doubts.FILE,
                                             merge_rejections.FILE))
    except Exception:  # noqa: BLE001 - an unreadable tree: commit what this step knows it wrote
        dirty = True
    if not (rest or dirty):
        return
    paths = list(dict.fromkeys(rest + [same_name_doubts.FILE, merge_rejections.FILE]))
    lines = [f"{p}: updated (trigger: {TRIGGER})" for p in paths]

    def commit(_before):
        return page_join._commit(memory_path, "Same-name review", lines, paths, authors=_author(), session=None,
                                 before=before0)

    try:
        await _in_lock(memory_path, commit)
        rest.clear()
    except Exception as exc:  # noqa: BLE001 - the flags and the store are left for the next run
        logger.warning(f"same-name review commit failed: {type(exc).__name__}")


def _speaker(memory_path: Path) -> str | None:
    """The owner's name as the pages write it, for the judge's prompt: the descriptions name the owner, and a judge that
    does not know whose conversations these are reads that name as someone two people share (2026-11-24)."""
    try:
        from api.services import owner_identity

        return owner_identity.owner_name(memory_path)
    except Exception:  # noqa: BLE001 - no name is the prompt as it was
        return None


async def tend(memory_path: Path, judge, *, today: date | None = None,
               max_questions: int = MAX_QUESTIONS) -> Report:
    """Look again at what Stage 2 flagged. ``judge(system, prompt)`` is the main model's call. A split or a join commits
    alone through `page_join` (undoable, and nothing Sleep remembers about having made it is in that commit); everything
    else this step writes (the pairs kept apart, the question, the store) is a `cicada` commit of its own. Counts only.
    Never raises but for an engine failure (G74(a)), in which case the flags stay for the next run."""
    import asyncio

    from api.services import git_service, merge_rejections, page_join

    memory_path = Path(memory_path)
    today = today or date.today()
    report = Report()
    before0 = await asyncio.to_thread(git_service.snapshot_dirty_sync, memory_path)
    rest: list[str] = []   # what the next store commit takes besides the store
    try:
        took_back = await asyncio.to_thread(reconcile, memory_path)
        report.apart += took_back["apart"]
        if took_back["one"]:
            report.skipped["split_taken_back"] = took_back["one"]
        pages, flagged_pairs = same_name_doubts.flagged(memory_path)
        held = same_name_doubts.pairs(memory_path)
        speaker = await asyncio.to_thread(_speaker, memory_path) if (pages or flagged_pairs) else None
        looks = 0
        for ref in sorted(pages):
            if looks >= MAX_LOOKS:
                report.skip("max_looks")
                break
            # The person's word stands: a page they folded another into is one person on their say, and a split of
            # Sleep's they took back is their "one person" too (`reconcile`). Neither is split by Sleep.
            if ref in same_name_doubts.one(memory_path):
                same_name_doubts.clear_flags(memory_path, pages=[ref])
                report.skip("joined_by_the_person")
                continue
            page = page_of(memory_path, ref) if _page_exists(memory_path, ref) else None
            if page is None or len(page.items) < 2:
                same_name_doubts.clear_flags(memory_path, pages=[ref])
                report.skip("nothing_to_read")
                continue
            looks += 1
            report.looked += 1
            name = str(page_conversations(memory_path, ref)[0])
            split = await snr.holds_two(name, page, judge, speaker)   # an engine failure leaves the flag for the next run
            if split.unreadable:
                report.skip("unreadable")   # an answer in the wrong shape: the page was not read (2026-11-24)
            if not split.episodes:
                same_name_doubts.clear_flags(memory_path, pages=[ref])
                continue
            # What the old page's unsourced prose (Summary, History, tags) still says of the person who leaves, read
            # outside the write window (a model call) and moved in the split's own commit. An engine failure here
            # leaves the flag too: the split is made with it, never without, the next run.
            cuts = await same_name_leftovers.plan(memory_path, ref, split.episodes, judge)
            same_name_doubts.clear_flags(memory_path, pages=[ref])
            out = await _in_lock(memory_path, lambda before, ref=ref, split=split, cuts=cuts: split_page(
                memory_path, ref, split.episodes, split, before=before, cuts=cuts))
            if out is None:
                report.skip("nothing_to_move")
                continue
            same_name_doubts.note_split(memory_path, ref, out.get("commit"))
            same_name_doubts.remove_pairs(memory_path, [(ref, out["new_id"])])
            report.split += 1
            report.paths += out["paths"]
        for a, b in sorted(flagged_pairs):
            if looks >= MAX_LOOKS:
                report.skip("max_looks")
                break
            if (a, b) not in held or (a, b) not in same_name_doubts.pairs(memory_path):
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                continue
            if merge_rejections.is_rejected(memory_path, a, b) or merge_rejections.is_split(memory_path, a, b):
                same_name_doubts.remove_pairs(memory_path, [(a, b)])   # the person said, or a contrast did
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                continue
            if not (_page_exists(memory_path, a) and _page_exists(memory_path, b)):
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                report.skip("a_line")   # a person on a line has nothing resting on it: no question yet
                continue
            looks += 1
            report.looked += 1
            pa, pb = page_of(memory_path, a), page_of(memory_path, b)
            name = page_conversations(memory_path, a)[0]
            verdict = await snr.settle_pair(name, pa or snr.Page(a, ()), pb or snr.Page(b, ()), judge, speaker)
            now = same_name_doubts.pairs(memory_path)
            busy = sum(1 for x, y in now if a in (x, y)) > 1 or sum(1 for x, y in now if b in (x, y)) > 1
            if verdict.verdict == "same" and not busy:
                # Owner 2026-11-23 (ruling 74a): Cicada joins them itself. A join is the costly thing to get wrong, so
                # the record is read a second time and both reads must find a located link.
                again = await snr.settle_pair(name, pa or snr.Page(a, ()), pb or snr.Page(b, ()), judge, speaker)
                if again.verdict == "same":
                    from api.services.id_utils import sanitize_id

                    loser, winner = _winner(memory_path, a, b, sanitize_id(name))
                    reason = f"The same person: “{verdict.here}” and “{verdict.there}” state one fact."
                    # The join's commit holds the join alone, so the person's undo reverses exactly that: the doubt
                    # leaves the store first, in the store's own commit, and what Sleep remembers of the join after.
                    meta = now.get((a, b), {})
                    same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                    same_name_doubts.remove_pairs(memory_path, [(a, b)])
                    await _commit_store(memory_path, rest, before0)
                    try:
                        out = await _in_lock(memory_path, lambda before, loser=loser, winner=winner, reason=reason: (
                            page_join.merge(memory_path, loser, winner, author=_author(), trigger=TRIGGER, reason=reason,
                                            before=before, by_sleep=True)))
                    except Exception as exc:  # noqa: BLE001 - the doubt goes back where it was
                        same_name_doubts.add_pairs(memory_path, [(a, b)], today=meta.get("since"))
                        if meta.get("asked"):
                            same_name_doubts.mark_asked(memory_path, a, b, today=meta["asked"])
                        logger.info(f"same-name join not applied: {type(exc).__name__}")
                        report.skip("join_refused")
                        continue
                    same_name_doubts.note_join(memory_path, a, b, out.get("commit"))
                    report.merged += 1
                    report.paths += out["paths"]
                    continue
            if verdict.verdict == "apart":
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                merge_rejections.add_split(memory_path, a, b)
                same_name_doubts.remove_pairs(memory_path, [(a, b)])
                report.apart += 1
                continue
            if not verdict.answered:
                # Nothing was read (a side with no conversation of its own on record), or the answer could not be stood
                # on: that is not "the record does not say", so nothing is asked and the pair's one question is kept.
                # The doubt stays; the next conversation that names the name flags it again.
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                report.skip("unreadable" if verdict.unreadable else "not_read")   # a wrong-shaped answer is counted apart (2026-11-24)
                continue
            if verdict.verdict != "same" and verdict.leaning == "two":
                # Owner 2026-11-23: the fewer the asks the better. They read like two people and nothing says they
                # cannot be one: they wait apart, each with their own facts, and nobody is asked. A later conversation
                # that links them joins them; one that sets them against each other keeps them apart for good.
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                report.skip("reads_like_two")
                continue
            if "asked" in now.get((a, b), {}):
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])   # the person was asked: never twice
                report.skip("already_asked")
                continue
            if report.asked < max_questions and open_questions(memory_path) < MAX_OPEN:
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                link = (verdict.here, verdict.there) if verdict.verdict == "same" else None
                made = ask_pair(memory_path, a, b, today=today, link=link)
                if made:
                    same_name_doubts.mark_asked(memory_path, a, b, today=today.isoformat())
                    report.asked += 1
                    rest.append(made)
                else:
                    report.skip("question_open")
            else:
                report.skip("question_budget")   # stays flagged: looked at again next drain, never lost
    finally:
        # The store changes whenever a flag is taken, looked at or not: it is never left uncommitted in the bank.
        await _commit_store(memory_path, rest, before0)
    report.paths = list(dict.fromkeys(report.paths + rest))
    return report


async def _in_lock(memory_path: Path, fn):
    """``fn(before)`` under the page lock with the dirty pages snapshotted first (the join routes' own rule), off the loop."""
    import asyncio

    from api.services import git_service, page_lock

    def run():
        with page_lock.page_lock(memory_path):
            before = git_service.snapshot_dirty_sync(memory_path)
            return fn(before)

    return await asyncio.to_thread(run)


def main_tier(resolved):
    """The same engine on its main model for a call labelled "disambiguation": the engine's small-tier fields are set to
    its main ones, so the second look is read by the stronger model and never by another engine or bill."""
    if not hasattr(resolved, "model_copy"):
        return resolved
    updates = {}
    # A batch of old bulk saves runs on the engine's lightest model (`light_reads`); a person's name is still judged by
    # the model they chose.
    kept = getattr(resolved, "kept_main_models", None) or {}
    for main, small in (("agent_model", "agent_disambiguation_model"), ("codex_model", "codex_disambiguation_model"),
                        ("cli_engine_model", "cli_engine_disambiguation_model"),
                        ("litellm_model", "litellm_disambiguation_model")):
        value = str(kept.get(main) or getattr(resolved, main, "") or "").strip()
        if value:
            updates[small] = value
    return resolved.model_copy(update=updates) if updates else resolved


async def main_engine(settings, *, user_triggered: bool):
    """``(settings, "")``: the engine's settings with its main model standing in for the small tier, or ``(None, why)`` —
    no engine, or a scheduled run the person's plan switch does not allow (ruling 4b). Nothing is sent here."""
    from api.services import engine_select, web_lookup

    try:
        resolved, _why = await engine_select.resolve_settings(settings, user_triggered=user_triggered)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"same-name review: no engine ({type(exc).__name__})")
        return None, "no_engine"
    if engine_select.no_engine(resolved):
        return None, "no_engine"
    mode = str(getattr(resolved, "llm_mode", "byok") or "byok").strip().lower()
    if mode in engine_select.SUBSCRIPTION_MODES and not user_triggered \
            and not engine_select.scheduled_plan_allowed(web_lookup._registry(settings)):
        return None, "scheduled_plan"   # ruling 4b: a scheduled run reaches a plan only through the switch
    return main_tier(resolved), ""


async def main_judge(settings, *, user_triggered: bool):
    """``(judge, "")``: the main model as the second look's call, or ``(None, why)`` (`main_engine`)."""
    from api.services import entity_resolver

    strong, why = await main_engine(settings, user_triggered=user_triggered)
    if strong is None:
        return None, why

    async def judge(system: str, prompt: str) -> object:
        return await entity_resolver._same_name_ask(strong, system, prompt)

    return judge, ""


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, judge=None, today: date | None = None) -> Report:
    """Sleep's tail step: what Stage 2 flagged, looked at again by the engine's main model. Nothing flagged: no engine is
    resolved and nothing is sent. A scheduled run reaches a plan only through the person's switch (ruling 4b), a plan
    limit is a pause (the flags stay), no engine means no look. Never raises."""
    from api.services import engine_errors

    report = Report()
    memory_path = Path(memory_path)
    pages, pairs = same_name_doubts.flagged(memory_path)
    if not pages and not pairs:
        if same_name_doubts.splits(memory_path) or same_name_doubts.joins(memory_path):
            # Nothing to read, but Sleep has joins of its own on record: has the person taken one back? No engine.
            async def unused(_system: str, _prompt: str) -> object:
                raise RuntimeError("nothing is flagged")

            try:
                return await tend(memory_path, unused, today=today)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"same-name review stopped: {type(exc).__name__}")
                report.skip("error")
        return report
    if judge is None:
        judge, why = await main_judge(settings, user_triggered=user_triggered)
        if judge is None:
            report.skip(why)
            return report

    try:
        return await tend(memory_path, judge, today=today)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")   # a plan limit is a pause: the flags stay for the next run
    except Exception as exc:  # noqa: BLE001 - the second look never fails a Sleep
        logger.warning(f"same-name review stopped: {type(exc).__name__}")
        report.skip("error")
    return report
