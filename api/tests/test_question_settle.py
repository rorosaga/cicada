"""Question settling (G98, ROR-31; owner rulings 2026-11-06 on the dry run): what Sleep may assume instead of asking,
and that no value said in a question is lost with it. Synthetic banks only; git is real; no engine, no network."""
from __future__ import annotations

import asyncio
import hashlib
import subprocess
from datetime import date
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import (
    bank_index,
    inbox_generator,
    inbox_questions,
    inbox_service,
    inbox_tend,
    inbox_wording,
    markdown_parser,
    predicates,
    value_words,
    web_settle,
)
from api.services.claims import Claim, parse_claims, write_claims

TODAY = date.today().isoformat()


def run(coro):
    return asyncio.run(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory: Path, msg: str = "seed") -> None:
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", msg)
    bank_index.invalidate()


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90
        self.llm_mode = "byok"


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    async def _fake(**kwargs):
        return f"{kwargs['new_description']}"

    monkeypatch.setattr("api.services.conflict_resolver._synthesize_entity_update", _fake)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    _entity(m, "owner-example", type="person", owner=True, name="Owner Example", status="active")
    _commit(m)
    return m


def _entity(memory: Path, eid: str, *, body: str | None = None, **fm) -> None:
    base = {"name": eid.replace("-", " ").title(), "type": "concept", "status": "active", "confidence": 0.8,
            "created": "2026-01-01", "last_referenced": "2026-05-01", "source_episodes": [], "tags": [],
            "related": [], "version": 1}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, body or f"## Summary\n{base['name']} line.\n")


def _item(memory: Path, item_id: str, body: str = "Context.", **fm) -> Path:
    base = {"status": "pending", "priority": 0.5, "created_date": "2026-09-01"}
    base.update(fm)
    path = memory / "inbox" / f"{item_id}.md"
    markdown_parser.write(path, base, body)
    return path


def _decide(memory: Path, item_id: str):
    path = memory / "inbox" / f"{item_id}.md"
    return inbox_tend.policy(memory, path, markdown_parser.parse(path).frontmatter)


def _settle(memory: Path, d) -> bool:
    d.fingerprint = (memory / "inbox" / f"{d.item_id}.md").read_bytes()
    return run(inbox_tend.apply(memory, _Settings(memory), d))


def _claim(cid: str, subject: str, predicate: str, obj: str, day: str, **kw) -> Claim:
    base = dict(id=cid, text=f"{subject} {predicate} {obj}", subject=subject, predicate=predicate, object=obj,
                observer="owner", context="general", source_trust="agent_extracted", origin="extraction",
                confidence=0.7, valid_from=day, recorded_at=day, source_episodes=["ep_2026-10-01_001"])
    base.update(kw)
    return Claim(**base)


def _claims(memory: Path, eid: str) -> dict[str, Claim]:
    return {c.object: c for c in parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)}


def _value_question(memory: Path, eid: str, predicate: str, page: list[Claim], offered: list[dict], **fm) -> None:
    """A conflict whose first answer is on the page and whose others reached only the question."""
    _entity(memory, eid, type="project", body=write_claims("## Summary\nA thing.\n", page))
    options = [{"key": "a", "label": page[0].object, "claim_id": page[0].id, "observed_at": page[0].valid_from}]
    options += offered
    options.append({"key": "both", "label": "Both"})
    _item(memory, "inbox-001", kind="conflict", entity_id=eid, entity_name=eid, predicate=predicate,
          question="Which?", options=options, **fm)
    _commit(memory)


def _offered(key: str, label: str, day: str, cid: str) -> dict:
    return {"key": key, "label": label, "claim_id": cid, "observed_at": day}


# --------------------------------------------------------------------------- value words


@pytest.mark.parametrize("labels", [["v0.3.2", "0.3.2"], ["$20 per month", "$20/mo"], ["29.8s", "29.8 s"],
                                    ["1,118", "about 1,118"], ["2022.3", "2022.3.62f2"], ["$5", "$5 per run"]])
def test_a_value_said_two_ways_is_one_value(labels):
    assert value_words.same_value(labels)


@pytest.mark.parametrize("labels", [["6840", "1180"], ["24%", "25%"], ["3", "3 million"], ["done", "done but not sent"],
                                    ["week", "forever"]])
def test_two_different_values_are_not(labels):
    assert not value_words.same_value(labels)


# --------------------------------------------------------------------------- same_value


def test_same_value_keeps_the_fuller_wording_and_closes_the_shorter(memory):
    _value_question(memory, "alpha-project", "value-of-sleep-spending-limit-per-run",
                    [_claim("clm_a", "alpha-project", "value-of-sleep-spending-limit-per-run", "$5", "2026-11-04")],
                    [_offered("b", "$5 per run", "2026-11-04", "clm_b")])
    d, _ = _decide(memory, "inbox-001")
    assert (d.rule, d.request, d.answer) == ("same_value", {"action": "resolve", "option_key": "b"}, "$5 per run")
    assert _settle(memory, d)
    held = _claims(memory, "alpha-project")
    assert held["$5 per run"].valid_to is None and held["$5"].valid_to is not None


def test_same_value_already_on_the_page_changes_nothing_and_adds_no_line(memory):
    _value_question(memory, "alpha-project", "value-of-version-in-use",
                    [_claim("clm_a", "alpha-project", "value-of-version-in-use", "v0.3.2", "2026-10-21")],
                    [_offered("b", "0.3.2", "2026-10-21", "clm_b")])
    before = (memory / "entities" / "alpha-project.md").read_text()
    d, _ = _decide(memory, "inbox-001")
    assert d.rule == "same_value" and d.request["option_key"] == "a"
    assert _settle(memory, d)
    assert (memory / "entities" / "alpha-project.md").read_text() == before     # no claim, no sentence, no bump
    assert not (memory / "inbox" / "inbox-001.md").exists()
    assert (memory / "inbox" / "settled" / "inbox-001.md").exists()


def test_two_values_from_one_conversation_stay_a_question(memory):
    """A conversation can change its mind: the rule that assumed otherwise is gone."""
    _value_question(memory, "alpha-project", "value-of-release-count",
                    [_claim("clm_a", "alpha-project", "value-of-release-count", "6", "2026-10-23")],
                    [_offered("b", "10", "2026-10-23", "clm_b")])
    assert "same_conversation" not in inbox_tend.RULES and "same_conversation" not in inbox_tend.ENGINE_FREE
    d, why = _decide(memory, "inbox-001")
    assert d is None


# --------------------------------------------------------------------------- moved_on / multi_valued


def test_a_part_that_moved_keeps_the_latest_and_closes_the_earlier_ones(memory):
    page = [_claim("clm_a", "part-one", "part-of", "suite-new", "2026-10-09")]
    _value_question(memory, "part-one", "part-of", page,
                    [_offered("b", "suite-old", "2026-07-27", "clm_b"), _offered("bx", "suite-older", "2026-05-05", "clm_c")])
    d, _ = _decide(memory, "inbox-001")
    assert (d.rule, d.request) == ("moved_on", {"action": "resolve", "option_key": "a"})
    assert _settle(memory, d)
    held = _claims(memory, "part-one")
    assert held["suite-new"].valid_to is None
    for old, day in (("suite-old", "2026-07-27"), ("suite-older", "2026-05-05")):
        assert held[old].valid_from == day and held[old].valid_to == "2026-10-09"
        assert held[old].source_trust != "user_stated" and held[old].authored_by != "user"


def test_values_said_the_same_day_for_a_part_are_a_set(memory):
    page = [_claim("clm_a", "part-one", "part-of", "suite-a", "2026-10-14")]
    _value_question(memory, "part-one", "part-of", page, [_offered("b", "suite-b", "2026-10-14", "clm_b")])
    d, _ = _decide(memory, "inbox-001")
    assert (d.rule, d.request) == ("multi_valued", {"action": "dismiss"})
    assert _settle(memory, d)
    held = _claims(memory, "part-one")
    assert held["suite-a"].valid_to is None and held["suite-b"].valid_to is None


def test_runs_on_is_a_set_and_the_seed_says_so(memory):
    assert predicates.cardinality(memory, "runs-on") == "multi" and predicates.cardinality(memory, "part-of") == "multi"
    page = [_claim("clm_a", "tool-one", "runs-on", "host-a", "2026-10-16")]
    _value_question(memory, "tool-one", "runs-on", page, [_offered("b", "host-b", "2026-09-08", "clm_b")])
    d, _ = _decide(memory, "inbox-001")
    assert d.rule == "multi_valued"      # not a move: only `part-of` moves


# --------------------------------------------------------------------------- the loser of a pick


def test_a_pick_writes_the_value_only_the_question_held_as_closed(memory):
    _value_question(memory, "alpha-project", "value-of-owner-city",
                    [_claim("clm_a", "alpha-project", "value-of-owner-city", "Lisbon", "2026-02-01")],
                    [_offered("b", "Porto", "2026-02-01", "clm_b")])
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="resolve", optionKey="a"),
                              _Settings(memory)))
    held = _claims(memory, "alpha-project")
    assert held["Lisbon"].valid_to is None
    assert held["Porto"].valid_to is not None and held["Porto"].source_trust != "user_stated"


def test_a_respelling_of_the_kept_value_is_not_written_as_a_loser(memory):
    _value_question(memory, "alpha-project", "value-of-version-in-use",
                    [_claim("clm_a", "alpha-project", "value-of-version-in-use", "v0.3.2", "2026-10-21")],
                    [_offered("b", "0.3.2", "2026-10-21", "clm_b")])
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="resolve", optionKey="a"),
                              _Settings(memory)))
    assert set(_claims(memory, "alpha-project")) == {"v0.3.2"}


# --------------------------------------------------------------------------- a closing question keeps its values


def test_a_question_closed_by_a_later_value_keeps_the_value_only_it_held(memory):
    page = [_claim("clm_a", "alpha-project", "value-of-owner-city", "Lisbon", "2026-02-01", valid_to="2026-03-01",
                   superseded_by="clm_c"),
            _claim("clm_c", "alpha-project", "value-of-owner-city", "Madrid", "2026-03-01")]
    _entity(memory, "alpha-project", type="project", body=write_claims("## Summary\nA thing.\n", page))
    _item(memory, "inbox-001", kind="conflict", entity_id="alpha-project", predicate="value-of-owner-city",
          options=[{"key": "a", "label": "Lisbon", "claim_id": "clm_a", "observed_at": "2026-02-01"},
                   _offered("b", "Porto", "2026-02-01", "clm_b")])
    _commit(memory)
    settings = _Settings(memory)
    result = inbox_questions.refresh_open_questions(
        memory, {"alpha-project": page}, "2026-11-06",
        keep_values=lambda fm: inbox_service.keep_values_of_closed_question(settings, fm))
    assert result["organic_resolutions"] == 1 and result["written_paths"] == ["entities/alpha-project.md"]
    held = _claims(memory, "alpha-project")
    assert held["Porto"].valid_to is not None and held["Porto"].source_trust != "user_stated"
    assert not (memory / "inbox" / "inbox-001.md").exists()


def test_a_question_that_cannot_keep_its_values_stays(memory):
    page = [_claim("clm_c", "alpha-project", "value-of-owner-city", "Madrid", "2026-03-01", valid_to="2026-04-01",
                   superseded_by="clm_d")]
    _entity(memory, "alpha-project", type="project", body=write_claims("## Summary\nA thing.\n", page))
    _item(memory, "inbox-001", kind="conflict", entity_id="alpha-project", predicate="value-of-owner-city",
          options=[{"key": "a", "label": "Madrid", "claim_id": "clm_c", "observed_at": "2026-03-01"},
                   _offered("b", "Porto", "2026-02-01", "clm_b")])

    def boom(fm):
        raise RuntimeError("page unreadable")

    inbox_questions.refresh_open_questions(memory, {"alpha-project": page}, "2026-11-06", keep_values=boom)
    assert (memory / "inbox" / "inbox-001.md").exists()


# --------------------------------------------------------------------------- bookkeeping


@pytest.mark.parametrize("entity,predicate,expected", [
    ("owner-example", "value-of-weekly-plan-counter", True),
    ("owner-example", "value-of-plan-weekly-usage", True),
    ("owner-example", "value-of-claude-plan-weekly-limit", True),
    ("cicada", "value-of-open-inbox-questions", True),
    ("cicada", "value-of-conversations-in-bank", True),
    ("cicada", "value-of-backend-test-result", True),
    ("alpha-project", "value-of-backend-test-result", False),     # another project's tests are its own business
    ("cicada", "value-of-sleep-spending-limit-per-run", False),    # a setting: `own_settings`, never a counter here
    ("alpha-project", "value-of-university-payment-amount", False),
    ("alpha-project", "runs-on", False),
])
def test_what_counts_as_cicadas_own_bookkeeping(entity, predicate, expected):
    assert web_settle.own_bookkeeping(entity, predicate) is expected


def test_a_counter_question_is_retired_with_nothing_written(memory):
    page = [_claim("clm_a", "owner-example", "value-of-weekly-plan-counter", "24%", "2026-11-05")]
    _value_question(memory, "owner-example", "value-of-weekly-plan-counter", page,
                    [_offered("b", "25%", "2026-11-05", "clm_b")])
    before = (memory / "entities" / "owner-example.md").read_text()
    d, _ = _decide(memory, "inbox-001")
    assert (d.rule, d.request) == ("own_bookkeeping", None)
    assert _settle(memory, d)
    assert (memory / "entities" / "owner-example.md").read_text() == before


def test_a_counter_reading_never_opens_a_question(memory):
    page = _claim("clm_a", "alpha-project", "value-of-plan-weekly-usage", "24%", "2026-11-05")
    other = _claim("clm_b", "alpha-project", "value-of-plan-weekly-usage", "25%", "2026-11-05")
    _entity(memory, "alpha-project", type="project", body=write_claims("## Summary\nA thing.\n", [page]))
    from api.services import claim_reconciler

    out = inbox_generator.write_claim_nudges([claim_reconciler._conflict_nudge(page, other, "2026-11-06")], memory)
    assert out["written"] == 0 and out["skipped_bookkeeping"] == 1
    assert not list((memory / "inbox").glob("inbox-*.md"))


# --------------------------------------------------------------------------- already_described / not_fading


def _clarification(memory: Path, name: str, words: str, body: str = "", **fm) -> None:
    _item(memory, "inbox-001", body, kind="clarification", entity_id=name, entity_name=name,
          uncertainty_type="Insufficient context to classify", suggested_classification=f"concept — {words}"[:120],
          **fm)
    _commit(memory)


def test_a_name_sleep_described_is_retired_with_nothing_written(memory):
    words = "Alpha Handbook is a study text planned for one chapter a week in October 2023."
    _clarification(memory, "alpha-handbook", words, words)
    d, _ = _decide(memory, "inbox-001")
    assert (d.rule, d.request) == ("already_described", None)
    assert _settle(memory, d)
    assert not (memory / "entities" / "alpha-handbook.md").exists()


@pytest.mark.parametrize("tail", [
    " The conversation does not name it.",
    " Its details are not stated.",
    " The account is probably a savings account.",
    " Install it if Rodrigo confirms he wants it.",
    " It is the label on a password note.",
])
def test_the_whole_text_is_read_so_an_admission_after_the_first_line_keeps_the_question(memory, tail):
    first = ("Alpha Handbook is a study text planned for one chapter a week in October 2023, as listed in a note "
             "that a friend shared alongside the reading list.")
    _clarification(memory, "alpha-handbook", first, first + tail)   # the stored line is cut; the body is whole
    assert len(first) > 120
    d, why = _decide(memory, "inbox-001")
    assert d is None


def test_a_question_the_person_was_asked_on_purpose_is_never_retired(memory):
    words = "Alpha Handbook is a study text planned for one chapter a week."
    _clarification(memory, "alpha-handbook", words, words, why_asked="a plan rests on it")
    assert _decide(memory, "inbox-001")[0] is None


def test_a_page_back_over_the_line_retires_its_decay_question(memory):
    _entity(memory, "alpha-tool", type="tool", confidence=0.55, status="active")
    _item(memory, "inbox-001", kind="decay", entity_id="alpha-tool", entity_name="Alpha Tool")
    d, _ = _decide(memory, "inbox-001")
    assert (d.rule, d.request) == ("not_fading", None)
    assert _settle(memory, d)
    assert "confidence: 0.55" in (memory / "entities" / "alpha-tool.md").read_text()   # nothing touched


def test_a_page_still_fading_is_not_retired(memory):
    _entity(memory, "alpha-tool", type="tool", confidence=0.36, status="active", source_episodes=["ep_x", "ep_y"])
    _item(memory, "inbox-001", kind="decay", entity_id="alpha-tool", entity_name="Alpha Tool")
    d, _ = _decide(memory, "inbox-001")
    assert d is None or d.rule != "not_fading"


# --------------------------------------------------------------------------- vetted apply


def _row(memory: Path, item_id: str, d) -> dict:
    path = memory / "inbox" / f"{item_id}.md"
    return {"id": item_id, "kind": d.kind, "apply": {"rule": d.rule, "request": d.request, "guard": d.guard,
                                                     "item_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}


def test_the_new_rules_are_vetted(memory):
    for rule in ("same_value", "moved_on", "own_bookkeeping", "already_described", "not_fading"):
        assert rule in inbox_tend.VETTED_RULES and rule in inbox_tend.ENGINE_FREE
    _value_question(memory, "alpha-project", "value-of-version-in-use",
                    [_claim("clm_a", "alpha-project", "value-of-version-in-use", "v0.3.2", "2026-10-21")],
                    [_offered("b", "0.3.2", "2026-10-21", "clm_b")])
    d, _ = _decide(memory, "inbox-001")
    vetted, _engine = inbox_tend.vetted_decision(memory, _row(memory, "inbox-001", d))
    assert vetted.rule == "same_value" and vetted.request == d.request
    with pytest.raises(inbox_tend.Unvetted):   # a request this rule never produces
        row = _row(memory, "inbox-001", d)
        row["apply"]["request"] = {"action": "resolve", "option_key": "both"}
        inbox_tend.vetted_decision(memory, row)


# --------------------------------------------------------------------------- a new contradiction opens its own question


def _description_change(a: str, b: str) -> dict:
    return {"action": "conflict_nudge", "id": "alpha-page", "entity": {"name": "Alpha Page"},
            "question": "Which is right?", "options": [
                {"key": "a", "label": a, "claim_id": None}, {"key": "b", "label": b, "claim_id": None},
                {"key": "both", "label": "Both are true (different contexts)", "claim_id": None},
                {"key": "neither", "label": "Neither", "claim_id": None}]}


def _open(memory: Path) -> list[Path]:
    return sorted((memory / "inbox").glob("inbox-*.md"))


def test_an_unrelated_contradiction_opens_its_own_question(memory):
    _entity(memory, "alpha-page", type="company")
    today = TODAY
    assert not inbox_generator.fold_into_open(memory, "conflict", "alpha-page", "description",
                                              _description_change("Sells software", "Sells hardware")["options"], today)
    asyncio.run(inbox_generator.generate([_description_change("Sells software", "Sells hardware")], [], memory))
    assert len(_open(memory)) == 1
    asyncio.run(inbox_generator.generate([_description_change("Founded in April", "Founded in August")], [], memory))
    opens = _open(memory)
    assert len(opens) == 2
    for path in opens:
        real = [o for o in markdown_parser.parse(path).frontmatter["options"] if o["key"] not in ("both", "neither")]
        assert len(real) == 2     # no pile-up: each question holds its own pair


def test_the_same_contradiction_in_other_words_joins_the_open_question(memory):
    _entity(memory, "alpha-page", type="company")
    asyncio.run(inbox_generator.generate([_description_change("Already in production", "Still in the beta")], [], memory))
    asyncio.run(inbox_generator.generate([_description_change("Already shipped to production", "Final beta weeks")],
                                         [], memory))
    assert len(_open(memory)) == 1


def test_past_the_cap_a_new_contradiction_folds_into_the_newest(memory):
    _entity(memory, "alpha-page", type="company")
    pairs = [("Sells software", "Sells hardware"), ("Founded in April", "Founded in August"),
             ("Based in Lisbon", "Based in Porto"), ("Has ten staff", "Has fifty staff"),
             ("Owned by a family", "Owned by a fund")]
    for a, b in pairs:
        asyncio.run(inbox_generator.generate([_description_change(a, b)], [], memory))
    assert len(_open(memory)) == inbox_generator.MAX_OPEN_CONTRADICTIONS


def test_a_value_conflict_still_has_one_question_a_key(memory):
    page = _claim("clm_a", "alpha-page", "value-of-owner-city", "Lisbon", "2026-02-01")
    _entity(memory, "alpha-page", type="company", body=write_claims("## Summary\nA.\n", [page]))
    from api.services import claim_reconciler

    for city in ("Porto", "Braga"):
        inbox_generator.write_claim_nudges(
            [claim_reconciler._conflict_nudge(page, _claim(f"clm_{city}", "alpha-page", "value-of-owner-city", city,
                                                           "2026-02-02"), "2026-03-01")], memory)
    assert len(_open(memory)) == 1


# --------------------------------------------------------------------------- the relation, in plain words


def test_a_person_known_only_by_relation_is_asked_as_that_relation():
    fm = {"kind": "merge_suggestion", "entity_name": "Alex Example (unnamed)", "entity_id": "alex-example",
          "merge_target_hint": "partner"}
    relation_page = {"name": "Partner", "type": "person", "unnamed": True, "owner_roles": ["Partner"]}
    said = inbox_wording.spoken(fm, "2026-11-06", page_fm={"name": "Alex Example", "type": "person"},
                                other_fm=relation_page)
    assert said.question == "Is Alex Example your partner?"
    back = inbox_wording.spoken({**fm, "entity_name": "Partner", "entity_id": "partner"}, "2026-11-06",
                                page_fm=relation_page, other_fm={"name": "Alex Example", "type": "person"})
    assert back.question == "Is Alex Example your partner?"


def test_two_named_people_are_still_asked_as_a_pair():
    fm = {"kind": "merge_suggestion", "entity_name": "Alex Example", "entity_id": "alex-example",
          "merge_target_hint": "alex-sample"}
    said = inbox_wording.spoken(fm, "2026-11-06", page_fm={"name": "Alex Example", "type": "person"},
                                other_fm={"name": "Alex Sample", "type": "person"})
    assert said.question == "Are Alex Example and Alex Sample the same person?"
