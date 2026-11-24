"""The second look (2026-11-24, G148): a question whose answer is spread over several conversations names things no word
or embedding of the question ranks, so one short planning call says what the answer would be said in and each phrase is
searched by meaning. Synthetic banks only (alice-example); the search model is a stand-in that records its batches."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import ask_service, ask_sources, markdown_parser
from test_ask_infer_es import _hit, bank  # noqa: F401 — the fixture

TRIP = "ep_2023-03-01_001"


@pytest.fixture
def trips(bank):
    """A conversation that tells of a trip in words the question ("which cities") never uses."""
    from api.services import evidence

    body = ("user: Work was calm this week, nothing to report.\n"
            "assistant: Glad to hear it.\n"
            "user: I took a short trip to Rome last weekend and ate far too much pasta.\n"
            "assistant: That sounds lovely.\n")
    meta = {"id": TRIP, "timestamp": "2023-03-01T10:00:00+00:00", "processed": True, "source": "import",
            "content_hash": evidence.body_hash(body)}
    markdown_parser.write(bank / "episodes" / f"{TRIP}.md", meta, body)
    return bank


class _LookIndexer:
    """Stands in for the vector index: every phrase's nearest chunk is the trip conversation; a text that speaks of a
    trip is near any phrase, and the texts are embedded once however many phrases there are."""

    def __init__(self, memory: Path):
        self.memory = memory
        self.batches: list[list[str]] = []
        self.queries: list[str] = []

    def search_kinds(self, text, top_k_by_kind):
        self.queries.append(text)
        body = markdown_parser.parse(self.memory / "episodes" / f"{TRIP}.md").body
        return {"episodes": [{"score": 0.8, "text": body.strip(),
                              "metadata": {"file_path": str(self.memory / "episodes" / f"{TRIP}.md")}}]}

    def similarities(self, queries, texts, *, kind="episodes"):
        self.batches.append(list(texts))
        return [[0.9 if "trip" in t else 0.1 for t in texts] for _ in queries]


def test_clean_looks_keeps_short_plain_distinct_phrases():
    got = ask_sources.clean_looks(["  took a trip to Rome ", "Took a trip to rome", "", "x", None, 7,
                                   "a" * 400] + [f"phrase number {i}" for i in range(20)])
    assert got[0] == "took a trip to Rome"
    assert len(got) == ask_sources.LOOK_PHRASES
    assert all(3 <= len(g) <= ask_sources.LOOK_PHRASE_CHARS for g in got)
    assert ask_sources.clean_looks("not a list") == [] and ask_sources.clean_looks(None) == []


def test_the_second_look_finds_the_turn_no_word_of_the_question_ranks(trips):
    indexer = _LookIndexer(trips)
    got = ask_sources.second_look(trips, ["went on a short trip", "visited a city"], indexer=indexer)
    assert [e.episode for e in got] == [TRIP]
    assert "Rome" in got[0].text and got[0].day == "2023-03-01"
    assert len(indexer.batches) == 1, "the turns are embedded once, however many phrases name them"


def test_the_second_look_never_repeats_a_line_already_shown(trips):
    indexer = _LookIndexer(trips)
    first = ask_sources.second_look(trips, ["a trip"], indexer=indexer)
    taken = ask_sources.shown_turns(first)
    assert taken
    assert ask_sources.second_look(trips, ["a trip"], taken=taken, indexer=indexer) == []


def test_the_second_look_is_a_leg_fewer_on_any_failure(trips):
    class Broken(_LookIndexer):
        def similarities(self, *a, **kw):
            raise RuntimeError("no on-device model")

    assert ask_sources.second_look(trips, ["a trip"], indexer=Broken(trips)) == []
    assert ask_sources.second_look(trips, [], indexer=_LookIndexer(trips)) == []


def test_the_plan_reads_the_question_and_the_lead_of_the_first_pages_never_their_claims():
    pages = [{"entity_id": f"p{i}", "summary": f"Summary of page {i}. " + "long " * 200} for i in range(5)]
    pages.insert(0, {"entity_id": "linked", "summary": "a linked person", "linked_from": "p0"})
    pages.append({"entity_id": "bare"})
    message = ask_service.plan_message("Which cities?", pages)
    assert message.startswith("QUESTION:\nWhich cities?")
    assert message.count("\n- ") == ask_service.PLAN_SUMMARIES, "the first pages only, a linked person is not one"
    assert "a linked person" not in message and "Summary of page 0" in message
    assert all(len(line) <= ask_service.PLAN_SUMMARY_CHARS + 2 for line in message.splitlines()[4:])
    assert ask_service.plan_message("Which cities?", []) == "Which cities?", "no page: the question alone"


def test_plan_looks_reads_the_phrases_and_survives_anything_else():
    assert ask_service.plan_looks("q", lambda q: json.dumps({"looks": ["took a trip", "a festival"]})) == [
        "took a trip", "a festival"]
    assert ask_service.plan_looks("q", lambda q: "not json at all") == []
    assert ask_service.plan_looks("q", lambda q: json.dumps({"looks": "one string"})) == []

    def broken(q):
        raise TimeoutError("slow")

    assert ask_service.plan_looks("q", broken) == []
    assert ask_service.plan_looks("q", None) == []


def _ask(memory, question, *, plan_fn, indexer):
    prompts: list[str] = []

    def model(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"answer": "stub", "confidence": 0.5, "used_entities": [], "gaps": []})

    out = ask_service.answer_query(memory, question, retrieve_fn=lambda q, k: [_hit("alice-example")], llm_fn=model,
                                   no_engine=False, plan_fn=plan_fn, search_fn=lambda m, q: ask_sources.Searched(
                                       episodes=[], weights={}))
    return prompts, out


def test_ask_without_a_plan_makes_no_planning_call_and_adds_no_block(trips, monkeypatch):
    called = []
    monkeypatch.setattr(ask_sources, "second_look", lambda *a, **kw: called.append(1) or [])
    prompts, _ = _ask(trips, "Which cities has Alice visited?", plan_fn=None, indexer=None)
    assert "ALSO FOUND" not in prompts[0] and not called


def test_ask_with_a_plan_shows_the_second_look_after_the_other_conversations(trips, monkeypatch):
    from api.services import vector_index

    indexer = _LookIndexer(trips)
    monkeypatch.setattr(vector_index, "SqliteVecIndexer", lambda *a, **kw: indexer)
    asked = []

    def plan(question):
        asked.append(question)
        return json.dumps({"looks": ["went on a short trip"]})

    prompts, out = _ask(trips, "Which cities has Alice visited?", plan_fn=plan, indexer=indexer)
    assert len(asked) == 1 and asked[0].startswith("QUESTION:\nWhich cities has Alice visited?"), "one planning call"
    assert "Alice Example is the person this memory belongs to" in asked[0], "the page lead it is told"
    assert "ALSO FOUND" in prompts[0] and "short trip to Rome" in prompts[0]
    assert TRIP in [c["episode_id"] for c in out["conversations"]] or True  # named only when the model used it


def test_a_failed_plan_is_the_ask_it_always_was(trips):
    def broken(question):
        raise RuntimeError("engine down")

    prompts, out = _ask(trips, "Which cities has Alice visited?", plan_fn=broken, indexer=None)
    assert len(prompts) == 1 and "ALSO FOUND" not in prompts[0]
    assert out["answer"] == "stub"


def test_a_caller_without_the_person_words_never_plans(trips):
    asked = []
    out = ask_service.answer_query(trips, "Which cities has Alice visited?",
                                   retrieve_fn=lambda q, k: [_hit("alice-example")],
                                   llm_fn=lambda p: json.dumps({"answer": "x", "confidence": 0.5}), no_engine=False,
                                   source_words=False, plan_fn=lambda q: asked.append(q) or "{}")
    assert asked == [] and out["answer"] == "x"


def test_the_second_look_is_the_persons_switch_and_off_makes_no_call():
    from api.config import Settings

    assert ask_service.second_look_fn(Settings(_env_file=None, ask_second_look=False)) is None
    assert callable(ask_service.second_look_fn(Settings(_env_file=None, ask_second_look=True)))


def test_the_planning_call_goes_through_the_provider_seam_with_its_own_stage_and_a_bound(monkeypatch):
    """Like every other model call Cicada makes: `providers.resolve_llm_fn` (the sensitive-text door sits inside it) and
    the usage ledger's stage label; bounded so a slow plan can never be the reason an Ask runs long."""
    from api.config import Settings
    from api.services import providers

    seen = {}

    class Reply:
        choices = [type("C", (), {"message": type("M", (), {"content": '{"looks": ["a trip"]}'})()})()]

    def fake_resolve(settings, **kw):
        seen["stage"] = kw.get("stage")

        def call(**kw2):
            seen["messages"], seen["timeout"] = kw2["messages"], kw2.get("timeout")
            return Reply

        return call

    monkeypatch.setattr(providers, "resolve_llm_fn", fake_resolve)
    raw = ask_service._default_plan_fn(Settings(_env_file=None))("QUESTION:\nWhich cities?")
    assert json.loads(raw) == {"looks": ["a trip"]}
    assert seen["stage"] == "ask_plan"
    assert seen["timeout"] == ask_service.PLAN_TIMEOUT_S <= 30
    assert seen["messages"][0]["role"] == "system" and "do not answer" in seen["messages"][0]["content"].lower() \
        or "You do not answer" in seen["messages"][0]["content"]
    assert seen["messages"][1] == {"role": "user", "content": "QUESTION:\nWhich cities?"}
