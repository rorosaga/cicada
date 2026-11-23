"""G148: Ask's meaning leg in every language, filling only the room the prompt has. Unslept LoCoMo 123 → 138 of 200,
slept 159 → 159, the wrong person's memory 15 → 15. Recall stays on the words: these lines cost it 128 → 114."""
from __future__ import annotations

from api.services import ask_service, ask_sources, markdown_parser, search_index
from test_ask_infer_es import _Indexer, _prompt, bank  # noqa: F401 — the fixture

ENGLISH = "When did Alice go to the support group?"


def _found(**kw):
    return ask_sources.Searched(episodes=[], weights={}, **kw)


def test_the_budget_is_what_the_prompt_has_left():
    budget = ask_sources._meaning_budget
    assert budget(ENGLISH, _found(), 6000, 0) == (ask_sources.MEANING_FILL_CHARS // ask_sources.MEANING_LINE_CHARS,
                                                  ask_sources.MEANING_FILL_CHARS)
    assert budget(ENGLISH, _found(), 6000, 4500) == (3, 1500)


def test_a_full_prompt_adds_nothing_to_an_english_question():
    assert ask_sources._meaning_budget(ENGLISH, _found(), 6000, 6000) == (0, 0)
    assert ask_sources._meaning_budget(ENGLISH, _found(), -9000, 0) == (0, 0), "a window the lines themselves overfilled"


def test_another_language_keeps_its_few_lines_when_the_prompt_is_full():
    fixed = (ask_sources.MEANING_EXTRA_EXCERPTS, ask_sources.MEANING_EXTRA_CHARS)
    assert ask_sources._meaning_budget("¿Cuándo fue Alice al grupo?", _found(), -9000, 0) == fixed


def test_a_request_for_advice_keeps_its_own_budget():
    found = _found(advice=True)
    assert ask_sources._meaning_budget(ENGLISH, found, 0, 0) == (ask_sources.ADVICE_EXTRA_EXCERPTS,
                                                                 ask_sources.ADVICE_EXTRA_CHARS)


def test_a_caller_with_no_room_stays_on_the_fixed_lines():
    fixed = (ask_sources.MEANING_EXTRA_EXCERPTS, ask_sources.MEANING_EXTRA_CHARS)
    assert ask_sources._meaning_budget(ENGLISH, _found(), None, 0) == fixed


def test_only_ask_asks_for_an_english_question_by_meaning(bank):
    assert not ask_sources.search(bank, ENGLISH, indexer=_Indexer(bank)).adds, "recall's call, the default, is unchanged"
    found = ask_sources.search(bank, ENGLISH, indexer=_Indexer(bank), any_language=True)
    assert found.adds and not found.meaning, "the words lead, meaning adds"


def test_ask_calls_the_search_with_any_language(bank, monkeypatch):
    seen = {}
    real = ask_sources.search

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(ask_sources, "search", spy)
    ask_service.answer_query(bank, ENGLISH, top_k=6, llm_fn=lambda p: '{"answer": "x", "confidence": 0.5}', no_engine=False)
    assert seen.get("any_language") is True


# 2026-11-23: a slept memory's pages alone are over the window, so a room counted against the whole prompt was always
# negative and the meaning leg added nothing there; a question whose answer is several conversations' lines (none of
# them sharing the question's words) was left with the page lines alone.

def _big_pages(memory, n: int = 4, chars: int = 6000) -> list[str]:
    ids = []
    for k in range(n):
        filler = "\n".join(f"- Alice detail {i} about the support group and her week, as of May 2023." for i in range(chars // 80))
        ids.append(f"alice-page-{k}")
        markdown_parser.write(memory / "entities" / f"{ids[-1]}.md",
                              {"name": f"Alice Page {k}", "type": "concept", "status": "active"},
                              f"## Summary\nAlice's errands, part {k}.\n\n## Article\n{filler}\n")
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    return ids


def test_ask_counts_only_lines_against_the_window_never_the_pages(bank, monkeypatch):
    pages = _big_pages(bank)
    seen = {}
    real = ask_sources.gather_search

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(ask_sources, "gather_search", spy)
    prompt = _prompt(bank, "What did Alice do at the support group?", pages=pages, indexer=_Indexer(bank))
    assert prompt.index("OTHER CONVERSATIONS") > 3000, "the pages took real room in the prompt"
    assert seen["meaning_room"] == ask_sources.ASK_WINDOW_CHARS, "no page line was shown: the whole window is the lines'"


def test_the_room_is_the_window_less_the_lines_shown():
    one = ask_sources.Excerpt(episode="ep_2023-01-01_001", day="2023-01-01", who="x", text="a" * 700, order=("", "", 0))
    assert ask_sources.lines_chars([one, one]) == 1400
    assert ask_sources.lines_chars([]) == 0


def test_ask_reads_more_conversations_by_meaning_than_recall(bank):
    eps = [f"ep_2023-0{i}-01_001" for i in range(1, 9)] + ["ep_2023-05-08_001"]
    passages = {ep: [markdown_parser.parse(bank / "episodes" / f"{ep}.md").body.strip()] for ep in eps}
    found = ask_sources.Searched(episodes=eps, weights={}, passages=passages, adds=True)
    default = {c[3] for c in ask_sources._meaning_turns(bank, found, {}, set())}
    ask = {c[3] for c in ask_sources._meaning_turns(bank, found, {}, set(), episodes=ask_sources.ASK_MEANING_EPISODES)}
    assert len(default) == ask_sources.MEANING_EPISODES, "recall and the language legs keep their four"
    assert len(ask) == min(ask_sources.ASK_MEANING_EPISODES, len(eps))
    assert ask_sources.window_limits()["meaning_episodes"] == ask_sources.ASK_MEANING_EPISODES
