"""The three Ask gaps left after #385 (2026-10-20, G148).

1. A question worded as a fact whose answer the record only implies ("does <name> live in <state>?", "which US
   state …", "what is the card game <name> was talking about?") declined as missing: it gets a stricter note than a
   judgement — a stated fact still wins, a loose link is still a decline.
2. An English question over conversations held in Spanish shared no word with them: the record's own language (the
   vector leg's nearest passages) now sends it by meaning, and only then.
3. A thing named in one language and said in the other: the vector legs bridge it; the meaning leg ranks a passage's
   turns on what the question asks, not on the names every greeting repeats, and reads a conversation's two nearest
   passages.

Synthetic banks only (alice-example, bob-example); the search model is a stand-in.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import ask_service, ask_sources, bank_index, evidence, markdown_parser, search_index


def _episode(memory, ep_id: str, lines: list[str], **fm) -> None:
    body = "\n".join(lines) + "\n"
    meta = {"id": ep_id, "timestamp": f"{ep_id[3:13]}T10:00:00+00:00", "processed": True, "source": "import",
            "content_hash": evidence.body_hash(body), **fm}
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", meta, body)


def _hit(entity_id: str) -> dict:
    return {"score": 0.9, "text": "", "metadata": {"entity_id": entity_id, "entity_name": entity_id, "type": "person",
                                                    "status": "active", "file_path": ""}}


def _prompt(memory, question: str, *, pages=("alice-example",), indexer=None) -> str:
    prompts: list[str] = []

    def model(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"answer": "stub", "confidence": 0.5, "used_entities": [], "gaps": []})

    search_fn = (lambda m, q: ask_sources.search(m, q, indexer=indexer)) if indexer is not None else None
    ask_service.answer_query(memory, question, retrieve_fn=lambda q, k: [_hit(p) for p in pages], llm_fn=model,
                             no_engine=False, search_fn=search_fn)
    [prompt] = prompts
    return prompt


def _pages(memory) -> None:
    markdown_parser.write(memory / "entities" / "alice-example.md",
                          {"name": "Alice Example", "type": "person", "status": "active", "owner": True},
                          "## Summary\nAlice Example is the person this memory belongs to.\n")
    markdown_parser.write(memory / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active", "aliases": ["Bobby"]},
                          "## Summary\nBob Example is a friend of Alice.\n")


# --------------------------------------------------------------------------------------------------------------- #
# 1. Fact-worded questions whose answer is implied
# --------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("question", [
    "Does Bob live in Connecticut?",
    "Is Bob married?",
    "Are Alice and Bob fans of the same football team?",
    "Was she feeling lonely before the move?",
    "Which US state was Bob travelling in during October 2023?",
    "What state did Bob visit in summer 2021?",
    "In which state is the shelter from which Bob adopted the puppy?",
    "In what country did Bob's mother buy the pendant?",
    "Around which US holiday did Bob get into a car accident?",
    "Which major holiday season coincides with Bob's wedding?",
    "What additional country did Bob visit during his trip?",
    "What card game is Bob talking about?",
    "What is the game with different colored cards that was Bob talking about with Alice?",
    "Which popular music composer's tunes does Bob enjoy playing?",
    "Who is Bob?",
    "How old is Bob?",
    "Which meat does Bob prefer eating more than others?",
    "¿En qué país compró Bob el colgante?",
    "¿Qué estado visitó Bob en 2021?",
    "¿De qué juego de cartas hablaba Bob?",
    "¿Quién es Bob?",
    "¿Cuántos años tiene Bob?",
])
def test_a_fact_the_record_may_only_imply_is_read_as_one(question):
    assert ask_sources.asks_implied(question, {"bob", "example", "bobby", "alice"})


@pytest.mark.parametrize("question", [
    # Judgements keep their own note.
    "Would Bob likely enjoy a theme park?",
    "Is it likely that Bob has friends besides Alice?",
    # Plain recorded facts.
    "When did Alice go to the support group?",
    "What did Bob say after talking about snacks?",
    "What did Evan offer to share with Sam after talking about healthy snacks?",
    "What is the name of my hamster?",
    "What is one of Bob's favorite movies?",
    # About I, we or you, or a thing — not someone.
    "Did I go to the gym yesterday?",
    "Do you remember the plan?",
    "Is it raining?",
    "Is Docker running?",
    "Was Python 3.12 released?",
    "How old is my laptop?",
    "Who is the owner of this repo?",
    "What do I prefer for breakfast?",
    "Which editor do you prefer?",
    # "State" as a status, never a place.
    "What state is the PR in?",
    "What is the state of my deployment?",
    "¿En qué estado está el PR?",
    # A request to the agent.
    "Could you tell me which country Bob visited?",
])
def test_a_plain_fact_a_judgement_or_a_request_is_not(question):
    assert not ask_sources.asks_implied(question, {"bob", "example", "bobby", "alice"})


def test_a_yes_or_no_is_about_someone_the_record_knows():
    assert ask_sources.asks_implied("Is Bobby married?", {"bob", "bobby"}), "an alias names them"
    assert ask_sources.asks_implied("Is Bob's sister married?", {"bob"})
    assert not ask_sources.asks_implied("Is Oscar Bob's pet?", {"bob"}), "a pet, a tool, a product: not a person"
    assert ask_sources.asks_implied("Is Oscar Bob's pet?"), "without the people known, any capitalised name counts"


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i in range(1, 9):
        _episode(memory, f"ep_2023-0{i}-01_001", [f"user: Can you help me plan the weekly errands list number {i}?",
                                                  f"assistant: Sure, errands list {i}: groceries, laundry, bank."])
    _episode(memory, "ep_2023-05-08_001", ["user: Bob adopted a puppy from a shelter in Stamford.",
                                           "assistant: How lovely."])
    _pages(memory)
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def test_only_an_implied_fact_gets_its_note(bank):
    pages = ("alice-example", "bob-example")
    implied = _prompt(bank, "Does Bob live in Connecticut?", pages=pages)
    assert ask_service._IMPLIED_NOTE in implied
    assert implied.index(ask_service._IMPLIED_NOTE) < implied.index("RETRIEVED MEMORY CONTEXT")
    assert ask_service._INFERENCE_NOTE not in implied
    judged = _prompt(bank, "Would Bob likely enjoy a dog park?", pages=pages)
    assert ask_service._INFERENCE_NOTE in judged and ask_service._IMPLIED_NOTE not in judged, "one note, never both"
    for fact in ("When did Bob adopt the puppy?", "Is Docker running?"):
        prompt = _prompt(bank, fact, pages=pages)
        assert "BY IMPLICATION" not in prompt and "JUDGEMENT" not in prompt, "rule 1 alone: say so when absent"


def test_a_yes_or_no_about_a_name_without_a_person_page_keeps_rule_1(bank):
    prompt = _prompt(bank, "Is Oscar Bob's pet?", pages=("alice-example",))
    assert "BY IMPLICATION" not in prompt, "no person page in front of the model is named Oscar"


def test_the_implied_note_keeps_the_honest_decline():
    note = ask_service._IMPLIED_NOTE
    assert "When a line states it, answer from that line" in note
    assert "Probably" in note and "general knowledge" in note.lower()
    assert "someone else" in note, "never transfers what one person did to another (LoCoMo's adversarial shape)"
    assert "say what memory does not hold" in note
    assert "below 0.7" in note


# --------------------------------------------------------------------------------------------------------------- #
# 2. An English question over conversations held in Spanish
# --------------------------------------------------------------------------------------------------------------- #

_SHELTER_ES = "user: Adopté un cachorro en un refugio de Stamford, se llama Ned."
_BOOK_ES = "user: Ahora mismo estoy leyendo *El método Lean Startup* y me está dando ideas."


class _Nearest:
    """A search model whose nearest passages are the given conversations' bodies, in order (``split`` cuts each body
    into that many passages, nearest first); a text is near when it holds one of ``near_words`` — a passage scores
    0.80 then, else 0.66, as EmbeddingGemma 2 scores the nearest passage of a question about something never said."""

    def __init__(self, memory: Path, episodes: list[str], near_words: tuple[str, ...], split: int = 1):
        self.memory, self.episodes, self.near_words, self.split = memory, episodes, near_words, split
        self.batches: list[list[str]] = []
        self.questions: list[str] = []

    def search_kinds(self, text, top_k_by_kind):
        rows = []
        for ep in self.episodes:
            path = self.memory / "episodes" / f"{ep}.md"
            lines = markdown_parser.parse(path).body.strip().splitlines()
            size = max(1, -(-len(lines) // self.split))
            parts = ["\n".join(lines[i:i + size]) for i in range(0, len(lines), size)]
            for part in reversed(parts) if self.split > 1 else parts:
                near = any(w in part for w in self.near_words)
                rows.append({"score": 0.8 if near else 0.66, "text": part, "metadata": {"file_path": str(path)}})
        return {"episodes": rows}

    def index_info(self, kind):
        return {"model": "google/embeddinggemma-2:768"}

    def similarity(self, question, texts, *, kind="episodes"):
        self.batches.append(list(texts))
        self.questions.append(question)
        return [0.9 if any(w in t for w in self.near_words) else 0.2 for t in texts]


@pytest.fixture
def spanish(tmp_path):
    """Conversations held in Spanish beside a few in English."""
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i in range(1, 9):
        _episode(memory, f"ep_2024-0{i}-01_001", [f"user: ¡Hola Bob! ¿Qué tal la semana número {i}?",
                                                  "assistant: ¡Hola! Todo bien, con mucho trabajo y poco tiempo."])
    _episode(memory, "ep_2024-09-03_001", ["user: ¡Hola Bob! ¿Qué tal?", "assistant: ¡Hola! ¿Qué tal todo?",
                                           _SHELTER_ES, "assistant: ¡Qué bonito, Bob!"])
    _episode(memory, "ep_2024-09-10_001", ["user: Long week at work, Bob.", "assistant: Tell me about it."])
    _pages(memory)
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def test_an_english_question_over_spanish_conversations_goes_by_meaning(spanish):
    indexer = _Nearest(spanish, ["ep_2024-09-03_001", "ep_2024-01-01_001", "ep_2024-02-01_001"], ("refugio",))
    question = "Where did Bob adopt the puppy?"
    found = ask_sources.search(spanish, question, indexer=indexer)
    assert found.record_lang == "es" and found.meaning, "most of the nearest passages are in Spanish: meaning leads"
    prompt = _prompt(spanish, question, indexer=indexer)
    other = prompt.split("OTHER CONVERSATIONS", 1)[1]
    assert _SHELTER_ES.split(": ", 1)[1][:50] in other, "the turn that says it, though it shares no word with it"
    assert ask_service._RECORD_LANGUAGE_NOTE.format(language="Spanish") in prompt
    assert ask_service._SPANISH_NOTE not in prompt, "the answer stays in the question's language"


def test_an_english_question_beside_some_spanish_adds_only_the_spanish(spanish):
    _episode(spanish, "ep_2024-09-12_001", ["user: Bob adopted a puppy? I thought he wanted a cat.",
                                            "assistant: He said so last week."])
    search_index.ensure_fresh(spanish, wait=True, max_age_s=0)
    indexer = _Nearest(spanish, ["ep_2024-09-10_001", "ep_2024-09-12_001", "ep_2024-09-03_001"],
                       ("refugio", "puppy"))
    question = "Where did Bob adopt the puppy?"
    found = ask_sources.search(spanish, question, indexer=indexer)
    assert found.record_lang == "es" and found.adds and not found.meaning, "the English words still lead"
    assert list(found.passages) == ["ep_2024-09-03_001"], "the words read the English ones; meaning adds the rest"
    other = _prompt(spanish, question, indexer=indexer).split("OTHER CONVERSATIONS", 1)[1]
    assert "I thought he wanted a cat" in other and _SHELTER_ES.split(": ", 1)[1][:50] in other


@pytest.fixture
def english(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i in range(1, 9):
        _episode(memory, f"ep_2023-0{i}-01_001", [f"user: Can you help me plan the weekly errands list number {i}?",
                                                  f"assistant: Sure, errands list {i}: groceries, laundry, bank."])
    _episode(memory, "ep_2023-09-03_001", ["user: Bob adopted a puppy from the shelter.", "assistant: Lovely."])
    _pages(memory)
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


@pytest.mark.parametrize("question", ["Where did Bob adopt the puppy?", "What is the name of my hamster?"])
def test_an_english_question_over_english_conversations_is_unchanged(english, question):
    """The record's language, never the question's missing words: an abstention over an English bank never turns
    into a lookup (#385's first cut)."""
    indexer = _Nearest(english, ["ep_2023-09-03_001", "ep_2023-01-01_001"], ("puppy",))
    found = ask_sources.search(english, question, indexer=indexer)
    assert not found.record_lang and not found.meaning and not found.adds and not found.passages
    assert indexer.batches == [], "nothing is embedded for it"
    assert "Spanish" not in _prompt(english, question, indexer=indexer)


def test_the_record_language():
    es, en = "user: Hoy fui al dentista por la muela, me la sacaron por fin.", "user: I went to the gym and it was fun."
    near = {"a": 0.8, "b": 0.8, "c": 0.8}
    assert ask_sources.record_language({"a": [en], "b": [en], "c": [es]}, "en", near, 0.72) == "es"
    assert ask_sources.record_language({"a": [en], "b": [en]}, "en", near, 0.72) == ""
    far = {f"e{i}": [en] for i in range(ask_sources.MEANING_EPISODES)} | {"z": [es]}
    assert ask_sources.record_language(far, "en", {"z": 0.9}, 0.72) == "", "only the nearest few conversations tell it"
    # Review of #390: Spanish passages near the question only by being the record's language are no evidence.
    assert ask_sources.record_language({"a": [en], "c": [es]}, "en", {"a": 0.8, "c": 0.70}, 0.72) == ""
    assert ask_sources.record_language({"c": [es]}, "en", {"c": 0.9}, None) == "", "a model with no measured floor"


def test_the_floor_is_the_measured_models_only():
    class Indexer:
        def __init__(self, model):
            self.model = model

        def index_info(self, kind):
            return {"model": self.model}

    assert ask_sources.record_floor(Indexer("google/embeddinggemma-2:768")) == 0.72
    assert ask_sources.record_floor(Indexer("intfloat/multilingual-e5-small")) is None
    assert ask_sources.record_floor(object()) is None


@pytest.mark.parametrize("question", ["What is the name of my hamster?", "What car does Bob drive?"])
def test_an_english_abstention_over_spanish_conversations_reads_as_on_dev(spanish, question):
    """Review of #390: on a record in Spanish the nearest passages always exist — never-said things must not turn into a
    lookup of unrelated Spanish turns."""
    indexer = _Nearest(spanish, ["ep_2024-09-03_001", "ep_2024-01-01_001", "ep_2024-02-01_001"], ("hamster",))
    found = ask_sources.search(spanish, question, indexer=indexer)
    assert not found.record_lang and not found.meaning and not found.adds and not found.passages
    prompt = _prompt(spanish, question, indexer=indexer)
    assert "found by meaning" not in prompt and "se llama Ned" not in prompt
    assert "held in Spanish" not in prompt


# --------------------------------------------------------------------------------------------------------------- #
# 3. Names across languages: turns ranked on what the question asks, from a conversation's two nearest passages
# --------------------------------------------------------------------------------------------------------------- #

def test_turns_are_ranked_on_the_question_without_the_names_every_turn_repeats(spanish):
    indexer = _Nearest(spanish, ["ep_2024-09-03_001", "ep_2024-01-01_001"], ("refugio",))
    found = ask_sources.search(spanish, "Where did Bob adopt the puppy?", indexer=indexer)
    ask_sources.gather_search(spanish, "Where did Bob adopt the puppy?", found)
    assert indexer.questions[-1] == "Where did adopt the puppy?", "Bob is in most conversations: it ranks nothing"
    assert ask_sources._without("Who is Bob?", {"bob"}) == "Who is Bob?", "a question of names alone keeps them"
    assert ask_sources._without("Where did Bob go?", set()) == "Where did Bob go?"


def test_a_conversations_second_nearest_passage_is_read(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    filler = [f"assistant: ¡Qué bien, Bob! Cuéntame más de la semana {i}." for i in range(6)]
    _episode(memory, "ep_2024-05-27_001", [_BOOK_ES, *filler])
    for i in range(1, 9):
        _episode(memory, f"ep_2024-0{i}-02_001", [f"user: ¡Hola! Semana {i}, todo tranquilo por aquí."])
    _pages(memory)
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    try:
        # The nearest passage is the conversation's second half; the book is in its first.
        indexer = _Nearest(memory, ["ep_2024-05-27_001", "ep_2024-01-02_001"], ("Lean Startup",), split=2)
        found = ask_sources.search(memory, "What book is Bob currently reading?", indexer=indexer)
        assert found.meaning and len(found.passages["ep_2024-05-27_001"]) == 2
        turns = ask_sources._meaning_turns(memory, found, {}, set())
        best = turns[0]
        doc_text = evidence.source_document(memory, best[3])[1]
        assert "Lean Startup" in doc_text[best[4].content_start:best[4].end]
    finally:
        bank_index.invalidate()


# --------------------------------------------------------------------------------------------------------------- #
# The harness: a turn fixture
# --------------------------------------------------------------------------------------------------------------- #

def test_the_spanish_turns_fixture_and_apply_turns():
    from benchmarks.public import datasets

    fixture = json.loads((Path(__file__).parents[2] / "benchmarks/public/fixtures/locomo-es-turns.json").read_text())
    turns = fixture["turns"]
    assert fixture["lang"] == "es" and set(turns) == {"conv-30", "conv-26"}
    assert len(turns["conv-30"]) == 19 and sorted(map(int, turns["conv-26"])) == list(range(2, 19, 2))
    texts = [t for unit in turns.values() for session in unit.values() for t in session.values()]
    assert len(texts) == 583 and all(t.strip() for t in texts)
    assert sum(ask_sources.text_language(t) == "es" for t in texts) > 0.85 * len(texts)

    unit = {"unit_id": "conv-30", "dataset": "locomo", "questions": [], "sessions": [
        {"source_id": "bench:conv-30:session-1", "date": "2023-01-20T16:04:00+00:00",
         "turns": [{"speaker": "user", "text": "Hi", "dia_id": "D1:1"},
                   {"speaker": "other", "text": "Hello", "dia_id": "D1:2"}]}]}
    small = {"turns": {"conv-30": {"1": {"1": "Hola"}}}}
    [out] = datasets.apply_turns([unit], small)
    assert [t["text"] for t in out["sessions"][0]["turns"]] == ["Hi", "Hola"]
    assert out["sessions"][0]["turns"][1]["dia_id"] == "D1:2", "the evidence still names the reworded turn"
    assert unit["sessions"][0]["turns"][1]["text"] == "Hello", "the dataset itself is never changed"
    assert datasets.apply_turns([{**unit, "unit_id": "conv-99"}], small)[0]["sessions"] == unit["sessions"]
    with pytest.raises(ValueError):
        datasets.apply_turns([unit], {"turns": {"conv-30": {"1": {"7": "?"}}}})
