"""Sleep looks at open questions again and closes the ones the record answers (ruling 81, owner 2026-11-24).

Synthetic banks only (invented people, a fake judge, real git). The engine is injected; nothing reaches a network."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from api.services import bank_index, inbox_tend, markdown_parser, merge_rejections, predicates, question_revisit, web_settle
from api.services.claims import Claim, Evidence, parse_claims, write_claims


def run(coro):
    return asyncio.run(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory: Path, msg: str = "seed") -> None:
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", msg)
    bank_index.invalidate(memory)


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90
        self.llm_mode = "byok"


def _page(memory: Path, pid: str, name: str, body: str, **fm) -> None:
    meta = {"name": name, "type": "person", "status": "active", "confidence": 0.8, "created": "2026-10-01",
            "last_referenced": "2026-11-14", "source_episodes": [], "related": [], "version": 1, **fm}
    markdown_parser.write(memory / "entities" / f"{pid}.md", meta, body)


def _episode(memory: Path, eid: str, text: str, **fm) -> None:
    meta = {"id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00", "processed": True, "title": "chat", "source": "claude-code"}
    markdown_parser.write(memory / "episodes" / f"{eid}.md", {**meta, **fm}, text)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(inbox_tend, "_RECORD_READ", {})
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    _page(m, "owner-example", "Owner Example", "## Summary\nThe owner.\n", owner=True)
    _commit(m)
    return m


APPOSITION = "Teodor Brandt, called Teo, starts on the platform team at Kestrel Robotics on Monday."
TOGETHER_TWO = "Teo and Teodor Brandt both came to the offsite, they sat at different tables."


def _pair(memory: Path, *, turn: str = APPOSITION, role: str = "user", extra_pages: bool = False, same_fact: bool = True) -> Path:
    """Two person pages, the short name and the full name, a conversation naming both, the open question."""
    first = "ep_2026-10-03_001"
    _episode(memory, first, f"{role}: {turn}\n\nassistant: Noted.\n" if role == "user" else f"user: Hello.\n\nassistant: {turn}\n")
    _episode(memory, "ep_2026-10-20_001", "user: Teo sent the rota for the week.\n\nassistant: Thanks.\n")
    _episode(memory, "ep_2026-10-21_001", "user: Teodor Brandt reviewed the migration plan.\n\nassistant: Good.\n")
    fact_a = "Teo leads the migration of the billing platform at Kestrel Robotics."
    fact_b = ("Teodor Brandt leads the migration of the billing platform at Kestrel Robotics." if same_fact
              else "Teodor Brandt is a salesman at Kestrel Robotics.")
    _page(memory, "teo", "Teo", f"## Summary\n{fact_a}\n\n## Key Facts\n- {fact_a}\n", source_episodes=["ep_2026-10-03_001", "ep_2026-10-20_001"])
    _page(memory, "teodor-brandt", "Teodor Brandt", f"## Summary\n{fact_b}\n\n## Key Facts\n- {fact_b}\n",
          source_episodes=["ep_2026-10-03_001", "ep_2026-10-21_001"])
    if extra_pages:
        _page(memory, "teodora-vance", "Teodora Vance", "## Summary\nTeodora Vance, a neighbour.\n")
    path = memory / "inbox" / "inbox-001.md"
    markdown_parser.write(path, {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.6, "entity_id": "teo",
        "entity_name": "Teo", "title": "Are Teo and Teodor Brandt the same person?", "created_date": "2026-11-01",
        "merge_target_hint": "teodor-brandt", "detected": "person_duplicate", "signals": ["short_in_full"],
        "source_episode": first}, "Why this is asked: one name is part of the other.")
    _commit(memory)
    return path


def _judge(*replies, calls: list | None = None):
    queue = list(replies)

    async def judge(system: str, prompt: str):
        if calls is not None:
            calls.append(prompt)
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return {**reply, "_model": "fake-main"}

    return judge


ONE_SAID = {"verdict": "one", "said_turn": 1, "said": "Teodor Brandt, called Teo, starts on the platform team",
            "reason": "one line presents them as one"}


def _assess(memory: Path, path: Path, judge):
    return run(question_revisit.assess(memory, path, dict(markdown_parser.parse(path).frontmatter), judge, speaker="Owner Example"))


# --------------------------------------------------------------------------- two people, one person


def test_a_located_line_that_presents_both_names_as_one_is_read_twice_and_joins(memory):
    path = _pair(memory)
    calls: list = []
    result = _assess(memory, path, _judge(ONE_SAID, calls=calls))
    assert (result.outcome, result.why) == ("join", "") and result.reads == 2
    d = result.decision
    assert d.rule == "revisit_one" and d.request == {"action": "merge", "merge_target": "teodor-brandt"}
    assert d.spans and d.spans[0]["kind"] == "user" and d.quote["episode"] == "ep_2026-10-03_001"
    assert "sceptical reader" in calls[1] and "sceptical reader" not in calls[0]


def test_a_line_in_an_assistants_turn_counts_and_its_kind_is_recorded(memory):
    path = _pair(memory, role="assistant")
    result = _assess(memory, path, _judge(ONE_SAID))
    assert result.outcome == "join"
    assert [s["kind"] for s in result.decision.spans] == ["assistant"]
    assert result.decision.quote is None      # the person's words only ever ride as the person's quote


def test_words_that_are_not_in_a_turn_shown_withdraw_the_answer(memory):
    path = _pair(memory)
    invented = {**ONE_SAID, "said": "Teodor Brandt is also known as Teo to everyone at Kestrel"}
    result = _assess(memory, path, _judge(invented))
    assert result.outcome == "unsure" and result.reads == 1       # a name-only pair has one kind: not enough


def test_a_quote_that_does_not_carry_both_names_is_no_evidence(memory):
    path = _pair(memory)
    one_name = {**ONE_SAID, "said": "starts on the platform team at Kestrel Robotics on Monday"}
    assert _assess(memory, path, _judge(one_name)).outcome == "unsure"


def test_the_second_read_looks_for_the_other_answer_and_any_two_stops_it(memory):
    path = _pair(memory)
    result = _assess(memory, path, _judge(ONE_SAID, {"verdict": "two", "reason": "different people"}))
    assert result.outcome == "two" and result.reads == 2 and result.decision is None
    assert _assess(memory, path, _judge({"verdict": "cannot_tell"})).outcome == "unsure"
    assert _assess(memory, path, _judge("not json")).outcome == "unread"


def test_two_people_named_in_one_breath_stay_two_when_either_read_says_so(memory):
    path = _pair(memory, turn=TOGETHER_TWO)
    belief = {"verdict": "one", "here": "Teo leads the migration of the billing platform at Kestrel Robotics.",
              "there": "Teodor Brandt leads the migration of the billing platform at Kestrel Robotics.", "reason": "same"}
    two = {"verdict": "two", "reason": "the offsite turn names them as two people at different tables"}
    calls: list = []
    result = _assess(memory, path, _judge(belief, two, calls=calls))
    assert result.outcome == "two" and result.decision is None and result.reads == 2
    assert "both came to the offsite" in calls[0] and "NAMING BOTH" in calls[0]     # every turn naming both is shown, whole
    assert _assess(memory, path, _judge(two)).outcome == "two"


def test_a_belief_needs_name_and_a_second_kind_and_lines_found_on_each_side(memory):
    path = _pair(memory, turn=TOGETHER_TWO)
    ok = {"verdict": "one", "here": "Teo leads the migration of the billing platform at Kestrel Robotics.",
          "there": "Teodor Brandt leads the migration of the billing platform at Kestrel Robotics.", "reason": "same fact"}
    assert _assess(memory, path, _judge(ok)).outcome == "join"
    wrong_side = {**ok, "there": "Teodor Brandt runs the whole sales team at Kestrel Robotics."}
    assert _assess(memory, path, _judge(wrong_side)).outcome == "unsure"
    common = _pair_common_ground(memory)
    assert _assess(memory, common, _judge({"verdict": "one", "here": "Teo works at Kestrel Robotics as an engineer.",
                                            "there": "Teodor Brandt works at Kestrel Robotics as an engineer.",
                                            "reason": "same"})).outcome in ("unsure", "join")


def _pair_common_ground(memory: Path) -> Path:
    _page(memory, "teo", "Teo", "## Summary\nTeo works at Kestrel Robotics as an engineer.\n")
    _page(memory, "teodor-brandt", "Teodor Brandt", "## Summary\nTeodor Brandt works at Kestrel Robotics as an engineer.\n")
    _commit(memory)
    return memory / "inbox" / "inbox-001.md"


def test_guards_leave_what_only_the_person_may_say(memory):
    path = _pair(memory)
    fm = dict(markdown_parser.parse(path).frontmatter)
    assert question_revisit.pair_case(memory, path, fm)[0] is not None
    # a pair the person called two
    merge_rejections.add_rejected(memory, "teo", "teodor-brandt")
    assert question_revisit.pair_case(memory, path, fm)[1] == "kept_apart"


def test_a_short_name_another_page_could_be_is_left_for_the_person(memory):
    path = _pair(memory, extra_pages=True)
    case, why = question_revisit.pair_case(memory, path, dict(markdown_parser.parse(path).frontmatter))
    assert case is None and why == "short_name_not_alone"


def test_the_owners_page_and_an_undone_question_are_never_read(memory):
    path = _pair(memory)
    fm = dict(markdown_parser.parse(path).frontmatter)
    markdown_parser.write(path, {**fm, "entity_id": "owner-example"}, "x")
    assert question_revisit.pair_case(memory, path, {**fm, "entity_id": "owner-example"})[0] is None
    markdown_parser.write(path, {**fm, "sleep_settle": "undone"}, "x")
    assert [p.stem for p, _ in question_revisit.candidates(memory)] == []


# --------------------------------------------------------------------------- the whole step


def test_the_step_joins_one_pair_as_sleeps_commit_and_listed_with_its_evidence(memory):
    path = _pair(memory)
    report = run(question_revisit.tend(memory, _Settings(memory), _llm(ONE_SAID, ONE_SAID), model="fake-main"))
    assert report.settled == 1 and report.read == 1
    assert not path.exists()
    row = web_settle.list_settled(memory)[0]
    assert row["rule"] == "revisit_one" and "called Teo" in row["reason"]
    rec = markdown_parser.parse(memory / "inbox" / "settled" / "inbox-001.md").frontmatter["settled"]
    assert rec["evidence_spans"][0]["episode"] == "ep_2026-10-03_001"
    names = markdown_parser.parse(memory / "entities" / "teodor-brandt.md").frontmatter
    assert "Teo" in (names.get("aliases") or [])
    # an undo is the person saying they are two: the pair is kept apart and the question does not come back
    inbox_tend.undo(memory, "inbox-001")
    assert merge_rejections.is_rejected(memory, "teo", "teodor-brandt") or merge_rejections.is_split(memory, "teo", "teodor-brandt")


def _llm(*replies, calls: list | None = None):
    queue = list(replies)

    def fn(messages, **_kw):
        if calls is not None:
            calls.append("\n".join(str(m["content"]) for m in messages))
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return {"choices": [{"message": {"content": json.dumps(reply)}}], "model": "fake-main"}

    return fn


def test_what_was_read_is_not_read_again_until_it_changes_or_the_reader_is_stronger(memory, monkeypatch):
    monkeypatch.setattr("api.services.pair_evidence.FRESH_S", 0.0)    # the lexical index is rebuilt for each look here
    _pair(memory)
    calls: list = []
    fn = _llm({"verdict": "cannot_tell"}, calls=calls)
    run(question_revisit.tend(memory, _Settings(memory), fn, model="claude-haiku-4"))
    assert len(calls) == 1
    run(question_revisit.tend(memory, _Settings(memory), fn, model="claude-haiku-4"))
    assert len(calls) == 1                                   # same material, same reader: not read again
    seen = json.dumps(question_revisit._seen(memory))
    assert "Teo" not in seen and "ep_" not in seen           # ids and a hash only, outside every bank
    run(question_revisit.tend(memory, _Settings(memory), fn, model="claude-sonnet-4"))
    assert len(calls) == 2                                   # a stronger reader reads it once more
    _episode(memory, "ep_2026-11-20_001", "user: Teo is leading the design review.\n")
    _commit(memory)
    run(question_revisit.tend(memory, _Settings(memory), fn, model="claude-sonnet-4"))
    assert len(calls) == 3                                   # a conversation about it arrived


def test_a_run_reads_a_fixed_few_and_looks_at_the_rest_next_time(memory):
    _pair(memory)
    calls: list = []
    report = run(question_revisit.tend(memory, _Settings(memory), _llm({"verdict": "cannot_tell"}, calls=calls),
                                       max_reads=0, model="m"))
    assert calls == [] and report.skipped.get("max_reads") == 1


def test_a_dry_run_reads_and_counts_and_writes_nothing(memory):
    path = _pair(memory)
    rows: list = []
    report = run(question_revisit.tend(memory, _Settings(memory), _llm(ONE_SAID), dry_run=True, trace=rows.append, model="m"))
    assert report.settled == 1 and path.exists() and not (memory / "inbox" / "settled").exists()
    assert rows == [{"id": "inbox-001", "kind": "merge_suggestion", "what": "would_join", "rule": "revisit_one",
                     "evidence": rows[0]["evidence"]}]
    assert question_revisit._seen(memory) == {}


def test_no_engine_no_read_and_a_demo_bank_is_never_read(memory, monkeypatch):
    _pair(memory)
    from api.services import demo_guard, same_name_tend

    async def none(settings, *, user_triggered):
        return None, "no_engine"

    monkeypatch.setattr(same_name_tend, "main_engine", none)
    assert run(question_revisit.run_tail(memory, _Settings(memory), user_triggered=True)).skipped == {"no_engine": 1}
    monkeypatch.setattr(demo_guard, "is_demo", lambda m: True)
    assert run(question_revisit.run_tail(memory, _Settings(memory), user_triggered=True, llm_fn=_llm(ONE_SAID))).skipped == {"demo": 1}


# --------------------------------------------------------------------------- conflicts and clarifications


def _conflict(memory: Path, *, later: str | None) -> None:
    old = Claim(id="clm_old", text="Tool A runs on alpha-os", subject="tool-a", predicate="takes-place-in", object="alpha-os",
                valid_from="2026-05-01", recorded_at="2026-05-01", evidence=[Evidence(episode="ep_2026-05-01_001", kind="user")])
    new = Claim(id="clm_new", text="Tool A runs on beta-os", subject="tool-a", predicate="takes-place-in", object="beta-os",
                valid_from="2026-05-01", recorded_at="2026-05-01", evidence=[Evidence(episode="ep_2026-05-01_002", kind="user")])
    _page(memory, "tool-a", "Tool A", write_claims("## Summary\nA tool.\n", [old, new]), type="tool", source_episodes=["ep_2026-05-01_001"])
    markdown_parser.write(memory / "inbox" / "inbox-002.md", {
        "kind": "conflict", "status": "pending", "priority": 0.5, "created_date": "2026-05-02", "entity_id": "tool-a",
        "entity_name": "Tool A", "predicate": "takes-place-in", "question": "What does Tool A run on?",
        "options": [{"key": "a", "label": "alpha-os", "claim_id": "clm_old"}, {"key": "b", "label": "beta-os", "claim_id": "clm_new"},
                    {"key": "both", "label": "Both"}]}, "Context.")
    _episode(memory, "ep_2026-05-01_001", "user: Tool A runs on alpha-os.\n")
    _episode(memory, "ep_2026-05-01_002", "user: Tool A runs on beta-os.\n")
    if later:
        _episode(memory, "ep_2026-10-01_001", later)
    _commit(memory)


PICK_B = {"answered": True, "option": "b", "conversation": "C1", "quote": "Tool A runs on beta-os now, I moved everything"}


def test_a_conflict_is_settled_by_the_persons_newest_words_read_twice(memory):
    _conflict(memory, later="user: Tool A runs on beta-os now, I moved everything last week.\n")
    calls: list = []
    fn = _llm(PICK_B, {"option": "b"}, calls=calls)
    report = run(question_revisit.tend(memory, _Settings(memory), fn, model="fake-main"))
    assert report.settled == 1 and len(calls) == 2 and "WRONG" in calls[1]
    row = web_settle.list_settled(memory)[0]
    assert row["rule"] == "said_on_record" and row["episode"] == "ep_2026-10-01_001"
    claims = {c.id: c for c in parse_claims((memory / "entities" / "tool-a.md").read_text())}
    assert claims["clm_old"].valid_to == "2026-10-01"      # the other value is kept, closed: none is dropped (ruling 73)


def test_a_second_read_that_names_another_option_leaves_the_conflict_alone(memory):
    _conflict(memory, later="user: Tool A runs on beta-os now, I moved everything last week.\n")
    report = run(question_revisit.tend(memory, _Settings(memory), _llm(PICK_B, {"option": "none"}), model="fake-main"))
    assert report.settled == 0 and (memory / "inbox" / "inbox-002.md").exists()


def test_a_conflict_with_no_later_word_costs_no_read(memory):
    _conflict(memory, later=None)
    calls: list = []
    report = run(question_revisit.tend(memory, _Settings(memory), _llm(PICK_B, calls=calls), model="fake-main"))
    assert calls == [] and report.read == 0 and report.settled == 0


def test_a_later_word_about_something_else_settles_nothing(memory):
    _conflict(memory, later="user: Tool A is great, I use it daily.\n")
    report = run(question_revisit.tend(memory, _Settings(memory), _llm({"answered": False}), model="fake-main"))
    assert report.settled == 0 and (memory / "inbox" / "inbox-002.md").exists()


def test_a_decay_question_a_later_mention_answered_is_closed_without_a_model(memory):
    _page(memory, "tool-b", "Tool B", "## Summary\nA tool.\n", type="tool", status="active", confidence=0.8)
    markdown_parser.write(memory / "inbox" / "inbox-003.md", {"kind": "decay", "status": "pending", "priority": 0.4,
                          "created_date": "2026-09-01", "entity_id": "tool-b", "entity_name": "Tool B"}, "Fading?")
    _commit(memory)
    d, _ = inbox_tend.policy(memory, memory / "inbox" / "inbox-003.md",
                             dict(markdown_parser.parse(memory / "inbox" / "inbox-003.md").frontmatter))
    assert d is not None and d.rule == "not_fading"
    _page(memory, "tool-b", "Tool B", "## Summary\nA tool.\n", type="tool", status="decaying", confidence=0.35)
    _commit(memory)
    d, why = inbox_tend.policy(memory, memory / "inbox" / "inbox-003.md",
                               dict(markdown_parser.parse(memory / "inbox" / "inbox-003.md").frontmatter))
    assert d is None or d.rule != "not_fading"


def test_stronger_means_a_higher_family_or_a_changed_unranked_model():
    assert question_revisit.stronger("claude-sonnet-4", "claude-haiku-4") and not question_revisit.stronger("claude-haiku-4", "claude-sonnet-4")
    assert question_revisit.stronger("model-x", "model-y") and not question_revisit.stronger("model-x", "model-x")
    assert not question_revisit.stronger("claude-sonnet-4", "")


# --------------------------------------------------------------------------- details


def test_a_short_name_inside_the_full_name_does_not_count_as_naming_the_short_page():
    a, b = ["Teo"], ["Teodor Brandt", "Teo Brandt"]
    assert question_revisit._hits(a, b, "Teo Brandt started on Monday.") == (False, True)
    assert question_revisit._hits(a, b, "Teo Brandt, called Teo, started on Monday.") == (True, True)
    assert question_revisit._hits(["Will"], ["William Hart"], "I will see William Hart.") == (False, True)   # the verb, not the page
    assert question_revisit._hits(["Will"], ["William Hart"], "Will called William Hart.") == (True, True)


def test_a_page_that_changed_after_the_reads_leaves_the_question(memory):
    path = _pair(memory)
    result = _assess(memory, path, _judge(ONE_SAID))
    assert result.outcome == "join"
    fm = dict(markdown_parser.parse(memory / "entities" / "teo.md").frontmatter)
    markdown_parser.write(memory / "entities" / "teo.md", {**fm, "tags": ["edited"]}, "## Summary\nEdited by the person meanwhile.\n")
    _commit(memory)
    assert run(inbox_tend.apply(memory, _Settings(memory), result.decision)) is False
    assert path.exists()


def test_the_record_read_uses_its_own_memory_and_leaves_the_in_process_one_alone(memory):
    _conflict(memory, later="user: Tool A is great, I use it daily.\n")
    run(question_revisit.tend(memory, _Settings(memory), _llm({"answered": False}), model="m"))
    assert inbox_tend._RECORD_READ == {}
    assert list(question_revisit._seen(memory)) == ["inbox-002"]


def test_a_question_the_person_put_off_is_not_looked_at(memory):
    _pair(memory)
    path = memory / "inbox" / "inbox-001.md"
    markdown_parser.write(path, {**dict(markdown_parser.parse(path).frontmatter),
                                 "remind_after": (date.today() + timedelta(days=5)).isoformat()}, "x")
    assert question_revisit.candidates(memory) == []
