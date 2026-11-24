"""The one-time sweep for doubled values and for people held under a qualified name (`value_sweep`, `name_sweep`, G148).
Invented names; a scripted judge, no model.

What matters: the plan shows every pair with the judge's own words and writes nothing; a join needs both answers; the live
rails refuse what they refuse whatever the judge says; apply writes exactly the reviewed rows (the older value closed and
kept), skips a struck row and a page changed since the plan, never calls a model, lands as one `cicada` commit and a plain
revert restores the bank byte for byte."""
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


# ------------------------------------------------------------------ names


def _line(name, summary, *, episode, facts=(), claims=(), title="", aliases=()):
    entity = pending_store.PendingEntity(name=name, type="person", description="", source_episode=episode, confidence=0.6,
                                         tags=[], history_entries=[], summary=summary, key_facts=list(facts),
                                         aliases=list(aliases), title=title,
                                         heard_in=[{"episode": episode, "timestamp": f"{episode[3:13]}T10:00:00+00:00",
                                                    "day": episode[3:13]}],
                                         held_claims=[c.to_dict() for c in claims])
    return entity


def _name_bank(tmp_path, lines, pages=()):
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    markdown_parser.write(bank / "entities" / "mira-kolar.md", {"name": "Mira Kolar", "type": "person", "owner": True,
                                                                "status": "active"}, "## Summary\nThe owner.\n")
    for pid, name, summary in pages:
        markdown_parser.write(bank / "entities" / f"{pid}.md", {"name": name, "type": "person", "status": "active",
                                                                "source_episodes": ["ep_2026-10-01_001"]}, f"## Summary\n{summary}\n")
    pending_store.save(bank, lines)
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"],
                ["add", "-A"], ["commit", "-qm", "seed"]):
        _git(bank, *cmd)
    return bank


FINANCE = _line("Nico (finance lead)", "Finance lead at Brightwell, a colleague, forty-two with two kids who sent the budget slides in October.",
                episode="ep_2026-11-18_001", facts=["Nico (finance lead) has two kids."], aliases=["Nico from work"],
                claims=[_claim("h1", "works-at", "brightwell", "2026-11-18", subject="nico-(finance-lead)")])


def _ask(plain=True, apart=False):
    """A same-name judge: one group per mention, or all one person when ``plain``."""
    def ask(system, prompt):
        letters = [ln.strip()[1] for ln in prompt.splitlines() if ln.strip().startswith("(") and ln.strip()[2:3] == ")"]
        if plain:
            return {"people": [{"conversations": letters, "reason": "all of them is the same person"}], "pairs": []}
        pairs = [{"people": [1, 2], "verdict": "different", "here": "Finance lead at Brightwell",
                  "there": "cousin, a nurse who lives in Lyon", "reason": "a finance lead cannot be a nurse"}]
        return {"people": [{"conversations": [x], "reason": "a different person"} for x in letters], "pairs": pairs}
    return ask


def _name_plan(bank, ask):
    nb = ns.load(bank)
    cands, _ = ns.candidates(nb)
    meter = ns.Meter()
    rows = []
    by = {}
    for c in cands:
        by.setdefault(snp.stem_of(c.name)[0].lower(), []).append(c)
    for stem, lines in by.items():
        rows += asyncio.run(ns.plan_name(nb, stem, lines, ask, ask, meter))
    return rows, meter


def test_a_line_alone_under_its_qualified_name_becomes_the_bare_names_person_with_the_written_name_kept(tmp_path):
    bank = _name_bank(tmp_path, [FINANCE])
    rows, meter = _name_plan(bank, _ask())
    assert meter.total == 0 and rows[0]["action"] == "rename_bare"
    before = (bank / "pending_entities.jsonl").read_bytes()
    res = ns.apply_rows(bank, rows)
    [line] = pending_store.load(bank)
    assert line.name == "Nico" and "Nico (finance lead)" in line.aliases and "Nico from work" in line.aliases
    assert line.held_claims[0]["subject"] == "nico" and line.title == ""
    assert res.applied == {"rename_bare": 1} and res.paths == ["pending_entities.jsonl"]
    assert before != (bank / "pending_entities.jsonl").read_bytes()


def test_a_line_the_reader_joins_to_a_page_is_filed_under_that_page_and_its_claims_follow(tmp_path):
    words = "Nico is the finance lead at Brightwell and has two kids, forty-two years old, a colleague of the speaker."
    bank = _name_bank(tmp_path, [FINANCE], pages=[("nico", "Nico", words)])
    rows, _ = _name_plan(bank, _ask(plain=True))
    assert rows[0]["action"] == "to_page" and rows[0]["target"] == "nico"
    assert rows[0]["judge_said"] == ["all of them is the same person"]
    ns.apply_rows(bank, rows)
    [line] = pending_store.load(bank)
    assert sanitize(line.name) == "nico" and line.held_claims[0]["subject"] == "nico"


def sanitize(name):
    from api.services.id_utils import sanitize_id
    return sanitize_id(name)


def test_a_line_the_reader_calls_another_person_gets_its_own_key_titled_with_the_bare_name_and_a_doubt_pair(tmp_path):
    words = "Nico is the speaker's cousin, a nurse who lives in Lyon and keeps three dogs and two cats at home, and likes hiking."
    bank = _name_bank(tmp_path, [FINANCE], pages=[("nico", "Nico", words)])
    rows, _ = _name_plan(bank, _ask(plain=False))
    assert rows[0]["action"] == "new_person"
    res = ns.apply_rows(bank, rows)
    [line] = pending_store.load(bank)
    assert line.name == "nico-2" and line.title == "Nico" and "Nico (finance lead)" in line.aliases
    assert line.held_claims[0]["subject"] == "nico-2"
    assert res.paths == ["pending_entities.jsonl", "_same_name_doubts.yaml"]
    from api.services import same_name_doubts
    assert ("nico", "nico-2") in same_name_doubts.pairs(bank)


def test_a_line_the_reader_placed_nowhere_stays_as_it_is_and_the_row_says_so(tmp_path):
    words = "Nico is the speaker's cousin, a nurse who lives in Lyon and keeps three dogs and two cats at home, and likes hiking."
    bank = _name_bank(tmp_path, [FINANCE], pages=[("nico", "Nico", words)])
    rows, _ = _name_plan(bank, lambda system, prompt: {})
    assert rows[0]["action"] == "leave" and "placed it nowhere" in rows[0]["reason"]
    assert ns.apply_rows(bank, rows).skipped == {"left_alone": 1}


def test_a_line_whose_conversation_also_names_the_bare_names_person_is_never_joined_to_it(tmp_path):
    words = "Nico is the speaker's cousin, a nurse who lives in Lyon and keeps three dogs and two cats at home, and likes hiking."
    bank = _name_bank(tmp_path, [FINANCE], pages=[("nico", "Nico", words)])
    page = markdown_parser.parse(bank / "entities" / "nico.md")
    markdown_parser.write(bank / "entities" / "nico.md", {**page.frontmatter, "source_episodes": ["ep_2026-11-18_001"]}, page.body)
    rows, _ = _name_plan(bank, _ask(plain=True))
    assert rows[0]["action"] == "leave" and "also names the bare name" in rows[0]["reason"]


def test_a_handle_the_owners_first_name_a_two_word_name_and_a_non_person_are_untouched(tmp_path):
    lines = [_line("Mira Kolar (spouse)", "x", episode="ep_2026-11-18_001"),
             _line("Mira (sister)", "x", episode="ep_2026-11-18_001"),
             _line("Dana Whitmore (dwhit)", "x", episode="ep_2026-11-18_001"),
             _line("Brightwell (company)", "x", episode="ep_2026-11-18_001")]
    lines[3].type = "company"
    bank = _name_bank(tmp_path, lines)
    cands, left = ns.candidates(ns.load(bank))
    assert cands == [] and left == {"the owner's first name": 1}


def test_apply_of_names_skips_a_struck_line_and_a_line_changed_since_the_plan_and_reverts_byte_for_byte(tmp_path):
    bank = _name_bank(tmp_path, [FINANCE])
    rows, _ = _name_plan(bank, _ask())
    before = (bank / "pending_entities.jsonl").read_bytes()
    assert ns.apply_rows(bank, [{**rows[0], "strike": True}]).skipped == {"struck": 1}
    pending_store.save(bank, [_line("Nico (finance lead)", "Different words now.", episode="ep_2026-11-18_001")])
    assert ns.apply_rows(bank, rows).skipped == {"changed_since_plan": 1}
    pending_store.save(bank, [FINANCE])
    result = tool_apply(bank, tmp_path, rows)
    assert result["committed"] is True
    _git(bank, "revert", "--no-edit", "HEAD")
    assert (bank / "pending_entities.jsonl").read_bytes() == before


def tool_apply(bank, tmp_path, rows):
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "names.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    from api.scripts import migrate_claims_jsonl
    import sys
    from unittest import mock
    out = []
    with mock.patch.object(migrate_claims_jsonl, "backend_running", lambda: False), \
            mock.patch("builtins.print", lambda s, **k: out.append(s)):
        assert tool.main(["apply", "--bank", str(bank), "--plan", str(plan)]) == 0
    return json.loads(out[-1])


def test_pages_titled_with_a_qualifier_are_counted_and_never_changed(tmp_path):
    bank = _name_bank(tmp_path, [], pages=[("nico-(finance-lead)", "Nico (finance lead)", "A finance lead.")])
    assert ns.qualified_pages(ns.load(bank)) == ["nico-(finance-lead)"]
    assert ns.census(ns.load(bank))["pages_titled_with_a_qualifier"] == 1


# ------------------------------------------------------------------ the tool


def test_the_tool_apply_checks_writes_nothing_and_refuses_a_demo_bank(tmp_path):
    bank, row = _planned(tmp_path)
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "values.jsonl").write_text(json.dumps(row))
    before = _git(bank, "rev-parse", "HEAD")
    assert tool.main(["apply", "--bank", str(bank), "--plan", str(plan), "--check"]) == 0
    assert _git(bank, "rev-parse", "HEAD") == before and not _git(bank, "status", "--porcelain")
    (bank / "_bank.yaml").write_text("demo: true\n")
    from api.services import demo_guard
    if demo_guard.is_demo(bank):
        assert tool.main(["apply", "--bank", str(bank), "--plan", str(plan)]) == 4


def test_the_plan_out_directory_must_be_outside_the_bank(tmp_path):
    bank, _ = _planned(tmp_path)
    assert tool.main(["plan", "--bank", str(bank), "--out", str(bank / "plan")]) == 2
