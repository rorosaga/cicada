"""G118 slice 1 — an agent citing what the person said records a real span.

`write_claim(evidence=[{episode, quote}])` verifies each quote against the
stored episode body through the same `evidence.verify` Stage 1 uses; a write
without evidence is `reasoning` (R6). The MCP tool exposes the parameter and
tells the agent what happened. The Telegram `saved-because` claim cites its
own `## Saved because` section (R13).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from api.services import agentic_write, evidence, markdown_parser
from api.services.claims import Evidence, parse_claims

_REPO_ROOT = Path(__file__).resolve().parents[2]
BODY = "user: I want alpha-project on sqlite-vec from now on.\nassistant: Noted."


def _load_server():
    spec = importlib.util.spec_from_file_location("cicada_mcp_server_evidence", _REPO_ROOT / "mcp" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server_evidence"] = mod
    spec.loader.exec_module(mod)
    return mod


def _episode(memory: Path, ep_id: str = "ep_2026-09-01_001", body: str = BODY) -> None:
    (memory / "episodes").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", {"id": ep_id, "processed": False}, body)


def test_write_claim_with_a_verified_quote_records_a_user_span(tmp_path):
    _episode(tmp_path)
    result = agentic_write.write_claim(
        tmp_path, "alpha-project", "uses", "sqlite-vec", observer="rodrigo",
        source_episode="ep_2026-09-01_001",
        evidence=[{"episode": "ep_2026-09-01_001", "quote": "alpha-project on sqlite-vec from now on"}],
    )
    assert result["action"] == "written"
    (c,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body)
    (ev,) = c.evidence
    assert ev.kind == "user" and BODY[ev.start:ev.end] == "alpha-project on sqlite-vec from now on"
    assert ev.hash == evidence.body_hash(BODY)
    assert result["evidence"] == [ev.to_dict()]


def test_write_claim_without_evidence_is_reasoning_on_the_source_episode(tmp_path):
    _episode(tmp_path)
    agentic_write.write_claim(tmp_path, "alpha-project", "uses", "sqlite-vec", observer="agent",
                              source_episode="ep_2026-09-01_001")
    (c,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body)
    # R6: reasoning on the source episode, hash kept because the episode is readable
    assert c.evidence == [Evidence(episode="ep_2026-09-01_001", start=-1, end=-1, kind="reasoning",
                                   hash=evidence.body_hash(BODY))]
    # and with no source episode at all, an anonymous reasoning entry (R6): never an empty list
    agentic_write.write_claim(tmp_path, "bob-example", "prefers", "dark mode", observer="agent")
    (b,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "bob-example.md").body)
    assert b.evidence == [Evidence()]


def test_write_claim_with_an_unverifiable_quote_still_writes_as_reasoning(tmp_path):
    _episode(tmp_path)
    result = agentic_write.write_claim(
        tmp_path, "alpha-project", "uses", "sqlite-vec", observer="agent",
        evidence=[{"episode": "ep_2026-09-01_001", "quote": "words nobody said"}],
    )
    assert result["action"] == "written"
    assert result["evidence"][0]["kind"] == "reasoning" and result["evidence"][0]["hash"] == evidence.body_hash(BODY)


def test_reissued_write_merges_a_later_span_onto_the_existing_claim(tmp_path):
    _episode(tmp_path)
    _episode(tmp_path, "ep_2026-09-02_001", "user: still alpha-project on sqlite-vec, confirmed.")
    agentic_write.write_claim(tmp_path, "alpha-project", "uses", "sqlite-vec", observer="agent",
                              evidence=[{"episode": "ep_2026-09-01_001", "quote": "alpha-project on sqlite-vec"}])
    agentic_write.write_claim(tmp_path, "alpha-project", "uses", "sqlite-vec", observer="agent",
                              evidence=[{"episode": "ep_2026-09-02_001", "quote": "alpha-project on sqlite-vec, confirmed"}])
    (c,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body)
    assert [ev.episode for ev in c.evidence] == ["ep_2026-09-01_001", "ep_2026-09-02_001"]
    assert all(ev.is_span() for ev in c.evidence)


def test_mcp_tool_advertises_evidence_and_dispatches_it(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    _episode(tmp_path)
    server = _load_server()
    tool = {t["name"]: t for t in server.TOOLS}["cicada_write_claim"]
    ev_schema = tool["inputSchema"]["properties"]["evidence"]
    assert ev_schema["type"] == "array"
    assert set(ev_schema["items"]["required"]) == {"episode", "quote"}
    assert "verbatim" in ev_schema["items"]["properties"]["quote"]["description"].lower()
    assert "reasoning" in ev_schema["description"]
    out = server.handle_tool("cicada_write_claim", {
        "subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec", "observer": "rodrigo",
        "source_episode": "ep_2026-09-01_001",
        "evidence": [{"episode": "ep_2026-09-01_001", "quote": "alpha-project on sqlite-vec"}],
    })
    assert "Recorded" in out and "evidence: 1 span verified" in out
    (c,) = parse_claims(markdown_parser.parse(tmp_path / "entities" / "alpha-project.md").body)
    assert c.evidence[0].is_span()


def test_mcp_reply_names_an_unverified_quote_so_the_agent_can_fix_it(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    _episode(tmp_path)
    server = _load_server()
    out = server.handle_tool("cicada_write_claim", {
        "subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec",
        "evidence": [{"episode": "ep_2026-09-01_001", "quote": "not what was said"}],
    })
    assert "Recorded" in out
    assert "evidence: reasoning" in out and "ep_2026-09-01_001" in out
    out2 = server.handle_tool("cicada_write_claim", {"subject": "bob-example", "predicate": "prefers", "object": "tea"})
    assert "evidence: reasoning (no quote given)" in out2


def test_telegram_saved_because_claim_cites_its_own_section(tmp_path, monkeypatch):
    import asyncio

    from api.services import media_ingestor, telegram_capture
    from api.services.media_ingestor import MediaMeta

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    # Bait: the site's own description repeats the reason's words, and
    # `media_ingestor._episode_body` writes `## Description` BEFORE
    # `## Saved because` — so without the section window the first
    # occurrence would be the site's blurb, not what the person typed.
    async def offline(url, client, from_bookmark_file=False):
        return MediaMeta(title="A Recipe", description="Readers say it is great for meal prep.",
                         site="example.com", media_type="url")

    async def no_commit(memory_path, count, paths=None):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    result = asyncio.run(telegram_capture._default_save_url(
        memory, "https://example.com/recipe", note="great for meal prep", reason="great for meal prep"))
    assert result["status"] == "created"  # `_default_save_url` returns a plain dict (telegram_capture.py:454-459)
    page = memory / "entities" / f"{result['media_entity_id']}.md"
    (claim,) = [c for c in parse_claims(markdown_parser.parse(page).body) if c.predicate == "saved-because"]
    (ev,) = claim.evidence
    body = evidence.source_text(memory, result["episode_id"])
    assert ev.kind == "user" and ev.episode == result["episode_id"]
    assert body[ev.start:ev.end] == "great for meal prep"
    section = body.rfind("## Saved because")
    assert body.find("great for meal prep") < section < ev.start  # bait above was skipped; the span is inside the section
