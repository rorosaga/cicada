"""Acting on the second look at two people who share a first name (2026-11-23): the disk half of `same_name_review`.

`same_name_people.plan` (Stage 2) places a batch's mentions and, when its re-read shows that a page may hold two people
or that two people held in doubt may be one, flags the name (`same_name_doubts.flag`). After the batch has committed, in
the engine-independent tail, this module reads what the record says about each flagged person **conversation by
conversation** (a page's beliefs and facts each carry the conversations they came from) and asks the main model, which
acts only on what it copies from those descriptions (`same_name_review`):

* a page that holds two people, on a located contrast, is split: the conversations that leave, with their beliefs and
  facts, move to a new page through `page_join.split`, one commit the person can undo (`page_join.undo`), authored by
  Sleep; the pair is recorded as split, so nothing joins them again;
* two people held in doubt that a located link shows to be one are merged through `page_join.merge`, the same way
  (ruling 74: the name is one kind of evidence, a located fact both sides state the other); a located contrast makes the
  pair a split (kept apart for good);
* two pages held in doubt that nothing settles are asked about **once**: "Are Marc (brother-in-law) and Marc (colleague)
  the same person?", an ordinary `merge_suggestion` between two pages (`fold_page`: yes folds one into the other, no keeps
  them apart for good, `merge_rejections`), with what each is known for in its reason. Never for a person held on a line
  (nothing rests on it yet), never a second time (`same_name_doubts.mark_asked`), never when the person already said.

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

from api.services import same_name_doubts, same_name_people as snp, same_name_review as snr

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


def moving(memory_path: Path, page_id: str, episodes: frozenset[str]) -> tuple[list[str], list[int]]:
    """``(belief ids, sentence numbers)`` that leave with ``episodes``: those whose every source is one of them."""
    from api.services import markdown_parser, same_name_split, section_provenance
    from api.services.claims import parse_claims, strip_claims_block

    parsed = markdown_parser.parse(Path(memory_path) / "entities" / f"{page_id}.md")
    claim_ids = [c.id for c in parse_claims(parsed.body)
                 if c.source_episodes and {str(e) for e in c.source_episodes} <= episodes]
    leaving: list[str] = []
    scanned = section_provenance.scan(strip_claims_block(parsed.body))
    for section, items in section_provenance.matched(parsed.frontmatter or {}, parsed.body).items():
        by_key = {item.key: item for item in scanned.get(section, [])}
        for key, (_guard, rows) in items.items():
            sources = {ev.episode for ev in rows}
            if sources and sources <= episodes and key in by_key:
                leaving.append(by_key[key].text)
    numbers = [s.n for s in same_name_split.sentences(parsed.body) if any(s.text in text for text in leaving)]
    return claim_ids, numbers


def _author() -> list[str]:
    return ["cicada"]


def split_page(memory_path: Path, page_id: str, episodes: frozenset[str], split: snr.Split, *, before=None) -> dict | None:
    """The page's leaving conversations, with their beliefs and facts, to a new page: one commit (`page_join.split`).
    ``None`` when there is nothing to move (no belief or sentence is sourced only from them)."""
    from api.services import page_join

    claims, sentences = moving(memory_path, page_id, episodes)
    if not claims and not sentences:
        return None
    reason = f"Two people share this name: “{split.here}” cannot be true of the same person as “{split.there}”."
    kept_name = None
    try:
        return page_join.split(
            memory_path, page_id, sentences=sentences, claims=claims, episodes=sorted(episodes), author=_author(),
            trigger=TRIGGER, reason=reason, before=before, extra_paths=[same_name_doubts.FILE],
            name=kept_name)
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


def ask_pair(memory_path: Path, a: str, b: str, *, today: date) -> str | None:
    """One "Are <A> and <B> the same person?" question about two pages the record cannot tell apart: an ordinary
    ``merge_suggestion`` (the card's one-tap merge, its undo and every reader already work) marked ``detected:
    same_name_doubt``, asked about the less-used page, with what each page is known for in its reason. Answered by the
    person only: yes folds one into the other (``fold_page``), no keeps the two apart for good. Files only; ``None`` when
    either page is gone or the pair is already settled."""
    from api.services import bank_index, inbox_service, markdown_parser, merge_rejections, page_use

    memory_path = Path(memory_path)
    if merge_rejections.is_rejected(memory_path, a, b) or merge_rejections.is_split(memory_path, a, b):
        return None
    fa, fb = bank_index.file(memory_path, "entities", f"{a}.md"), bank_index.file(memory_path, "entities", f"{b}.md")
    if fa is None or fb is None:
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


async def tend(memory_path: Path, judge, *, today: date | None = None,
               max_questions: int = MAX_QUESTIONS) -> Report:
    """Look again at what Stage 2 flagged. ``judge(system, prompt)`` is the main model's call. A split or a merge commits
    alone through `page_join` (undoable); everything else this step writes (the pairs kept apart, the question, the store)
    is one `cicada` commit at the end, and a path dirty before it ran is left as it was. Counts only. Never raises but
    for an engine failure (G74(a)), in which case the flags stay for the next run."""
    import asyncio

    from api.services import git_service, merge_rejections, page_join

    memory_path = Path(memory_path)
    today = today or date.today()
    report = Report()
    pages, flagged_pairs = same_name_doubts.flagged(memory_path)
    if not pages and not flagged_pairs:
        return report
    before0 = await asyncio.to_thread(git_service.snapshot_dirty_sync, memory_path)
    held = same_name_doubts.pairs(memory_path)
    rest: list[str] = []   # what the final commit takes
    looks = 0
    try:
        for ref in sorted(pages):
            if looks >= MAX_LOOKS:
                report.skip("max_looks")
                break
            page = page_of(memory_path, ref) if _page_exists(memory_path, ref) else None
            if page is None or len(page.items) < 2:
                same_name_doubts.clear_flags(memory_path, pages=[ref])
                report.skip("nothing_to_read")
                continue
            looks += 1
            report.looked += 1
            name = str(page_conversations(memory_path, ref)[0])
            split = await snr.holds_two(name, page, judge)
            if not split.episodes:
                same_name_doubts.clear_flags(memory_path, pages=[ref])
                continue

            def do_split(before, ref=ref, split=split):
                same_name_doubts.clear_flags(memory_path, pages=[ref])
                out = split_page(memory_path, ref, split.episodes, split, before=before)
                if out is not None:
                    same_name_doubts.remove_pairs(memory_path, [(ref, out["new_id"])])
                return out

            out = await _in_lock(memory_path, do_split)
            if out is None:
                report.skip("nothing_to_move")
                rest.append(same_name_doubts.FILE)
                continue
            report.split += 1
            report.paths += out["paths"]
            rest.append(same_name_doubts.FILE)
        for a, b in sorted(flagged_pairs):
            if looks >= MAX_LOOKS:
                report.skip("max_looks")
                break
            if (a, b) not in held:
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                continue
            if not (_page_exists(memory_path, a) and _page_exists(memory_path, b)):
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                report.skip("a_line")   # a person on a line has nothing resting on it: no question, no join, yet
                continue
            if merge_rejections.is_rejected(memory_path, a, b) or merge_rejections.is_split(memory_path, a, b):
                same_name_doubts.remove_pairs(memory_path, [(a, b)])
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                continue
            if "asked" in held[(a, b)]:
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])   # the person was asked: never twice
                report.skip("already_asked")
                continue
            looks += 1
            report.looked += 1
            pa, pb = page_of(memory_path, a), page_of(memory_path, b)
            name = page_conversations(memory_path, a)[0]
            verdict = await snr.settle_pair(name, pa or snr.Page(a, ()), pb or snr.Page(b, ()), judge)
            busy = sum(1 for x, y in held if a in (x, y)) > 1 or sum(1 for x, y in held if b in (x, y)) > 1
            if verdict.verdict == "same" and not busy:
                from api.services.id_utils import sanitize_id

                loser, winner = _winner(memory_path, a, b, sanitize_id(name))
                reason = f"The same person: \u201c{verdict.here}\u201d and \u201c{verdict.there}\u201d state one fact."

                def do_merge(before, a=a, b=b, loser=loser, winner=winner, reason=reason):
                    same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                    same_name_doubts.remove_pairs(memory_path, [(a, b)])
                    return page_join.merge(memory_path, loser, winner, author=_author(), trigger=TRIGGER, reason=reason,
                                           before=before, extra_paths=[same_name_doubts.FILE])

                out = await _in_lock(memory_path, do_merge)
                report.merged += 1
                report.paths += out["paths"]
            elif verdict.verdict == "apart":
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                merge_rejections.add_split(memory_path, a, b)
                same_name_doubts.remove_pairs(memory_path, [(a, b)])
                report.apart += 1
                rest += [merge_rejections.FILE, same_name_doubts.FILE]
            elif report.asked < max_questions and open_questions(memory_path) < MAX_OPEN:
                same_name_doubts.clear_flags(memory_path, pairs_=[(a, b)])
                made = ask_pair(memory_path, a, b, today=today)
                if made:
                    same_name_doubts.mark_asked(memory_path, a, b, today=today.isoformat())
                    report.asked += 1
                    rest += [made, same_name_doubts.FILE]
            else:
                report.skip("question_budget")   # stays flagged: looked at again next drain, never lost
    finally:
        if rest or report.looked:
            paths = list(dict.fromkeys(rest + [same_name_doubts.FILE]))
            lines = [f"{p}: updated (trigger: {TRIGGER})" for p in paths]

            def commit(_before):
                return page_join._commit(memory_path, "Same-name review", lines, paths, authors=_author(), session=None,
                                         before=before0)

            try:
                await _in_lock(memory_path, commit)
            except Exception as exc:  # noqa: BLE001 - the flags and the store are left for the next run
                logger.warning(f"same-name review commit failed: {type(exc).__name__}")
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
    for main, small in (("agent_model", "agent_disambiguation_model"), ("codex_model", "codex_disambiguation_model"),
                        ("cli_engine_model", "cli_engine_disambiguation_model"),
                        ("litellm_model", "litellm_disambiguation_model")):
        value = str(getattr(resolved, main, "") or "").strip()
        if value:
            updates[small] = value
    return resolved.model_copy(update=updates) if updates else resolved


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, judge=None, today: date | None = None) -> Report:
    """Sleep's tail step: what Stage 2 flagged, looked at again by the engine's main model. Nothing flagged: no engine is
    resolved and nothing is sent. A scheduled run reaches a plan only through the person's switch (ruling 4b), a plan
    limit is a pause (the flags stay), no engine means no look. Never raises."""
    from api.services import engine_errors

    report = Report()
    memory_path = Path(memory_path)
    pages, pairs = same_name_doubts.flagged(memory_path)
    if not pages and not pairs:
        return report
    if judge is None:
        from api.services import engine_select, entity_resolver, web_lookup

        try:
            resolved, _why = await engine_select.resolve_settings(settings, user_triggered=user_triggered)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"same-name review: no engine ({type(exc).__name__})")
            report.skip("no_engine")
            return report
        if engine_select.no_engine(resolved):
            report.skip("no_engine")
            return report
        mode = str(getattr(resolved, "llm_mode", "byok") or "byok").strip().lower()
        if mode in engine_select.SUBSCRIPTION_MODES and not user_triggered \
                and not engine_select.scheduled_plan_allowed(web_lookup._registry(settings)):
            report.skip("scheduled_plan")   # ruling 4b: a scheduled run reaches a plan only through the switch
            return report
        strong = main_tier(resolved)

        async def judge(system: str, prompt: str) -> object:
            return await entity_resolver._same_name_ask(strong, system, prompt)

    try:
        return await tend(memory_path, judge, today=today)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")   # a plan limit is a pause: the flags stay for the next run
    except Exception as exc:  # noqa: BLE001 - the second look never fails a Sleep
        logger.warning(f"same-name review stopped: {type(exc).__name__}")
        report.skip("error")
    return report
