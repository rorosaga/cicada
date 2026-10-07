"""G194 A1 — every prompt that writes about a conversation is told when it was said and what day it is now.

A two-year-old import used to reach Stage 1 with no date at all, so its pages read as if everything were said today.
These tests pin the plumbing: each chunk of each conversation (and its retry) carries that conversation's own day and
today, the merge and contradiction prompts carry the page's and the new information's days, and none of it moves a
G118 evidence span — the note lives in the model's message only, never in a stored body.

Synthetic mixed-age conversations only (`alpha-co`, `bob-example`); no bank, engine or network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.config import Settings
from api.services import conflict_resolver, entity_extractor, providers, source_dates

TODAY = date(2026, 10, 7)
OLD = {"id": "ep_2025-02-04_001", "timestamp": "2025-02-04T18:20:00Z", "origin": "claude-ai",
       "content": "user: I am thinking about applying for an internship at Alpha Co.\n"
                  "assistant: Alpha Co runs a summer programme for students."}
RECENT = {"id": "ep_2026-09-30_002", "timestamp": "2026-09-30T09:00:00Z", "origin": "claude-code",
          "content": "user: Alpha Co moved its office to the harbour last week.\n"
                     "assistant: Noted — the new office is by the harbour."}


def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _run_extract(episodes, reply, *, today=TODAY, fail_first=False):
    """The real `extract` over synthetic episodes; the completion is fake and records every user message."""
    seen: list[str] = []
    calls = {"n": 0}

    async def fake(**kw):
        seen.append(kw["messages"][1]["content"])
        calls["n"] += 1
        if fail_first and calls["n"] == 1:
            return _resp("not json at all")          # a malformed answer: the chunk is retried once
        return _resp(reply(kw["messages"][1]["content"]))

    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake), \
            patch.object(entity_extractor.asyncio, "sleep", _no_sleep):
        out = asyncio.run(entity_extractor.extract([dict(e) for e in episodes], Settings(_env_file=None), today=today))
    return out, seen


async def _no_sleep(*_a, **_k):
    return None


def _empty(_msg: str) -> str:
    return json.dumps({"entities": [], "relationships": []})


# --------------------------------------------------------------------------- #
# source_dates
# --------------------------------------------------------------------------- #


def test_the_conversation_day_is_its_timestamp_else_its_id_and_never_guessed():
    assert source_dates.episode_day(OLD) == date(2025, 2, 4)
    assert source_dates.episode_day({"id": "ep_2025-03-01_004", "timestamp": "t"}) == date(2025, 3, 1)
    assert source_dates.episode_day({"id": "ep_ok", "timestamp": "t"}) is None
    assert source_dates.episode_day({"id": "ep_2025-02-30_001"}) is None          # an impossible day is no day
    assert source_dates.date_note(None, TODAY) is None


def test_old_means_more_than_ninety_days():
    assert source_dates.OLD_AFTER_DAYS == 90
    assert not source_dates.is_old(date(2026, 7, 9), TODAY)                        # 90 days: not old yet
    assert source_dates.is_old(date(2026, 7, 8), TODAY)                            # 91 days
    assert not source_dates.is_old(date(2026, 10, 9), TODAY)                       # a clock-skewed future day
    assert not source_dates.is_old(None, TODAY)


def test_the_note_names_both_days_and_the_month_only_when_old():
    old = source_dates.date_note(date(2025, 2, 4), TODAY)
    assert old.startswith(source_dates.DATE_NOTE_PREFIX) and old.endswith("]\n\n")
    assert "dated 2025-02-04" in old and "today is 2026-10-07" in old and "610 days before today" in old
    assert "as of February 2025" in old and "never as current" in old
    recent = source_dates.date_note(date(2026, 9, 30), TODAY)
    assert "dated 2026-09-30" in recent and "7 days before today" in recent and "older than" not in recent
    assert "took place today" in source_dates.date_note(TODAY, TODAY)
    assert "after today" in source_dates.date_note(date(2026, 10, 9), TODAY)       # said so, never hidden


# --------------------------------------------------------------------------- #
# Stage 1
# --------------------------------------------------------------------------- #


def test_each_conversation_in_a_mixed_age_batch_is_told_its_own_day_and_today():
    _, seen = _run_extract([OLD, RECENT], _empty)
    by_day = {("2025-02-04" if "dated 2025-02-04" in m else "2026-09-30"): m for m in seen}
    assert set(by_day) == {"2025-02-04", "2026-09-30"} and len(seen) == 2
    assert all("today is 2026-10-07" in m for m in seen)
    assert "as of February 2025" in by_day["2025-02-04"]
    assert "older than" not in by_day["2026-09-30"]
    for m, ep in ((by_day["2025-02-04"], OLD), (by_day["2026-09-30"], RECENT)):
        assert m.startswith(source_dates.DATE_NOTE_PREFIX) and m.endswith(ep["content"])   # notes first, words last


def test_every_chunk_and_its_retry_carry_the_note():
    long = dict(OLD, content="\n".join(f"user: line {i} about Alpha Co and its programme." for i in range(800)))
    assert len(entity_extractor._chunk_spans(long["content"])) >= 3
    _, seen = _run_extract([long], _empty, fail_first=True)
    assert len(seen) == len(entity_extractor._chunk_spans(long["content"])) + 1      # one retried chunk
    assert all(m.startswith(source_dates.DATE_NOTE_PREFIX) and "dated 2025-02-04" in m for m in seen)


def test_an_undated_conversation_gets_no_note_and_nothing_is_guessed():
    _, seen = _run_extract([dict(OLD, id="ep_ok", timestamp="t")], _empty)
    assert seen == [OLD["content"]]


def test_the_note_follows_the_gap_note_and_precedes_a_memory_note():
    note = entity_extractor._gap_note(((10, 20),), 0, 100)
    seen = []

    async def fake(**kw):
        seen.append(kw["messages"][1]["content"])
        return _resp("{}")

    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake):
        asyncio.run(entity_extractor._extract_chunk(
            "ep_2025-02-04_001", "chunk words", 0, 1, Settings(_env_file=None), source="claude_memory",
            gap_note=note, date_note=source_dates.date_note(date(2025, 2, 4), TODAY)))
    msg = seen[0]
    assert entity_extractor.GAP_NOTE_PREFIX not in source_dates.DATE_NOTE_PREFIX     # never mistaken for a gap note
    gap_at, date_at = msg.index(entity_extractor.GAP_NOTE_PREFIX), msg.index(source_dates.DATE_NOTE_PREFIX)
    assert gap_at == 0 < date_at < msg.index(entity_extractor.MEMORY_SOURCE_NOTE) < msg.index("chunk words")


def test_the_system_prompt_states_the_time_rules():
    prompt = entity_extractor.EXTRACTION_SYSTEM_PROMPT
    assert "TIME (every conversation is written up as of its own date)" in prompt
    for words in ("never as of today", "older than 90 days", '"currently", "now", "recently"',
                  "the Monday before the conversation", "one never replaces the other",
                  "always name\n  the month and year they were stated"):
        assert words in prompt


def test_evidence_spans_and_hashes_are_those_of_the_stored_body_not_the_message():
    quote = "Alpha Co runs a summer programme for students."
    note_words = "this conversation is dated 2025-02-04"

    def reply(_msg: str) -> str:
        return json.dumps({"entities": [], "relationships": [
            {"source": "Alpha Co", "target": "summer programme", "label": "runs", "evidence_quote": quote},
            {"source": "the user", "target": "Alpha Co", "label": "considering", "evidence_quote": note_words},
        ]})

    dated, _ = _run_extract([OLD], reply)
    undated, seen = _run_extract([dict(OLD, id="ep_x", timestamp="t")], reply)
    assert seen == [OLD["content"]]
    span = dated[0]["relationships"][0]["evidence"][0]
    start = OLD["content"].index(quote)
    assert (span["start"], span["end"], span["kind"]) == (start, start + len(quote), "assistant")
    same = undated[0]["relationships"][0]["evidence"][0]
    assert (span["start"], span["end"], span["hash"]) == (same["start"], same["end"], same["hash"])
    # A quote of Cicada's own note is not in the conversation: it degrades to reasoning, never a span.
    assert dated[0]["relationships"][1]["evidence"][0]["kind"] == "reasoning"


def test_a_run_tells_every_conversation_the_same_today():
    _, seen = _run_extract([OLD, RECENT], _empty, today=date(2026, 10, 8))
    assert all("today is 2026-10-08" in m for m in seen)


# --------------------------------------------------------------------------- #
# Synthesis and contradiction
# --------------------------------------------------------------------------- #


def _capture_prompt(monkeypatch, reply: str) -> list[str]:
    prompts: list[str] = []

    async def fake_acompletion(**kw):
        prompts.append(kw["messages"][0]["content"])
        return _resp(reply)

    monkeypatch.setattr(conflict_resolver.litellm, "acompletion", fake_acompletion)
    return prompts


def test_the_merge_prompt_carries_today_the_page_day_and_every_new_day(monkeypatch):
    prompts = _capture_prompt(monkeypatch, "Merged body.")
    asyncio.run(conflict_resolver._synthesize_entity_update(
        entity_name="Alpha Co", entity_type="company", existing_body="Alpha Co runs a programme.",
        new_description="Alpha Co moved office.", new_history_entries=[], source_reference_date="2026-09-30",
        settings=Settings(_env_file=None, litellm_model="gpt-5.4-mini"),
        page_last_referenced="2025-02-06", source_dates_seen=["2026-09-30T09:00:00Z", "2025-02-04"],
        today="2026-10-07"))
    p = prompts[0]
    assert "Today: 2026-10-07" in p
    assert "last mentioned in a conversation dated: 2025-02-06" in p
    assert "comes from conversation(s) dated: 2025-02-04, 2026-09-30" in p
    assert "preferring the information with the LATER DATE" in p and "never replaces the page's later" in p
    assert "never presented as current" in p and "Keep every date already written on the page" in p


def test_a_merge_with_no_known_days_says_unknown_rather_than_guessing(monkeypatch):
    prompts = _capture_prompt(monkeypatch, "Merged body.")
    asyncio.run(conflict_resolver._synthesize_entity_update(
        entity_name="Alpha Co", entity_type="company", existing_body="Old.", new_description="New.",
        new_history_entries=[], source_reference_date=None, settings=Settings(_env_file=None)))
    p = prompts[0]
    assert "last mentioned in a conversation dated: unknown" in p and "dated: unknown" in p
    assert f"Today: {date.today().isoformat()}" in p


def test_the_contradiction_prompt_dates_both_descriptions(monkeypatch):
    prompts = _capture_prompt(monkeypatch, json.dumps({"has_unresolvable_contradiction": False, "options": []}))
    asyncio.run(conflict_resolver._detect_contradiction(
        entity_name="Alpha Co", existing_body="Old.", new_description="New.", settings=Settings(_env_file=None),
        existing_as_of="2026-09-30", new_as_of=["2025-02-04"], today="2026-10-07"))
    p = prompts[0]
    assert "TODAY: 2026-10-07" in p
    assert "EXISTING DESCRIPTION (last mentioned in a conversation dated 2026-09-30)" in p
    assert "NEW DESCRIPTION (from conversation(s) dated 2025-02-04)" in p
    assert '"Newer" means said on a later date' in p


def test_stage_three_hands_both_prompts_the_page_day_the_change_days_and_the_cycle_day(monkeypatch):
    seen: dict = {}

    async def synth(**kw):
        seen["synth"] = kw
        return None

    async def contradiction(**kw):
        seen["contradiction"] = kw
        return None

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", synth)
    monkeypatch.setattr(conflict_resolver, "_detect_contradiction", contradiction)
    change = {"id": "alpha-co", "action": "update",
              "entity": {"name": "Alpha Co", "type": "company", "description": "Alpha Co moved office."},
              "source_episode": "ep_2026-09-30_002", "source_episode_timestamp": "2026-09-30T09:00:00Z",
              "source_episode_timestamps": ["2025-02-04T18:20:00Z", "2026-09-30T09:00:00Z"]}
    existing = [{"id": "alpha-co", "body": "## Summary\nAlpha Co runs a programme.\n",
                 "frontmatter": {"name": "Alpha Co", "type": "company", "last_referenced": "2025-02-06"}}]
    asyncio.run(conflict_resolver.resolve_and_prune(
        [change], existing, SimpleNamespace(memory_path=None), now=datetime(2026, 10, 7, 3, 0), decay=False))
    s, c = seen["synth"], seen["contradiction"]
    assert s["page_last_referenced"] == "2025-02-06" and c["existing_as_of"] == "2025-02-06"
    assert s["source_dates_seen"] == ["2025-02-04", "2026-09-30"] == c["new_as_of"]
    assert s["today"] == "2026-10-07" == c["today"]
    assert s["source_reference_date"] == "2026-09-30"                                  # unchanged


@pytest.fixture
def conflict_bank(tmp_path, monkeypatch):
    from _synthetic_bank import _bank
    from api.services import markdown_parser, state_dictionary

    memory = _bank(tmp_path)
    markdown_parser.write(
        memory / "inbox" / "conflict-review.md",
        {"kind": "conflict", "entity_id": "alpha-project", "entity_name": "Alpha Project", "predicate": "uses",
         "options": [{"key": "a", "label": "sqlite-vec", "claim_id": None},
                     {"key": "b", "label": "other", "claim_id": None}], "title": "Synthetic choice"},
        "Synthetic context")

    async def no_refresh(*a, **k):
        return None

    monkeypatch.setattr(state_dictionary, "refresh_and_commit", no_refresh)
    return memory


def test_an_inbox_answer_s_merge_is_told_today_and_the_page_day(conflict_bank, monkeypatch):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service, markdown_parser

    seen: list[dict] = []

    async def synth(**kw):
        seen.append(kw)
        return None

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", synth)
    page = markdown_parser.parse(conflict_bank / "entities" / "alpha-project.md").frontmatter
    asyncio.run(inbox_service.resolve("conflict-review", InboxResolveRequest(action="choose", option_key="a"),
                                      SimpleNamespace(memory_path=conflict_bank)))
    kw = seen[0]
    assert kw["today"] == date.today().isoformat() == kw["source_reference_date"]
    assert kw["source_dates_seen"] == [kw["today"]]
    assert str(page["last_referenced"]) == "2026-09-02" == kw["page_last_referenced"]
