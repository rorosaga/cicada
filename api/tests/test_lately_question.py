"""What has come up lately names no subject: Ask and recall hand over the newest conversations, never a record with no
mention behind it (owner, 2026-11-06; rulings 30, 39, 62). Synthetic bank."""
from __future__ import annotations

from datetime import date

import pytest

from api.services import ask_sources, question_intent


def _episode(memory, ep, *, body=None, **fields):
    head = "\n".join(f"{k}: {v}" for k, v in {"title": ep, "processed": "false", "timestamp": f"{ep[3:13]}T10:00:00+00:00",
                                              **fields}.items())
    text = body or f"user: first thing said in {ep}\nassistant: an answer\nuser: last thing said in {ep}\n"
    (memory / "episodes" / f"{ep}.md").write_text(f"---\n{head}\n---\n\n{text}", encoding="utf-8")


@pytest.fixture
def memory(tmp_path):
    (tmp_path / "episodes").mkdir()
    (tmp_path / "entities").mkdir()
    return tmp_path


def test_newest_first_with_room_for_earlier_days_and_no_record_without_a_mention(memory):
    for n in range(1, 6):
        _episode(memory, f"ep_2026-11-05_00{n}")
    _episode(memory, "ep_2026-11-04_001")
    _episode(memory, "ep_2026-11-06_001", source="claude_memory")
    _episode(memory, "ep_2026-11-06_002", origin="rss")
    _episode(memory, "ep_2026-11-07_001")   # past today: a clock that moved back, or a benchmark's own day
    newest = ask_sources.newest_conversations(memory, today=date(2026, 11, 6))
    assert newest == ["ep_2026-11-05_005", "ep_2026-11-05_004", "ep_2026-11-05_003", "ep_2026-11-04_001"]


def test_the_lines_are_the_persons_first_and_last_turn_with_no_word_shared(memory, monkeypatch):
    _episode(memory, "ep_2026-11-05_001")
    monkeypatch.setattr(question_intent, "asks_lately", lambda *_a, **_k: True)
    found = ask_sources.search(memory, "zzz", today=date(2026, 11, 6), indexer=object())
    assert found.lately == ["ep_2026-11-05_001"] and not found.episodes
    shown = ask_sources.gather_search(memory, "zzz", found, **ask_sources.window_limits())
    assert [e.text.split(" in ")[0] for e in shown] == ["first thing said", "last thing said"]


def test_with_no_model_or_another_question_nothing_changes(memory):
    _episode(memory, "ep_2026-11-05_001")
    assert not question_intent.asks_lately(None, "what's new?")
    assert ask_sources.search(memory, "zzz", today=date(2026, 11, 6), indexer=object()).lately == []


def test_a_question_with_a_subject_must_clear_the_margin(monkeypatch):
    near = {k: 0.5 for k in question_intent.EXAMPLES}
    monkeypatch.setattr(question_intent, "_scores", lambda *_a: {**near, "lately": 0.51})
    assert question_intent.asks_lately(object(), "q", no_subject=True)
    assert not question_intent.asks_lately(object(), "q")
    monkeypatch.setattr(question_intent, "_scores", lambda *_a: {**near, "lately": 0.53})
    assert question_intent.asks_lately(object(), "q")
