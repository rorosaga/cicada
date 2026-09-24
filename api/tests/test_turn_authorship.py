"""Round 4 C3 (R4B-6, R4B-7): which model and effort wrote a harness claim —
joined at read from the capture episode's per-turn sidecar, never stored, never
guessed. Pure rules first, then over a synthetic bank."""
from __future__ import annotations

import pytest

from api.services import agent_turns, bank_index, episode_staging, evidence, markdown_parser
from api.services import turn_authorship as ta
from api.services.claims import Claim, Evidence

SID = "22222222-3333-4444-8555-666666666666"
EP = "ep_2026-09-03_001"
BODY = ("user: Should alpha-project move to sqlite-vec?\n"
        "assistant: Yes — bob-example agreed last week.\n"
        "user: Then ship it.\n"
        "assistant: Shipped to example.com.")
STARTS = [0] + [i + 1 for i, ch in enumerate(BODY) if ch == "\n"]
SIDECAR = [
    {"offset": STARTS[0], "ts": "2026-09-03T10:00:00+00:00", "speaker": "user"},
    {"offset": STARTS[1], "ts": "2026-09-03T10:00:05+00:00", "speaker": "assistant",
     "model": "claude-opus-5-5", "effort": "xhigh"},
    {"offset": STARTS[2], "ts": "2026-09-03T10:05:00.600000+00:00", "speaker": "user"},
    {"offset": STARTS[3], "ts": "2026-09-03T10:05:30+00:00", "speaker": "assistant",
     "model": "claude-sonnet-5", "effort": "low"},
]


def _stamps(entries=SIDECAR):
    return agent_turns.stamps({"turns": entries})


@pytest.mark.parametrize("at, expected", [
    ("2026-09-03T10:00:03Z", ("claude-opus-5-5", "xhigh")),   # written during the first turn
    ("2026-09-03T10:05:00Z", ("claude-sonnet-5", "low")),     # the question's own second (both floored)
    ("2026-09-03T10:07:00Z", ("claude-sonnet-5", "low")),     # still the last question's turn
    ("2026-09-03T09:59:59Z", (None, None)),                   # before anyone asked
    ("not a time", (None, None)),
])
def test_a_write_belongs_to_the_turn_it_happened_in(at, expected):
    assert ta.turn_at(_stamps(), at) == expected


def test_a_question_with_no_kept_reply_answers_nothing():
    only_tools = [SIDECAR[0], SIDECAR[2], SIDECAR[3]]  # the first question's reply was tool calls only
    assert ta.turn_at(_stamps(only_tools), "2026-09-03T10:00:30Z") == (None, None)


def test_past_the_head_stable_cap_nothing_is_claimed(monkeypatch):
    monkeypatch.setattr(episode_staging, "MAX_TURN_STAMPS", 4)
    assert ta.turn_at(_stamps(), "2026-09-03T10:06:00Z") == (None, None)
    assert ta.turn_at(_stamps(), "2026-09-03T10:00:03Z") == ("claude-opus-5-5", "xhigh")


def test_without_recorded_ts_only_a_one_model_session_answers():
    assert ta.only_pair(_stamps()) == (None, None)
    assert ta.only_pair(_stamps(SIDECAR[:2])) == ("claude-opus-5-5", "xhigh")


def test_the_sidecar_reader_is_tolerant_and_cleans():
    raw = [{"offset": 0, "ts": "x", "speaker": "user", "model": "claude-opus-5-5"},   # a person names no model
           {"offset": 5, "ts": "y", "speaker": "assistant", "model": "<synthetic>", "effort": "HIGH"},
           {"offset": "bad"}, "junk", {"offset": 5, "speaker": "assistant", "model": "dup"}]
    assert [(s.offset, s.model, s.effort) for s in agent_turns.stamps({"turns": raw})] == [
        (0, None, None), (5, None, "high")]
    assert agent_turns.stamps({"turns": 7}) == []  # a pre-PJ-4 count


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    (m / "entities").mkdir()
    markdown_parser.write(m / "episodes" / f"{EP}.md", {
        "id": EP, "timestamp": "2026-09-03T10:00:00+00:00", "source": "claude-code", "origin": "claude-code",
        "title": "Sync race", "session_id": SID, "harness": "claude-code", "capture_kind": "transcript",
        "processed": True, "turns": SIDECAR}, BODY)
    # An MCP episode of the SAME session is never the capture (R3): its sidecar is ignored.
    markdown_parser.write(m / "episodes" / "ep_2026-09-03_002.md", {
        "id": "ep_2026-09-03_002", "session_id": SID, "harness": "claude-code",
        "turns": [{"offset": 0, "ts": "2026-09-03T10:05:05+00:00", "speaker": "assistant", "model": "decoy-1"}]},
        "assistant: a note")
    bank_index.invalidate()
    return m


def _span(quote, *, digest=None):
    start = BODY.index(quote)
    return Evidence(episode=EP, start=start, end=start + len(quote), kind="assistant",
                    hash=digest or evidence.body_hash(BODY))


def _claim(**kw):
    base = dict(id="clm_alpha", text="alpha-project uses sqlite-vec", subject="alpha-project", predicate="uses",
                object="sqlite-vec", authored_by="claude-code", session_id=SID, recorded_ts="2026-09-03T10:05:10Z")
    base.update(kw)
    return Claim(**base)


def test_a_harness_claim_joins_to_its_sessions_capture_turn(memory):
    turns = ta.TurnAuthorship(memory)
    assert turns.for_claim(_claim(), "harness") == ("claude-sonnet-5", "low")
    assert turns.for_claim(_claim(recorded_ts=None), "harness") == (None, None)       # two models: no guess
    assert turns.for_claim(_claim(session_id="ses_2026-09-03_nomatch"), "harness") == (None, None)
    assert turns.for_claim(_claim(), "model") == (None, None)   # a Sleep claim's model is its Cicada-Author


def test_an_assistant_span_carries_its_turns_model(memory):
    turns = ta.TurnAuthorship(memory)
    assert turns.for_span(_span("Yes — bob-example agreed")) == ("claude-opus-5-5", "xhigh")
    assert turns.for_span(_span("Shipped to example.com")) == ("claude-sonnet-5", "low")
    assert turns.for_span(_span("Yes — bob-example", digest="000000000000")) == (None, None)  # stale: never
    person = Evidence(episode=EP, start=0, end=5, kind="user", hash=evidence.body_hash(BODY))
    assert turns.for_span(person) == (None, None)


def test_a_body_is_read_once_and_only_where_a_sidecar_names_a_model(memory):
    markdown_parser.write(memory / "episodes" / "ep_2026-09-04_001.md", {
        "id": "ep_2026-09-04_001",
        "turns": [{"offset": 0, "ts": "2026-09-04T09:00:00+00:00", "speaker": "assistant"}]}, "assistant: hi")
    bank_index.invalidate()
    reads: list[str] = []
    turns = ta.TurnAuthorship(memory, text=lambda ep: reads.append(ep) or BODY)
    bare = Evidence(episode="ep_2026-09-04_001", start=11, end=13, kind="assistant", hash="")
    assert turns.for_span(bare) == (None, None) and reads == []
    turns.for_span(_span("Yes — bob-example"))
    turns.for_span(_span("Shipped"))
    assert reads == [EP]
