"""G162 C5 — the hand-off prompt: short, neutral about providers, names only tools that exist, carries no
video content, and names no browser route unless the person's single permission is on (H1)."""
from __future__ import annotations

import re

import pytest

from api.remote import catalog
from api.services import video_prompt

CLOSED = re.compile(r"\b(gemini|google|claude|codex|chatgpt|openai|anthropic|ollama|openrouter|sonnet|haiku|opus|"
                    r"gpt|grok|mistral|groq|whisper|safari|chrome|firefox)\b", re.I)


@pytest.mark.parametrize("count", [0, 1, 5, 300, 12345])
@pytest.mark.parametrize("method", ["auto", "captions", "link"])
def test_prompt(count, method):
    text = video_prompt.build(count, method)
    assert len(text) <= video_prompt.MAX_CHARS
    tools = set(re.findall(r"cicada_[a-z_]+", text))
    assert tools == {"cicada_video_claim", "cicada_record_watch"} and tools <= set(catalog.TOOL_SCOPE)
    assert not CLOSED.search(text), CLOSED.search(text)
    assert "browser" not in text.lower() and "never sign in yourself" in text, "R-VU10: no browser route by default"
    assert "$" not in text and "token" not in text.lower(), "ruling 12: no price, no token talk"


def test_the_full_prompt_with_every_optional_line_still_fits():
    text = video_prompt.build(99, "link", browser_clause=video_prompt.BROWSER_CLAUSE,
                              method_clause="Use the skill the person chose: " + "x" * 200)
    assert len(text) <= video_prompt.MAX_CHARS, len(text)


def test_the_count_reads_naturally():
    assert video_prompt.build(1).splitlines()[0] == "Cicada has 1 video waiting for you to read or watch."
    assert video_prompt.build(5).splitlines()[0] == "Cicada has 5 videos waiting for you to read or watch."
    assert video_prompt.build(0).splitlines()[0] == "Cicada has no videos waiting for you to read or watch."


def test_the_claim_loop_and_no_cap_are_in_the_words():
    text = video_prompt.build(300)
    assert "Call cicada_video_claim until it returns nothing" in text and "up to 10 links a call" in text
    assert "If you can run sub-agents, one per video is fine." in text and "small model" not in text
    assert "use code needs_login" in text and "never sign in yourself" in text


def test_it_carries_no_video_content():
    text = video_prompt.build(3, "captions")
    assert "http" not in text and "youtube" not in text.lower()


def test_method_lines():
    assert video_prompt.method_line("auto") is None and video_prompt.method_line(None) is None
    assert "captions or a transcript are enough" in video_prompt.build(1, "captions")
    assert "the link directly" in video_prompt.build(1, "link")
    assert video_prompt.method_line("anything else") is None


def test_browser_clause_only_when_permission_on():
    """H1: the builder adds the clause only when handed it; step 4 is the same either way; the clause names no
    site, no browser product, no provider — an instruction, not a promise."""
    off, on = video_prompt.build(2), video_prompt.build(2, browser_clause=video_prompt.BROWSER_CLAUSE)
    assert video_prompt.BROWSER_CLAUSE not in off and video_prompt.BROWSER_CLAUSE in on
    step4 = lambda t: next(line for line in t.splitlines() if line.startswith("4."))  # noqa: E731
    assert step4(off) == step4(on)
    clause = video_prompt.BROWSER_CLAUSE
    assert not CLOSED.search(clause) and not re.search(r"\b\w+\.(com|tv|org|net)\b", clause)
    assert "Do not type credentials, post, comment or change anything" in clause
    assert "hand it back with code needs_login" in clause


def test_the_method_seam_is_empty_until_agent_methods_lands():
    """The reading branch's `agent_methods` selection fills `method_clause`; until then it says nothing and the
    prompt is unchanged."""
    assert video_prompt.method_clause(None) is None
    assert video_prompt.build(2, "auto", method_clause=None) == video_prompt.build(2, "auto")
    assert "Use the person's chosen skill." in video_prompt.build(2, method_clause="Use the person's chosen skill.")
