"""`entity_article.fit` always ends, and what it returns fits when it can (2026-11-26).

A night's run spun for hours at 100% CPU on the event loop: the backend answered nothing. `fit` trims a page's inputs
until the writer's prompt fits its budget, and it added the prompt up a second way that left out the rules a page
with CORRECTIONS or SAME_PAGE gets. A page over the budget by less than those rules was "still over" for `prompt` and
"not over" for `fit`, so no input was ever left out again and the loop never ended. Synthetic inputs only."""
from __future__ import annotations

import threading

import pytest

from api.services import entity_article as article
from api.services.entity_article import Inputs, Source


def _inputs(*, claims: int = 400, history: int = 40, extra: dict | None = None) -> Inputs:
    sources = [Source("f1", "fact", "alpha-project ships in spring."),
               Source("s1", "said", "They said the launch moved to the autumn.", ["2026-03-02"])]
    for n in range(claims):
        sources.append(Source(f"c{n}", "claim", f"Worked on task number {n} of alpha-project with bob-example.",
                              [f"2026-01-{1 + n % 28:02d}"], [], False, (f"worked_on_{n % 7}", f"task-{n}"), 1 + n % 3))
    for n in range(history):
        sources.append(Source(f"h{n}", "history", f"History line {n}: something dated happened.",
                              [f"2025-{1 + n % 12:02d}-01"]))
    data = {"OWNER": "alex-example", "NAME": "alex-example", "TYPE": "person",
            "LINKABLE": ["alpha-project", "bob-example"],
            "INPUT": [article._item(s) for s in sources], **(extra or {})}
    return Inputs(sources, data)


def _fit(inputs: Inputs, max_chars: int, seconds: float = 20.0) -> Inputs:
    """`fit`, failing instead of hanging: the defect was a loop that never returned."""
    out: list[Inputs] = []
    worker = threading.Thread(target=lambda: out.append(article.fit(inputs, max_chars=max_chars)), daemon=True)
    worker.start()
    worker.join(seconds)
    assert out, f"fit did not return in {seconds:.0f}s at max_chars={max_chars}: the loop does not end"
    return out[0]


SAME_PAGE = {"SAME_PAGE": [{"as": "Alfa Project", "is": "alpha-project"}]}
CORRECTIONS = {"CORRECTIONS": [{"with": "autumn", "never": "spring"}]}


@pytest.mark.parametrize("extra", [SAME_PAGE, CORRECTIONS, {**SAME_PAGE, **CORRECTIONS}, {}],
                         ids=["same_page", "corrections", "both", "neither"])
def test_a_page_over_the_budget_is_trimmed_until_its_prompt_fits(extra):
    inputs = _inputs(extra=extra)
    whole = len(article._text(inputs))
    budget = whole // 2
    assert article.prompt(inputs, max_chars=budget) is None          # the page needs trimming
    trimmed = _fit(inputs, budget)
    assert article.prompt(trimmed, max_chars=budget) is not None     # and what comes back fits
    kept = {s.id for s in trimmed.sources}
    assert {"f1", "s1"} <= kept                                      # this update's words and facts are never left out
    assert len(kept) < len(inputs.sources)


def test_it_ends_at_every_budget_near_the_one_that_spun():
    """The loop spun when the page was over by less than the extra rules' length: every budget in that band, and well
    on both sides of it, ends and fits."""
    inputs = _inputs(claims=120, history=10, extra={**SAME_PAGE, **CORRECTIONS})
    rules = len(article._SAME_PAGE_RULE) + len(article._CORRECTIONS_RULE)
    middle = len(article._text(inputs)) * 2 // 3
    for budget in range(middle - rules - 40, middle + rules + 40, 3):
        trimmed = _fit(inputs, budget, seconds=10)
        assert article.prompt(trimmed, max_chars=budget) is not None, budget


def test_what_can_never_be_left_out_ends_too():
    """Over the budget with every claim and History line gone: it returns what is left (and `prompt` refuses it)."""
    inputs = _inputs(claims=30, history=5, extra=SAME_PAGE)
    trimmed = _fit(inputs, 200)
    assert {s.kind for s in trimmed.sources} <= {"fact", "said"}
    assert article.prompt(trimmed, max_chars=200) is None


def test_a_large_page_is_measured_a_handful_of_times(monkeypatch):
    """The whole prompt is put together once per pass, and the passes stay few: a hub page (thousands of claims) is
    trimmed on the event loop, so a pass per input left out would freeze the backend for minutes."""
    inputs = _inputs(claims=3_000, history=200, extra={**SAME_PAGE, **CORRECTIONS})
    budget = len(article._text(inputs)) // 5
    calls = 0
    real = article._text

    def counted(value):
        nonlocal calls
        calls += 1
        return real(value)

    monkeypatch.setattr(article, "_text", counted)
    trimmed = _fit(inputs, budget, seconds=60)
    assert len(real(trimmed)) <= budget
    assert calls <= 8, f"{calls} whole-prompt measurements for one page"
