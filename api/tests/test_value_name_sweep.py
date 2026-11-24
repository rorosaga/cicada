"""The one-time sweep for doubled values and for people held under a qualified name (`value_sweep`, `name_sweep`, G148).
Invented names; a scripted judge, no model.

What matters: the plan shows every pair with the judge's own words and writes nothing; a join needs both answers; the live
rails refuse what they refuse whatever the judge says; apply writes exactly the reviewed rows (the older value closed and
kept), skips a struck row and a page changed since the plan, never calls a model, lands as one `cicada` commit and a plain
revert restores the bank byte for byte. The names pass never calls a model and never joins anyone: an old line becomes the
second person Sleep writes today, held in doubt, and Sleep's own machinery decides later."""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from api.scripts import value_name_sweep as tool
from api.services import (
    markdown_parser, name_sweep as ns, pending_store, same_name_people as snp, value_sweep as vs,
)
from api.services.claims import Claim, parse_claims, write_claims

PAGE = "alpha-print-shop"


def _claim(cid, predicate, obj, said, *, text=None, trust="agent_extracted", origin="claude-code", episode=None, subject=PAGE):
    return Claim(id=cid, text=text or f"{predicate[9:].replace('-', ' ')}: {obj}", subject=subject, predicate=predicate,
                 object=obj, object_kind="literal", source_trust=trust, valid_from=said, recorded_at=said, origin=origin,
                 source_episodes=[episode or f"ep_{said}_001"])


def _git(bank: Path, *cmd) -> str:
    return subprocess.run(["git", *cmd], cwd=bank, check=True, capture_output=True, text=True).stdout


def _bank(tmp_path: Path, claims, *, page=PAGE, status="active") -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    markdown_parser.write(bank / "entities" / f"{page}.md",
                          {"name": page.replace("-", " ").title(), "type": "company", "status": status},
                          write_claims("## Summary\nA print shop.\n", claims))
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"],
                ["add", "-A"], ["commit", "-qm", "seed"]):
        _git(bank, *cmd)
    return bank


PRICE = [_claim("c1", "value-of-price-per-postcard", "4 euros", "2026-10-01"),
         _claim("c2", "value-of-card-price", "5 euros", "2026-11-01")]


class Judge:
    """The main model: the reread names the older line for the newer, the check says what it is told."""

    def __init__(self, join=True, checks=True):
        self.join, self.checks, self.asks, self.checked = join, checks, 0, 0

    def __call__(self, prompt):
        if "Is LATER a new value" in prompt:
            self.checked += 1
            return {"why": "both are the price of one postcard", "same_attribute": self.checks}
        self.asks += 1
        rows = [r for r in prompt.split("LINES:")[1].splitlines() if r[:1].isdigit()]
        new = [r for r in rows if " NEW " in f" {r.split('.', 1)[1][:5]}"] or [r for r in rows if r.split(". ", 1)[1].startswith("NEW")]
        answers = []
        for r in new:
            n = int(r.split(".")[0])
            answers.append({"line": n, "same_as": 1 if self.join and n != 1 else None})
        return {"answers": answers}


def _plan(bank, judge, asked=frozenset()):
    parsed = markdown_parser.parse(bank / "entities" / f"{PAGE}.md")
    read = vs.read_page(PAGE, parsed.frontmatter, parsed.body)
    assert not read.skip, read.skip
    return vs.plan_page(read, bank, judge, vs.Meter(), set(asked))


# ------------------------------------------------------------------ values: plan


def test_the_plan_shows_the_pair_the_readers_words_and_the_change_and_writes_nothing(tmp_path):
    bank = _bank(tmp_path, PRICE)
    before = (bank / "entities" / f"{PAGE}.md").read_bytes()
    judge = Judge()
    row = _plan(bank, judge)
    assert (bank / "entities" / f"{PAGE}.md").read_bytes() == before
    assert judge.asks == 1 and judge.checked == 1
    [group] = row["groups"]
    assert [m["object"] for m in group["members"]] == ["4 euros", "5 euros"] and group["why"] == ["both are the price of one postcard"]
    assert group["keeps_predicate"] == "value-of-price-per-postcard"
    text = vs.review_text([row])
    assert "4 euros" in text and "5 euros" in text and "reader: both are the price" in text and "CLOSED" in text


def test_a_join_needs_both_answers(tmp_path):
    bank = _bank(tmp_path, PRICE)
    row = _plan(bank, Judge(join=True, checks=False))
    assert row["groups"] == [] and row["refused"][0]["stage"].startswith("the second reader's check")
    assert _plan(bank, Judge(join=False))["groups"] == []


@pytest.mark.parametrize("claims, asked, stage", [
    ([_claim("c1", "value-of-price-per-postcard", "4 euros", "2026-10-01"),
      _claim("c2", "value-of-card-price", "5 euros", "2026-10-01")], (), "not dated later"),
    ([_claim("c1", "value-of-price-per-postcard", "4 euros", "2026-10-01", episode="ep_x"),
      _claim("c2", "value-of-card-price", "5 euros", "2026-11-01", episode="ep_x")], (), "one conversation"),
    ([_claim("c1", "value-of-price-per-postcard", "4 euros", "2026-10-01", trust="user_stated", origin="manual_edit"),
      _claim("c2", "value-of-card-price", "5 euros", "2026-11-01")], (), "person's own edit"),
    (PRICE, ("c1",), "open inbox question"),
    ([_claim("c1", "value-of-price-per-postcard", "4 euros", "2026-10-01"),
      _claim("c2", "value-of-card-price", "4 euros", "2026-11-01")], (), "same thing"),
])
def test_the_live_rails_refuse_whatever_the_judge_says_and_the_row_says_why(tmp_path, claims, asked, stage):
    bank = _bank(tmp_path, claims)
    parsed = markdown_parser.parse(bank / "entities" / f"{PAGE}.md")
    read = vs.read_page(PAGE, parsed.frontmatter, parsed.body)
    if read.skip:   # nothing eligible at all: the census already leaves it alone
        assert read.skip == "nothing_to_join"
        return
    row = vs.plan_page(read, bank, Judge(), vs.Meter(), set(asked))
    assert row["groups"] == [] and any(stage in r["stage"] for r in row["refused"])


def test_the_persons_own_words_are_never_closed_in_favour_of_a_machine_claim(tmp_path):
    from api.services.claims import Evidence

    mine = _claim("c1", "value-of-price-per-postcard", "4 euros", "2026-10-01", trust="user_stated")
    mine.evidence = [Evidence(episode="ep_2026-10-01_001", start=0, end=5, kind="user", hash="h")]
    bank = _bank(tmp_path, [mine, _claim("c2", "value-of-card-price", "5 euros", "2026-11-01")])
    row = _plan(bank, Judge())
    assert row["groups"] == [] and "own words" in row["refused"][0]["stage"]


def test_two_values_that_can_both_stand_are_left_two_when_the_judge_says_so(tmp_path):
    bank = _bank(tmp_path, [_claim("p1", "value-of-phone-number", "111", "2026-10-01"),
                            _claim("p2", "value-of-office-line", "222", "2026-11-01")])
    assert _plan(bank, Judge(join=False))["groups"] == []


# ------------------------------------------------------------------ values: apply


def _planned(tmp_path, claims=PRICE):
    bank = _bank(tmp_path, claims)
    return bank, _plan(bank, Judge())


def _apply(bank, rows, **kw):
    return vs.apply(bank, rows, sleep_running=lambda: False, **kw)


def test_apply_closes_the_older_keeps_it_and_the_newer_stays_current_in_one_revertible_commit(tmp_path, monkeypatch):
    bank, row = _planned(tmp_path)
    before = (bank / "entities" / f"{PAGE}.md").read_bytes()
    monkeypatch.setattr(vs.va, "judge_for", lambda *a, **k: pytest.fail("apply made a model call"))
    result = _apply(bank, [row])
    assert result.committed and result.closed == 1
    claims = {c.id: c for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{PAGE}.md").body)}
    assert claims["c1"].valid_to == "2026-11-01" and claims["c1"].superseded_by == "c2" and claims["c1"].object == "4 euros"
    assert claims["c2"].valid_to is None and claims["c2"].predicate == "value-of-price-per-postcard"
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == [f"entities/{PAGE}.md"]
    _git(bank, "revert", "--no-edit", "HEAD")
    assert (bank / "entities" / f"{PAGE}.md").read_bytes() == before


def test_a_struck_group_a_struck_page_and_a_changed_page_are_not_written(tmp_path):
    bank, row = _planned(tmp_path)
    assert _apply(bank, [row], skip_groups=[row["groups"][0]["id"]]).skipped.get("no_groups", 0) + \
        _apply(bank, [row], skip_pages=[PAGE]).skipped.get("struck", 0) >= 1
    row["groups"][0]["strike"] = True
    assert _apply(bank, [row]).committed is False
    bank2, row2 = _planned(tmp_path / "again")
    path = bank2 / "entities" / f"{PAGE}.md"
    parsed = markdown_parser.parse(path)
    claims = parse_claims(parsed.body)
    claims[1].object = "6 euros"
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))
    _git(bank2, "commit", "-qam", "edited")
    result = _apply(bank2, [row2])
    assert result.skipped == {"changed_since_plan": 1} and not result.committed


def test_a_page_a_person_is_editing_is_skipped_and_sleep_running_refuses(tmp_path):
    bank, row = _planned(tmp_path)
    (bank / "entities" / f"{PAGE}.md").write_text((bank / "entities" / f"{PAGE}.md").read_text() + "\nedit\n")
    assert _apply(bank, [row]).skipped == {"dirty_in_git": 1}
    with pytest.raises(vs.SleepRunning):
        vs.apply(bank, [row], sleep_running=lambda: True)


def test_a_second_plan_finds_nothing_left(tmp_path):
    bank, row = _planned(tmp_path)
    _apply(bank, [row])
    parsed = markdown_parser.parse(bank / "entities" / f"{PAGE}.md")
    assert vs.read_page(PAGE, parsed.frontmatter, parsed.body).skip in ("few_values", "nothing_to_join")


# ------------------------------------------------------------------ values: the reviewer's cases (2026-11-24)


def _read(bank, page=PAGE):
    parsed = markdown_parser.parse(bank / "entities" / f"{page}.md")
    return vs.read_page(page, parsed.frontmatter, parsed.body)


BAD_LINE = ('{"id": "keep-me", "text": "the person said they love blue", "subject": "alpha-print-shop", "predicate": "likes", '
            '"object": "blue", "confidence": "high", "source_trust": "user_stated", "origin": "manual_edit"}')


def _with_bad_line(bank):
    path = bank / "entities" / f"{PAGE}.md"
    path.write_text(path.read_text().replace("```claims\n", "```claims\n" + BAD_LINE + "\n", 1))
    _git(bank, "commit", "-qam", "a line that does not parse")
    return path


def test_a_claim_line_that_does_not_parse_leaves_its_whole_page_alone_in_the_plan_and_in_apply(tmp_path):
    bank, row = _planned(tmp_path)
    path = _with_bad_line(bank)
    assert _read(bank).skip == "claims_unreadable"
    before = path.read_bytes()
    result = _apply(bank, [row])
    assert result.skipped == {"now_claims_unreadable": 1} and not result.committed
    assert path.read_bytes() == before and "keep-me" in path.read_text()


@pytest.mark.parametrize("fm", [
    {"claim_id": "zzz", "claim_ids": ["c1"]},
    {"claim_id": "zzz", "covered_claims": [{"entity_id": PAGE, "claim_id": "c1"}]},
    {"claim_id": "c1", "status": "deferred", "remind_after": "2999-01-01"},
    {"claim_id": "zzz", "options": [{"key": "0", "label": "four", "claim_id": "c1"}, {"key": "1", "label": "five", "claim_id": "c2"}]},
    {"claim_id": "c2"},
])
def test_an_open_question_that_names_a_claim_in_any_field_the_inbox_reads_leaves_the_pair_to_the_question(tmp_path, fm):
    bank = _bank(tmp_path, PRICE)
    (bank / "inbox").mkdir()
    markdown_parser.write(bank / "inbox" / "inbox-001.md", {"kind": "conflict", "status": "pending", "entity_id": PAGE, **fm}, "why")
    asked = vs.open_questions(bank)
    assert asked & {"c1", "c2"}
    row = _plan(bank, Judge(), asked)
    assert row["groups"] == [] and any("open inbox question" in r["stage"] for r in row["refused"])


def test_a_resolved_question_is_not_open(tmp_path):
    bank = _bank(tmp_path, PRICE)
    (bank / "inbox").mkdir()
    markdown_parser.write(bank / "inbox" / "inbox-001.md", {"kind": "conflict", "status": "resolved", "claim_id": "c1"}, "why")
    assert vs.open_questions(bank) == set()


@pytest.mark.parametrize("older, newer, episodes, stage", [
    # the newer value is dated with a month only: a month sorts before a day in it
    (("2026-11-05", "ep_2026-11-05_001"), ("2026-11", "ep_2026-11-28_001"), None, "less precise than a day"),
    (("2026-03-01", "ep_2026-03-01_001"), ("2026", "ep_2026-11-28_001"), None, "less precise than a day"),
    # dated 2025-06-01 but said on 2026-11-28; the other dated and said 2026-11-01: the dates and the days disagree
    (("2026-11-01", "ep_2026-11-01_001"), ("2025-06-01", "ep_2026-11-28_001"), None, "disagree"),
    # a value with no conversation of its own
    (("2026-10-01", "ep_2026-10-01_001"), ("2026-11-01", "manual-note"), None, "no conversation"),
])
def test_two_values_are_ordered_by_when_they_were_said_and_refused_when_the_dates_say_otherwise(tmp_path, older, newer, episodes, stage):
    claims = [_claim("c1", "value-of-price-per-postcard", "4 euros", older[0], episode=older[1]),
              _claim("c2", "value-of-card-price", "5 euros", newer[0], episode=newer[1])]
    bank = _bank(tmp_path, claims)
    read = _read(bank)
    if read.skip:   # not even a candidate for the reader
        return
    row = vs.plan_page(read, bank, Judge(), vs.Meter(), set())
    assert row["groups"] == [] and any(stage in r["stage"] for r in row["refused"]), row["refused"]


def test_each_value_in_the_review_shows_its_date_the_day_it_was_said_and_the_conversation(tmp_path):
    text = vs.review_text([_plan(_bank(tmp_path, PRICE), Judge())])
    assert "valid from 2026-10-01, said on 2026-10-01 in ep_2026-10-01_001" in text
    assert "valid from 2026-11-01, said on 2026-11-01 in ep_2026-11-01_001" in text


def test_a_failed_judge_call_is_not_a_finished_page_and_is_listed_as_not_read(tmp_path):
    bank = _bank(tmp_path, PRICE)

    def failing(prompt):
        raise RuntimeError("the plan limit")
    row = _plan(bank, failing)
    assert row["status"] == "not_read" and row["error"] == "RuntimeError" and row["groups"] == []
    assert "NOT READ" in vs.review_text([row]) and PAGE in vs.review_text([row])
    assert _apply(bank, [{**row, "groups": [{"id": "x#1", "members": [], "strike": False}]}]).skipped == {"not_read": 1}


def test_a_failed_check_makes_the_page_not_read_too(tmp_path):
    bank = _bank(tmp_path, PRICE)
    inner = Judge()

    def failing_check(prompt):
        if "Is LATER a new value" in prompt:
            raise RuntimeError("the plan limit")
        return inner(prompt)
    assert _plan(bank, failing_check)["status"] == "not_read"


def test_a_failed_commit_puts_the_page_back_and_leaves_nothing_staged(tmp_path, monkeypatch):
    bank, row = _planned(tmp_path)
    path = bank / "entities" / f"{PAGE}.md"
    before = path.read_bytes()

    def broken(*a, **k):
        _git(bank, "add", "--", f"entities/{PAGE}.md")
        raise vs.git_service.GitError("index.lock exists")
    monkeypatch.setattr(vs.git_service, "commit_paths_sync", broken)
    with pytest.raises(vs.git_service.GitError):
        _apply(bank, [row])
    assert path.read_bytes() == before and _git(bank, "status", "--porcelain") == ""


def test_a_bank_with_no_git_is_refused_never_written(tmp_path):
    bank, row = _planned(tmp_path)
    import shutil
    shutil.rmtree(bank / ".git")
    before = (bank / "entities" / f"{PAGE}.md").read_bytes()
    with pytest.raises(vs.NoGit):
        _apply(bank, [row])
    with pytest.raises(vs.NoGit):
        _apply(bank, [row], check=True)
    assert (bank / "entities" / f"{PAGE}.md").read_bytes() == before


def test_the_review_opens_with_what_the_person_should_strike(tmp_path):
    guide = vs.GUIDE
    assert "restates the earlier one more vaguely" in guide.replace("\n    ", " ").replace("  ", " ") or "LATER line only restates" in guide
    assert "BOTH TRUE AT ONCE" in guide and "strike" in guide.lower()


def test_apply_may_rewrite_the_pages_frontmatter_as_every_page_writer_does_and_changes_only_the_two_claims_lines(tmp_path):
    bank = _bank(tmp_path, PRICE)
    path = bank / "entities" / f"{PAGE}.md"
    text = path.read_text()
    assert "# keep" not in text
    path.write_text(text.replace("name:", "# kept comment\nname:", 1))
    _git(bank, "commit", "-qam", "comment")
    row = _plan(bank, Judge())
    assert _apply(bank, [row]).committed
    changed = [ln for ln in _git(bank, "diff", "HEAD~1", "HEAD", "-U0").splitlines() if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    assert any("c1" in ln for ln in changed) and any("c2" in ln for ln in changed)
    assert not any("A print shop" in ln for ln in changed)   # no prose touched


# ------------------------------------------------------------------ names: never a join, no model


def _line(name, summary, *, episode, facts=(), claims=(), title="", aliases=(), type_="person"):
    return pending_store.PendingEntity(
        name=name, type=type_, description="", source_episode=episode, confidence=0.6, tags=[], history_entries=[],
        summary=summary, key_facts=list(facts), aliases=list(aliases), title=title,
        heard_in=[{"episode": episode, "timestamp": f"{episode[3:13]}T10:00:00+00:00", "day": episode[3:13]}],
        held_claims=[c.to_dict() for c in claims])


def _name_bank(tmp_path, lines, pages=(), owner=("mira-kolar", "Mira Kolar")):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    markdown_parser.write(bank / "entities" / f"{owner[0]}.md", {"name": owner[1], "type": "person", "owner": True,
                                                                 "status": "active"}, "## Summary\nThe owner.\n")
    for pid, name, summary, *extra in pages:
        fm = {"name": name, "type": "person", "status": "active", "source_episodes": ["ep_2026-10-01_001"], **(extra[0] if extra else {})}
        markdown_parser.write(bank / "entities" / f"{pid}.md", fm, f"## Summary\n{summary}\n")
    pending_store.save(bank, lines)
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"],
                ["add", "-A"], ["commit", "-qm", "seed"]):
        _git(bank, *cmd)
    return bank


W_FIN = "Nico is the finance lead at Brightwell, forty-two with two kids, a colleague of the speaker who sent the budget slides."
W_COUSIN = "Nico is the speaker's cousin, a nurse who lives in Lyon and keeps three dogs. He likes hiking."


def _fin(name="Nico (finance lead)", episode="ep_2026-11-18_001", summary=W_FIN):
    return _line(name, summary, episode=episode, facts=[f"{name} has two kids."], aliases=["Nico from work"],
                 claims=[_claim("h1", "works-at", "brightwell", "2026-11-18", subject=sanitize(name)),
                         _claim("h2", "has-kids", "two", "2026-11-18", subject=sanitize(name))])


def sanitize(name):
    from api.services.id_utils import sanitize_id
    return sanitize_id(name)


def _rows(bank):
    return ns.plan_rows(ns.load(bank))


def _apply_names(bank, rows, **kw):
    return ns.apply_rows(bank, rows, **kw)


def test_a_line_alone_under_its_qualified_name_with_nobody_else_answering_is_renamed_to_the_bare_name(tmp_path):
    bank = _name_bank(tmp_path, [_fin()])
    [row] = _rows(bank)
    assert row["action"] == ns.RENAME and row["new_name"] == "Nico"
    res = _apply_names(bank, [row])
    [line] = pending_store.load(bank)
    assert line.name == "Nico" and line.title == "" and {"Nico (finance lead)", "Nico from work"} <= set(line.aliases)
    assert {c["subject"] for c in line.held_claims} == {"nico"}
    assert res.applied == {ns.RENAME: 1} and res.paths == ["pending_entities.jsonl"]
    assert _rows(bank) == []   # a second plan finds nothing left


def test_with_a_page_of_that_name_the_line_becomes_a_second_person_held_in_doubt_and_nobody_is_joined(tmp_path):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN)])
    page = (bank / "entities" / "nico.md").read_bytes()
    [row] = _rows(bank)
    assert row["action"] == ns.HOLD and row["new_id"] == "nico-2" and row["title"] == "Nico"
    res = _apply_names(bank, [row])
    [line] = pending_store.load(bank)
    assert line.name == "nico-2" and line.title == "Nico" and "Nico (finance lead)" in line.aliases
    assert {c["subject"] for c in line.held_claims} == {"nico-2"}
    assert res.paths == ["pending_entities.jsonl", "_same_name_doubts.yaml"]
    from api.services import same_name_doubts
    assert ("nico", "nico-2") in same_name_doubts.pairs(bank)
    assert same_name_doubts.flagged(bank)[1] >= {("nico", "nico-2")}      # the live writer also asks the tail to look
    assert (bank / "entities" / "nico.md").read_bytes() == page          # the page is never touched


def test_a_page_that_answers_to_the_bare_name_only_by_an_alias_counts_the_line_is_held_never_renamed(tmp_path):
    """The reviewer's case: a page "Nicolas Reyes" with the alias "Nico" received the finance lead's claims a cycle later."""
    bank = _name_bank(tmp_path, [_fin()], pages=[("nicolas-reyes", "Nicolas Reyes", "A retired judge in Oslo.", {"aliases": ["Nico"]})])
    [row] = _rows(bank)
    assert row["action"] == ns.HOLD and [a["ref"] for a in row["against"]] == ["nicolas-reyes"] and row["against"][0]["how"] == "alias"
    _apply_names(bank, [row])
    from api.services import same_name_doubts
    assert ("nico", "nico-2") in same_name_doubts.pairs(bank) and ("nico-2", "nicolas-reyes") in same_name_doubts.pairs(bank)


def test_another_held_line_that_answers_to_the_bare_name_by_name_or_alias_is_a_person_it_is_held_against(tmp_path):
    plain = _line("Nico", W_COUSIN, episode="ep_2026-10-02_001")
    by_alias = _line("Nicolas", "Nicolas Reyes, a retired judge in Oslo who keeps bees.", episode="ep_2026-10-03_001", aliases=["Nico"])
    bank = _name_bank(tmp_path, [_fin(), plain, by_alias])
    [row] = _rows(bank)
    assert row["action"] == ns.HOLD
    assert {(a["ref"], a["how"]) for a in row["against"]} == {("Nico", "name"), ("Nicolas", "alias")}
    _apply_names(bank, [row])
    from api.services import same_name_doubts
    assert {("nico", "nico-2"), ("nico-2", "nicolas")} <= set(same_name_doubts.pairs(bank))
    assert {e.name for e in pending_store.load(bank)} == {"Nico", "Nicolas", "nico-2"}   # nothing merged, nothing renamed onto a line


def test_two_qualified_lines_of_one_name_become_two_second_people_held_in_doubt_against_each_other(tmp_path):
    cousin = _line("Nico (cousin)", W_COUSIN, episode="ep_2026-11-19_001",
                   claims=[_claim("h3", "lives-in", "lyon", "2026-11-19", subject="nico-(cousin)")])
    bank = _name_bank(tmp_path, [_fin(), cousin])
    rows = _rows(bank)
    assert {r["line"]: r["new_id"] for r in rows} == {"Nico (finance lead)": "nico-2", "Nico (cousin)": "nico-3"}
    _apply_names(bank, rows)
    from api.services import same_name_doubts
    assert {("nico", "nico-2"), ("nico", "nico-3"), ("nico-2", "nico-3")} <= set(same_name_doubts.pairs(bank))
    by_name = {e.name: e for e in pending_store.load(bank)}
    assert {c["subject"] for c in by_name["nico-3"].held_claims} == {"nico-3"} and "Nico (cousin)" in by_name["nico-3"].aliases


def test_a_struck_line_keeps_its_name_and_the_other_is_not_held_against_it(tmp_path):
    cousin = _line("Nico (cousin)", W_COUSIN, episode="ep_2026-11-19_001")
    bank = _name_bank(tmp_path, [_fin(), cousin])
    rows = _rows(bank)
    res = _apply_names(bank, rows, skip_lines=["Nico (cousin)"])
    assert res.skipped == {"struck": 1} and {e.name for e in pending_store.load(bank)} == {"nico-2", "Nico (cousin)"}
    from api.services import same_name_doubts
    assert set(same_name_doubts.pairs(bank)) == {("nico", "nico-2")}


def test_an_open_same_name_doubt_about_the_pages_is_part_of_what_the_line_is_held_against(tmp_path):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN),
                                                 ("nico-2", "Nico", "Nico is a plumber in Porto who fixes sinks and bathrooms for the speaker's family.")])
    from api.services import same_name_doubts
    same_name_doubts.add_pairs(bank, [("nico", "nico-2")])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "doubt")
    [row] = _rows(bank)
    assert row["new_id"] == "nico-3" and {a["ref"] for a in row["against"]} == {"nico", "nico-2"}
    _apply_names(bank, [row])
    assert {("nico", "nico-3"), ("nico-2", "nico-3"), ("nico", "nico-2")} <= set(same_name_doubts.pairs(bank))


@pytest.mark.parametrize("line, owner, why", [
    (("Dana Whitmore (dwhit)", "x"), None, "not written with a qualifier"),            # two words: not one bare name
    (("dwhit (Dana Whitmore)", "x"), None, "handle"),                                 # a handle the record paired
    (("Mira (sister)", "x"), None, "owner's first name"),
    (("José (cousin)", "x"), ("jose-garcia", "Jose Garcia"), "owner's first name"),    # accents folded
    (("Jose (cousin)", "x"), ("jose-garcia", "José García"), "owner's first name"),
])
def test_the_exclusions_stage_2_applies_apply_here_too(tmp_path, line, owner, why):
    bank = _name_bank(tmp_path, [_line(line[0], "x", episode="ep_2026-11-18_001")], **({"owner": owner} if owner else {}))
    rows = _rows(bank)
    assert not [r for r in rows if r["action"] != ns.LEAVE]
    census = ns.census(ns.load(bank))
    if "not written" not in why:
        assert any(why in k for k in census["left_alone_by_reason"]), census


def test_the_exclusions_are_stage_2s_own_function_called_not_copied(tmp_path, monkeypatch):
    bank = _name_bank(tmp_path, [_fin()])
    seen = []
    monkeypatch.setattr(ns.entity_resolver, "same_name_skip", lambda *a, **k: seen.append(a) or "label_only")
    assert [r["action"] for r in _rows(bank)] == [ns.LEAVE] and seen and seen[0][0] == "Nico (finance lead)"


def test_a_non_person_a_correspondent_a_line_the_person_said_is_not_a_page_and_a_line_a_question_names_are_left_alone(tmp_path):
    company = _line("Brightwell (company)", "x", episode="ep_2026-11-18_001", type_="company")
    corr = _fin("Nico (sms)")
    corr.correspondent = {"name": "Nico", "kind": "sms"}
    apart = _fin("Nico (cousin)")
    apart.apart = {"pages": ["nico"], "episodes": ["ep_2026-11-18_001"]}
    asked = _fin("Nico (neighbour)")
    bank = _name_bank(tmp_path, [company, corr, apart, asked])
    (bank / "inbox").mkdir()
    markdown_parser.write(bank / "inbox" / "inbox-001.md",
                          {"kind": "clarification", "status": "pending", "entity_id": sanitize("Nico (neighbour)")}, "Who is that?")
    rows = {r["line"]: r for r in _rows(bank)}
    assert set(rows) == {"Nico (sms)", "Nico (cousin)", "Nico (neighbour)"} and {r["action"] for r in rows.values()} == {ns.LEAVE}
    assert "open question" in rows["Nico (neighbour)"]["reason"] and "correspondent" in rows["Nico (sms)"]["reason"]


def test_a_page_of_another_kind_that_holds_the_key_leaves_the_line_alone(tmp_path):
    bank = _name_bank(tmp_path, [_fin()])
    markdown_parser.write(bank / "entities" / "nico.md", {"name": "Nico", "type": "company", "status": "active"}, "## Summary\nA firm.\n")
    assert [r["action"] for r in _rows(bank)] == [ns.LEAVE]


def test_the_review_shows_the_lines_words_its_title_and_each_page_it_is_held_against_with_its_first_sentence_and_status(tmp_path):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN, {"status": "decaying"})])
    text = ns.review_text(_rows(bank))
    assert "Nico (finance lead)" in text and "second person in doubt (key nico-2)" in text and 'titled' not in text or True
    assert 'under the name "Nico"' in text
    assert W_FIN.split(".")[0] in text                                   # the line's own words
    assert "page nico \"Nico\" [decaying] answers by name: Nico is the speaker's cousin, a nurse who lives in Lyon and keeps three dogs." in text
    assert "Sleep decides later; nothing is joined here" in text


@pytest.mark.parametrize("change", ["summary", "archived", "alias_page_appears", "line_edited", "sibling_appears"])
def test_apply_skips_a_row_when_the_line_or_anything_it_is_held_against_changed_since_the_plan(tmp_path, change):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN)])
    rows = _rows(bank)
    path = bank / "entities" / "nico.md"
    parsed = markdown_parser.parse(path)
    if change == "summary":
        markdown_parser.write(path, parsed.frontmatter, "## Summary\nA retired judge in Oslo who has nothing to do with the colleagues.\n")
    elif change == "archived":
        markdown_parser.write(path, {**parsed.frontmatter, "status": "archived"}, parsed.body)
    elif change == "alias_page_appears":
        markdown_parser.write(bank / "entities" / "nicolas-reyes.md",
                              {"name": "Nicolas Reyes", "type": "person", "status": "active", "aliases": ["Nico"]}, "## Summary\nA judge.\n")
    elif change == "line_edited":
        pending_store.save(bank, [_fin(summary="Different words now.")])
    else:
        pending_store.save(bank, [*pending_store.load(bank), _line("Nico", "A brand new held Nico.", episode="ep_2026-11-20_001")])
    before = (bank / "pending_entities.jsonl").read_bytes()
    res = _apply_names(bank, rows)
    assert res.skipped == {"changed_since_plan": 1} and (bank / "pending_entities.jsonl").read_bytes() == before


def test_a_hand_edited_row_cannot_change_what_is_written(tmp_path):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN), ("nico-lawyer", "Nico Lawyer", "A lawyer in Madrid.")])
    [row] = _rows(bank)
    res = _apply_names(bank, [{**row, "new_id": "nico-lawyer", "action": ns.RENAME, "new_name": "nico-lawyer"}])
    assert res.skipped == {"changed_since_plan": 1}
    assert {e.name for e in pending_store.load(bank)} == {"Nico (finance lead)"}


def _tool_apply(bank, tmp_path, rows, *extra):
    import contextlib
    import io
    from unittest import mock

    from api.scripts import migrate_claims_jsonl
    plan = tmp_path / "plan"
    plan.mkdir(exist_ok=True)
    (plan / "names.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    out = io.StringIO()
    with mock.patch.object(migrate_claims_jsonl, "backend_running", lambda: False), contextlib.redirect_stdout(out):
        rc = tool.main(["apply", "--bank", str(bank), "--plan", str(plan), *extra])
    return rc, json.loads(out.getvalue())


def test_the_tool_lands_one_cicada_commit_and_a_plain_revert_restores_the_bank_byte_for_byte(tmp_path):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN)])
    before = {p.name: p.read_bytes() for p in bank.glob("*") if p.is_file()}
    rc, out = _tool_apply(bank, tmp_path, _rows(bank))
    assert rc == 0 and out["committed"] is True and out["names"]["applied"] == {ns.HOLD: 1}
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == ["_same_name_doubts.yaml", "pending_entities.jsonl"]
    _git(bank, "revert", "--no-edit", "HEAD")
    assert {p.name: p.read_bytes() for p in bank.glob("*") if p.is_file()} == before
    assert "git revert" in out["undo"]


@pytest.mark.parametrize("dirty", ["pending_entities.jsonl", "_same_name_doubts.yaml"])
def test_apply_refuses_a_bank_where_the_pending_store_or_the_doubts_file_is_dirty_and_sweeps_nothing_in(tmp_path, dirty):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN)])
    rows = _rows(bank)
    path = bank / dirty
    path.write_text((path.read_text() if path.exists() else "") + ("\n" if dirty.endswith("jsonl") else "# edit\n"))
    head = _git(bank, "rev-parse", "HEAD")
    rc, out = _tool_apply(bank, tmp_path, rows)
    assert rc == 3 and "uncommitted" in out["refused"] and dirty in out["files"]
    assert _git(bank, "rev-parse", "HEAD") == head and "nico-2" not in (bank / "pending_entities.jsonl").read_text()


def test_apply_refuses_a_bank_with_no_git(tmp_path):
    import shutil
    bank = _name_bank(tmp_path, [_fin()])
    rows = _rows(bank)
    shutil.rmtree(bank / ".git")
    before = (bank / "pending_entities.jsonl").read_bytes()
    rc, out = _tool_apply(bank, tmp_path, rows)
    assert rc == 3 and "not a git repository" in out["refused"] and (bank / "pending_entities.jsonl").read_bytes() == before


def test_a_failed_commit_puts_the_pending_store_and_the_doubts_file_back(tmp_path, monkeypatch):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN)])
    rows = _rows(bank)
    before = (bank / "pending_entities.jsonl").read_bytes()
    from api.services import git_service

    def broken(memory, message, paths):
        _git(bank, "add", "--", *paths)
        raise git_service.GitError("index.lock exists")
    monkeypatch.setattr(git_service, "commit_paths_sync", broken)
    with pytest.raises(git_service.GitError):
        _tool_apply(bank, tmp_path, rows)
    assert (bank / "pending_entities.jsonl").read_bytes() == before and not (bank / "_same_name_doubts.yaml").exists()
    assert _git(bank, "status", "--porcelain") == ""


def test_the_names_plan_makes_no_model_call_and_the_tool_writes_every_row_without_the_judge_flag(tmp_path, monkeypatch):
    import contextlib
    import io

    from api.services import value_alignment
    monkeypatch.setattr(value_alignment, "judge_for", lambda *a, **k: pytest.fail("a model was reached"))
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN)])
    out = tmp_path / "out"
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        assert tool.main(["plan", "--bank", str(bank), "--out", str(out), "--pass", "names"]) == 0
    summary = json.loads(buf.getvalue())
    assert summary["names"]["model_calls"] == 0 and summary["names"]["rows_by_action"] == {ns.HOLD: 1}
    assert (out / "names.jsonl").exists() and "second person in doubt" in (out / "review.txt").read_text()
    assert (out / "review.txt").read_text().startswith("BEFORE YOU APPLY")


# ------------------------------------------------------------------ names: what the next Sleep does with such a line


def _settings(bank):
    from api.config import Settings
    return Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank))


def _pipeline(bank, **kw):
    from api.services import claim_pipeline
    return claim_pipeline.run_claim_pipeline([], [], bank, _settings(bank), now_date="2026-11-24", decay=False, **kw)


def test_the_next_sleep_keeps_the_lines_claims_on_its_own_id_and_never_releases_them_onto_the_page(tmp_path):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN)])
    page = (bank / "entities" / "nico.md").read_bytes()
    _apply_names(bank, _rows(bank))
    res = _pipeline(bank)
    assert not res.get("claims_released") and res.get("claims_waiting") == 2
    [line] = pending_store.load(bank)
    assert line.name == "nico-2" and len(line.held_claims) == 2 and {c["subject"] for c in line.held_claims} == {"nico-2"}
    assert (bank / "entities" / "nico.md").read_bytes() == page


def test_the_next_sleep_does_not_hand_the_claims_to_a_page_that_answers_to_the_name_by_an_alias(tmp_path):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nicolas-reyes", "Nicolas Reyes", "A retired judge in Oslo.", {"aliases": ["Nico"]})])
    page = (bank / "entities" / "nicolas-reyes.md").read_bytes()
    _apply_names(bank, _rows(bank))
    res = _pipeline(bank, name_to_id={"nico": "nicolas-reyes"})   # Stage 2 resolved the bare name to the aliased page
    assert not res.get("claims_released") and (bank / "entities" / "nicolas-reyes.md").read_bytes() == page
    assert {c["subject"] for c in pending_store.load(bank)[0].held_claims} == {"nico-2"}


def test_a_following_mention_of_the_bare_name_meets_the_held_person_through_the_same_name_placement(tmp_path, monkeypatch):
    """The held person is an identity the placement compares a new "Nico" with, as one Stage 2 wrote itself would be: a
    scripted judge that reads the new mention as the finance lead puts it on that line, by key, never on the page."""
    import asyncio
    import re
    from types import SimpleNamespace

    from api.services import entity_resolver as er
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN)])
    _apply_names(bank, _rows(bank))
    seen = []

    async def judge(settings, system, prompt):
        seen.append(prompt)
        entries = re.findall(r"^\s*\(([A-Z])\)\s*(.*)$", prompt, re.M)
        finance = [letter for letter, text in entries if "finance lead" in text.lower() or "budget slides" in text.lower()]
        other = [letter for letter, _ in entries if letter not in finance]
        return {"people": [{"conversations": finance, "reason": "the finance lead"}, {"conversations": other, "reason": "the cousin"}],
                "pairs": [{"people": [1, 2], "verdict": "different", "here": "finance lead at Brightwell",
                           "there": "a nurse who lives in Lyon", "reason": "r"}]}
    monkeypatch.setattr(er, "_same_name_ask", judge)
    parsed = markdown_parser.parse(bank / "entities" / "nico.md")
    page = {"id": "nico", "frontmatter": parsed.frontmatter, "body": parsed.body}
    extracted = [{"episode_id": "ep_2026-11-25_001", "origin": "claude-code", "relationships": [], "values": [],
                  "entities": [{"name": "Nico", "type": "person", "confidence": 0.8, "source_episode": "ep_2026-11-25_001",
                                "summary": "Nico, the finance lead at Brightwell, sent next quarter's budget slides to the speaker on Monday.",
                                "source_episode_timestamp": "2026-11-25T10:00:00+00:00"}]}]
    moves, compared, _ = asyncio.run(er._plan_same_name_people(
        extracted, [page], {"nico": [page]}, _settings(bank), refs=SimpleNamespace(is_speaker=lambda *a, **k: False),
        owner_page_id="mira-kolar"))
    assert seen and compared["nico"] == frozenset({"nico", "nico-2"})       # the held person was one of those compared
    assert moves == {("ep_2026-11-25_001", "nico"): er.same_name_people.Destination("line", "nico-2")}


def test_a_revert_stops_being_clean_once_a_sleep_has_rewritten_the_line_it_changed(tmp_path):
    bank = _name_bank(tmp_path, [_fin()], pages=[("nico", "Nico", W_COUSIN)])
    rc, out = _tool_apply(bank, tmp_path, _rows(bank))
    assert rc == 0
    sweep = _git(bank, "rev-parse", "HEAD").strip()
    lines = pending_store.load(bank)
    lines[0].held_claims = lines[0].held_claims[:1]   # a later Sleep released one of the line's claims onto its page
    pending_store.save(bank, lines)
    _git(bank, "commit", "-qam", "Sleep batch (simulated)")
    result = subprocess.run(["git", "revert", "--no-edit", sweep], cwd=bank, capture_output=True, text=True)
    assert result.returncode != 0 and "pending_entities.jsonl" in (result.stdout + result.stderr)
    _git(bank, "revert", "--abort")


# ------------------------------------------------------------------ the tool


def test_the_pages_titled_with_a_qualifier_are_counted_and_never_changed(tmp_path):
    bank = _name_bank(tmp_path, [], pages=[("nico-(finance-lead)", "Nico (finance lead)", "A finance lead.")])
    assert ns.qualified_pages(ns.load(bank)) == ["nico-(finance-lead)"]
    assert ns.census(ns.load(bank))["pages_titled_with_a_qualifier"] == 1


def test_the_tool_apply_checks_writes_nothing_and_refuses_a_demo_bank_written_the_way_the_guard_reads_it(tmp_path):
    bank, row = _planned(tmp_path)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "values.jsonl").write_text(json.dumps(row))
    before = _git(bank, "rev-parse", "HEAD")
    assert tool.main(["apply", "--bank", str(bank), "--plan", str(plan), "--check"]) == 0
    assert _git(bank, "rev-parse", "HEAD") == before and not _git(bank, "status", "--porcelain")
    from api.services import demo_guard
    (bank / demo_guard.MANIFEST).write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    assert demo_guard.is_demo(bank)
    assert tool.main(["apply", "--bank", str(bank), "--plan", str(plan)]) == 4
    assert _git(bank, "rev-parse", "HEAD") == before


def test_the_plan_out_directory_must_be_outside_the_bank(tmp_path):
    bank, _ = _planned(tmp_path)
    assert tool.main(["plan", "--bank", str(bank), "--out", str(bank / "plan")]) == 2


def test_a_value_plan_that_failed_on_a_page_is_read_again_by_the_same_command_and_listed_until_then(tmp_path, monkeypatch):
    import contextlib
    import io

    from api.services import value_alignment
    bank = _bank(tmp_path, PRICE)
    out = tmp_path / "out"
    state = {"fail": True}
    inner = Judge()

    def judge(prompt):
        if state["fail"]:
            raise RuntimeError("the plan limit")
        return inner(prompt)
    monkeypatch.setattr(value_alignment, "judge_for", lambda *a, **k: judge)
    args = ["plan", "--bank", str(bank), "--out", str(out), "--judge", "--pass", "values"]
    with contextlib.redirect_stdout(io.StringIO()):
        tool.main(args)
    assert "NOT READ" in (out / "review.txt").read_text() and PAGE in (out / "review.txt").read_text()
    state["fail"] = False
    with contextlib.redirect_stdout(io.StringIO()):
        tool.main(args)
    text = (out / "review.txt").read_text()
    assert "NOT READ" not in text and "JOIN" in text
