"""Ask reaches what was said in conversations no page points at (2026-10-19, the search leg).

The owner's eval (60 questions about one conversation each): 25 wrong answers, 25 of them about one known source
conversation; that conversation's own words reached the prompt for 5, although plain episode search ranked it in the
top five for 16. Ask was page-first: a conversation's words arrived only through a shown page's evidence or
provenance. The search leg finds the conversations by the question's own words and shows their matching turns as
OTHER CONVERSATIONS. Synthetic banks only (alice-example, bob-example); no embedding, no network — the vector index
is absent, so the word index alone finds conversations here. The model is a stub that records its prompt.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from api.services import ask_service, ask_sources, bank_index, evidence, markdown_parser, search_index


def _episode(memory, ep_id: str, turns: list[str], **fm) -> None:
    body = "\n".join(turns) + "\n"
    meta = {"id": ep_id, "timestamp": f"{ep_id[3:13]}T10:00:00+00:00", "processed": True, "source": "import",
            "content_hash": evidence.body_hash(body), **fm}
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", meta, body)


def _filler(i: int) -> list[str]:
    return [f"user: Can you help me plan the weekly errands list number {i}?",
            f"assistant: Sure, here is a plan for errands list {i}: groceries, laundry and the bank."]


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i in range(1, 9):
        _episode(memory, f"ep_2024-0{i}-01_001", _filler(i))
    # The decision, said once, in the middle of a long multi-topic export that no page cites.
    long_turns = []
    for i in range(40):
        long_turns += [f"user: Another question about the garden irrigation schedule, part {i}.",
                       f"assistant: The irrigation schedule part {i} looks fine; water early in the morning."]
    long_turns[41] = ("user: For alpha-project I decided on Postgres over the document store, because the reports "
                      "need joins.")
    _episode(memory, "ep_2025-03-14_001", long_turns, title="Chat export")
    # The person's page exists but says nothing about the decision.
    markdown_parser.write(memory / "entities" / "alice-example.md",
                          {"name": "Alice Example", "type": "person", "status": "active", "owner": True},
                          "## Summary\nAlice Example is the person this memory belongs to.\n")
    assert search_index.ensure_fresh(memory, wait=True) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def _hit(entity_id: str) -> dict:
    return {"score": 0.9, "text": "", "metadata": {"entity_id": entity_id, "entity_name": entity_id, "type": "person",
                                                    "status": "active", "file_path": ""}}


class _Model:
    def __init__(self, reply: dict | None = None):
        self.prompts: list[str] = []
        self.reply = reply or {"answer": "stub", "confidence": 0.8, "used_entities": [], "gaps": []}

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.reply)


def _ask(bank, question: str, *, pages=("alice-example",), model=None, **kw):
    model = model or _Model()
    result = ask_service.answer_query(bank, question, retrieve_fn=lambda q, k: [_hit(p) for p in pages],
                                      llm_fn=model, no_engine=False, **kw)
    return result, model


def _tree(memory) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in memory.rglob("*") if p.is_file() and p.name != search_index.DB_FILE
                       and not p.name.startswith(search_index.DB_FILE)):
        digest.update(path.relative_to(memory).as_posix().encode() + path.read_bytes())
    return digest.hexdigest()


def test_a_decision_deep_in_a_long_export_no_page_cites_reaches_the_model(bank):
    before = _tree(bank)
    _, model = _ask(bank, "Which database did I choose for alpha-project?")
    [prompt] = model.prompts
    other = prompt.split("OTHER CONVERSATIONS", 1)[1]
    assert "I decided on Postgres over the document store" in other
    assert "[ep_2025-03-14_001], Alice Example (the person this memory belongs to)" in other, "dated, its conversation and speaker"
    assert "WHAT WAS SAID" not in prompt, "no page pointed there: the words come only from the search leg"
    assert _tree(bank) == before, "Ask never writes to the bank"


def test_without_the_sources_scope_the_leg_never_runs(bank):
    called = []
    _, model = _ask(bank, "Which database did I choose for alpha-project?", source_words=False,
                    search_fn=lambda m, q: called.append(q))
    assert not called
    assert "OTHER CONVERSATIONS" not in model.prompts[0] and "Postgres" not in model.prompts[0]


def test_no_page_but_a_conversation_answers_calls_the_model_and_cites_the_conversation(bank):
    reply = {"answer": "Postgres.", "confidence": 0.8, "used_entities": ["ep_2025-03-14_001"],
             "used_conversations": ["ep_2025-03-14_001", "ep_9999-01-01_001"], "gaps": []}
    result, model = _ask(bank, "Which database was chosen for alpha-project?", pages=(), model=_Model(reply))
    assert len(model.prompts) == 1, "a conversation to ground on is not a gap"
    assert result["answer"] == "Postgres."
    assert result["used_entities"] == [], "an episode id is not an invented entity"
    assert [c["episode_id"] for c in result["conversations"]] == ["ep_2025-03-14_001"], "only ids that were shown"
    assert result["conversations"][0]["title"] == "Chat export"


def test_omitted_used_conversations_falls_back_to_every_one_shown(bank):
    result, _ = _ask(bank, "Which database was chosen for alpha-project?", pages=())
    assert [c["episode_id"] for c in result["conversations"]] == ["ep_2025-03-14_001"]


def test_nothing_found_by_pages_or_words_is_still_the_honest_gap(bank):
    result, model = _ask(bank, "What is the capital of Zanzibarland?", pages=())
    assert model.prompts == [], "the gap fast path never calls the model"
    assert result["confidence"] <= 0.05 and result["conversations"] == []


def test_a_turn_holding_only_common_words_is_never_shown(bank):
    # "errands" and "plan" are in most of the bank's conversations: they rank nothing.
    found = ask_sources.search(bank, "What errands did I plan?")
    assert "errand" not in found.weights and "plan" not in found.weights
    _, model = _ask(bank, "What errands did I plan?")
    assert "OTHER CONVERSATIONS" not in model.prompts[0]


def test_index_only_episodes_are_never_shown(bank):
    from api.services import history_index

    _episode(bank, "ep_2025-05-01_001", ["user: Watched: the alpha-project Postgres talk"],
             source=history_index.HISTORY_SOURCE)
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    found = ask_sources.search(bank, "Which Postgres talk about alpha-project?")
    # 2026-10-19: neither ranked nor counted — a word's rarity is over the conversations the leg can show.
    assert "ep_2025-05-01_001" not in found.episodes
    found.episodes.append("ep_2025-05-01_001")   # and were one handed to the reader, it is still never shown
    shown = ask_sources.gather_search(bank, "Which Postgres talk about alpha-project?", found)
    assert "ep_2025-05-01_001" not in {e.episode for e in shown}, "ruling 30: a watched day is a record, not words"


def test_an_agents_saved_note_is_never_the_persons_words(bank):
    _episode(bank, "ep_2025-06-01_001", ["The person prefers Postgres for alpha-project reporting."], source="mcp")
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    _, model = _ask(bank, "Does alpha-project reporting use Postgres?")
    other = model.prompts[0].split("OTHER CONVERSATIONS", 1)[1]
    assert "[ep_2025-06-01_001], an agent's saved note (not the person's own words)" in other


def test_the_assistants_words_are_labelled_as_the_assistants(bank):
    _episode(bank, "ep_2025-07-01_001", ["user: What should alpha-project use for queues?",
                                         "assistant: I would suggest a Kafkaesque broker for alpha-project queues."])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    _, model = _ask(bank, "Which broker for alpha-project queues?")
    other = model.prompts[0].split("OTHER CONVERSATIONS", 1)[1]
    assert "the assistant (an AI agent, not the person): \"I would suggest a Kafkaesque broker" in other


def test_a_turn_the_page_leg_showed_is_not_repeated(bank):
    found = ask_sources.search(bank, "Which database did I choose for alpha-project?")
    first = ask_sources.gather_search(bank, "Which database did I choose for alpha-project?", found)
    again = ask_sources.gather_search(bank, "Which database did I choose for alpha-project?", found,
                                      taken=ask_sources.shown_turns(first))
    assert first and not ({(e.episode, e.order[2]) for e in first} & {(e.episode, e.order[2]) for e in again})


def test_the_leg_is_bounded(bank):
    for i in range(30):
        _episode(bank, f"ep_2026-01-{i + 1:02d}_001",
                 [f"user: alpha-project Postgres note {i}: " + "the reporting joins need care " * 30])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    found = ask_sources.search(bank, "alpha-project Postgres reporting joins")
    shown = ask_sources.gather_search(bank, "alpha-project Postgres reporting joins", found)
    assert len({e.episode for e in shown}) <= ask_sources.SEARCH_EPISODES
    assert len(shown) <= ask_sources.SEARCH_EXCERPTS
    assert sum(len(e.text) for e in shown) <= ask_sources.SEARCH_CHARS


def test_the_question_is_never_logged(bank, monkeypatch):
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")

    def boom(*a, **k):
        raise RuntimeError("Which database did I choose for alpha-project?")

    monkeypatch.setattr(search_index, "Reader", boom)
    try:
        found = ask_sources.search(bank, "Which database did I choose for alpha-project?")
    finally:
        logger.remove(sink)
    assert found.episodes == []
    assert lines and not any("alpha-project" in line or "database" in line for line in lines)


# --------------------------------------------------------------------------------------------------------------- #
# Which conversation is current, counts and lists, and what the leg counts (2026-10-19, Ask depth)
# --------------------------------------------------------------------------------------------------------------- #

def _bike_bank(memory) -> None:
    """Five earlier conversations about a bike's listing price, then the later one where the price was agreed — which
    shares fewer of a question's words than any of them."""
    for i, day in enumerate(("2025-04-02", "2025-04-05", "2025-04-09", "2025-04-12", "2025-04-15")):
        _episode(memory, f"ep_{day}_001", [
            f"user: The listing price for the gravel bike is 900; the seller says the price is firm, note {i}.",
            "assistant: A listing price is where a negotiation starts; ask about the price again later."])
    _episode(memory, "ep_2025-05-20_001", ["user: Done: we settled at 720 for the gravel bike, picking it up Friday.",
                                           "assistant: Congratulations on the new bike!"])
    search_index.ensure_fresh(memory, wait=True, max_age_s=0)


def test_the_later_conversation_that_settled_it_is_shown_beside_the_earlier_plan(bank):
    _bike_bank(bank)
    question = "What was the final price for the gravel bike?"
    assert ask_sources.question_shape(question) == ask_sources.SHAPE_LATEST
    found = ask_sources.search(bank, question)
    assert found.kept.get("ep_2025-05-20_001") == "latest"
    assert "ep_2025-05-20_001" in found.episodes[:ask_sources.SEARCH_EPISODES], "kept inside the window"
    shown = ask_sources.gather_search(bank, question, found)
    assert any("settled at 720" in e.text for e in shown), "the outcome reaches the model"
    assert any("listing price" in e.text for e in shown), "beside the earlier value, as history"
    _, model = _ask(bank, question)
    other = model.prompts[0].split("OTHER CONVERSATIONS", 1)[1]
    assert other.index("listing price") < other.index("settled at 720"), "oldest first: the last line is the latest"
    assert "the later one carries what happened after the earlier" in ask_service.ASK_SYSTEM_PROMPT


def test_a_plain_question_keeps_the_newest_conversation_on_its_subject_too(bank):
    _bike_bank(bank)
    found = ask_sources.search(bank, "How much is the gravel bike?")
    assert found.shape == ask_sources.SHAPE_LOOKUP
    assert "ep_2025-05-20_001" in found.episodes[:ask_sources.SEARCH_EPISODES]


def test_a_kept_conversation_shows_its_best_turn_before_the_rest_fill_by_score(bank):
    _bike_bank(bank)
    for i in range(3):   # the earlier conversations' second lines outscore the later one's only line
        _episode(bank, f"ep_2025-04-2{i}_001", [f"user: Gravel bike listing price check {i}: price still 900 for the "
                                                "gravel bike, the price is firm."] * 3)
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    found = ask_sources.search(bank, "What was the final price for the gravel bike?")
    shown = ask_sources.gather_search(bank, "What was the final price for the gravel bike?", found)
    assert any(e.episode == "ep_2025-05-20_001" for e in shown), "the newest on the subject is never crowded out"


def test_a_day_the_question_names_is_never_pushed_out_by_a_later_one(bank):
    _bike_bank(bank)
    question = "What did the seller say about the gravel bike price on 9 April 2025?"
    assert ask_sources.question_shape(question) == ask_sources.SHAPE_ANCHORED
    found = ask_sources.search(bank, question)
    assert found.kept == {"ep_2025-04-09_001": "named"}, "the named day, and no newest-on-the-subject slot"
    assert "ep_2025-04-09_001" in found.episodes[:ask_sources.SEARCH_EPISODES]


def test_a_question_about_the_first_time_gets_no_later_conversation_slot(bank):
    _bike_bank(bank)
    found = ask_sources.search(bank, "What was the price of the gravel bike when I first saw it?")
    assert found.shape == ask_sources.SHAPE_ANCHORED and "latest" not in found.kept.values()


def test_the_page_legs_evidence_stays_in_front_of_the_model(bank):
    """A question a page's claim answers from an older conversation keeps that evidence word for word, before the
    leg's lines; the leg never repeats it, and a question about the first time gets no later-conversation slot."""
    from api.services.claims import Claim, Evidence, write_claims

    _bike_bank(bank)
    old = "ep_2025-04-02_001"
    body = evidence.source_text(bank, old)
    quote = "The listing price for the gravel bike is 900"
    at = body.index(quote)
    span = Evidence(episode=old, start=at, end=at + len(quote), kind="user", hash=evidence.body_hash(body))
    page = write_claims("## Summary\nA bike the person looked at.\n", [Claim(
        id="clm_2025-04-02_bike", text="The gravel bike was listed at 900", subject="gravel-bike",
        predicate="listed-at", object="900", valid_from="2025-04-02", recorded_at="2025-04-02",
        source_episodes=[old], evidence=[span])])
    markdown_parser.write(bank / "entities" / "gravel-bike.md",
                          {"name": "Gravel Bike", "type": "concept", "status": "active", "source_episodes": [old]},
                          page)
    bank_index.invalidate()
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    _, model = _ask(bank, "What was the gravel bike listed at the first time?", pages=("gravel-bike",))
    prompt = model.prompts[0]
    assert "WHAT WAS SAID" in prompt
    said = prompt.split("WHAT WAS SAID", 1)[1].split("OTHER CONVERSATIONS", 1)[0]
    other = prompt.split("OTHER CONVERSATIONS", 1)[1] if "OTHER CONVERSATIONS" in prompt else ""
    assert quote in said
    assert f"[{old}], Alice Example (the person this memory belongs to): \"{quote}" not in other, "never twice"
    assert prompt.index("WHAT WAS SAID") < (prompt.index("OTHER CONVERSATIONS") if other else len(prompt))


def test_a_count_reads_every_conversation_on_its_subject_one_line_each(bank):
    days = ["2025-02-03", "2025-02-17", "2025-03-02", "2025-03-16", "2025-04-06", "2025-04-20", "2025-05-04"]
    for day in days:
        _episode(bank, f"ep_{day}_002", [f"user: Went bouldering at the climbing gym today ({day}), sent a new problem.",
                                         "assistant: Nice progress at the climbing gym! " + "Keep resting well. " * 20])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    question = "How many times did I go to the climbing gym?"
    assert ask_sources.question_shape(question) == ask_sources.SHAPE_ENUMERATE
    found = ask_sources.search(bank, question)
    shown = ask_sources.gather_search(bank, question, found)
    assert {e.episode for e in shown} == {f"ep_{d}_002" for d in days}, "all seven, past the plain four"
    assert {e.episode for e in shown if "Went bouldering" in e.text} == {f"ep_{d}_002" for d in days}, \
        "each conversation's own best line"
    depth = [e for e in shown if e.episode in found.episodes[:ask_sources.SEARCH_EPISODES]]
    breadth = [e for e in shown if e not in depth]
    assert len(breadth) >= len(found.more) == 3 and all(len(e.text) <= ask_sources.ENUM_EXCERPT_CHARS for e in breadth)
    assert sum(len(e.text) for e in breadth) <= ask_sources.ENUM_CHARS
    assert sum(len(e.text) for e in depth) <= ask_sources.SEARCH_CHARS, "the plain leg's four, read as for any question"
    _, model = _ask(bank, question)
    assert "asks for a count or a list" in model.prompts[0] and "Count each distinct event once" in model.prompts[0]


def test_question_shapes_and_named_days():
    from datetime import date

    shape = ask_sources.question_shape
    assert shape("How many projects have I led?") == ask_sources.SHAPE_ENUMERATE
    assert shape("Which books have I read this year?") == ask_sources.SHAPE_ENUMERATE
    assert shape("What activities does bob-example partake in?") == ask_sources.SHAPE_ENUMERATE
    assert shape("Where did I end up moving?") == ask_sources.SHAPE_LATEST
    assert shape("What is my current personal best?") == ask_sources.SHAPE_LATEST
    assert shape("What did I decide on March 3?") == ask_sources.SHAPE_ANCHORED
    assert shape("What did bob-example say originally about the plan?") == ask_sources.SHAPE_ANCHORED
    assert shape("Which database did I choose for alpha-project?") == ask_sources.SHAPE_LOOKUP
    named = ask_sources.named_days
    assert named("What happened on 2024-05-08?") == ["2024-05-08"]
    assert named("What did I say on the 8th of May 2023?") == ["2023-05-08"]
    assert named("What did we plan on March 3?") == ["-03-03"]
    assert named("Where was I in June 2024?") == ["2024-06"]
    assert named("What did I eat yesterday?", today=date(2025, 1, 10)) == ["2025-01-09"]
    assert named("What did I do three days ago?", today=date(2025, 1, 10)) == ["2025-01-07"]
    assert named("How was the bike?") == []


def test_a_words_rarity_is_counted_over_conversations_not_watched_days(bank):
    """Thousands of watched days can't make a word look common: counted over every episode, "guitar" (in most of
    them) would rank nothing and the one conversation about it could not be found."""
    from api.services import history_index

    for i in range(30):
        _episode(bank, f"ep_2025-08-{1 + i % 28:02d}_{100 + i:03d}", [f"user: Watched: guitar lesson video {i}"],
                 source=history_index.HISTORY_SOURCE)
    _episode(bank, "ep_2025-09-01_001", ["user: I bought a used guitar from the music store for 300."])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    found = ask_sources.search(bank, "Where did I buy the guitar?")
    assert "guitar" in found.weights
    assert found.episodes[0] == "ep_2025-09-01_001"
    assert not any(ep.startswith("ep_2025-08-") for ep in found.episodes)


# --------------------------------------------------------------------------------------------------------------- #
# The turn that answers, not the turn that matches best (2026-10-19, Ask edges)
# --------------------------------------------------------------------------------------------------------------- #

def test_the_newest_conversation_shows_its_answer_turn_not_its_opening_request(bank):
    """The newest conversation on the subject opens with a request that repeats the question's words; the answer
    is the person's own statement further in, with the value. Before: the request was shown and the value never
    reached the model (one knowledge-update question in the owner's eval)."""
    _episode(bank, "ep_2025-03-01_002", [
        "user: I keep thinking about my recent family trip to Lisbon, the trams were the best part.",
        "assistant: Lisbon's trams are wonderful."])
    for i, day in enumerate(("2025-03-20", "2025-04-11", "2025-05-02")):   # talk about a family trip, no value
        _episode(bank, f"ep_{day}_002", [
            f"user: We talked about a family trip again over dinner, nothing booked yet for the family trip ({i}).",
            "assistant: A family trip takes time to plan; a family trip with kids even more so."])
    _episode(bank, "ep_2025-06-10_002", [
        "user: Can you help me plan a family trip itinerary with kids? A family trip needs slow days.",
        "assistant: Sure: plan one slow day for every two busy ones on a family trip, and book rooms near parks.",
        "user: Thanks. Since I've been thinking about my recent family trip to Kyoto, I want quieter places.",
        "assistant: Quieter places are easy to find."])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    question = "Where did I go on my most recent family trip?"
    found = ask_sources.search(bank, question)
    assert found.kept.get("ep_2025-06-10_002") == "latest"
    shown = ask_sources.gather_search(bank, question, found)
    newest = [e for e in shown if e.episode == "ep_2025-06-10_002"]
    assert any("Kyoto" in e.text for e in newest), "the newest conversation's answer turn is shown"
    assert any("Lisbon" in e.text for e in shown), "the earlier one stays, as history"


def test_a_count_shows_each_conversations_own_statement_over_a_reply_that_repeats_the_words(bank):
    """A count's evidence is the person's statement in each conversation ("my own orange bitters"), which shares
    fewer of the question's words than the agent's long reply about citrus cocktail recipes in the same
    conversation. Each conversation's line is the statement, and each conversation gets one before any gets two."""
    fruits = {"2025-02-02": "orange", "2025-02-09": "lime", "2025-02-16": "grapefruit", "2025-02-23": "lemon",
              "2025-03-02": "yuzu", "2025-03-09": "mandarin"}
    for day, fruit in fruits.items():
        _episode(bank, f"ep_{day}_003", [
            f"user: I made a cocktail recipe last night with fresh {fruit} juice, it was great.",
            "assistant: Citrus fruits make cocktail recipes bright: citrus fruits like lemon, lime, orange and "
            "grapefruit each bring their own acidity to cocktail recipes, and citrus fruit peels add aroma. "
            + "More citrus fruit cocktail recipe ideas follow. " * 6])
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    question = "How many different citrus fruits have I used in my cocktail recipes?"
    found = ask_sources.search(bank, question)
    shown = ask_sources.gather_search(bank, question, found)
    for day, fruit in fruits.items():
        own = [e for e in shown if e.episode == f"ep_{day}_003" and not e.who.startswith("the assistant")]
        assert own and f"fresh {fruit} juice" in own[0].text, f"{day}: the person's own statement is shown"


def test_answer_score_reads_the_speaker_the_value_and_a_question():
    weights = {"trip": 2.0, "family": 1.0}
    pattern = ask_sources.re.compile(r"\b(trip|family)")
    prefs = ask_sources.answer_prefs("Where did I go on my most recent family trip?")
    asks, _ = ask_sources.answer_score("Can you help me plan a family trip?", pattern, weights, "user", prefs)
    states, where = ask_sources.answer_score("Thanks! My recent family trip to Kyoto was calm.", pattern, weights,
                                             "user", prefs)
    assert states > asks and where == len("Thanks! ")
    agent, _ = ask_sources.answer_score("My recent family trip to Kyoto was calm.", pattern, weights, "assistant",
                                        prefs)
    assert states > agent, "the person's own statement over the same words from the agent"
    tag, _ = ask_sources.answer_score("The family trip I took was to Kyoto, have you been?", pattern, weights,
                                      "user", prefs)
    assert tag > asks, "a statement with a tag question still states its value"
    about_agent = ask_sources.answer_prefs("What hotel did you recommend for the family trip?")
    assert about_agent.agent
    mine, _ = ask_sources.answer_score("The family trip hotel is Kyoto Inn.", pattern, weights, "user", about_agent)
    yours, _ = ask_sources.answer_score("The family trip hotel is Kyoto Inn.", pattern, weights, "assistant",
                                        about_agent)
    assert yours > mine, "a question about what the agent said reads the agent's turns first"
    assert ask_sources.answer_score("Nothing here.", pattern, weights, "user", prefs) == (0.0, 0)


def test_a_count_never_takes_an_agents_saved_note_for_the_persons_statement(bank):
    """An episode an agent saved through a tool door (source mcp) opens with its own unmarked note — the agent's
    words, never the person's (`_who`'s rule). A count's line is the speaker's own statement: the person's marked
    turn, not the note, even when the note holds more of the question's words and a value."""
    days = ["2025-02-03", "2025-02-17", "2025-03-02", "2025-03-16", "2025-04-06"]
    for day in days:
        _episode(bank, f"ep_{day}_004", [
            f"Agent note ({day}): the person went to the climbing gym for bouldering, 12 visits to the climbing gym "
            "so far.",
            "user: Went bouldering at the climbing gym today, sent a new problem.",
            "assistant: Nice!"], source="mcp")
    search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    question = "How many times did I go to the climbing gym?"
    found = ask_sources.search(bank, question)
    shown = ask_sources.gather_search(bank, question, found)
    for day in days:
        first = [e for e in shown if e.episode == f"ep_{day}_004"]
        assert first, day
        assert any("Went bouldering" in e.text for e in first), f"{day}: the person's own turn is its line"
    notes = [e for e in shown if e.text.startswith("Agent note")]
    assert all(e.who.startswith("an agent's saved note") for e in notes), "a note shown is labelled the agent's"
    turn = evidence.turns("Agent note: x.\nuser: y.\n")[0]
    assert ask_sources._speaker(turn, {"source": "mcp"}) == ask_sources.AGENT_NOTE
    assert ask_sources._speaker(turn, {"source": "import"}) == "user"
    assert not ask_sources._speaks(ask_sources.AGENT_NOTE, ask_sources.Prefs())


def test_spanish_questions_read_their_shape_who_they_ask_about_and_what_only_asks():
    shape = ask_sources.question_shape
    assert shape("¿Cuántas veces fui al gimnasio de escalada?") == ask_sources.SHAPE_ENUMERATE
    assert shape("¿Cuántos libros he leído este año?") == ask_sources.SHAPE_ENUMERATE
    assert shape("¿Cuáles proyectos he terminado?") == ask_sources.SHAPE_ENUMERATE
    assert shape("Dame la lista de restaurantes que probé") == ask_sources.SHAPE_ENUMERATE
    assert shape("Enumera los viajes que hice con mi familia") == ask_sources.SHAPE_ENUMERATE
    assert shape("¿Qué base de datos elegí para alpha-project?") == ask_sources.SHAPE_LOOKUP
    for q in ("¿Qué hotel me recomendaste en Lisboa?", "¿Cómo se llamaba el libro que sugeriste?",
              "Recuérdame lo que me dijiste sobre la bici", "¿Cuál fue tu recomendación para el viaje?"):
        assert ask_sources.answer_prefs(q).agent, q
    assert not ask_sources.answer_prefs("¿Qué hotel reservé en Lisboa?").agent
    assert ask_sources._asks("¿Me puedes ayudar a planear un viaje en familia?")
    assert ask_sources._asks("Qué hotel reservé en Lisboa?")
    assert not ask_sources._asks("El viaje en familia fue a Kioto, ¿sabes?"), "a tag still states its value"
    assert not ask_sources._asks("Nuestro último viaje en familia fue a Kioto.")
