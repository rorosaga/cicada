"""Ask: a question about two moments needs both ends in front of the model (2026-10-20, G148).

The owner's hard set: 0 of 7 temporal questions right — "when I first … and by the time I later …" found the first
conversation and not the later one; "between <month> and <month>" got one end and an adjacent conversation for the
other; "how many days between A and B" came back one day off, or as a range. One search over the whole question ranks
the conversation holding most of its words first, and that is one end. Each end is now searched for on its own words,
kept in the window (on its own named month or day), leads with its own best turns, and the prompt carries the days and
the gap computed from the conversations' dates. Synthetic banks only (alpha-project, bob-example); the word index
alone (no vector index, no network); the model is a stub that records its prompt.
"""
from __future__ import annotations

import json
import re

import pytest

from api.services import ask_service, ask_sources, bank_index, evidence, markdown_parser, search_index


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
    # Filler, so a subject's words are rare across the bank's conversations.
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


def _prompt(memory, question: str) -> str:
    model = _Model()
    ask_service.answer_query(memory, question, retrieve_fn=lambda q, k: [], llm_fn=model, no_engine=False)
    [prompt] = model.prompts
    return prompt


def _window(found) -> set[str]:
    return set(found.episodes[:ask_sources.SEARCH_EPISODES])


# --------------------------------------------------------------------------------------------------------------- #
# The forms
# --------------------------------------------------------------------------------------------------------------- #

def test_the_forms_that_name_two_moments():
    two = ask_sources.two_ends

    def halves(q):
        found = two(q)
        assert found is not None, q
        return [e.text for e in found.ends]

    assert halves("When I first asked about the garden robot, what did I want, and what had changed by the time I "
                  "later said I'd put tracks on it?")[1].startswith("by the time i later said")
    assert halves("How many days passed between the day I sold the bike and the day I bought the kayak?") == [
        "i sold the bike", "i bought the kayak"]
    assert halves("Which happened first, the alpha-project launch or the move to the new office?") == [
        "the alpha-project launch", "the move to the new office"]
    assert halves("How many days had passed since I finished the pottery course when I signed up for "
                  "the glazing class?") == ["i finished the pottery course", "i signed up for the glazing class"]
    assert halves("What is the order of the three events: 'I sold the bike', 'I bought the kayak' and "
                  "'I joined the rowing club'?") == ["i sold the bike", "i bought the kayak", "i joined the rowing club"]
    # Spanish, folded (no accents needed in the bank's words).
    assert halves("¿Cuántos días pasaron entre la mudanza del estudio y la primera clase de cerámica?") == [
        "la mudanza del estudio", "la primera clase de ceramica"]
    assert halves("¿Cómo pasó mi idea de la tienda de ser una web sencilla a ser una aplicación móvil, y cuánto "
                  "tiempo pasó entre esas dos conversaciones?") == ["una web sencilla", "una aplicacion movil"]
    split = two("¿Qué me dijeron sobre el contrato en marzo, y cómo había cambiado mi planteamiento a finales de "
                "julio?")
    assert [e.days for e in split.ends] == [["-03"], ["-07"]], "a month named alone is that end's month"
    split = two("¿Cómo cambió mi forma de abordar la meditación entre octubre de 2024 y abril de 2025, y cuántos "
                "días pasaron?")
    assert [e.days for e in split.ends] == [["2024-10"], ["2025-04"]]
    pair = two("I came across stoicism in two conversations about 47 days apart. What did each tell me?")
    assert pair.pair and pair.apart_days == 47
    assert two("¿Qué pensaba del huerto al principio y qué dije cuando volví a hablar de él?") is not None

    # Not two moments: a count stays a count, a comparison without time stays a lookup, one moment stays one.
    for q in ("How many times did I go to the gym between March and July?",
              "What is the difference between my old and new laptop?",
              "How many days ago did I buy a smoker?",
              "What was the price of the gravel bike when I first saw it?",
              "Which database did I choose for alpha-project?",
              "When did bob-example go to the support group?"):
        assert two(q) is None, q
    assert ask_sources.question_shape("How many times did I go to the gym between March and July?") == \
        ask_sources.SHAPE_ENUMERATE
    assert ask_sources.question_shape("How many days passed between the day I sold the bike and the day I bought "
                                      "the kayak?") == ask_sources.SHAPE_TWO_ENDS


def test_spanish_dates_are_named_days():
    named = ask_sources.named_days
    assert named("¿Qué decidí el 5 de marzo de 2025?") == ["2025-03-05"]
    assert named("¿Qué pasó en octubre de 2024?") == ["2024-10"]
    assert named("¿Qué dije el 8 de mayo?") == ["-05-08"]


# --------------------------------------------------------------------------------------------------------------- #
# Both ends reach the model
# --------------------------------------------------------------------------------------------------------------- #

def _robot_bank(memory) -> None:
    """Six early conversations full of the question's first-half words, then the later one that says the change in
    few of them."""
    for d in ("2024-03-02", "2024-03-05", "2024-03-09", "2024-03-12", "2024-03-16", "2024-03-20"):
        _episode(memory, f"ep_{d}_001", [
            f"user: About the garden robot: I want wheels and ultrasonic sensors, and I asked about wheels again ({d}).",
            "assistant: Wheels with ultrasonic sensors suit a garden robot on flat paths; wheels are simplest."])
    _episode(memory, "ep_2024-07-21_001", ["user: Update: I'll put tracks on it instead, the lawn is too muddy.",
                                           "assistant: Tracks will cope with mud much better."])
    _index(memory)


ROBOT_Q = ("When I first asked about the garden robot's wheels and ultrasonic sensors, what did I want, and how had it "
           "changed by the time I later said I'd put tracks on it?")


def test_the_later_end_reaches_the_model_beside_the_first(bank):
    _robot_bank(bank)
    found = ask_sources.search(bank, ROBOT_Q)
    assert found.shape == ask_sources.SHAPE_TWO_ENDS
    assert "ep_2024-07-21_001" in _window(found), "the later conversation is kept for its end"
    assert any(ep.startswith("ep_2024-03") for ep in _window(found)), "beside the first"
    shown = ask_sources.gather_search(bank, ROBOT_Q, found)
    assert any("put tracks on it" in e.text for e in shown), "its own turn, by the end's own words"
    prompt = _prompt(bank, ROBOT_Q)
    other = prompt.split("OTHER CONVERSATIONS", 1)[1]
    assert "I'll put tracks on it instead" in other


def _meditation_bank(memory) -> None:
    """A subject on six days; the question names two months, and the strongest conversations are on neither."""
    for d, words in (("2024-09-28", "meditation breathing practice, counting breaths, meditation timer"),
                     ("2024-10-15", "meditation in the morning, ten minutes"),
                     ("2024-11-02", "meditation breathing practice and a meditation app for breathing"),
                     ("2025-03-30", "meditation breathing practice with a meditation teacher, breathing drills"),
                     ("2025-04-12", "meditation walking outside, no timer"),
                     ("2025-04-25", "meditation breathing practice, meditation retreat, breathing workshop")):
        _episode(memory, f"ep_{d}_001", [f"user: Mi práctica de meditación: {words}.",
                                         "assistant: Bien, sigue así."])
    _index(memory)


def test_each_end_is_its_own_named_month(bank):
    _meditation_bank(bank)
    q = "¿Cómo cambió mi forma de abordar la meditación entre octubre de 2024 y abril de 2025, y cuántos días pasaron?"
    found = ask_sources.search(bank, q)
    assert [p.episode for p in found.ends] == ["ep_2024-10-15_001", "ep_2025-04-12_001"]
    assert {"ep_2024-10-15_001", "ep_2025-04-12_001"} <= _window(found)
    prompt = _prompt(bank, q)
    timing = prompt.split("TIME BETWEEN THE CONVERSATIONS", 1)[1]
    # 2024-10-15 → 2025-04-12 = 179 days, computed, never a range.
    assert "said 2025-04-12 — 179 days (= 25 weeks 4 days" in timing
    assert re.search(r"\[ep_2024-10-15_001\], said 2024-10-15", timing)


def _move_bank(memory) -> None:
    """Shape 5 of the hard set: the second end's own conversation, and an adjacent day that shares more words."""
    _episode(memory, "ep_2025-01-10_001", ["user: Hoy terminé la mudanza del estudio, todo en cajas.",
                                           "assistant: ¡Enhorabuena por la mudanza!"])
    _episode(memory, "ep_2025-01-26_001", ["user: Mañana empiezo la clase de cerámica en el estudio nuevo, "
                                           "después de la mudanza del estudio todo cambia.",
                                           "assistant: Qué bien, disfruta la clase."])
    _episode(memory, "ep_2025-01-27_001", ["user: Primera clase de cerámica hecha: torno y barro.",
                                           "assistant: ¡Qué buena primera clase!"])
    _index(memory)


def test_the_gap_between_the_ends_is_computed_exactly(bank):
    _move_bank(bank)
    q = "¿Cuántos días pasaron entre la mudanza del estudio y la primera clase de cerámica?"
    found = ask_sources.search(bank, q)
    assert [p.episode for p in found.ends] == ["ep_2025-01-10_001", "ep_2025-01-27_001"]
    prompt = _prompt(bank, q)
    timing = prompt.split("TIME BETWEEN THE CONVERSATIONS", 1)[1]
    assert "- 2025-01-10 = day 0" in timing and "- 2025-01-27 = day 17" in timing
    assert "said 2025-01-27 — 17 days (= 2 weeks 3 days" in timing


def test_two_conversations_n_days_apart_are_the_pair_that_far_apart(bank):
    for d in ("2024-05-01", "2024-05-20", "2024-06-17", "2024-08-01"):
        _episode(bank, f"ep_{d}_001", [f"user: Reading about stoicism today ({d}): the dichotomy of control.",
                                       "assistant: Stoicism separates what you control from what you don't."])
    _index(bank)
    found = ask_sources.search(bank, "I came across stoicism in two conversations about 47 days apart. What did each "
                                     "tell me?")
    assert [p.episode for p in found.ends] == ["ep_2024-05-01_001", "ep_2024-06-17_001"]
    shown = ask_sources.gather_search(bank, "stoicism two conversations 47 days apart", found)
    assert {e.episode for e in shown} >= {"ep_2024-05-01_001", "ep_2024-06-17_001"}, "both ends have their words"


def test_three_listed_events_each_keep_their_conversation(bank):
    _episode(bank, "ep_2024-02-03_001", ["user: I sold the bike to a neighbour today.", "assistant: Nice."])
    _episode(bank, "ep_2024-02-11_001", ["user: Bought the kayak at last!", "assistant: Enjoy the water."])
    _episode(bank, "ep_2024-03-02_001", ["user: Joined the rowing club this morning.", "assistant: Great."])
    for i in range(4):   # conversations that hold more of the whole question's words than any one end
        _episode(bank, f"ep_2024-04-0{i + 1}_001", [f"user: Kayak versus bike versus rowing club, option {i}: the "
                                                    "kayak, the bike and the rowing club all compete for weekends.",
                                                    "assistant: Pick one."])
    _index(bank)
    q = "What is the order of the three events: 'I sold the bike', 'I bought the kayak' and 'I joined the rowing club'?"
    found = ask_sources.search(bank, q)
    assert [p.episode for p in found.ends] == ["ep_2024-02-03_001", "ep_2024-02-11_001", "ep_2024-03-02_001"]
    assert {p.episode for p in found.ends} <= _window(found)


# --------------------------------------------------------------------------------------------------------------- #
# The time block is there only when time is asked
# --------------------------------------------------------------------------------------------------------------- #

def test_a_question_that_is_not_about_time_gets_no_time_block(bank):
    _robot_bank(bank)
    prompt = _prompt(bank, "What sensors does the garden robot use?")
    assert "TIME BETWEEN THE CONVERSATIONS" not in prompt


def test_how_long_ago_gets_the_days_numbered_with_today(bank, monkeypatch):
    from datetime import date

    _move_bank(bank)
    monkeypatch.setattr(ask_service, "current_day", lambda: date(2025, 2, 6))
    prompt = _prompt(bank, "¿Hace cuántos días fue la primera clase de cerámica?")
    timing = prompt.split("TIME BETWEEN THE CONVERSATIONS", 1)[1]
    assert "- 2025-02-06 (the current local day) = day" in timing
    assert "The question asks about more than one moment" not in timing, "one moment: no ends"


def test_only_elapsed_time_is_a_time_question():
    elapsed = ask_sources.asks_elapsed
    assert elapsed("How many weeks ago did I start the pottery course?")
    assert elapsed("How many months have passed since I last visited a museum?")
    assert elapsed("How long ago was bob-example's birthday?")
    assert elapsed("¿Hace cuántos días fue la primera clase de cerámica?")
    assert not elapsed("How long is my daily commute?"), "a length, not time passed"
    assert not elapsed("How many days did I spend on the camping trip?")
    assert not elapsed("What hobby did bob-example start a few years ago?"), "not a question of how long"


# --------------------------------------------------------------------------------------------------------------- #
# Review of #379: ordinary questions stay ordinary; the local day; a session that ran over several days
# --------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("question", [
    "What did I say on March 5 about switching from vim to emacs?",
    "What's my latest decision about moving from Madrid to Lisbon?",
    "When did I move from Madrid to Lisbon?",
    "What's the time difference between Madrid and Lima that I noted?",
    "¿Cuál es la diferencia de tiempo entre Madrid y Lima?",
    "How long is the flight between Lima and Madrid?",
    "Which train did I take between Madrid and Barcelona last time?",
    "What should I do first, the taxes or the report?",
    "What's the difference between my first and second car?",
    "Which did I prefer, the first draft or the second?",
    "First and foremost, how long have I been vegan, and later what did I add?",
    "Primero que nada, ¿qué cambió en alpha-project después del lanzamiento?",
    "¿Cuántas veces fui al gimnasio entre marzo y julio?",
    "¿Cuántos libros leí entre marzo y julio?",
    "What do I like to do in May and June?",
    "Did I prefer coffee or tea at first?",
    "Just between you and me, has my opinion of the new manager changed?",
])
def test_ordinary_questions_are_not_two_ends(question):
    assert ask_sources.two_ends(question) is None
    assert ask_sources.question_shape(question) != ask_sources.SHAPE_TWO_ENDS


def _editor_bank(memory) -> None:
    for d in ("2025-01-10", "2025-01-20", "2025-02-02", "2025-02-14", "2025-02-25", "2025-03-20", "2025-04-02"):
        _episode(memory, f"ep_{d}_001", [f"user: I keep thinking about switching from vim to emacs; emacs org-mode vs "
                                         f"vim modal editing, vim plugins, emacs lisp ({d}).",
                                         "assistant: Switching from vim to emacs: evil-mode keeps vim keys inside emacs."])
    _episode(memory, "ep_2025-03-05_001", ["user: Decision on editors: I'm staying with vim, not switching.",
                                           "assistant: Noted, vim it is."])
    _index(memory)


def test_a_named_day_phrased_from_a_to_b_keeps_its_day(bank):
    _editor_bank(bank)
    q = "What did I say on March 5 about switching from vim to emacs?"
    found = ask_sources.search(bank, q)
    assert found.shape == ask_sources.SHAPE_ANCHORED and found.kept == {"ep_2025-03-05_001": "named"}
    assert any(e.episode == "ep_2025-03-05_001" for e in ask_sources.gather_search(bank, q, found))


def test_the_newest_phrased_from_a_to_b_stays_the_newest(bank):
    for d in ("2025-01-10", "2025-01-20", "2025-02-02", "2025-02-14", "2025-02-25", "2025-03-20", "2025-04-02"):
        _episode(bank, f"ep_{d}_001", [f"user: Thinking about moving from Madrid to Lisbon: Lisbon rent, Madrid job, "
                                       f"moving costs, Lisbon weather ({d}).",
                                       "assistant: Moving from Madrid to Lisbon could lower rent; Lisbon is sunny."])
    _episode(bank, "ep_2025-06-01_001", ["user: Final call on the move: I'm staying in Madrid after all, not moving.",
                                         "assistant: Understood, staying put."])
    _index(bank)
    q = "What's my latest decision about moving from Madrid to Lisbon?"
    found = ask_sources.search(bank, q)
    assert found.shape == ask_sources.SHAPE_LATEST and found.kept.get("ep_2025-06-01_001") == "latest"


def test_a_two_ends_question_keeps_a_named_day_and_the_newest_too(bank):
    _editor_bank(bank)
    _episode(bank, "ep_2025-05-01_001", ["user: Final editor decision: vim stays, emacs is out for good.",
                                         "assistant: Final answer noted."])
    _index(bank)
    q = ("How had my thinking on vim and emacs changed between the org-mode chats and the evil-mode chats, what did I "
         "say on March 5, and what is my final decision?")
    found = ask_sources.search(bank, q)
    assert found.shape == ask_sources.SHAPE_TWO_ENDS and found.ends
    assert found.kept.get("ep_2025-03-05_001") == "named", "a day outside every end is still that day's"
    assert "latest" in found.kept.values(), "an outcome still keeps the newest on the subject"
    assert set(found.kept) <= set(found.episodes[:max(ask_sources.SEARCH_EPISODES, len(found.kept) + 1)])


def test_days_are_local_days_never_the_utc_slice(bank, monkeypatch):
    """Said at 01:30 in Madrid on 20 October is stored as 19 October 23:30 UTC; asked the same local day, it is
    day 0 and today, never "yesterday"."""
    import time
    from datetime import date

    monkeypatch.setenv("TZ", "Europe/Madrid")
    time.tzset()
    try:
        body = ["user: Just booked the pottery workshop for next month.", "assistant: Nice, enjoy the pottery workshop."]
        _episode(bank, "ep_2026-10-19_001", body, timestamp="2026-10-19T23:30:00+00:00",
                 turns=[{"offset": 0, "ts": "2026-10-19T23:30:00+00:00", "speaker": None},
                        {"offset": len(body[0]) + 1, "ts": "2026-10-19T23:30:05+00:00", "speaker": None}])
        _index(bank)
        monkeypatch.setattr(ask_service, "current_day", lambda: date(2026, 10, 20))
        timing = _prompt(bank, "How many days ago did I book the pottery workshop?").split(
            "TIME BETWEEN THE CONVERSATIONS", 1)[1]
        assert "- 2026-10-20 = day 0 (lines dated 2026-10-19 above: their stored UTC date)" in timing
        assert "- 2026-10-19 = day" not in timing, "never numbered as the day before"
        assert "- 2026-10-20 (the current local day) = day 0" in timing
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_a_session_over_several_days_dates_each_end_by_its_own_turn(bank):
    turns = ["user: Started the sourdough starter today, feeding it flour and water.",
             "assistant: Keep the sourdough starter warm.",
             "user: Baked my first loaf from the sourdough starter at last, crusty and open crumb!",
             "assistant: Congratulations on the loaf."]
    stamps = ["2025-01-01T09:00:00+00:00", "2025-01-01T09:01:00+00:00", "2025-01-10T09:00:00+00:00",
              "2025-01-10T09:01:00+00:00"]
    offsets, at = [], 0
    for t in turns:
        offsets.append(at)
        at += len(t) + 1
    _episode(bank, "ep_2025-01-01_001", turns,
             turns=[{"offset": o, "ts": s, "speaker": None} for o, s in zip(offsets, stamps)])
    _episode(bank, "ep_2024-12-20_001", ["user: Thinking of making a sourdough starter soon.", "assistant: Sure."])
    _index(bank)
    q = "How many days passed between the day I started the sourdough starter and the day I baked my first loaf?"
    found = ask_sources.search(bank, q)
    assert [p.episode for p in found.ends] == ["ep_2025-01-01_001", "ep_2025-01-01_001"], \
        "one conversation holds both moments in different turns: shared, not a weaker one for the second"
    timing = _prompt(bank, q).split("TIME BETWEEN THE CONVERSATIONS", 1)[1]
    assert "- 2025-01-01 = day" in timing and "- 2025-01-10 = day" in timing, "every day a shown turn was said"
    assert "said 2025-01-01" in timing and "said 2025-01-10 — 9 days (= 1 week 2 days" in timing
