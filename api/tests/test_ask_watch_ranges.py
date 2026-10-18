"""Ask over watch history ranges, the computed record over an older note, and citations that name what grounded the
answer (2026-10-18, ruling 30 follow-up; G71, G94, G118).

A month's summary answered "what was I watching in <month>"; a range ("this year", "since March", "ever", "the
most", "when did I first watch …") answered "no per-channel counts exist". A range is now counted from the watched
days with no model into a table whose size does not depend on the range. Synthetic banks, placeholder channels and
titles only; the model is injected — nothing here reaches one."""
from __future__ import annotations

import json
import time
from datetime import date

import pytest

from _synthetic_bank import _bank, _entity

from api.services import ask_service, bank_index, evidence, markdown_parser, mcp_tools, watch_history
from api.services.claims import Claim, Evidence, write_claims
from api.services.watch_history import Span, asked_span

TODAY = date(2026, 10, 18)


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    bank_index.invalidate()
    watch_history._ROWS_CACHE.clear()
    yield
    monkeypatch.undo()
    time.tzset()


_n = iter(range(1, 10_000))


def _w(at: str, channel: str, *, vid: str | None = None, title: str | None = None):
    vid = vid or f"v{next(_n):010d}"
    return watch_history.make(f"https://www.youtube.com/watch?v={vid}", at=at, title=title or f"Talk {vid}",
                              channel=channel, door="takeout")


def _history(memory):
    watches = [
        # 2024: carol-example only
        _w("2024-05-01T10:00:00Z", "carol-example"), _w("2024-05-02T10:00:00Z", "carol-example"),
        _w("2024-11-20T10:00:00Z", "carol-example"),
        # 2025: bob-example most
        *[_w(f"2025-03-{d:02d}T10:00:00Z", "bob-example") for d in range(1, 11)],
        _w("2025-07-04T10:00:00Z", "carol-example"),
        # 2026: alice-example most, a video watched on two days
        _w("2026-01-05T09:00:00Z", "alice-example", vid="rewatched01", title="Bridge design, part one"),
        _w("2026-01-05T11:00:00Z", "alice-example"), _w("2026-02-10T09:00:00Z", "alice-example"),
        _w("2026-02-11T09:00:00Z", "alice-example"), _w("2026-09-01T09:00:00Z", "alice-example"),
        _w("2026-10-03T07:00:00Z", "alice-example", vid="rewatched01", title="Bridge design, part one"),
        _w("2026-09-02T09:00:00Z", "bob-example"), _w("2026-09-02T12:00:00Z", "bob-example"),
    ]
    watch_history.record(memory, watches)
    bank_index.invalidate()


@pytest.mark.parametrize("query, want", [
    ("Which YouTube channels have I watched the most this year?", Span(date(2026, 1, 1), TODAY, "this year (2026)")),
    ("what did I watch last year", Span(date(2025, 1, 1), date(2025, 12, 31), "last year (2025)")),
    ("channels I watched in 2024", Span(date(2024, 1, 1), date(2024, 12, 31), "2024")),
    ("what have I watched since March 2025", Span(date(2025, 3, 1), TODAY, "since 2025-03-01")),
    ("videos since 2026-09-15", Span(date(2026, 9, 15), TODAY, "since 2026-09-15")),
    ("watched since November", Span(date(2025, 11, 1), TODAY, "since 2025-11-01")),
    ("between 2024 and 2025 which channels", Span(date(2024, 1, 1), date(2025, 12, 31), "2024-01-01 to 2025-12-31")),
    ("from 2025-02 to 2025-04", Span(date(2025, 2, 1), date(2025, 4, 30), "2025-02-01 to 2025-04-30")),
    ("in the last 30 days", Span(date(2026, 9, 19), TODAY, "the last 30 days")),
    ("last month on youtube", Span(date(2026, 9, 1), date(2026, 9, 30), "last month (2026-09)")),
    ("what channel have I watched the most ever", Span(None, None, "all time")),
    ("What was I watching in September 2026?", None),        # one month: that month's summary answers
    ("When did I watch the bridge design video?", None),
])
def test_the_range_a_question_names(query, want):
    assert asked_span(query, TODAY) == want


def test_a_range_is_counted_from_the_days_with_no_model(tmp_path):
    memory = _bank(tmp_path, git=False)
    _history(memory)
    lines = watch_history.lookup(memory, "Which YouTube channels have I watched the most this year?", today=TODAY)
    text = "\n".join(lines)
    assert lines[0].startswith("Counted now from the watch history (YouTube), this year (2026): 8 videos watched on "
                               "6 days, 2026-01-05 to 2026-10-03 (7 different videos, 2 channels)")
    channels = lines[lines.index("Channels watched most (2 of 2):") + 1:][:2]
    assert channels == ["- alice-example — 6 videos on 5 days in 4 weeks, 2026-01-05 to 2026-10-03",
                        "- bob-example — 2 videos on 1 day in 1 week, 2026-09-02 to 2026-09-02"]
    assert "- Bridge design, part one — alice-example · 2 days, first 2026-01-05, last 2026-10-03" in lines
    assert "- 2026-02 · 2 videos on 2 days; most: alice-example (2)" in lines
    assert "carol-example" not in text                        # 2024 and 2025 are outside the range

    last_year = watch_history.lookup(memory, "what did I watch most last year", today=TODAY)
    assert "- bob-example — 10 videos on 10 days in 3 weeks, 2025-03-01 to 2025-03-10" in last_year
    assert "alice-example" not in "\n".join(last_year)


def test_ever_counts_by_year_and_names_the_first_and_last_watch_of_a_channel(tmp_path):
    memory = _bank(tmp_path, git=False)
    _history(memory)
    lines = watch_history.lookup(memory, "When did I first watch carol-example?", today=TODAY)
    assert lines[0].startswith("Counted now from the watch history (YouTube), all time: 22 videos watched on 20 days")
    assert "By year:" in lines and "- 2025 · 11 videos on 11 days; most: bob-example (10), carol-example (1)" in lines
    focus = lines[lines.index("The channel(s) the question names, in this range:") + 1]
    assert focus.startswith("- carol-example — 4 videos on 4 days; first watched 2024-05-01 (")
    assert "last watched 2025-07-04 (" in focus
    # The question's own words also find the watched rows, dated and naming their day's episode.
    assert any(ln.startswith("2024-05-01 10:00 · ") and "carol-example" in ln for ln in lines)
    # A named month still reads its summary; a plain question still reads the matching rows.
    month = watch_history.lookup(memory, "What was I watching in September 2026?", today=TODAY)
    assert "# Watched on YouTube · September 2026" in month[0]
    rows = watch_history.lookup(memory, "When did I watch the bridge design video?", today=TODAY)
    assert len(rows) == 2 and rows[0].startswith("2026-01-05 09:00 · Bridge design, part one")


def test_since_and_between_and_an_empty_range(tmp_path):
    memory = _bank(tmp_path, git=False)
    _history(memory)
    since = watch_history.lookup(memory, "which channels have I watched since September 2026", today=TODAY)
    assert since[0].startswith("Counted now from the watch history (YouTube), since 2026-09-01: 4 videos")
    between = watch_history.lookup(memory, "top channels between 2024 and 2025", today=TODAY)
    assert "- bob-example — 10 videos on 10 days in 3 weeks, 2025-03-01 to 2025-03-10" in between
    assert "- carol-example — 4 videos on 4 days in 3 weeks, 2024-05-01 to 2025-07-04" in between
    assert watch_history.lookup(memory, "what did I watch most in 2019", today=TODAY) == []


def test_the_table_is_bounded_whatever_the_range(tmp_path):
    memory = _bank(tmp_path, git=False)
    watches = [_w(f"20{18 + i % 9}-{1 + i % 12:02d}-{1 + i % 28:02d}T10:00:00Z", f"channel-{i % 300:03d}-example",
                  vid=f"b{i % 700:010d}") for i in range(3000)]
    watch_history.record(memory, watches)
    bank_index.invalidate()
    lines = watch_history.lookup(memory, "which channels have I watched the most ever, and channel 007?",
                                 today=TODAY)
    limit = (1 + 1 + watch_history.RANGE_CHANNELS + 1 + watch_history.RANGE_RETURNED + 1
             + watch_history.RANGE_REWATCHED + 1 + watch_history.RANGE_PERIODS + 1 + watch_history.RANGE_FOCUS
             + 1 + watch_history.RANGE_MATCHES + 1)
    assert len(lines) <= limit and sum(len(ln) for ln in lines) < 16_000
    assert lines[0].startswith("Counted now from the watch history (YouTube), all time: 3,000 videos")


def _owner_with_noise(memory, n: int = 300):
    """An owner page touched by ``n`` conversations, one claim pointing at one of them."""
    ep = "ep_2026-10-18_001"
    body = "user: the watch history has not been read yet, it is waiting for Sleep."
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "source": "mcp", "timestamp": "2026-10-18T08:00:00+00:00"}, body)
    quote = "the watch history has not been read yet"
    s = body.index(quote)
    ev = Evidence(episode=ep, start=s, end=s + len(quote), kind="user", hash=evidence.body_hash(body))
    claim = Claim(id="clm_w1", text="Owner's watch history has not been read yet", subject="owner-example",
                  source_episodes=[ep], evidence=[ev])
    noise = [f"ep_2026-0{1 + i % 9}-{1 + i % 28:02d}_{i:03d}" for i in range(n)]
    _entity(memory, "owner-example", type="person", owner=True, name="Owner Example", source_episodes=[*noise, ep],
            body=write_claims("## Summary\nThe person this memory belongs to.\n", [claim]))
    return ep


def test_the_computed_record_is_marked_newer_than_an_agents_earlier_note(tmp_path):
    memory = _bank(tmp_path, git=False)
    _history(memory)
    ep = _owner_with_noise(memory)
    prompts: list[str] = []

    def llm(prompt):
        prompts.append(prompt)
        return json.dumps({"answer": "alice-example, 6 videos.", "confidence": 0.8,
                           "used_entities": ["owner-example"], "gaps": []})

    hit = {"score": 0.9, "text": "", "metadata": {"entity_id": "owner-example", "entity_name": "Owner Example"}}
    out = ask_service.answer_query(memory, "Which YouTube channels have I watched the most this year? watch history",
                                   retrieve_fn=lambda q, k: [hit], llm_fn=llm, no_engine=False)
    prompt = prompts[0]
    assert "WATCH HISTORY — COMPUTED FROM THE RECORD NOW (" in prompt
    assert prompt.index("WHAT WAS SAID") < prompt.index("WATCH HISTORY — COMPUTED")
    assert "- alice-example — 6 videos on 5 days" in prompt
    assert "never repeat an earlier statement that the history was not yet imported, read or counted" in prompt
    assert "10. A block COMPUTED FROM THE RECORD NOW" in ask_service.ASK_SYSTEM_PROMPT
    # The owner page's citation names the conversation this answer was grounded in, not all 301.
    [c] = out["citations"]
    assert c["source_episodes"] == [ep] and c["source_episodes_more"] == 300


def test_a_citation_names_at_most_a_few_episodes_newest_first_with_a_count(tmp_path):
    memory = _bank(tmp_path, git=False)
    eps = [f"ep_2026-09-{d:02d}_001" for d in range(1, 21)]
    _entity(memory, "beta-project", type="project", source_episodes=eps)
    hit = {"score": 0.9, "text": "", "metadata": {"entity_id": "beta-project", "entity_name": "Beta Project"}}

    def llm(prompt):
        return json.dumps({"answer": "A fixture.", "confidence": 0.6, "used_entities": ["beta-project"], "gaps": []})

    out = ask_service.answer_query(memory, "what is beta project", retrieve_fn=lambda q, k: [hit], llm_fn=llm,
                                   no_engine=False)
    [c] = out["citations"]
    assert c["source_episodes"] == eps[::-1][:ask_service.MAX_CITED_EPISODES]
    assert c["source_episodes_more"] == 20 - ask_service.MAX_CITED_EPISODES
    text = mcp_tools._render_ask(out)
    assert f"(episodes: {', '.join(eps[::-1][:5])} +15 more)" in text
    from api.models.schemas import AskCitation

    wire = AskCitation(**c).model_dump(by_alias=True)
    assert wire["sourceEpisodesMore"] == 15 and len(wire["sourceEpisodes"]) == 5
