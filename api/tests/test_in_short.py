"""In short (ruling 48 part 5): Sleep's 2–3 sentences for a long page the person talks about often.

Bank facts only (≥ 400 words of article, ≥ 5 conversations in 30 days), at most 10 a run, only when the article
changed, on the person's engine's small tier; stored as a derived frontmatter field the card and every agent read.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from api.services import engine_errors, in_short, markdown_parser, page_blocks
from api.services.claims import Claim, write_claims

TODAY = date(2026, 10, 28)


def _episode(memory, ep_id, **fm):
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", {"source": "claude-code", **fm}, "user: hi\n")


def _eps(memory, n, *, start=1, days_ago=2, **fm):
    ids = []
    for i in range(start, start + n):
        day = (TODAY - timedelta(days=days_ago)).isoformat()
        ep = f"ep_{day}_{i:03d}"
        _episode(memory, ep, **fm)
        ids.append(ep)
    return ids


def _prose(words: int) -> str:
    return "## Summary\n\n" + " ".join(["The alpha project grows."] * (words // 4 + 1)) + "\n"


def _page(memory, entity_id, *, words=450, episodes=(), **fm):
    body = write_claims(_prose(words), [Claim(id=f"c-{entity_id}", text="A belief.", subject=entity_id,
                                              predicate="is", object="x")])
    markdown_parser.write(memory / "entities" / f"{entity_id}.md",
                          {"name": entity_id.replace("-", " ").title(), "type": "project", "status": "active",
                           "source_episodes": list(episodes), **fm}, body)


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "episodes").mkdir()
    return m


def test_the_rule_is_bank_facts(memory):
    recent = _eps(memory, 5)
    old = _eps(memory, 5, start=10, days_ago=40)
    feed = _eps(memory, 3, start=20, origin="rss")
    _page(memory, "busy-long", episodes=recent)
    _page(memory, "busy-short", episodes=recent, words=200)
    _page(memory, "quiet-long", episodes=recent[:4] + old + feed)   # 4 recent conversations; feed items do not count
    _page(memory, "owner-page", episodes=recent, owner=True)
    found = [c.entity_id for c in in_short.candidates(memory, today=TODAY)]
    assert found == ["busy-long"]
    c = in_short.candidates(memory, today=TODAY)[0]
    assert c.conversations == 5 and "```claims" not in c.article and in_short.words(c.article) >= 400


def test_busiest_first_and_capped(memory):
    for n in range(12):
        _page(memory, f"page-{n:02d}", episodes=_eps(memory, 5 + n, start=100 * (n + 1)))
    found = in_short.candidates(memory, today=TODAY, cap=10)
    assert len(found) == 10 and found[0].entity_id == "page-11" and found[-1].entity_id == "page-02"


@pytest.mark.parametrize("text, ok", [
    ("Alpha is your robotics side project. You work on it most evenings.", True),
    ("One sentence only.", True),
    ("A. B. C. D.", False),
    ("- a list item", False),
    ("", False),
    ("x" * 700 + ".", False),
])
def test_only_plain_short_prose_is_kept(text, ok):
    assert (in_short.clean(text) is not None) is ok


def test_the_small_tier_keeps_the_engine():
    from api.config import Settings

    s = Settings(llm_mode="agent", agent_model="sonnet", agent_disambiguation_model="haiku")
    small = in_short.small_tier(s)
    assert small.llm_mode == "agent" and small.agent_model == "haiku"


def _engine():
    return (SimpleNamespace(llm_mode="agent"), "claude-cli", "ok")


def _reply(text, model="claude-haiku-4-5"):
    return {"model": model, "choices": [{"message": {"content": text}}]}


def test_a_run_writes_once_and_skips_an_unchanged_article(memory):
    _page(memory, "busy-long", episodes=_eps(memory, 6))
    calls = []

    def fn(messages, **kw):
        calls.append(messages)
        return _reply("Busy Long is the project you talk about most. It keeps growing.")

    settings = SimpleNamespace(in_short_per_run=10)
    report = asyncio.run(in_short.run_tail(memory, settings, user_triggered=True, llm_fn=fn, engine=_engine(),
                                           today=TODAY))
    assert report.written == 1 and report.paths == ["entities/busy-long.md"] and report.models == ["claude-haiku-4-5"]
    assert "trigger: sleep/in-short" in report.lines[0]
    fm = markdown_parser.parse(memory / "entities" / "busy-long.md").frontmatter
    assert fm["in_short"]["text"].startswith("Busy Long is the project") and fm["in_short"]["conversations"] == 6
    block = page_blocks.summary(fm)
    assert block["by"] == "sleep" and block["model"] == "claude-haiku-4-5"
    assert "Busy Long (project)" in calls[0][1]["content"]
    # The article is unchanged: the next run sends nothing and resolves no engine.
    again = asyncio.run(in_short.run_tail(memory, settings, user_triggered=True, llm_fn=fn, engine=None, today=TODAY))
    assert again.reason == "nothing" and len(calls) == 1


def test_a_plan_limit_pauses_and_bad_answers_are_dropped(memory):
    for n in range(3):
        _page(memory, f"page-{n}", episodes=_eps(memory, 5 + n, start=100 * (n + 1)))
    answers = iter([_reply("- not prose"), engine_errors.EngineThrottled("limit")])

    def fn(messages, **kw):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a

    report = asyncio.run(in_short.run_tail(memory, SimpleNamespace(in_short_per_run=10), user_triggered=False,
                                           llm_fn=fn, engine=_engine(), today=TODAY))
    assert report.written == 0 and report.skipped == {"unusable": 1, "plan_limit": 1} and report.looked == 2


def test_off_and_no_engine_send_nothing(memory, monkeypatch):
    _page(memory, "busy-long", episodes=_eps(memory, 6))
    off = asyncio.run(in_short.run_tail(memory, SimpleNamespace(in_short_per_run=0), user_triggered=True,
                                        llm_fn=lambda **kw: pytest.fail("sent"), today=TODAY))
    assert off.reason == "off"
    none = asyncio.run(in_short.run_tail(memory, SimpleNamespace(in_short_per_run=10), user_triggered=False,
                                         llm_fn=lambda **kw: pytest.fail("sent"),
                                         engine=(None, "claude-cli", "scheduled_plan"), today=TODAY))
    assert none.reason == "scheduled_plan" and none.written == 0


def test_a_scheduled_run_reaches_a_plan_only_through_the_switch(monkeypatch):
    from api.config import Settings
    from api.services import engine_select

    async def resolve(settings, *, user_triggered):
        return Settings(llm_mode="agent", agent_disambiguation_model="haiku"), None

    monkeypatch.setattr(engine_select, "resolve_settings", resolve)
    monkeypatch.setattr(engine_select, "scheduled_plan_allowed", lambda registry: False)
    resolved, _, why = asyncio.run(in_short.engine_for(Settings(), user_triggered=False))
    assert resolved is None and why == "scheduled_plan"
    resolved, _, why = asyncio.run(in_short.engine_for(Settings(), user_triggered=True))
    assert why == "ok" and resolved.agent_model == "haiku"
