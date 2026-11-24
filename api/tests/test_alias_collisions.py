"""Two pages that go by one name (`alias_collisions`, G21 / G209, 2026-11-24).

A labelled synthetic set (invented names): the three kinds the real bank held in roughly equal parts, a saved link that
shares a name, a short name two things fairly share (one called by it in the person's own words), a pair the person
already said is different, a pair the model cannot tell, and people. A scripted judge, real git, no engine, no network.
The bar for a wrong removal is zero: every pair here has a labelled right answer."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import (alias_collisions, bank_index, conflict_resolver, entity_merge, inbox_service, inbox_tend,
                          markdown_parser, merge_rejections, page_edits, predicates, web_settle, wrong_aliases)

TODAY = "2026-11-24"


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory: Path, msg: str = "seed") -> None:
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", msg, "--allow-empty")
    bank_index.invalidate(memory)


def _page(memory: Path, eid: str, name: str, typ: str = "company", aliases=(), body: str | None = None, **fm) -> None:
    meta = {"name": name, "type": typ, "status": "active", "confidence": 0.8, "created": "2026-10-01",
            "last_referenced": "2026-11-20", "source_episodes": [], "related": [], "version": 1,
            **({"aliases": list(aliases)} if aliases else {}), **fm}
    markdown_parser.write(memory / "entities" / f"{eid}.md", meta, body or f"## Summary\n{name} is a synthetic {typ}.\n")


def _question(memory: Path, num: int, asked: str, target: str, **extra) -> str:
    item = f"inbox-{num:03d}"
    fm = {"kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.8,
          "entity_id": asked, "entity_name": asked.replace("-", " ").title(), "merge_target_hint": target,
          "title": f"Is {asked} the same as {target}?", "uncertainty_type": f"Possible duplicate of {target}",
          "suggested_classification": "company — could refer to the same thing", "created_date": "2026-11-10", **extra}
    markdown_parser.write(memory / "inbox" / f"{item}.md", fm, "Context.")
    return item


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@example.test")
    _git(memory, "config", "user.name", "t")
    return memory


class Judge:
    """A scripted reader: the answer is looked up by the two page titles in the prompt, one per read."""

    def __init__(self, table: dict[frozenset, tuple[str, str] | str]):
        self.table, self.calls = table, []

    async def __call__(self, system: str, prompt: str):
        import re

        names = frozenset(re.findall(r'PAGE [AB]: "([^"]+)"', prompt))
        self.calls.append((names, "sceptical" in prompt))
        answer = self.table.get(names, "unsure")
        first, second = (answer, answer) if isinstance(answer, str) else answer
        return {"decision": second if "sceptical" in prompt else first, "reason": "synthetic", "_model": "haiku"}


def _labelled(memory: Path) -> dict:
    """The set and the right answer for each pair."""
    # (a) one thing under two names — mutual, and one-way.
    _page(memory, "nwdb", "NWDB", "tool", aliases=["Northwind Database"])
    _page(memory, "northwind-database", "Northwind Database", "tool", aliases=["NWDB"])
    _page(memory, "acme-cloud-co", "Acme Cloud Co", "company", aliases=["Acme Cloud"])
    _page(memory, "acme-cloud", "Acme Cloud", "company")
    # (b) a part and its whole.
    _page(memory, "lumen-search", "Lumen Search", "tool", aliases=["Lumen Platform"])
    _page(memory, "lumen-platform", "Lumen Platform", "tool")
    _page(memory, "pylib", "Pylib", "tool", aliases=["Snakelang"])
    _page(memory, "snakelang", "Snakelang", "concept")
    # (c) two unrelated things, one carrying the other's name.
    _page(memory, "harbor-institute", "Harbor Institute", "company", aliases=["Delta University"])
    _page(memory, "delta-university", "Delta University", "company")
    # (c) a short name two things fairly share; a third page is titled exactly that.
    _page(memory, "alpha-engine", "Alpha Reasoning Engine", "tool", aliases=["XQ"],
          source_episodes=["ep_2026-11-01_001"])
    _page(memory, "beta-toolkit", "Beta Quantum Toolkit", "tool", aliases=["XQ"])
    _page(memory, "xq", "XQ", "tool")
    # A saved link titled with a company's bare name.
    _page(memory, "solstice-co", "Solstice Co", "company", aliases=["Solstice"])
    _page(memory, "solstice", "Solstice", "media", origin="saved-link")
    # The person already said this pair is different.
    _page(memory, "orbit-labs", "Orbit Labs", "company", aliases=["Orbit Station"])
    _page(memory, "orbit-station", "Orbit Station", "company")
    merge_rejections.add_rejected(memory, "orbit-labs", "orbit-station")
    # The model cannot tell.
    _page(memory, "fern-app", "Fern App", "tool", aliases=["Fern"])
    _page(memory, "fern", "Fern", "concept")
    # Two people sharing a first name: ruling 74 owns them, nothing here reads them.
    _page(memory, "sam-ortega", "Sam Ortega", "person", aliases=["Sam"])
    _page(memory, "sam", "Sam", "person")
    # The person calls the first one XQ in their own words.
    markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                          {"id": "ep_2026-11-01_001", "timestamp": "2026-11-01T09:00:00+00:00", "processed": True,
                           "source": "claude-code", "title": "chat", "authorship": {"kind": "user"}},
                          "I asked about the XQ run again today.\n")
    for num, (asked, target) in enumerate([("nwdb", "northwind-database"), ("acme-cloud", "acme-cloud-co"),
                                           ("lumen-platform", "lumen-search"), ("harbor-institute", "delta-university"),
                                           ("solstice", "solstice-co"), ("fern", "fern-app")], 301):
        _question(memory, num, asked, target)
    _commit(memory)
    return {
        frozenset({"NWDB", "Northwind Database"}): ("same", "same"),
        frozenset({"Acme Cloud Co", "Acme Cloud"}): ("same", "same"),
        frozenset({"Lumen Search", "Lumen Platform"}): ("part", "part"),
        frozenset({"Pylib", "Snakelang"}): ("part", "same"),
        frozenset({"Harbor Institute", "Delta University"}): ("different", "different"),
        frozenset({"Alpha Reasoning Engine", "XQ"}): ("different", "different"),
        frozenset({"Beta Quantum Toolkit", "XQ"}): ("different", "different"),
        frozenset({"Fern App", "Fern"}): ("unsure", "unsure"),
    }


def _aliases(memory: Path, eid: str) -> list:
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter.get("aliases") or []


def _open(memory: Path) -> dict[str, dict]:
    return {p.stem: markdown_parser.parse(p).frontmatter for p in sorted((memory / "inbox").glob("inbox-*.md"))}


def _tend(memory: Path, judge, **kw):
    return asyncio.run(alias_collisions.tend(memory, SimpleNamespace(memory_path=memory), judge, **kw))


# ---------- finding the pairs ----------


def test_the_pairs_are_found_once_each_and_people_are_never_read(bank):
    _labelled(bank)
    found = {p.key: p for p in alias_collisions.pairs(bank)}
    assert found["northwind-database|nwdb"].mutual and not found["acme-cloud|acme-cloud-co"].mutual
    assert found["sam|sam-ortega"].skip == "person"
    assert {k for k, p in found.items() if not p.skip} == {
        "northwind-database|nwdb", "acme-cloud|acme-cloud-co", "lumen-platform|lumen-search", "pylib|snakelang",
        "delta-university|harbor-institute", "alpha-engine|xq", "beta-toolkit|xq", "solstice|solstice-co",
        "orbit-labs|orbit-station", "fern|fern-app"}


# ---------- the labelled set: decisions, wrong ones, questions ----------


def test_the_labelled_set_has_no_wrong_decision(bank):
    table = _labelled(bank)
    before = _open(bank)
    judge = Judge(table)
    report = _tend(bank, judge)
    # Two things: the alias is gone from the page that listed it, remembered, and nothing else was touched.
    assert _aliases(bank, "lumen-search") == []
    assert _aliases(bank, "harbor-institute") == []
    assert _aliases(bank, "beta-toolkit") == []                       # not called XQ in the person's words
    assert _aliases(bank, "alpha-engine") == ["XQ"]                   # called XQ in the person's own words: kept
    assert _aliases(bank, "orbit-labs") == []                         # the person's "different": no model was asked
    removed = markdown_parser.parse(bank / "entities" / "lumen-search.md").frontmatter
    assert "lumen platform" in page_edits.removed_aliases(removed)
    assert frozenset({"Orbit Labs", "Orbit Station"}) not in {c[0] for c in judge.calls}
    # One thing under two names, or a doubt: the aliases stay; the first is asked ONCE, the second held.
    assert _aliases(bank, "acme-cloud-co") == ["Acme Cloud"] and _aliases(bank, "nwdb") == ["Northwind Database"]
    assert _aliases(bank, "fern-app") == ["Fern"]
    assert _aliases(bank, "pylib") == ["Snakelang"]
    # A person's page is never touched.
    assert _aliases(bank, "sam-ortega") == ["Sam"]
    # The saved link took nothing and asked nothing.
    assert _aliases(bank, "solstice-co") == ["Solstice"]
    # Questions: six old unflagged ones before; after, one per kind-(a) pair, the closed ones are the two things and the
    # saved link; the question about the pair Sleep could not tell stays exactly as it was (ruling 29).
    after = _open(bank)
    assert len(before) == 6
    asked = {n: fm for n, fm in after.items() if fm.get("detected") == alias_collisions.DETECTED}
    assert len(asked) == 2 and set(after) == {"inbox-301", "inbox-302", "inbox-306"}
    assert after["inbox-306"] == before["inbox-306"]
    assert all(fm["fold_page"] is True and "one thing under two names" in fm["title"] for fm in asked.values())
    assert {frozenset({fm["entity_id"], fm["merge_target_hint"]}) for fm in asked.values()} == {
        frozenset({"nwdb", "northwind-database"}), frozenset({"acme-cloud", "acme-cloud-co"})}
    assert (report.removed, report.asked, report.held, report.quiet) == (4, 2, 3, 1)
    # Every settle is one commit by Sleep, listed with the rule.
    log = _git(bank, "log", "--format=%s")
    assert "Inbox settled by Sleep" in log
    settled = {markdown_parser.parse(p).frontmatter["settled"]["rule"] for p in (bank / "inbox" / "settled").glob("*.md")}
    assert settled == {alias_collisions.APART, alias_collisions.QUIET}   # a doubt writes no settle: it closes nothing


def test_a_second_run_reads_nothing_and_asks_nothing(bank):
    table = _labelled(bank)
    judge = Judge(table)
    _tend(bank, judge)
    _commit(bank, "after")
    calls, open_before = len(judge.calls), _open(bank)
    report = _tend(bank, judge)
    assert len(judge.calls) == calls and _open(bank) == open_before
    assert report.reads == 0 and report.asked == 0 and report.removed == 0


def test_a_model_that_is_not_there_still_settles_what_the_record_says(bank):
    _labelled(bank)
    report = _tend(bank, None, no_model=True)
    assert _aliases(bank, "orbit-labs") == [] and report.removed == 1   # the person's "different"
    assert _aliases(bank, "lumen-search") == ["Lumen Platform"]         # needs a read: untouched
    assert report.quiet == 1


def test_a_read_that_cannot_be_made_changes_nothing_and_is_tried_again_twice(bank):
    _page(bank, "lumen-search", "Lumen Search", "tool", aliases=["Lumen Platform"])
    _page(bank, "lumen-platform", "Lumen Platform", "tool")
    _question(bank, 301, "lumen-platform", "lumen-search")
    _commit(bank)

    async def broken(system, prompt):
        return {"nonsense": True}
    for _ in range(3):
        _tend(bank, broken)
    assert _aliases(bank, "lumen-search") == ["Lumen Platform"] and "inbox-301" in _open(bank)


def test_the_tail_step_in_sleep_runs_the_engine_free_half_with_no_model(bank):
    from api.services import sleep_cycle

    _labelled(bank)
    asyncio.run(sleep_cycle._alias_collisions_safely(bank, SimpleNamespace(memory_path=bank), user_triggered=False,
                                                     no_model=True))
    assert _aliases(bank, "orbit-labs") == [] and _aliases(bank, "lumen-search") == ["Lumen Platform"]
    # The same step with a plan the person did not switch on: no engine, the engine-free half still ran, nothing broke.
    assert "inbox-305" not in _open(bank)


# ---------- a question the person took back or put off, a doubt, the person's own words ----------


def _undo_a_quiet_settle(bank) -> str:
    """A company page with an alias, a saved link titled the same, an open question about the pair: Sleep closes it as
    quiet, the person takes that back. Returns the reopened question's id."""
    _page(bank, "solstice-co", "Solstice Co", "company", aliases=["Solstice"])
    _page(bank, "solstice", "Solstice", "media", origin="saved-link")
    _question(bank, 305, "solstice", "solstice-co")
    _commit(bank)
    assert _tend(bank, None, no_model=True).quiet == 1 and not _open(bank)
    _commit(bank, "settled")
    settled = next(p.stem for p in (bank / "inbox" / "settled").glob("*.md"))
    restored, _paths, _lines, _rec = inbox_tend.undo(bank, settled)
    _commit(bank, "undone")
    assert _open(bank)[restored]["sleep_settle"] == "undone"
    return restored


def test_a_question_the_person_took_back_is_never_closed_again(bank):
    item = _undo_a_quiet_settle(bank)
    head, before = _git(bank, "rev-parse", "HEAD"), _open(bank)
    for _ in range(2):
        report = _tend(bank, None, no_model=True)
        assert (report.quiet, report.skipped.get("person_holds")) == (0, 1)
    assert _open(bank) == before and item in _open(bank) and _git(bank, "rev-parse", "HEAD") == head
    assert alias_collisions.owns(bank, "solstice", "solstice-co")   # Stage 2 raises no second lead beside it


def test_a_question_the_person_put_off_is_never_closed_rewritten_or_counted(bank):
    _page(bank, "acme-cloud-co", "Acme Cloud Co", "company", aliases=["Acme Cloud"])
    _page(bank, "acme-cloud", "Acme Cloud", "company")
    _question(bank, 301, "acme-cloud", "acme-cloud-co", remind_after="2026-12-24")
    _commit(bank)
    judge = Judge({frozenset({"Acme Cloud Co", "Acme Cloud"}): ("same", "same")})
    before, head = _open(bank), _git(bank, "rev-parse", "HEAD")
    report = _tend(bank, judge, today=date(2026, 11, 24))
    assert judge.calls == [] and _open(bank) == before and _git(bank, "rev-parse", "HEAD") == head
    assert (report.asked, report.reads) == (0, 0)
    # The settle and the question writers refuse it too, whoever calls them.
    pair = next(p for p in alias_collisions.pairs(bank))
    assert alias_collisions.ask_sync(bank, pair, TODAY) is None and alias_collisions.open_questions(bank, pair, TODAY) == []
    assert not alias_collisions._settle_sync(bank, alias_collisions.Plan(pair, rule=alias_collisions.QUIET), TODAY)
    assert _open(bank) == before
    # The day it comes back the tending may read it again.
    report = _tend(bank, judge, today=date(2026, 12, 25))
    assert report.asked == 1 and len(judge.calls) == 2


def test_an_undone_settle_does_not_make_the_step_ask_a_second_question(bank):
    _page(bank, "acme-cloud-co", "Acme Cloud Co", "company", aliases=["Acme Cloud"])
    _page(bank, "acme-cloud", "Acme Cloud", "company")
    _question(bank, 301, "acme-cloud", "acme-cloud-co", sleep_settle="undone")
    _commit(bank)
    judge = Judge({frozenset({"Acme Cloud Co", "Acme Cloud"}): ("same", "same")})
    _tend(bank, judge)
    assert judge.calls == [] and list(_open(bank)) == ["inbox-301"] and "detected" not in _open(bank)["inbox-301"]


def test_a_doubt_closes_no_question_and_is_remembered(bank):
    table = _labelled(bank)
    judge = Judge(table)
    before = _open(bank)
    _tend(bank, judge)
    # The pair the model could not tell (unsure) and the pair its reads disagreed on: their questions stand as they were.
    assert _open(bank)["inbox-306"] == before["inbox-306"]
    assert alias_collisions.owns(bank, "fern", "fern-app") and alias_collisions.owns(bank, "pylib", "snakelang")
    # Remembered: nothing is read again until a page changes.
    _commit(bank, "after")
    calls = len(judge.calls)
    _tend(bank, judge)
    assert len(judge.calls) == calls and _open(bank)["inbox-306"] == before["inbox-306"]
    # A page it read changes: it is read again, and a doubt still closes nothing.
    page = bank / "entities" / "fern.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body + "\nMore words.\n")
    _commit(bank, "changed")
    _tend(bank, judge)
    assert len(judge.calls) == calls + 1 and _open(bank)["inbox-306"] == before["inbox-306"]


def test_a_read_of_two_things_does_not_close_the_question_when_the_persons_words_use_the_name(bank):
    _labelled(bank)
    _question(bank, 307, "xq", "alpha-engine")
    _commit(bank)
    _tend(bank, Judge({frozenset({"Alpha Reasoning Engine", "XQ"}): ("different", "different")}))
    assert "inbox-307" in _open(bank) and _aliases(bank, "alpha-engine") == ["XQ"]


def test_the_record_saying_two_but_not_the_person_never_closes_a_question_over_a_name_they_use(bank):
    # A relation claim (a model may have written it) holds the pair as two; the alias is the person's own word: held, open.
    _labelled(bank)
    _question(bank, 307, "xq", "alpha-engine")
    from api.services import entity_relations
    monkey = pytest.MonkeyPatch()
    monkey.setattr(entity_relations, "known", lambda mp, a, b: {a, b} == {"alpha-engine", "xq"})
    try:
        _commit(bank)
        report = _tend(bank, None, no_model=True)
    finally:
        monkey.undo()
    assert "inbox-307" in _open(bank) and report.held >= 1 and _aliases(bank, "alpha-engine") == ["XQ"]


def _episode(memory: Path, num: int, text: str) -> str:
    eid = f"ep_2026-10-{num:02d}_001"
    markdown_parser.write(memory / "episodes" / f"{eid}.md",
                          {"id": eid, "timestamp": f"2026-10-{num:02d}T09:00:00+00:00", "processed": True,
                           "source": "claude-code", "title": "chat", "authorship": {"kind": "user"}}, text)
    return eid


def test_the_persons_own_words_are_looked_for_in_every_conversation_the_page_lists(bank):
    # The name is used only in the oldest of twenty conversations, well past the twelve the guard used to read.
    ids = [_episode(bank, n, "XQ came up once.\n" if n == 1 else "Nothing about it today.\n") for n in range(1, 21)]
    _page(bank, "alpha-engine", "Alpha Reasoning Engine", "tool", aliases=["XQ"], source_episodes=ids)
    fm = markdown_parser.parse(bank / "entities" / "alpha-engine.md").frontmatter
    assert alias_collisions.called_by_own_words(bank, fm, "XQ")
    assert not alias_collisions.called_by_own_words(bank, fm, "Zed")
    # Only the person's own turns count: an agent's saved note naming it does not.
    note = _episode(bank, 25, "XQ is mentioned by the agent only.\n")
    p = bank / "episodes" / f"{note}.md"
    parsed = markdown_parser.parse(p)
    markdown_parser.write(p, {**parsed.frontmatter, "evidence_kind": "assistant"}, parsed.body)
    assert not alias_collisions.called_by_own_words(bank, {"source_episodes": [note]}, "XQ")


def test_a_page_with_too_many_conversations_to_scan_keeps_its_alias(bank, monkeypatch):
    monkeypatch.setattr(alias_collisions, "MAX_EPISODES", 3)
    ids = [_episode(bank, n, "Nothing about it today.\n") for n in range(1, 6)]
    assert alias_collisions.called_by_own_words(bank, {"source_episodes": ids}, "Zed")      # not scanned: kept
    assert not alias_collisions.called_by_own_words(bank, {"source_episodes": ids[:3]}, "Zed")


def test_the_scan_stops_at_the_first_hit(bank, monkeypatch):
    from api.services import full_name_join

    ids = [_episode(bank, n, "XQ again.\n") for n in range(1, 11)]
    seen = []
    real = full_name_join._user_turns
    monkeypatch.setattr(full_name_join, "_user_turns", lambda mp, eid: seen.append(eid) or real(mp, eid))
    assert alias_collisions.called_by_own_words(bank, {"source_episodes": ids}, "XQ")
    assert seen == [ids[-1]]


# ---------- undo, and the question Stage 2 would have raised ----------


def test_taking_the_removal_back_keeps_the_name_for_good(bank):
    table = _labelled(bank)
    _tend(bank, Judge(table))
    rec = next(p for p in (bank / "inbox" / "settled").glob("*.md")
               if markdown_parser.parse(p).frontmatter["settled"]["rule"] == alias_collisions.APART
               and any(r["page"] == "lumen-search" for r in markdown_parser.parse(p).frontmatter["settled"]["alias_apart"]))
    item = rec.stem
    restored, paths, lines, _rec = inbox_tend.undo(bank, item)
    fm = markdown_parser.parse(bank / "entities" / "lumen-search.md").frontmatter
    assert fm["aliases"] == ["Lumen Platform"] and fm[wrong_aliases.KEPT] == ["Lumen Platform"]
    assert not (bank / "inbox" / "settled" / f"{item}.md").exists()
    assert f"inbox/{restored}.md" not in paths or not (bank / "inbox" / f"{restored}.md").exists()
    _commit(bank, "undo")
    # Kept: never a pair again, never read, never removed.
    assert "lumen-platform|lumen-search" not in {p.key for p in alias_collisions.pairs(bank)}
    # A second run changes nothing at all: no commit, no read, the name stays.
    head, judge = _git(bank, "rev-parse", "HEAD"), Judge(table)
    _tend(bank, judge)
    assert _git(bank, "rev-parse", "HEAD") == head and _aliases(bank, "lumen-search") == ["Lumen Platform"]
    assert not any(c[0] == frozenset({"Lumen Search", "Lumen Platform"}) for c in judge.calls)


def test_the_pair_is_the_tendings_so_stage_2_raises_no_lead_for_it(bank):
    table = _labelled(bank)
    assert not alias_collisions.owns(bank, "lumen-platform", "lumen-search")
    _tend(bank, Judge(table))
    assert alias_collisions.owns(bank, "fern", "fern-app")             # held
    assert alias_collisions.owns(bank, "acme-cloud", "acme-cloud-co")   # asked


# ---------- the old rule that read an alias as a join ----------


def test_same_spelling_no_longer_decides_two_pages_that_meet_only_on_an_alias(bank):
    _page(bank, "harbor-institute", "Harbor Institute", "company", aliases=["Delta University"])
    _page(bank, "delta-university", "Delta University", "company")
    item = _question(bank, 301, "delta-university", "harbor-institute", entity_name="Delta University")
    _commit(bank)
    path = bank / "inbox" / f"{item}.md"
    decided, why = inbox_tend.policy(bank, path, markdown_parser.parse(path).frontmatter, today=TODAY)
    assert decided is None and why == "alias_collision"
    # The same name written two ways on the TITLE is still the older rule's.
    _page(bank, "delta-uni", "Delta  University", "company")
    item2 = _question(bank, 302, "delta-uni", "delta-university", entity_name="Delta  University")
    _commit(bank)
    decided, _why = inbox_tend.policy(bank, bank / "inbox" / f"{item2}.md",
                                      markdown_parser.parse(bank / "inbox" / f"{item2}.md").frontmatter, today=TODAY)
    assert decided is not None and decided.rule == "same_spelling"


# ---------- the question for one thing under two names ----------


def test_the_one_question_folds_on_the_persons_yes_and_a_no_removes_the_alias(bank):
    table = _labelled(bank)
    _tend(bank, Judge(table))
    _commit(bank, "asked")
    item = next(n for n, fm in _open(bank).items() if fm.get("detected") == alias_collisions.DETECTED
                and "acme-cloud" in (fm["entity_id"], fm["merge_target_hint"]))
    fm = _open(bank)[item]
    asyncio.run(inbox_service.resolve(item, InboxResolveRequest(action="merge", merge_target=fm["merge_target_hint"]),
                                      SimpleNamespace(memory_path=bank, inbox_defer_days=30)))
    assert not (bank / "entities" / f"{fm['entity_id']}.md").exists()
    assert (bank / "entities" / f"{fm['merge_target_hint']}.md").exists()


def test_a_no_to_the_one_question_takes_the_alias_off_without_another_read(bank):
    table = _labelled(bank)
    _tend(bank, Judge(table))
    _commit(bank, "asked")
    item = next(n for n, fm in _open(bank).items() if "acme-cloud" in (fm["entity_id"], fm["merge_target_hint"]))
    asyncio.run(inbox_service.resolve(item, InboxResolveRequest(action="reject"),
                                      SimpleNamespace(memory_path=bank, inbox_defer_days=30)))
    _commit(bank, "answered")
    judge = Judge(table)
    _tend(bank, judge)
    assert _aliases(bank, "acme-cloud-co") == [] and judge.calls == []


# ---------- the birth half ----------


def _change(eid: str, name: str, typ: str, aliases, action: str = "create") -> dict:
    return {"id": eid, "action": action, "source_episodes": ["ep_2026-11-01_001"],
            "entity": {"name": name, "type": typ, "confidence": 0.8, "description": "x", "aliases": list(aliases),
                       "source_episode": "ep_2026-11-01_001", "source_episode_timestamp": "2026-11-01T10:00:00+00:00",
                       "tags": [], "history_entries": []}}


def test_a_page_never_comes_to_list_another_pages_title_as_its_own_name(bank):
    _page(bank, "northwind-university", "Northwind University", "company")
    _page(bank, "atletico-madrid", "Atlético Madrid", "company")   # an id that is not the alias's own slug
    _page(bank, "club-x", "Club X", "company")
    conflict_resolver.apply_changes(
        [_change("northwind-labs", "Northwind Labs", "company", ["Northwind University", "NWL"]),
         _change("club-x", "Club X", "company", ["Atlético Madrid"], "update")], bank)
    assert _aliases(bank, "northwind-labs") == ["NWL"] and _aliases(bank, "club-x") == []
    # A merge does not carry such a name over to the page that stays.
    _page(bank, "loser", "Loser Co", "company", aliases=["Northwind University", "Lo Co"])
    _page(bank, "winner", "Winner Co", "company")
    entity_merge.merge_entities(bank, "loser", "winner")
    assert _aliases(bank, "winner") == ["Lo Co", "Loser Co"]


def test_people_and_saved_links_are_outside_the_birth_guard(bank):
    _page(bank, "sam", "Sam", "person")
    _page(bank, "solstice", "Solstice", "media")
    assert not wrong_aliases.title_of_other_page(bank, "sam-ortega", "Sam", "person")
    assert not wrong_aliases.title_of_other_page(bank, "solstice-co", "Solstice", "company")   # a quiet page's title
    assert not wrong_aliases.title_of_other_page(bank, "sam-ortega", "Sam", "company")
    assert not wrong_aliases.title_of_other_page(bank, "solstice-co", "Solstice Co", "company")   # its own title


# ---------- the dry run says what would really happen ----------


def test_the_dry_run_prints_one_stable_line_per_pair_and_no_false_join(bank, capsys):
    import importlib.util

    _labelled(bank)
    spec = importlib.util.spec_from_file_location(
        "answered_questions_dry_run", Path(__file__).resolve().parents[2] / "scripts" / "answered_questions_dry_run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--memory", str(bank)]) == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("ALIAS ")]
    assert len(lines) == 11 and lines == sorted(lines, key=lambda ln: ln.split()[1:3])
    assert "ALIAS orbit-labs orbit-station one-way company/company alias_apart record_says_two" in lines
    assert any(ln.startswith("ALIAS solstice solstice-co") and " alias_quiet saved_link questions: inbox-305" in ln
               for ln in lines)
    assert any(" skip person" in ln and ln.startswith("ALIAS sam ") for ln in lines)
    assert not any(" JOIN " in ln for ln in out.splitlines() if ln.startswith("inbox-")) and "would JOIN or FOLD pages: none" in out   # the resolver refuses a fold of two pages that meet only on an alias: never a join
    def files():
        return {p.name: p.read_bytes() for p in bank.rglob("*") if p.is_file() and ".git" not in p.parts}
    before = files()
    module.main(["--memory", str(bank)])
    assert before == files()


def test_the_dry_run_says_a_held_question_is_left_and_a_doubt_closes_nothing(bank, capsys):
    import importlib.util

    _undo_a_quiet_settle(bank)
    _page(bank, "fern-app", "Fern App", "tool", aliases=["Fern"])
    _page(bank, "fern", "Fern", "concept")
    _question(bank, 306, "fern", "fern-app")
    _commit(bank)
    _tend(bank, Judge({frozenset({"Fern App", "Fern"}): ("unsure", "unsure")}))
    spec = importlib.util.spec_from_file_location(
        "answered_questions_dry_run2", Path(__file__).resolve().parents[2] / "scripts" / "answered_questions_dry_run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--memory", str(bank)]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ALIAS ")]
    assert any(ln.startswith("ALIAS solstice solstice-co") and " skip person_holds questions: inbox-" in ln for ln in lines)
    assert not any("alias_doubt" in ln and "questions:" in ln for ln in lines)
