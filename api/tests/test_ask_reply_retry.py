"""Ask asks once more when its reply can't be read, and only then (2026-11-06): the answer isn't thrown away for one bad
reply, and a good reply spends one call. Synthetic bank; the model is a stub."""
from __future__ import annotations

import json

import pytest

from api.services import ask_service, bank_index, evidence, markdown_parser, search_index


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    said = {f"ep_2023-{i:02d}-01_001": f"user: Can you help me plan the weekly errands list number {i}?\n"
                                       f"assistant: Sure, errands list {i}: groceries, laundry, bank.\n"
            for i in range(1, 13)}
    said["ep_2024-02-03_001"] = "user: We chose alpha-database for the ledger project.\nassistant: Noted.\n"
    for ep, body in said.items():
        markdown_parser.write(memory / "episodes" / f"{ep}.md",
                              {"id": ep, "timestamp": f"{ep[3:13]}T10:00:00+00:00", "processed": False,
                               "source": "import", "content_hash": evidence.body_hash(body)}, body)
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


GOOD = json.dumps({"answer": "alpha-database", "confidence": 0.8, "used_entities": [], "gaps": []})


def _ask(bank, replies: list[str]):
    prompts: list[str] = []

    def model(prompt: str) -> str:
        prompts.append(prompt)
        return replies[min(len(prompts) - 1, len(replies) - 1)]

    return ask_service.answer_query(bank, "Which database did we choose for the ledger project?",
                                    retrieve_fn=lambda q, k: [], llm_fn=model, no_engine=False), prompts


def test_a_good_reply_spends_one_call(bank):
    result, prompts = _ask(bank, [GOOD])
    assert result["answer"] == "alpha-database" and len(prompts) == 1


def test_an_unreadable_reply_is_asked_once_more(bank):
    result, prompts = _ask(bank, ["Sure! The answer is alpha-database.", GOOD])
    assert result["answer"] == "alpha-database" and len(prompts) == 2
    assert prompts[1].startswith(prompts[0])


def test_two_unreadable_replies_degrade_honestly_and_stop(bank):
    result, prompts = _ask(bank, ["not json"])
    assert "could not synthesize" in result["answer"] and len(prompts) == 2
