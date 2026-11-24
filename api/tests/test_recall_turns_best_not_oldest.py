"""Recall's lead turns are the best four, not the oldest four of the best eight (2026-11-24).

A person says something once ("the physiotherapist who treated my shoulder said to swim") in a conversation Sleep has not
read, and asks an agent about it among a hundred others. Ask's search leg finds the conversation; recall used to keep the
OLDEST four of the turns it gathered, so any conversation newer than four others that share a word never reached the
reply. Synthetic, no embedding, no model."""
from __future__ import annotations

import pytest

from api.services import ask_sources, bank_index, evidence, markdown_parser, mcp_tools, search_index


def _episode(memory, ep_id: str, turns: list[str]) -> None:
    body = "\n".join(turns) + "\n"
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md",
                          {"id": ep_id, "timestamp": f"{ep_id[3:13]}T10:00:00+00:00", "processed": False, "source": "mcp",
                           "content_hash": evidence.body_hash(body)}, body)


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    yield memory
    bank_index.invalidate()


def test_a_newer_conversation_the_words_found_is_not_lost_to_older_ones_sharing_a_word(bank, monkeypatch):
    for day in range(1, 7):
        _episode(bank, f"ep_2026-09-{day:02d}_001",
                 [f"user: The physiotherapist at the gym number {day} has a waiting list for knees."])
    newest = "ep_2026-11-20_001"
    _episode(bank, newest, ["user: The physiotherapist who treated my shoulder said I should swim twice a week."])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    bank_index.invalidate()
    # The meaning leg (a vector index in a real memory) adds the nearest turns of four older conversations.
    real = ask_sources.search

    def with_meaning(memory_path, query):
        found = real(memory_path, query)
        found.meaning = True
        found.passages = {f"ep_2026-09-{d:02d}_001": [f"user: The physiotherapist at the gym number {d} has a waiting list "
                                                      "for knees."] for d in range(1, 5)}
        return found

    monkeypatch.setattr(ask_sources, "search", with_meaning)
    shown = mcp_tools._turn_excerpts(bank, "physiotherapist shoulder swim")
    assert newest in {e.episode for e in shown}
    assert len(shown) <= mcp_tools.RECALL_TURNS
