"""G162 N-8 (R-VU11, owner 2026-09-30) — provider-neutral copy: every string the video surfaces write describes the
step ("the reader reads…", "a model that takes the link") and never names a provider or model as the one that does
the job. Names appear only as DATA — a harness label the person's own agent sent, shown as who did something that
happened. Out of scope, named: `recommended_skills.json` (a reviewed fact about a named skill) and the per-harness
handshake preludes."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from _video_fixtures import add_watch_episode, bank_with_videos, url_of
from api.remote import tools as remote_tools
from api.services import handshake, mcp_tools, skill_catalog, video_prompt, video_queue

ROOT = Path(__file__).resolve().parents[2]
NAMES = re.compile(r"\b(gemini|google|claude|codex|chatgpt|openai|anthropic|ollama|openrouter|sonnet|haiku|opus|gpt|"
                   r"grok|mistral|groq|whisper)\b", re.I)
SOURCES = ("api/services/video_state.py", "api/services/video_queue.py", "api/services/video_prompt.py",
           "api/routers/videos.py")
VIDEO_TOOLS = ("cicada_video_queue", "cicada_video_claim")


def _names(text: str) -> list[str]:
    return NAMES.findall(text)


@pytest.mark.parametrize("path", SOURCES)
def test_the_new_modules_name_no_provider(path):
    assert _names((ROOT / path).read_text(encoding="utf-8")) == []


def test_the_two_tool_descriptions_and_the_new_arguments():
    stdio = {t["name"]: t for t in stdio_server().TOOLS}
    texts = [json.dumps(stdio[n]) for n in VIDEO_TOOLS] + [json.dumps(remote_tools.REMOTE_TOOLS[n]) for n in VIDEO_TOOLS]
    for name in ("cicada_record_watch",):
        for source in (stdio[name], remote_tools.REMOTE_TOOLS[name]):
            props = source["inputSchema"]["properties"]
            texts += [json.dumps(props[a]) for a in ("basis", "engine", "duration")]
    assert all(_names(t) == [] for t in texts), [(t[:60], _names(t)) for t in texts if _names(t)]


def test_the_contract_clause_and_the_bridge_line():
    (contract,) = re.findall(r"3\. Save as you learn:.*?\n4\. Write facts", handshake._CONTRACT, re.S) or [
        handshake._CONTRACT[handshake._CONTRACT.index("3. Save as you learn"):handshake._CONTRACT.index("4. Write facts")]]
    assert "cicada_video_claim" in contract and _names(contract) == []
    remote = handshake._remote_video_queue(frozenset({"cicada_video_claim", "cicada_video_queue"}))
    assert remote and _names(remote) == []
    assert _names(skill_catalog.BRIDGE_TEXT["video"]) == []


def test_every_reply_the_tools_write_is_neutral_and_attribution_is_data(tmp_path, monkeypatch):
    memory, keys = bank_with_videos(tmp_path, 2)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_acme_01", harness="acme-agent")
    video_queue.put(memory, keys[0], "watch")
    video_queue.put(memory, keys[1], "transcript")
    replies = [mcp_tools.video_claim(ctx, limit=1),
               mcp_tools.video_queue_list(ctx),
               mcp_tools.video_claim(ctx, release=[{"url": url_of("00"), "code": "needs_login", "reason": "wall"}]),
               mcp_tools.video_claim(ctx, release=[{"url": url_of("01")}]),
               mcp_tools.video_claim(ctx),
               mcp_tools.video_claim(ctx),
               mcp_tools.record_watch(ctx, url_of("00"), "A summary.", None, None, "telepathy", "gemini_url", "soon"),
               mcp_tools.record_watch(ctx, url_of("01"), "Another summary.")]
    joined = "\n".join(replies)
    assert _names(joined) == [], _names(joined)
    assert "Recorded the watch" in joined


def test_the_queue_list_shows_the_harness_it_was_sent(tmp_path, monkeypatch):
    """Attribution is built from data: a label no code has ever heard of is rendered as sent."""
    memory, keys = bank_with_videos(tmp_path, 1)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_acme_01", harness="acme-agent")
    video_queue.put(memory, keys[0], "watch")
    mcp_tools.video_claim(ctx)
    assert "picked up by acme-agent" in mcp_tools.video_queue_list(ctx)


def test_the_prompt_with_every_line_is_neutral():
    assert _names(video_prompt.build(7, "link", browser_clause=video_prompt.BROWSER_CLAUSE)) == []
