"""Ask: a count or a list needs every conversation that told the thing, with the line that tells it (2026-10-20, G148).

The broad sample: LoCoMo multi-hop 65 J against the whole-conversation control's 96, its answer turns in Ask's prompt
for 147 of 322; LongMemEval_S multi-session 11.7 %, 28 of 71. Three causes, each fixed here and each tested on a
synthetic bank (alice-example, bob-example; the word index alone, no network; the model is a stub that records its
prompt):

* the other side of a chat repeats the question's words ("weddings are such fun to attend!") and its turn beat the
  person's own line that told the event — a count or a list now prefers the turns of whoever it is about;
* a list asked as a plain question ("where has <name> camped?", "what are <name>'s hobbies?", Spanish counts) was read
  as one fact;
* a list over a page's subject shares no word with the things in it ("what activities …" vs "went camping at the
  beach"): the page's own items nearest the question by the search model fill its budget, and each leads to the turn
  that told it by the item's own words.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from api.services import ask_service, ask_sources, bank_index, evidence, markdown_parser, search_index, \
    section_provenance


def _episode(memory, ep_id: str, lines: list[str], **fm) -> None:
    body = "\n".join(lines) + "\n"
    meta = {"id": ep_id, "timestamp": f"{ep_id[3:13]}T10:00:00+00:00", "processed": True, "source": "import",
            "content_hash": evidence.body_hash(body), **fm}
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", meta, body)


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i in range(1, 13):
        _episode(memory, f"ep_2023-{i:02d}-01_001", [f"user: Can you help me plan the weekly errands list number {i}?",
                                                     f"assistant: Sure, errands list {i}: groceries, laundry, bank."])
    yield memory
    bank_index.invalidate()


def _index(memory) -> None:
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()


class _Model:
    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"answer": "stub", "confidence": 0.8, "used_entities": [], "gaps": []})


def _hit(entity_id: str) -> dict:
    return {"score": 0.9, "text": "", "metadata": {"entity_id": entity_id, "entity_name": entity_id, "type": "person",
                                                    "status": "active", "file_path": ""}}


def _prompt(memory, question: str, *, pages=(), search_fn=None) -> str:
    model = _Model()
    ask_service.answer_query(memory, question, retrieve_fn=lambda q, k: [_hit(p) for p in pages], llm_fn=model,
                             no_engine=False, search_fn=search_fn)
    [prompt] = model.prompts
    return prompt


# --------------------------------------------------------------------------------------------------------------- #
# The forms
# --------------------------------------------------------------------------------------------------------------- #

def test_lists_asked_as_plain_questions_and_spanish_counts_are_counts_or_lists():
    shape = ask_sources.question_shape
    for q in ("Where has Bob camped?", "What are Bob's hobbies?",
              "What were Bob's mother's hobbies?", "What are the names of Bob's dogs?",
              "Which of my friends have passed away?", "Which of Bob's screenplays were rejected?",
              "What kind of indoor activities has bob-example pursued with his girlfriend?",
              "What places give bob-example peace?",
              "¿Cuántas veces fui al gimnasio?", "¿Cuántos libros he leído este año?", "¿Qué libros he leído?",
              "¿Qué países he visitado?"):
        assert shape(q) == ask_sources.SHAPE_ENUMERATE, q
    # One thing, an outcome, a day, a value: not lists.
    assert shape("What type of movies does bob-example enjoy watching the most?") == ask_sources.SHAPE_LOOKUP
    assert shape("What are bob-example's favorite games?") == ask_sources.SHAPE_LOOKUP
    assert shape("What type of workout class did bob-example start doing in December 2023?") == \
        ask_sources.SHAPE_ANCHORED
    assert shape("What is bob-example allergic to?") == ask_sources.SHAPE_LOOKUP
    assert shape("¿Cuánto cuesta la bici?") == ask_sources.SHAPE_LOOKUP
    assert shape("What did Caroline research?") == ask_sources.SHAPE_LOOKUP
    assert shape("¿Cuántos días pasaron entre la mudanza del estudio y la primera clase de cerámica?") == \
        ask_sources.SHAPE_TWO_ENDS


def test_one_thing_asked_in_the_plural_is_not_a_list():
    """Review of #381: plural nouns that name one thing about a subject, a choice among several, an age, a habit,
    "what else", a greeting — none of them is a list."""
    shape = ask_sources.question_shape
    for q in ("¿Cuáles son tus planes?", "¿Cuáles son tus pensamientos sobre la mudanza?",
              "What are Bob's thoughts on the move?", "What were Alice's reasons for leaving?",
              "What are the chances that it rains?", "What are the details of the lease?", "Where have you been?",
              "Which of my laptops is faster?", "¿Cuántos años tiene Bob?", "¿A qué hora me levanto todos los días?",
              "¿Qué más has hecho?", "What are Bob's plans for the weekend?", "What are Bob's opinions on remote work?"):
        assert shape(q) != ask_sources.SHAPE_ENUMERATE, q
    for q in ("¿Cuáles fueron los resultados?", "¿Cuáles son mis libros favoritos de este año?" ,
              "Where has Bob lived?", "¿Cuántas veces fui a la playa todos los veranos?"):
        assert shape(q) == ask_sources.SHAPE_ENUMERATE, q


def test_who_a_question_is_about():
    asked = ask_sources.asked_about("How many weddings have I attended?", "Alice Example")
    assert asked.person and not asked.agent
    asked = ask_sources.asked_about("What sports does Bob Example play?", "Alice Example")
    assert not asked.person and not asked.agent and {"bob", "example"} <= asked.words
    asked = ask_sources.asked_about("Which books did you recommend to me?", "Alice Example")
    assert asked.person and asked.agent
    assert ask_sources.asked_about("What did Alice Example plan?", "Alice Example").person
    assert ask_sources.asked_about("Which tools has the user tried?", None).person
    for q in ("¿Qué libros he leído?", "¿Cuántas veces fui al gimnasio?", "¿Qué compré en marzo?",
              "¿Qué hemos comido esta semana?"):
        assert ask_sources.asked_about(q, None).person, q
    for q in ("¿Qué hay aquí?", "¿Qué café tiene Bob?", "¿Cuántos libros leyó Bob?"):
        assert not ask_sources.asked_about(q, None).person, q


# --------------------------------------------------------------------------------------------------------------- #
# Whose turn tells it
# --------------------------------------------------------------------------------------------------------------- #

def _weddings(memory) -> list[str]:
    days = ["2024-03-02", "2024-04-13", "2024-05-18", "2024-06-22", "2024-08-03", "2024-09-14"]
    for i, day in enumerate(days):
        _episode(memory, f"ep_{day}_001", [
            f"user: Can you suggest a playlist for a dinner party, number {i}?",
            f"assistant: Sure! Weddings you attend often use songs like these, so here is a wedding-style list {i}.",
            f"user: Thanks! I attended a wedding last weekend, guest {i} of the couple, and loved it.",
        ])
    _index(memory)
    return [f"ep_{d}_001" for d in days]


def test_a_count_shows_the_persons_own_line_not_the_agent_repeating_the_words(bank):
    eps = _weddings(bank)
    question = "How many weddings have I attended?"
    found = ask_sources.search(bank, question)
    shown = ask_sources.gather_search(bank, question, found, owner_name="Alice Example")
    mine = {e.episode for e in shown if e.text.startswith("Thanks! I attended a wedding")}
    assert mine == set(eps), "every conversation's line is the person's own"
    assert all(e.who.startswith("Alice Example (the person this memory belongs to)")
               for e in shown if e.text.startswith("Thanks!"))


def test_without_the_preference_the_agents_repeat_wins(bank, monkeypatch):
    """The test above discriminates: weighed equally, the agent's earlier turn holding the same words is shown."""
    eps = _weddings(bank)
    monkeypatch.setattr(ask_sources, "OTHER_SPEAKER_SHARE", 1.0)
    question = "How many weddings have I attended?"
    found = ask_sources.search(bank, question)
    shown = ask_sources.gather_search(bank, question, found, owner_name="Alice Example")
    assert {e.episode for e in shown if e.text.startswith("Thanks! I attended a wedding")} != set(eps)


def test_a_list_about_another_speaker_prefers_their_turns(bank):
    days = ["2024-02-03", "2024-03-09", "2024-04-20", "2024-05-25", "2024-07-06"]
    sports = ["tennis", "squash", "rowing", "climbing", "cycling"]
    for day, sport in zip(days, sports):
        _episode(bank, f"ep_{day}_001", [
            f"user: Which sports do you play these days, Bob? I only watch sports, {sport} included.",
            f"speaker:bob-example: Mostly {sport} now, I play twice a week; sports keep me sane.",
        ], correspondent={"name": "Bob Example", "kind": "person", "decided_by": "person"})
    _index(bank)
    question = "What sports does Bob Example play?"
    assert ask_sources.question_shape(question) == ask_sources.SHAPE_ENUMERATE
    found = ask_sources.search(bank, question)
    shown = ask_sources.gather_search(bank, question, found, owner_name="Alice Example")
    bobs = {e.episode for e in shown if e.who.startswith("Bob Example") and e.text.startswith("Mostly")}
    assert bobs == {f"ep_{d}_001" for d in days}, "each conversation's line is Bob's, the one the question names"


# --------------------------------------------------------------------------------------------------------------- #
# A page's whole inventory, and the turns behind it
# --------------------------------------------------------------------------------------------------------------- #

ACTIVITIES = {
    "ep_2024-05-04_001": ("Bob Example went camping at the beach with his kids.",
                          "speaker:bob-example: We went camping at the beach with the kids, it was lovely!"),
    "ep_2024-06-08_001": ("Bob Example took a pottery class and made a bowl.",
                          "speaker:bob-example: Took a pottery class on Saturday, made a wonky bowl."),
    "ep_2024-07-13_001": ("Bob Example swims in the lake every summer morning.",
                          "speaker:bob-example: Every summer morning I swim in the lake before work."),
}


def _bob_page(memory) -> None:
    for ep, (_fact, turn) in ACTIVITIES.items():
        _episode(memory, ep, ["user: How was your weekend, Bob?", turn, "user: Sounds great."],
                 correspondent={"name": "Bob Example", "kind": "person", "decided_by": "person"})
    filler = [f"Bob Example mentioned ordinary detail number {i} about the office schedule." for i in range(40)]
    facts = filler + [fact for fact, _turn in ACTIVITIES.values()]
    body = ("## Summary\nBob Example is a friend of Alice Example.\n\n## Key Facts\n"
            + "".join(f"- {f}\n" for f in facts))
    sources = {fact: ep for ep, (fact, _turn) in ACTIVITIES.items()}
    records = {"key_facts": {}}
    for item in section_provenance.scan(body)["key_facts"]:
        ep = sources.get(item.text, "ep_2023-01-01_001")
        records["key_facts"][item.key] = (item.text_hash, [evidence.reasoning(ep, hash=evidence.body_hash("x"))])
    markdown_parser.write(memory / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active",
                           section_provenance.FIELD: section_provenance.encode(records)}, body)
    _index(memory)


class _Indexer:
    """A stand-in for the vector index's on-device nearness: the activity items are near "activities", the rest
    far. Records each batch; ``fail`` raises as an unavailable or warming model does."""

    def __init__(self, fail: bool = False):
        self.batches: list[list[str]] = []
        self.fail = fail

    def similarity(self, question, texts, *, kind="episodes"):
        self.batches.append(list(texts))
        if self.fail:
            from api.services.vector_index import SimilarityUnavailable

            raise SimilarityUnavailable("no on-device model")
        return [0.9 if any(w in t for w in ("camping", "pottery", "swims")) else 0.1 for t in texts]


def _near(indexer: _Indexer):
    """The real :func:`ask_sources._similarity` (its allowance, clipping and failure path) over ``indexer``."""
    def search_fn(memory, question):
        found = ask_sources.search(memory, question)
        if found.shape == ask_sources.SHAPE_ENUMERATE:
            found.similar = ask_sources._similarity(indexer, question)
        return found

    return search_fn


def test_a_list_about_a_named_page_reads_its_nearest_items_and_the_turns_that_told_them(bank):
    _bob_page(bank)
    indexer = _Indexer()
    prompt = _prompt(bank, "What activities does Bob Example partake in?", pages=("bob-example",),
                     search_fn=_near(indexer))
    assert len(indexer.batches) == 1 and len(indexer.batches[0]) <= ask_sources.SIMILAR_TEXTS
    for fact, turn in ACTIVITIES.values():
        assert fact in prompt, "the item, though it shares no word with the question"
    said = prompt.split("WHAT WAS SAID", 1)[1]
    for fact, turn in ACTIVITIES.values():
        assert turn.split(": ", 1)[1] in said, "the turn that told it, followed by the item's own words"
    assert "Bob Example (another person, not the person this memory belongs to)" in said


def test_without_the_search_model_the_page_reads_as_before(bank):
    _bob_page(bank)
    prompt = _prompt(bank, "What activities does Bob Example partake in?", pages=("bob-example",))
    for fact, _turn in ACTIVITIES.values():
        assert fact not in prompt, "no conversations' index here: the items sharing no word stay off the page block"


def test_a_question_that_names_no_page_never_embeds_its_items(bank):
    _bob_page(bank)
    indexer = _Indexer()
    _prompt(bank, "What activities do I partake in?", pages=("bob-example",), search_fn=_near(indexer))
    assert indexer.batches == [], "the person's own words name no page; nothing is embedded"
    _prompt(bank, "What did Bob Example say about the office schedule?", pages=("bob-example",),
            search_fn=_near(indexer))
    assert indexer.batches == [], "not a list: the page reads as before"


def test_a_failed_or_unavailable_model_leaves_the_page_as_before(bank):
    _bob_page(bank)
    indexer = _Indexer(fail=True)
    prompt = _prompt(bank, "What activities does Bob Example partake in?", pages=("bob-example",),
                     search_fn=_near(indexer))
    for fact, _turn in ACTIVITIES.values():
        assert fact not in prompt
    assert "Bob Example is a friend" in prompt, "the page still reads"


def test_one_allowance_for_the_whole_question_each_text_clipped():
    indexer = _Indexer()
    similar = ask_sources._similarity(indexer, "What activities do Bob and Carol share?")
    long_item = "Bob Example went camping " + "and then kept talking about the weather " * 30
    first = similar([long_item] * 100)
    second = similar(["Carol Example took a pottery class"] * 100)
    third = similar(["anything"] * 5)
    assert [len(b) for b in indexer.batches] == [100, ask_sources.SIMILAR_TEXTS - 100], "one allowance, not per page"
    assert all(len(t) <= ask_sources.SIMILAR_CHARS for b in indexer.batches for t in b), "what the prompt shows, less"
    assert len(first) == 100 and len(second) == 100 and second[20:] == [0.0] * 80 and third == [0.0] * 5
    failing = _Indexer(fail=True)
    similar = ask_sources._similarity(failing, "What activities?")
    assert similar(["a", "b"]) == [0.0, 0.0] and similar(["c"]) == [0.0]
    assert len(failing.batches) == 1, "after a failure nothing more is embedded for the question"


def test_an_item_with_no_words_of_its_own_never_makes_every_turn_a_candidate(bank):
    ep = "ep_2024-08-11_001"
    _episode(bank, ep, ["user: Morning!", "speaker:bob-example: Lovely weather today."],
             correspondent={"name": "Bob Example", "kind": "person", "decided_by": "person"})
    shown = ask_sources.gather(bank, "What activities does Bob Example partake in?",
                               [ask_sources.Pointer(episode=ep, weight=1, terms=set())], breadth=True)
    assert shown == []


def test_breadth_keeps_two_things_one_conversation_told(bank):
    ep = "ep_2024-08-10_001"
    _episode(bank, ep, ["user: Busy week?",
                        "speaker:bob-example: We went camping at the beach on Friday.",
                        "user: Nice!",
                        "speaker:bob-example: And on Sunday I swim in the lake with my brother."],
             correspondent={"name": "Bob Example", "kind": "person", "decided_by": "person"})
    found = [ask_sources.Pointer(episode=ep, weight=1, terms={"camp", "beach", "friday"}),
             ask_sources.Pointer(episode=ep, weight=1, terms={"swim", "lake", "brother"})]
    shown = ask_sources.gather(bank, "What activities does Bob Example partake in?", found, breadth=True,
                               max_episodes=ask_sources.ENUM_EPISODES, max_excerpts=ask_sources.BREADTH_EXCERPTS,
                               total_chars=ask_sources.BREADTH_CHARS)
    texts = " ".join(e.text for e in shown)
    assert "camping at the beach" in texts and "swim in the lake" in texts
    assert all(len(e.text) <= ask_sources.BREADTH_EXCERPT_CHARS + 2 for e in shown)


# --------------------------------------------------------------------------------------------------------------- #
# The search model's nearness, in the table's own space
# --------------------------------------------------------------------------------------------------------------- #

_VOCAB = ["camping", "beach", "pottery", "office", "activity"]


def _bow(texts, *, is_query=False):
    rows = []
    for text in texts:
        vec = np.array([float(text.lower().count(w)) for w in _VOCAB], dtype=np.float32)
        rows.append(vec / (np.linalg.norm(vec) or 1.0))
    return np.vstack(rows)


def _indexed(bank, model: str, seen: list):
    from api.services.vector_index import SqliteVecIndexer

    def recording(texts, *, is_query=False):
        seen.append(("query" if is_query else "passage", list(texts)))
        return _bow(texts, is_query=is_query)

    _episode(bank, "ep_2024-01-05_001", ["user: camping at the beach, an activity I love"])
    indexer = SqliteVecIndexer(bank, embed_fn=recording, model_name=model)
    indexer.index_episodes()
    assert indexer.index_info("episodes").get("model") == model
    seen.clear()
    return indexer


def test_similarity_embeds_texts_as_passages_with_the_tables_on_device_model(bank, monkeypatch):
    from api.services import onnx_embedder

    model = "google/embeddinggemma-2:768"
    monkeypatch.setattr(onnx_embedder, "find", lambda mid, *a, **k: object() if mid == model else None)
    seen: list = []
    indexer = _indexed(bank, model, seen)
    scores = indexer.similarity("camping beach activity", ["camping at the beach", "office hours", ""])
    assert len(scores) == 3 and scores[0] > 0.8 and scores[1] == 0.0
    assert ("passage", ["camping at the beach", "office hours", ""]) in seen, "the texts are embedded as passages"
    assert indexer.similarity("anything", []) == []


@pytest.mark.parametrize("model", ["openai/text-embedding-3-small", "text-embedding-3-large",
                                   "openrouter/google/gemini-embedding-001", "some/model-not-on-this-mac"])
def test_similarity_never_sends_a_page_to_a_hosted_or_missing_model(bank, monkeypatch, model):
    from api.services import onnx_embedder
    from api.services.vector_index import SimilarityUnavailable

    monkeypatch.setattr(onnx_embedder, "find", lambda mid, *a, **k: None)
    seen: list = []
    indexer = _indexed(bank, model, seen)
    with pytest.raises(SimilarityUnavailable):
        indexer.similarity("camping beach activity", ["Bob Example went camping at the beach"])
    assert seen == [], "nothing embedded, nothing sent anywhere"


def test_passage_functions_load_within_a_bounded_wait():
    """A dropped compile cache (a ~90 s load) never stalls an answer: past the wait the ranking is skipped and the
    load goes on in the background."""
    import threading
    import time
    from types import SimpleNamespace

    from api.services import coreml_embedder

    release = threading.Event()
    emb = coreml_embedder.CoreMLEmbedder(SimpleNamespace(dimensions=768))
    emb._load_function = lambda name: (release.wait(10), object())[1]
    started = time.monotonic()
    with pytest.raises(coreml_embedder.EmbedderWarming):
        emb._ready(["embed_64", "pack_256"], 0.2)
    assert time.monotonic() - started < 1.0, "one bound for every function the batch needs"
    release.set()
    assert emb._functions_for([[1] * 20] * 8) == ["pack_256"], "short texts share packed calls"
    assert emb._functions_for([[1] * 300, [1] * 20]) == ["embed_32", "embed_512"]
