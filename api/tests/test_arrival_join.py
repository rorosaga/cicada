"""G245 (owner 2026-11-24, "yes ofc join ... accross sources"): a first name joined to the person who newly appeared the same week.

He met people at an event, connected with some that week, and wrote a few first names in a note; he wants Cicada to tie them
together itself and let him say no. A wrong join tells him things about someone who is someone else, so every rule of the
plan's 3.4 is one block here, tested on its own and in the order the code asks them (the first failure is the counted reason).
This file is the DECISION and the REPORT (no write): `test_arrival_join_write.py` holds the write, the record and the undo.

Synthetic people (`<given-a> <family-a>`, example.com); nothing reads a real bank, `~/.cicada` or the network."""
from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

from _synthetic_bank import _bank, _entity
from api.services import arrival_join as aj
from api.services import linkedin_people, markdown_parser

LI = "https://www.linkedin.com/in"
HOLDER_DAY = "2026-11-10"


def _day(delta: int, base: str = HOLDER_DAY) -> str:
    return (aj.parse_day(base) + __import__("datetime").timedelta(days=delta)).isoformat()


def row(ref="r1", *, kind=aj.CONNECTION, given="sam", family="okafor", day=None, precision=None, **kw) -> aj.Row:
    full = f"{given} {family}".strip() if family else ""
    base = dict(ref=ref, kind=kind, given=given, full=full, day=day, precision=precision or ("day" if day else None),
                linked=kind == aj.CONNECTION)
    base.update(kw)
    return aj.Row(**base)


def holder(**kw) -> aj.Holder:
    base = dict(page="sam", word="sam", day=HOLDER_DAY, day_from="conversation")
    base.update(kw)
    return aj.Holder(**base)


def case(*rows, fresh=None, **hkw) -> aj.Case:
    return aj.Case(holder(**hkw), tuple(rows), {aj.CONNECTION: "2026-11-24"} if fresh is None else fresh)


ARRIVAL = row("a", day=_day(2))
PASS = aj.Veto(("fits", "fits"))


def verdict(c: aj.Case, veto=None) -> tuple[str, str]:
    d = aj.decide(c, veto)
    return d.outcome, d.reason


# --- the happy path -------------------------------------------------------------------------------------------------


def test_one_holder_one_arrival_the_same_week_reaches_the_veto_and_joins_on_two_clear_reads():
    c = case(ARRIVAL)
    assert verdict(c) == ("candidate", "veto_pending")
    d = aj.decide(c, PASS)
    assert (d.outcome, d.delta, d.arrival_day, d.holder_day) == ("join", 2, _day(2), HOLDER_DAY)
    assert d.alias_key == aj.key_hash("sam okafor") and d.refs == ("a",)


# --- rule 2: the holder -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("fm, stem, why", [
    ({"name": "Sam", "type": "person", "status": "archived"}, "sam", "holder_inactive"),
    ({"name": "Sam", "type": "person", "status": "dropped"}, "sam", "holder_inactive"),
    ({"name": "Sam", "type": "person", "owner": True}, "sam", "holder_owner"),
    ({"name": "Sam", "type": "person"}, "me", "holder_owner"),
    ({"name": "Partner", "type": "person", "unnamed": True}, "partner", "holder_role"),
    ({"name": "Partner", "type": "person"}, "partner", "holder_role"),
    ({"name": "Sam Okafor", "type": "person"}, "sam-okafor", "holder_not_one_word"),
    ({"name": "Al", "type": "person"}, "al", "holder_short_word"),
    ({"name": "Sam", "type": "person"}, "sam-2", "holder_second_of_name"),
    ({"name": "Sam", "type": "person", "status": "active"}, "sam", None),
    ({"name": "Zoë", "type": "person"}, "zoë", None),
])
def test_rule_2_who_may_hold_a_first_name(fm, stem, why):
    assert aj.holder_block(fm, stem, {"me"}) == why


def test_a_blocked_holder_is_the_counted_reason_before_anything_else():
    assert verdict(case(ARRIVAL, block="holder_owner")) == ("skip", "holder_owner")


# --- rule 3: the given name, by token equality ----------------------------------------------------------------------


def test_rule_3_a_nickname_a_longer_name_and_a_compound_given_name_are_misses_on_purpose():
    for given in ("samuel", "sammy", "mary ann", "sa"):
        assert verdict(case(row("a", given=given, day=_day(2)))) == ("skip", "no_namesake")


# --- rule 4: exactly one holder -----------------------------------------------------------------------------------


def test_rule_4_another_page_or_held_line_carrying_the_word_means_the_bank_already_knows_who_it_is():
    assert verdict(case(ARRIVAL, others=1)) == ("skip", "other_holder")


def test_a_page_with_no_day_never_joins():
    assert verdict(case(ARRIVAL, day=None)) == ("skip", "no_day")


# --- rule 5: exactly one arrival, counting namesakes ----------------------------------------------------------------


@pytest.mark.parametrize("delta, want", [(0, "candidate"), (7, "candidate"), (-7, "candidate"), (8, "skip"), (-8, "skip")])
def test_rule_5_the_window_is_seven_days_either_way_inclusive_day_eight_does_not_join(delta, want):
    out, _ = verdict(case(row("a", day=_day(delta))))
    assert out == want


def test_two_connections_the_same_week_are_two_people_and_refuse():
    assert verdict(case(row("a", day=_day(1)), row("b", family="adeyemi", day=_day(3)))) == ("skip", "two_arrivals")


def test_a_connection_and_a_card_of_one_full_name_are_one_lead_not_two():
    card = row("c", kind=aj.CARD, day=_day(2), linked=False)
    assert verdict(case(ARRIVAL, card, fresh={aj.CONNECTION: "2026-11-24", aj.CARD: "2026-11-24"})) == ("candidate", "veto_pending")


def test_a_card_and_a_connection_of_other_full_names_are_two_arrivals():
    card = row("c", kind=aj.CARD, family="berg", day=_day(2), linked=False)
    assert verdict(case(ARRIVAL, card, fresh={aj.CONNECTION: "2026-11-24", aj.CARD: "2026-11-24"})) == ("skip", "two_arrivals")


def test_two_linkless_rows_of_one_full_name_are_two_people_until_told_apart():
    twins = (row("a", day=_day(2), linked=False), row("b", day=_day(3), linked=False, dup=1))
    assert verdict(case(*twins)) == ("skip", "two_arrivals")


def test_a_week_or_month_row_is_never_the_arrival_it_only_blocks():
    assert verdict(case(row("a", day=_day(2), precision="week"))) == ("skip", "no_arrival")
    assert verdict(case(row("a", day=_day(2), precision="month"))) == ("skip", "no_arrival")


@pytest.mark.parametrize("other, why", [
    (row("b", family="adeyemi", day=_day(20)), "day within 30 days"),
    (row("b", family="adeyemi", day=_day(-30)), "day within 30 days (the edge)"),
    (row("b", family="adeyemi", day=_day(37), precision="week"), "a fuzzy week's range reaches the band"),
    (row("b", family="adeyemi", day=_day(60), precision="month"), "a fuzzy month's range reaches the band"),
    (row("b", family="adeyemi", day=_day(-37), precision="week"), "a fuzzy week before the holder's day"),
    (row("b", family="adeyemi", day=None, linked=True), "no day at all, with a profile link"),
    (row("b", family="adeyemi", day=None, linked=False, dup=1), "no day at all, ambiguous"),
])
def test_rule_5b_a_plausible_same_season_namesake_blocks(other, why):
    assert verdict(case(ARRIVAL, other)) == ("skip", "namesake_block"), why


@pytest.mark.parametrize("other, why", [
    (row("b", family="adeyemi", day=_day(-400)), "connected years ago: not new"),
    (row("b", family="adeyemi", day=_day(31)), "day 31: outside the band"),
    (row("b", family="adeyemi", day=_day(38), precision="week"), "a fuzzy week whose range just misses the band"),
    (row("b", family="adeyemi", day=_day(61), precision="month"), "a fuzzy month whose range just misses the band"),
    (row("b", family="adeyemi", day=_day(100), precision="week"), "a fuzzy week far away"),
    (row("b", family="adeyemi", day=None, linked=False), "no day, no link, no ambiguity: junk"),
    (row("b", kind=aj.CARD, family="adeyemi", day=None, linked=False), "an unstamped card is dormant"),
])
def test_a_dormant_old_namesake_does_not_block(other, why):
    fresh = {aj.CONNECTION: "2026-11-24", aj.CARD: "2026-11-24"}
    assert verdict(case(ARRIVAL, other, fresh=fresh)) == ("candidate", "veto_pending"), why


def test_a_row_with_no_family_name_can_never_be_the_arrival():
    assert verdict(case(row("a", family="", day=_day(2)))) == ("skip", "arrival_no_family_name")


# --- rule 6: the arrival is waiting -------------------------------------------------------------------------------


def test_rule_6_a_full_name_a_page_already_holds_is_never_joined():
    assert verdict(case(row("a", day=_day(2), page_held=True, waiting=False))) == ("skip", "full_name_has_page")
    assert verdict(case(row("a", day=_day(2), waiting=False))) == ("skip", "arrival_not_waiting")


# --- rule 7: no doubt, no history ---------------------------------------------------------------------------------


def test_rule_7_a_same_name_doubt_on_either_side_refuses():
    assert verdict(case(ARRIVAL, doubt=True)) == ("skip", "doubt")
    assert verdict(case(row("a", day=_day(2), doubt=True))) == ("skip", "doubt")


@pytest.mark.parametrize("history", ["removed", "refused", "split"])
def test_rule_7_what_the_person_said_about_this_very_pair_is_never_overridden(history):
    assert verdict(case(row("a", day=_day(2), history=history))) == ("skip", "history")


# --- rule 8: nothing already points elsewhere -----------------------------------------------------------------------


@pytest.mark.parametrize("why", ["full_name_alias", "profile_elsewhere", "candidate_pair"])
def test_rule_8_a_page_that_already_points_at_someone_else_joins_nobody(why):
    assert verdict(case(ARRIVAL, elsewhere=why)) == ("skip", why)


# --- rule 9: the directory is fresh -------------------------------------------------------------------------------


def test_rule_9_a_directory_not_looked_at_since_the_week_ended_defers_the_join():
    assert verdict(case(ARRIVAL, fresh={aj.CONNECTION: _day(6)})) == ("skip", "directory_not_fresh")     # day + 7 is the week's end
    assert verdict(case(ARRIVAL, fresh={aj.CONNECTION: _day(7)})) == ("candidate", "veto_pending")
    assert verdict(case(ARRIVAL, fresh={aj.CONNECTION: None})) == ("skip", "directory_not_fresh")        # a stamp nobody knows


def test_rule_9_every_directory_the_bank_keeps_must_be_fresh_not_only_the_arrivals():
    fresh = {aj.CONNECTION: "2026-11-24", aj.CARD: _day(2)}
    assert verdict(case(ARRIVAL, fresh=fresh)) == ("skip", "directory_not_fresh")


# --- rule 10: the conflict screen (no model) -----------------------------------------------------------------------


def test_rule_10_a_page_at_one_company_and_a_row_at_another_with_no_word_in_common_refuses():
    mine = dict(companies=("alpha robotics",))
    assert verdict(case(row("a", day=_day(2), company="Beta Logistics GmbH", position="Buyer"), **mine)) == ("skip", "fact_conflict")


@pytest.mark.parametrize("company, headline", [
    ("Alpha Robotics Inc", ""),                       # the same company, with a legal suffix
    ("Robotics Corp", ""),                             # one significant word in common
    ("Gamma", "Founder at Alpha Robotics"),            # the headline names the page's company
    ("", "Something else entirely"),                   # no company on the row: nothing to compare
])
def test_a_company_that_agrees_or_cannot_be_compared_is_no_conflict(company, headline):
    c = case(row("a", day=_day(2), company=company, headline=headline), companies=("alpha robotics",))
    assert verdict(c) == ("candidate", "veto_pending")


def test_a_page_that_names_no_employer_has_nothing_to_conflict_with():
    assert verdict(case(row("a", day=_day(2), company="Beta Logistics"))) == ("candidate", "veto_pending")


# --- rule 11: the two-read veto --------------------------------------------------------------------------------------


@pytest.mark.parametrize("answers, joins", [
    (("fits", "fits"), True), (("fits", "conflict"), False), (("conflict", "fits"), False), (("fits", "unsure"), False),
    (("unread", "fits"), False), (("fits", "unread"), False), (("fits",), False), ((), False),
])
def test_rule_11_both_reads_must_find_nothing_one_doubt_or_an_unreadable_answer_is_no_join(answers, joins):
    d = aj.decide(case(ARRIVAL), aj.Veto(answers))
    assert d.joins is joins
    assert d.reason == ("ok" if joins else "veto")


def test_the_veto_is_asked_only_after_every_other_rule_held():
    d = aj.decide(case(ARRIVAL, others=1), PASS)
    assert (d.outcome, d.reason) == ("skip", "other_holder")


# --- the order: the first failure is the reason --------------------------------------------------------------------


def test_the_first_failing_rule_is_the_counted_reason_and_never_a_name():
    c = case(row("a", day=_day(2), history="refused", doubt=True), elsewhere="full_name_alias", fresh={aj.CONNECTION: None})
    d = aj.decide(c)
    assert d.reason == "doubt"          # rule 7 before 8 before 9
    assert "sam okafor" not in json.dumps(d.__dict__, default=str)


# --- 3.3: what "newly appeared" means for the first-name side ---------------------------------------------------------


def _fm(**kw):
    base = {"timestamp": "2026-11-10T12:00:00+00:00", "harness": "claude-code"}
    base.update(kw)
    return base


def test_a_conversation_is_dated_by_its_own_day_never_the_day_it_was_received_or_read():
    day, kind = aj.episode_day(_fm(received_at="2026-11-20T09:00:00+00:00"))
    assert (day, kind) == ("2026-11-10", "conversation")


@pytest.mark.parametrize("fm", [
    {"source": "claude_memory"}, {"source": "agent_relay"}, {"source": "web-check"},               # not a time signal
    {"origin": "rss"}, {"published_at": "2026-11-10T00:00:00+00:00"},                               # a feed
    {"source": "tab-group"}, {"source": "calendar"}, {"origin": "calendar-local"},                  # a filing label
    {"media_entity_id": "media-x"}, {"url": "https://example.com/x"},                               # a save
    {"source": "video-watch"}, {"source": "source-refresh"},                                        # a watch, a check
    {"locked_note": True, "origin": "apple-notes", "created_at": "2026-11-10T08:00:00+00:00"},
])
def test_an_episode_that_is_no_mention_by_the_person_gives_no_day(fm):
    assert aj.episode_day(_fm(**fm)) == (None, "")


def test_a_note_is_dated_by_the_day_it_was_created_and_only_when_it_is_not_a_living_note():
    note = dict(origin="apple-notes", source="apple-notes")
    assert aj.episode_day(_fm(**note, created_at="2026-11-09T08:00:00+00:00")) == ("2026-11-09", "note")
    assert aj.episode_day(_fm(**note, created_at="2026-11-03T08:00:00+00:00"))[0] == "2026-11-03"       # 7 days: still new
    assert aj.episode_day(_fm(**note, created_at="2026-11-02T08:00:00+00:00")) == (None, "")             # 8 days: living
    assert aj.episode_day(_fm(**note, timestamp="2026-11-24T08:00:00+00:00", created_at="2025-01-04T08:00:00+00:00")) == (None, "")


def test_an_old_note_edited_this_week_has_no_day_and_neither_has_a_note_the_app_never_dated():
    note = dict(origin="apple-notes", source="apple-notes")
    assert aj.episode_day(_fm(**note)) == (None, "")                                                      # no created_at: an older app
    assert aj.episode_day(_fm(**note, created_at="2024-02-01T08:00:00+00:00")) == (None, "")             # created long before its last edit


def test_a_watched_folder_note_has_no_day_and_only_a_meeting_is_dated_and_says_so():
    note = dict(source="folder", origin="folder", folder_id="f", relpath="a.md")
    assert aj.episode_day(_fm(**note)) == (None, "")
    assert aj.episode_day(_fm(**note, created_at="2026-11-10T08:00:00+00:00")) == (None, "")
    meeting = dict(note, folder_kind="meetings", meeting={"attendees": []})
    assert aj.episode_day(_fm(**meeting)) == ("2026-11-10", "meeting")


def test_a_nonsense_creation_moment_gives_no_day():
    note = dict(origin="apple-notes", source="apple-notes")
    assert aj.episode_day(_fm(**note, created_at="not a date")) == (None, "")
    assert aj.episode_day(_fm(**note, created_at="2030-01-01T00:00:00+00:00")) == (None, "")             # after its own last edit


def test_days_are_whole_days_apart_and_unreadable_ones_are_nothing():
    assert aj.gap("2026-11-10", "2026-11-17") == 7 and aj.gap("2026-11-17", "2026-11-10") == 7
    assert aj.gap("2026-11-10", "") is None and aj.gap(None, "2026-11-10") is None


# --- reading the bank: gather ------------------------------------------------------------------------------------


def _bank_with(tmp_path, monkeypatch, *, rows=None, holder_days=(HOLDER_DAY,), directory_day="2026-11-24"):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    mem = _bank(tmp_path)
    eps = []
    for n, day in enumerate(holder_days, start=1):
        ep = f"ep_{day}_{n:03d}"
        markdown_parser.write(mem / "episodes" / f"{ep}.md", {"id": ep, "timestamp": f"{day}T12:00:00+00:00", "processed": True,
                                                              "harness": "claude-code"}, "user: met Sam at the event today")
        eps.append(ep)
    _entity(mem, "sam", type="person", name="Sam", source_episodes=eps)
    conns = [linkedin_people.Connection(*r) for r in (rows if rows is not None else [
        ("Sam", "Okafor", f"{LI}/sam-okafor", "", "", _day(2), "", "day")])]
    linkedin_people.save_directory(mem.name, conns, directory_day)
    commit_all(mem)
    return mem


def commit_all(mem) -> None:
    for args in (["add", "-A"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(mem), *args], check=True, capture_output=True)


def test_gather_builds_a_case_from_the_bank_and_the_directory_and_the_rules_pass(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    g = aj.gather(mem)
    assert g.holders == 1 and len(g.cases) == 1
    c = g.cases[0]
    assert (c.holder.page, c.holder.day, c.holder.day_from, c.holder.block) == ("sam", HOLDER_DAY, "conversation", None)
    assert c.fresh == {aj.CONNECTION: "2026-11-24"} and [r.given for r in c.rows] == ["sam"]
    assert aj.decide(c).outcome == "candidate"


def test_the_holders_day_is_its_earliest_conversation_and_a_page_first_said_months_earlier_never_joins(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch, holder_days=("2026-05-01", HOLDER_DAY))
    c = aj.gather(mem).cases[0]
    assert c.holder.day == "2026-05-01"
    assert aj.decide(c).reason == "no_arrival"


def test_a_namesake_the_bank_already_has_a_page_for_is_other_holder_not_a_join(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    _entity(mem, "sam-okafor", type="person", name="Sam Okafor")
    c = aj.gather(mem).cases[0]
    assert c.holder.others == 1 and aj.decide(c).reason == "other_holder"


def test_a_second_held_person_line_of_the_word_is_another_holder(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    from api.services import pending_store

    pending_store.save(mem, [pending_store.PendingEntity(name="Sam Berg", type="person", description="", source_episode="",
                                                         confidence=0.5, tags=[], history_entries=[])])
    assert aj.gather(mem).cases[0].holder.others == 1


def test_the_owners_own_first_name_is_never_a_holder_and_the_owners_namesake_row_is_never_an_arrival(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    page = markdown_parser.parse(mem / "entities" / "sam.md")
    markdown_parser.write(mem / "entities" / "sam.md", {**page.frontmatter, "owner": True}, page.body)
    assert aj.gather(mem).cases[0].holder.block == "holder_owner"


def test_a_same_name_doubt_for_the_word_blocks(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    from api.services import same_name_doubts

    same_name_doubts.add_pairs(mem, [("sam", "sam-2")])
    assert aj.gather(mem).cases[0].holder.doubt is True


def test_what_the_person_removed_from_the_page_names_the_pair_in_the_history(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    page = markdown_parser.parse(mem / "entities" / "sam.md")
    fm = {**page.frontmatter, "aliases_removed": [{"alias": "Sam Okafor", "by": "user", "on": "2026-11-01"}]}
    markdown_parser.write(mem / "entities" / "sam.md", fm, page.body)
    c = aj.gather(mem).cases[0]
    assert c.rows[0].history == "removed" and aj.decide(c).reason == "history"


def test_a_page_that_already_carries_a_full_name_or_another_profile_points_elsewhere(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    page = markdown_parser.parse(mem / "entities" / "sam.md")
    markdown_parser.write(mem / "entities" / "sam.md", {**page.frontmatter, "aliases": ["Sam Berg"]}, page.body)
    assert aj.gather(mem).cases[0].holder.elsewhere == "full_name_alias"
    markdown_parser.write(mem / "entities" / "sam.md", {**page.frontmatter, "sources": [
        {"ref": f"{LI}/someone-else", "kind": "url", "predicate": "linkedin", "added_by": "user", "accepted": True}]}, page.body)
    assert aj.gather(mem).cases[0].holder.elsewhere == "profile_elsewhere"


def test_the_employer_a_page_holds_is_read_for_the_conflict_screen(tmp_path, monkeypatch):
    from api.services.claims import Claim, write_claims

    mem = _bank_with(tmp_path, monkeypatch, rows=[("Sam", "Okafor", f"{LI}/sam-okafor", "Beta Logistics", "Buyer", _day(2), "", "day")])
    page = markdown_parser.parse(mem / "entities" / "sam.md")
    claim = Claim(id="clm_sam_works", text="Sam works at Alpha Robotics", subject="sam", predicate="works-at",
                  object="Alpha Robotics", object_kind="literal", observer="user", context="career", epistemic="explicit",
                  source_trust="user", confidence=0.9, valid_from="2026-11-10", recorded_at="2026-11-10")
    markdown_parser.write(mem / "entities" / "sam.md", page.frontmatter, write_claims(page.body, [claim]))
    c = aj.gather(mem).cases[0]
    assert c.holder.companies == ("alpha robotics",)
    assert aj.decide(c).reason == "fact_conflict"


def test_a_demo_bank_and_a_bank_with_no_directory_read_nothing(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch, rows=[])
    assert aj.gather(mem).cases == []


# --- the step: reports, and writes NOTHING to the bank while LIVE is false -------------------------------------------


def _status(mem) -> str:
    return subprocess.run(["git", "-C", str(mem), "status", "--porcelain"], capture_output=True, text=True).stdout


def _head(mem) -> str:
    return subprocess.run(["git", "-C", str(mem), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _judge(*answers):
    seq = list(answers)
    calls: list[str] = []

    async def judge(system, prompt):
        calls.append(prompt)
        return {"verdict": seq.pop(0) if seq else "unsure", "quote": "", "reason": "x"}

    judge.calls = calls
    return judge


def test_it_ships_deciding_and_reporting_only():
    assert aj.LIVE is False


def test_the_step_decides_reports_and_writes_nothing_into_the_bank(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    before, head = _status(mem), _head(mem)
    judge = _judge("fits", "fits")
    report = asyncio.run(aj.run_tail(mem, None, user_triggered=False, judge=judge, today=__import__("datetime").date(2026, 11, 24)))
    assert (report.looked, report.candidates, report.reads, report.would_join, report.joined) == (1, 1, 1, 1, 0)
    assert report.joins == []                                  # LIVE false: nothing is handed back to write
    assert _status(mem) == before and _head(mem) == head       # not a byte of the bank, not a commit
    assert "Okafor" not in (mem / "entities" / "sam.md").read_text()
    assert len(judge.calls) == 2                               # the veto's two reads
    item = aj.load_report(mem.name)["items"][0]
    assert (item["page"], item["decision"], item["reason"], item["veto"]) == ("sam", "would_join", "ok", ["fits", "fits"])
    assert (item["holder_day"], item["arrival_day"], item["gap"], item["fresh"]) == (HOLDER_DAY, _day(2), 2, {"connection": "2026-11-24"})
    assert item["namesakes"][0]["role"] == "arrival" and aj.load_report(mem.name)["live"] is False


def test_a_second_night_reads_the_veto_from_its_cache_and_pays_nothing_again(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    first, second = _judge("fits", "fits"), _judge("conflict", "conflict")
    asyncio.run(aj.run_tail(mem, None, user_triggered=False, judge=first))
    report = asyncio.run(aj.run_tail(mem, None, user_triggered=False, judge=second))
    assert second.calls == [] and report.reads == 0 and report.would_join == 1


def test_a_veto_that_doubts_is_the_report_s_reason_and_no_join(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    report = asyncio.run(aj.run_tail(mem, None, user_triggered=False, judge=_judge("fits", "conflict")))
    item = aj.load_report(mem.name)["items"][0]
    assert report.would_join == 0 and (item["decision"], item["reason"], item["veto"]) == ("skip", "veto", ["fits", "conflict"])


def test_with_no_model_the_rules_run_and_the_veto_is_reported_unavailable(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch)
    report = asyncio.run(aj.run_tail(mem, None, user_triggered=False, no_model=True))
    item = aj.load_report(mem.name)["items"][0]
    assert report.skipped == "no_model" and item["reason"] == "veto_unavailable" and report.reads == 0


def test_the_veto_prompts_carry_the_page_and_the_entrys_company_never_its_name_or_link(tmp_path, monkeypatch):
    mem = _bank_with(tmp_path, monkeypatch, rows=[("Sam", "Okafor", f"{LI}/sam-okafor", "Beta Logistics", "Buyer", _day(2), "Buying", "day")])
    judge = _judge("fits", "fits")
    asyncio.run(aj.run_tail(mem, None, user_triggered=False, judge=judge))
    assert len(judge.calls) == 2 and judge.calls[0] != judge.calls[1]          # two differently phrased reads
    for prompt in judge.calls:
        assert "Beta Logistics" in prompt and "Buyer" in prompt and "Buying" in prompt and "sam" in prompt.lower()
        assert "Okafor" not in prompt and "linkedin.com" not in prompt


def test_a_plan_limit_pauses_the_veto_and_the_rules_still_report(tmp_path, monkeypatch):
    from api.services import engine_errors

    mem = _bank_with(tmp_path, monkeypatch)

    async def limited(system, prompt):
        raise engine_errors.EngineThrottled("limit")

    report = asyncio.run(aj.run_tail(mem, None, user_triggered=False, judge=limited))
    assert report.skipped == "plan_limit" and aj.load_report(mem.name)["items"][0]["reason"] == "veto_unavailable"


def test_a_bank_with_nothing_to_say_leaves_no_report_and_no_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    mem = _bank(tmp_path)
    asyncio.run(aj.run_tail(mem, None, user_triggered=False, no_model=True))
    assert not (tmp_path / "home" / "people").exists()


# --- the command ------------------------------------------------------------------------------------------------------


def test_the_command_prints_what_the_report_holds_per_item_and_names_only_on_request(tmp_path, monkeypatch, capsys):
    from api.scripts import arrival_join_report as cmd

    mem = _bank_with(tmp_path, monkeypatch)
    assert cmd.main(["--bank", str(mem), "--run"]) == 0
    out = capsys.readouterr().out
    assert "reporting only (writes nothing)" in out and "page sam" in out and "arrival" in out and "Okafor" not in out
    assert cmd.main(["--bank", str(mem), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["page"] == "sam"
    assert cmd.main(["--bank", str(mem), "--names"]) == 0
    assert "Sam Okafor" in capsys.readouterr().out                 # the terminal only, on request
    assert "Okafor" not in json.dumps(aj.load_report(mem.name))     # never in the report
    assert cmd.main(["--bank", str(tmp_path / "nowhere")]) == 2


# --- privacy (3.5): no directory row's name, company, headline or link in anything that persists -----------------------


def test_no_row_name_company_headline_or_link_reaches_the_report_the_cache_or_a_log(tmp_path, monkeypatch):
    from loguru import logger

    rows = [("Sam", "Okafor", f"{LI}/sam-okafor-secretslug", "Zebra Zeppelins", "Chief Zeppelin Officer", _day(2),
             "Zeppelin visionary", "day")]
    mem = _bank_with(tmp_path, monkeypatch, rows=rows)
    logs: list[str] = []
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG")
    try:
        asyncio.run(aj.run_tail(mem, None, user_triggered=False, judge=_judge("fits", "fits")))
    finally:
        logger.remove(sink)
    persisted = "".join(p.read_text() for p in (tmp_path / "home" / "people" / mem.name).glob("arrival-join-*.json"))
    assert persisted and "".join(logs) is not None
    for secret in ("Okafor", "okafor", "Zebra", "Zeppelin", "secretslug", "linkedin.com"):
        assert secret not in persisted, secret
        assert secret not in "".join(logs), secret
    assert _status(mem) == ""
