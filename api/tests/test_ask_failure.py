"""Ask says why its model call failed, and what to do (G148, 2026-11-06): a plan limit, a sign-out, a timeout and a
dropped connection used to answer one sentence ("could not synthesize") that fits none of them. Synthetic bank; the
model is a stub that raises the engine's own classes. An unreadable reply still degrades as it did."""
from __future__ import annotations

import json
import time
import urllib.error

import pytest

from api.services import ask_failure, ask_service, bank_index, engine_errors, engine_readiness, engine_select, evidence
from api.services import markdown_parser, mcp_tools, search_index


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    said = {f"ep_2023-{i:02d}-01_001": f"user: Can you help me plan the weekly errands list number {i}?\n"
                                       f"assistant: Sure, errands list {i}: groceries, laundry, bank.\n"
            for i in range(1, 13)}
    said["ep_2024-02-03_001"] = "user: We chose alpha-database for the ledger project.\nassistant: Noted.\n"
    for ep, body in said.items():
        markdown_parser.write(memory / "episodes" / f"{ep}.md",
                              {"id": ep, "timestamp": f"{ep[3:13]}T10:00:00+00:00", "processed": False,
                               "source": "import", "content_hash": evidence.body_hash(body)}, body)
    assert search_index.ensure_fresh(memory, wait=True, max_age_s=0) == "ready"
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


GOOD = json.dumps({"answer": "alpha-database", "confidence": 0.8, "used_entities": [], "gaps": []})
QUESTION = "Which database did we choose for the ledger project?"


def _ask(bank, exc: BaseException | None = None, then: str = GOOD):
    calls: list[str] = []

    def model(prompt: str) -> str:
        calls.append(prompt)
        if exc is not None:
            raise exc
        return then

    result = ask_service.answer_query(bank, QUESTION, retrieve_fn=lambda q, k: [], llm_fn=model, no_engine=False)
    return result, calls


class _Signal(Exception):
    """A stand-in for a provider's exception: only its class name and text classify (engine_cause)."""


CLASSES = [
    (engine_errors.EngineExhausted("x", resets_at=None), "plan_limit"),
    (engine_errors.EngineOverage("x"), "overage"),
    (engine_errors.EngineUnavailable("signed out"), "engine_unavailable"),
    (engine_errors.EngineModelNotFound("nope"), "model_unknown"),
    (engine_errors.EngineTimeout("slow"), "timeout"),
    (TimeoutError("slow"), "timeout"),
    (engine_errors.EngineConnectionLost("gone"), "offline"),
    (ConnectionError("down"), "offline"),
    (_Signal("Incorrect API key provided"), "key_refused"),
    (_Signal("Key limit exceeded (total limit)"), "key_limit"),
    (_Signal("429 Too many requests"), "rate_limited"),
]


@pytest.mark.parametrize("exc,code", CLASSES, ids=[c for _, c in CLASSES])
def test_a_failed_call_is_told_with_its_cause(bank, exc, code):
    result, calls = _ask(bank, exc)
    assert result["failure"] == code
    assert result["answer"].startswith(ask_failure.sentence(code))
    assert result["confidence"] == 0.0 and "could not synthesize" not in result["answer"]
    assert len(calls) == 1, "a named failure is not a lost reply: the same wall is not asked twice"


def test_a_plan_window_names_when_it_resets_only_when_the_vendor_said(bank):
    at = int(time.time()) + 3600
    window = engine_errors.EngineThrottled("limit", resets_at=at)
    window.limit_type = "five_hour"
    told, _ = _ask(bank, window)
    assert told["failure"] == "plan_window" and told["resets_at"] == at
    assert "Ask again after" in told["answer"]
    silent = engine_errors.EngineThrottled("limit")
    silent.limit_type = "seven_day"
    told, _ = _ask(bank, silent)
    assert told["failure"] == "plan_weekly" and told["resets_at"] is None
    assert "once it resets" in told["answer"]


def test_the_exception_message_never_reaches_the_reply(bank):
    secret = "sk-ant-api03-SECRET at https://internal.example/acct_123"
    result, _ = _ask(bank, engine_errors.EngineUnavailable(secret))
    wire = json.dumps(result)
    assert "SECRET" not in wire and "internal.example" not in wire


def test_the_pages_it_found_are_still_named_and_no_figure_is_shown(bank):
    window = engine_errors.EngineThrottled("limit", resets_at=int(time.time()) + 60)
    window.limit_type = "five_hour"
    result, _ = _ask(bank, window)
    assert "Relevant pages:" in result["answer"]
    assert "%" not in result["answer"] and "$" not in result["answer"]


def test_an_unnamed_failure_and_an_unreadable_reply_still_degrade_as_before(bank):
    result, calls = _ask(bank, ValueError("boom"))
    assert "could not synthesize" in result["answer"] and result["confidence"] == 0.15
    assert result["failure"] == "unreadable" and len(calls) == 2
    result, calls = _ask(bank, None, then="not json at all, but it says rate limit and 429")
    assert "could not synthesize" in result["answer"] and result["failure"] == "unreadable" and len(calls) == 2


def test_a_good_answer_carries_no_failure(bank):
    result, _ = _ask(bank)
    assert result["answer"] == "alpha-database" and "failure" not in result


def test_every_code_has_a_sentence_and_the_set_is_closed():
    for code in ask_failure.CODES:
        if code in (ask_failure.UNREADABLE, ask_failure.NO_ENGINE):
            continue
        assert ask_failure.sentence(code)
    with pytest.raises(ValueError):
        ask_failure.sentence("nope")


def test_no_engine_is_told_as_a_code_too(bank):
    result = ask_service.answer_query(bank, QUESTION, retrieve_fn=lambda q, k: [], llm_fn=lambda p: GOOD, no_engine=True)
    assert result["failure"] == "no_engine" and engine_readiness.ASK_NO_ENGINE in result["answer"]


# --- the MCP door ------------------------------------------------------------------------------------------------


def _ctx(bank):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="claude-code",
                                 backend_url="http://127.0.0.1:9")


def test_a_slow_backend_is_not_asked_twice(bank, monkeypatch):
    """The backend took the question and ran past the wait: the tool says so and never runs the job itself."""
    import urllib.request

    def slow(*a, **kw):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", slow)
    monkeypatch.setattr(ask_service, "answer_query", lambda *a, **kw: pytest.fail("the job ran a second time"))
    reply = mcp_tools.ask(_ctx(bank), QUESTION)
    assert "still working" in str(reply)


def test_a_backend_that_is_down_is_answered_directly_on_the_resolved_engine(bank, monkeypatch):
    """Auto is resolved like the route does: a signed-in plan answers, and is never told there is no engine."""
    import urllib.request

    from api.config import get_settings

    def down(*a, **kw):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(urllib.request, "urlopen", down)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.delenv("CICADA_LLM_MODE", raising=False)
    get_settings.cache_clear()
    seen: dict = {}

    async def resolve(settings, *a, **kw):
        seen["asked"] = True
        return settings.model_copy(update={"llm_mode": "agent"}), "plan"

    monkeypatch.setattr(engine_select, "resolve_settings", resolve)
    monkeypatch.setattr(ask_service, "_default_llm_fn", lambda settings=None, **kw: (lambda prompt: GOOD))
    try:
        text = str(mcp_tools.ask(_ctx(bank), QUESTION))
    finally:
        get_settings.cache_clear()
    assert seen.get("asked") and "no engine" not in text.lower()
    assert "alpha-database" in text


def test_unresolved_auto_reads_as_no_engine_when_nothing_resolves_it(monkeypatch):
    """The reproduction behind the MCP fix: with no `no_engine` given, Ask asks the raw settings, and the raw default
    (Auto) is `key_missing` even for a person whose plan is signed in."""
    from api.config import Settings

    assert engine_readiness.key_missing(Settings(llm_mode="auto")) is True
