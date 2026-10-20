"""Ask answers what the record implies, and answers a Spanish question as well as an English one (2026-10-20, G148).

The broad sample: LoCoMo open-domain scored 48.8 against 75 for the whole-conversation control, 37 of 42 misses
saying memory doesn't state what was a reasonable inference from what it found. The owner's hard set: Spanish
questions answered half as often as their English counterparts — a Spanish question over English conversations put
none of their words in front of the model (8 of 74 LoCoMo answer turns, against 38 for the same questions in
English). Synthetic banks only (alice-example, bob-example); the search model is a stand-in that records its batches.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import ask_service, ask_sources, bank_index, evidence, markdown_parser, search_index, text_fold


def _episode(memory, ep_id: str, lines: list[str], **fm) -> None:
    body = "\n".join(lines) + "\n"
    meta = {"id": ep_id, "timestamp": f"{ep_id[3:13]}T10:00:00+00:00", "processed": True, "source": "import",
            "content_hash": evidence.body_hash(body), **fm}
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", meta, body)


_SUPPORT = "user: I went to a support group meeting yesterday and it was so powerful to hear everyone's stories."


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i in range(1, 9):
        _episode(memory, f"ep_2023-0{i}-01_001", [f"user: Can you help me plan the weekly errands list number {i}?",
                                                  f"assistant: Sure, errands list {i}: groceries, laundry, bank."])
    _episode(memory, "ep_2023-05-08_001", ["user: Hi Bob, long week at work.", "assistant: Tell me about it.",
                                           _SUPPORT, "assistant: That sounds meaningful, Alice."])
    markdown_parser.write(memory / "entities" / "alice-example.md",
                          {"name": "Alice Example", "type": "person", "status": "active", "owner": True},
                          "## Summary\nAlice Example is the person this memory belongs to.\n")
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


class _Indexer:
    """The vector index, standing in for a multilingual search model: the conversation that speaks of the support
    group is nearest a question about it in either language; its turn is the nearest of that passage's turns."""

    def __init__(self, memory: Path):
        self.memory = memory
        self.batches: list[list[str]] = []

    def search_kinds(self, text, top_k_by_kind):
        out = []
        for ep in ("ep_2023-05-08_001", "ep_2023-02-01_001"):
            body = markdown_parser.parse(self.memory / "episodes" / f"{ep}.md").body
            out.append({"score": 0.8, "text": body.strip(), "metadata": {"file_path": str(self.memory / "episodes"
                                                                                           / f"{ep}.md")}})
        return {"episodes": out}

    def similarity(self, question, texts, *, kind="episodes"):
        self.batches.append(list(texts))
        return [0.9 if "support group" in t else 0.2 for t in texts]


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


# --------------------------------------------------------------------------------------------------------------- #
# Inference: a judgement is reasoned from the record; a recorded fact still declines when absent
# --------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("question", [
    "Would Alice likely have Dr. Seuss books on her bookshelf?",
    "What might Bob's financial status be?",
    "Is it likely that Bob has friends besides Alice?",
    "Would Alice be considered religious?",
    "What fields would Alice be likely to pursue in her education?",
    "What are Bob's suspected health problems?",
    "Based on Bob's collections, what is a shop he would enjoy in New York?",
    "Does Bob live close to a beach or the mountains?",
    "¿Es probable que Bob tenga amigos aparte de Alice?",
    "¿Le gustaría a Bob leer libros de fantasía?",
    "¿Cuál podría ser la situación financiera de Bob?",
    "¿Qué problemas de salud se sospecha que tiene Bob?",
    "¿Sería Alice considerada religiosa?",
    "¿Preferiría Bob un parque nacional o un parque temático?",
    "What could Bob do after his basketball career?",
    "What is something that Alice could do to fit birdwatching in?",
    "Would she enjoy a theme park?",
    "¿Qué actividad disfrutaría Alice con su perro?",
])
def test_a_judgement_is_read_as_one(question):
    assert ask_sources.asks_inference(question)


@pytest.mark.parametrize("question", [
    "When did Alice go to the support group?",
    "What did Bob say he would do after the move?",
    "What does Bob feel he could do when out in cool places?",
    "What type of dog was Alice looking to adopt based on her living space?",
    "What motivated Bob to discuss potential solutions for the community?",
    "I'm planning to revisit the city — could you remind me of that dessert shop we talked about?",
    "Can you suggest some accessories that would complement my current photography setup?",
    "What is the name of my hamster?",
    "¿Cuándo fue Alice al grupo de apoyo?",
    "¿Qué dijo Bob que haría después de la mudanza?",
    "¿Qué historia me contó Bob?",
    # Review of #385: requests, and conditionals about I, we or a thing — facts asked politely.
    "¿Sabrías decirme cuándo es la reunión?",
    "¿Me harías un resumen de lo que hablamos?",
    "¿Tendrías a mano el número del fontanero?",
    "¿Qué día sería la cita?",
    "When would the dentist appointment be?",
    "What would the address be?",
    "Which restaurant would we go to on Fridays?",
    "Where would we go every Sunday as kids?",
    "What would I have paid for the flight?",
    "Please remind me what Ana could not find",
    "What couldn't Bob find at the store?",
    "¿Adónde iríamos los domingos?",
])
def test_a_recorded_fact_or_a_request_is_not_a_judgement(question):
    assert not ask_sources.asks_inference(question)


def test_only_a_judgement_gets_the_inference_note(bank):
    judged = _prompt(bank, "Would Alice likely enjoy a support group retreat?")
    assert ask_service._INFERENCE_NOTE in judged
    assert judged.index(ask_service._INFERENCE_NOTE) < judged.index("RETRIEVED MEMORY CONTEXT")
    fact = _prompt(bank, "When did Alice go to the support group?")
    assert "JUDGEMENT" not in fact, "a recorded fact keeps rule 1: say so when absent"


# --------------------------------------------------------------------------------------------------------------- #
# Spanish
# --------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("question", [
    "When did Juan de la Torre move to Los Olivos?",
    "What did we do at la casa de la playa?",
    "How did Bob celebrate el Día de los Muertos?",
    "Did El Niño y La Niña come up when we talked about the weather?",
    "Who is Ella?",
    "where did Maria de los Angeles study",
])
def test_an_english_question_with_spanish_names_is_english(question):
    assert ask_sources.question_language(question) == "en"


def test_the_question_language():
    assert ask_sources.question_language("¿Cuándo fue Caroline al grupo de apoyo LGBTQ?") == "es"
    assert ask_sources.question_language("¿Qué investigó Caroline?") == "es"
    assert ask_sources.question_language("Qué artes marciales ha practicado John") == "es"
    assert ask_sources.question_language("When did Caroline go to the LGBTQ support group?") == "en"
    assert ask_sources.question_language("What is the name of my hamster?") == "en"


def test_spanish_function_words_carry_no_subject_in_a_spanish_question_only():
    assert ask_sources.question_terms("¿Cuándo fue Caroline al grupo de apoyo?") == {"caroline", "grupo", "apoyo"}
    assert ask_sources.question_terms("¿Con quién cenó Maria el 3 de mayo?") == {"ceno", "maria", "mayo"}
    # Review of #385: in English they are names and subjects, and the shared list is dev's.
    assert {"ella", "han", "como", "esa", "algo", "mas"} <= ask_sources.question_terms(
        "When did Ella, Han, Como, ESA, Algo and Mas meet?")
    assert {"ella", "han", "como"} <= text_fold.subject_terms("Ella and Han went to Como")
    assert {"todo", "uno", "hay", "era"} <= text_fold.subject_terms("the todo list, uno cards, hay bales, an era")
    assert "primer" in ask_sources.search_terms("Which primer did Bob buy first?")


def test_spanish_cues_never_read_an_english_question():
    assert not ask_service._wants_history("What era is the Rococo style from?")
    assert not ask_service._wants_history("Who is Bob's favourite artist, Miró?")
    assert ask_sources.question_shape("Is the ahora cafe open?") == ask_sources.SHAPE_LOOKUP


def test_spanish_time_phrasing_reads_as_english_does():
    assert ask_sources.question_shape("¿Cuándo vio Joanna por primera vez esa película?") == ask_sources.SHAPE_ANCHORED
    assert ask_sources.question_shape("¿Qué precio acordaron al final?") == ask_sources.SHAPE_LATEST
    assert ask_sources.question_shape("¿Dónde vive Bob actualmente?") == ask_sources.SHAPE_LATEST
    from datetime import date

    today = date(2023, 5, 9)
    assert ask_sources.named_days("¿Qué hice ayer?", today) == ["2023-05-08"]
    assert ask_sources.named_days("¿Qué pasó anteayer?", today) == ["2023-05-07"]
    assert ask_sources.named_days("¿Qué dije hace tres días?", today) == ["2023-05-06"]
    assert ask_sources.named_days("¿Con quién cenó Maria el 3 de mayo de 2023?", today) == ["2023-05-03"]
    assert ask_service._wants_history("¿Qué investigó Caroline?")
    assert ask_service._wants_history("¿Dónde vivía antes?")


def test_a_spanish_question_over_english_conversations_finds_the_turn_by_meaning(bank):
    indexer = _Indexer(bank)
    found = ask_sources.search(bank, "¿Cuándo fue Alice al grupo de apoyo?", indexer=indexer)
    assert found.meaning and found.episodes[0] == "ep_2023-05-08_001"
    prompt = _prompt(bank, "¿Cuándo fue Alice al grupo de apoyo?", indexer=_Indexer(bank))
    other = prompt.split("OTHER CONVERSATIONS", 1)[1]
    assert _SUPPORT.split(": ", 1)[1][:60] in other, "the turn that says it, though it shares no word with the question"
    assert "[ep_2023-05-08_001]" in other
    assert "found by meaning" in other
    assert ask_service._SPANISH_NOTE in prompt


def test_without_the_search_model_a_spanish_question_reads_as_before(bank):
    prompt = _prompt(bank, "¿Cuándo fue Alice al grupo de apoyo?")
    assert "found by meaning" not in prompt, "no search model: only what the question's words find (here the name)"


def test_a_named_day_leads_by_meaning_too(bank):
    _episode(bank, "ep_2023-05-04_001", ["user: My mom and I made dinner together last night, a feast!",
                                         "assistant: Lovely."])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    found = ask_sources.search(bank, "¿Qué cené con mi madre el 4 de mayo de 2023?", indexer=_Indexer(bank))
    assert found.meaning and found.episodes[0] == "ep_2023-05-04_001", "the named day's conversation, read whole"
    turns = ask_sources.gather_search(bank, "¿Qué cené con mi madre el 4 de mayo de 2023?", found)
    assert any("made dinner together" in e.text for e in turns)


@pytest.mark.parametrize("question", ["When did Alice go to the support group?", "What is the name of my hamster?"])
def test_an_english_question_never_goes_by_meaning(bank, question):
    """A word the record lacks is also how a question about something never said looks: the nearest passage by
    meaning would answer it wrongly (the first cut turned an abstention into a lookup)."""
    indexer = _Indexer(bank)
    found = ask_sources.search(bank, question, indexer=indexer)
    assert not found.meaning and not found.passages
    assert indexer.batches == [], "nothing is embedded for it"


def test_claims_by_meaning_take_the_nearest_few():
    class Row:
        def __init__(self, text):
            self.text, self.predicate, self.object = text, "", ""

    rows = [Row(f"Alice ordinary fact {i}") for i in range(30)] + [Row("Alice attended a support group")]
    seen: list = []

    def similar(texts):
        seen.append(len(texts))
        return [0.9 if "support group" in t else (0.1 if "fact 1" in t else 0.0) for t in texts]

    assert ask_service._near_claims(rows, rows, similar) == {1, 10, 11, 12}, "the scan stops at the budget's claims"
    near = ask_service._near_claims(rows[-3:], rows[-3:], similar)
    assert near == {2}, "only claims that score, nearest first"
    assert seen[0] == ask_service._NEAR_SCAN, "about what the claim budget shows, never a whole long page"


# --------------------------------------------------------------------------------------------------------------- #
# The harness: a question fixture
# --------------------------------------------------------------------------------------------------------------- #

def test_the_spanish_fixture_and_apply_questions():
    from benchmarks.public import datasets

    fixture = json.loads((Path(__file__).parents[2] / "benchmarks/public/fixtures/locomo-es.json").read_text())
    qs = fixture["questions"]
    assert fixture["lang"] == "es" and len(qs) == 50
    assert sum(q["category"] == "adversarial" for q in qs.values()) == 10
    assert all(ask_sources.question_language(q["es"]) == "es" and ask_sources.question_language(q["en"]) == "en"
               for q in qs.values())
    qid = next(iter(qs))
    unit = {"unit_id": qid.split(":")[0], "dataset": "locomo", "sessions": [], "questions": [
        {"qid": qid, "question": "x", "category": "single-hop"}, {"qid": "other:q999", "question": "y"}]}
    [kept] = datasets.apply_questions([unit, {**unit, "unit_id": "none", "questions": []}], fixture)
    assert [q["question"] for q in kept["questions"]] == [qs[qid]["es"]]
    assert datasets.apply_questions([unit], fixture, "en")[0]["questions"][0]["question"] == qs[qid]["en"]


# --------------------------------------------------------------------------------------------------------------- #
# Review of #385: by meaning beside the words, not instead of them
# --------------------------------------------------------------------------------------------------------------- #

_DENTIST = ["user: Hoy fui al dentista por la muela del juicio, me la sacaron por fin.",
            "user: Otra vez al dentista: revisión de la muela, todo bien.",
            "user: Tercera visita al dentista este año, ahora por una limpieza."]


@pytest.fixture
def mixed(tmp_path):
    """Spanish conversations (the person's own, word hits strong) beside English ones (a Spanish question's words
    find nothing there), and Spanish filler the search model wrongly finds nearest."""
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i in range(1, 9):
        _episode(memory, f"ep_2024-0{i}-01_001", [f"user: Ayúdame a planear la lista de recados número {i}.",
                                                  f"assistant: Claro, recados {i}: compras, lavandería y el banco."])
    for i, turn in enumerate(_DENTIST):
        _episode(memory, f"ep_2024-0{i + 2}-15_001", ["user: Buenos días, qué semana.", turn,
                                                      "assistant: Me alegro de que haya ido bien."])
    _episode(memory, "ep_2024-09-03_001", ["user: Long week at work.", _SUPPORT, "assistant: That sounds meaningful."])
    markdown_parser.write(memory / "entities" / "alice-example.md",
                          {"name": "Alice Example", "type": "person", "status": "active", "owner": True},
                          "## Summary\nAlice Example is the person this memory belongs to.\n")
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


class _Nearest:
    """A search model whose nearest passages are the given conversations, in order; a turn is near when it holds
    one of ``near_words``."""

    def __init__(self, memory: Path, episodes: list[str], near_words: tuple[str, ...]):
        self.memory, self.episodes, self.near_words = memory, episodes, near_words
        self.batches: list[list[str]] = []

    def search_kinds(self, text, top_k_by_kind):
        rows = []
        for ep in self.episodes:
            path = self.memory / "episodes" / f"{ep}.md"
            rows.append({"score": 0.8, "text": markdown_parser.parse(path).body.strip(),
                         "metadata": {"file_path": str(path)}})
        return {"episodes": rows}

    def similarity(self, question, texts, *, kind="episodes"):
        self.batches.append(list(texts))
        return [0.9 if any(w in t for w in self.near_words) else 0.2 for t in texts]


def test_a_spanish_question_over_spanish_conversations_keeps_its_word_hits(mixed):
    # The search model is wrong here: it finds the errands chats nearest. The words find the dentist.
    indexer = _Nearest(mixed, ["ep_2024-01-01_001", "ep_2024-02-01_001"], ("recados",))
    found = ask_sources.search(mixed, "¿Cuándo me sacaron la muela del juicio?", indexer=indexer)
    assert not found.meaning and found.adds, "same language as the record: the words lead, meaning only adds"
    prompt = _prompt(mixed, "¿Cuándo me sacaron la muela del juicio?", indexer=indexer)
    other = prompt.split("OTHER CONVERSATIONS", 1)[1]
    assert "me la sacaron por fin" in other
    lines = [l for l in other.splitlines() if l.startswith("- ")]
    assert sum("recados" in l for l in lines) <= ask_sources.MEANING_EXTRA_EXCERPTS
    words_only = _prompt(mixed, "¿Cuándo me sacaron la muela del juicio?").split("OTHER CONVERSATIONS", 1)[1]
    for line in (l for l in words_only.splitlines() if l.startswith("- ")):
        assert line in lines, "every line the words found is still shown: meaning adds, never displaces"


def test_a_spanish_count_over_spanish_conversations_keeps_the_list_path(mixed):
    indexer = _Nearest(mixed, ["ep_2024-01-01_001"], ("recados",))
    prompt = _prompt(mixed, "¿Cuántas veces fui al dentista?", indexer=indexer)
    other = prompt.split("OTHER CONVERSATIONS", 1)[1]
    assert "the question asks for a count or a list" in other
    for turn in _DENTIST:
        assert turn.split(": ", 1)[1][:40] in other, "every conversation that told it (#381's list path)"
    words_only = _prompt(mixed, "¿Cuántas veces fui al dentista?").split("OTHER CONVERSATIONS", 1)[1]
    for line in (l for l in words_only.splitlines() if l.startswith("- ")):
        assert line in other


def test_a_spanish_question_over_english_conversations_still_goes_by_meaning(mixed):
    indexer = _Nearest(mixed, ["ep_2024-09-03_001", "ep_2024-01-01_001"], ("support group",))
    found = ask_sources.search(mixed, "¿Cuándo fue Alice al grupo de apoyo?", indexer=indexer)
    assert found.meaning and not found.adds, "the nearest passages are English: meaning leads"
    other = _prompt(mixed, "¿Cuándo fue Alice al grupo de apoyo?", indexer=indexer).split("OTHER CONVERSATIONS", 1)[1]
    assert _SUPPORT.split(": ", 1)[1][:60] in other


def test_a_passages_language():
    assert ask_sources.text_language("user: Hoy fui al dentista por la muela, me la sacaron por fin.") == "es"
    assert ask_sources.text_language("user: I went to the support group and it was powerful.") == "en"
