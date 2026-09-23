"""G135 R-R2 / R-R14 — the stdio server's replies, byte for byte.

Recorded at the end of Task 3 (after the last stdio behaviour change) and
replayed by every later commit: Task 4 moves every tool body into
`api/services/mcp_tools.py`, and a refactor must not change a single reply an
agent sees. Location-agnostic on purpose — it patches the vector index, urllib
and the ask/enrich services at their OWN modules, and `_backend_post` /
`SESSION` / `get_memory_path` on the server (which the stdio wrappers read at
call time), never a helper that moves. Dates in the bank are relative to today
(replies carry ages such as "4 months ago"), and today's ISO date is replaced
by `<today>` before comparing. Re-record ONLY for a deliberate reply change:
`CICADA_RECORD_GOLDEN=1`.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from api.services import ask_service, markdown_parser, media_ingestor, predicates, vector_index

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_stdio_golden.json"


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox", "hubs", "sources"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)

    def entity(eid: str, body: str, **fm):
        base = {"name": eid.replace("-", " ").title(), "type": "concept", "status": "active",
                "confidence": 0.6, "created": _ago(90), "last_referenced": _ago(30), "decay_rate": 0.05,
                "source_episodes": [], "tags": [], "related": [], "version": 1}
        base.update(fm)
        markdown_parser.write(memory / "entities" / f"{eid}.md", base, body)

    # Alpha's dates are FIXED, not relative: `cicada_recall_detail` prints the
    # page's frontmatter verbatim, so a relative date would change the reply
    # every day. Only beta's `last_referenced` must stay relative (its decay
    # card prints an age phrase), and beta's frontmatter is never printed.
    entity("alpha-project", "## Summary\nAlpha Project is a synthetic search index.\n", type="project",
           created="2026-01-05", last_referenced="2026-01-05",
           source_episodes=["ep_2026-01-05_001"], related=["Bob Example"])
    entity("bob-example", "## Summary\nBob Example is a synthetic person.\n", type="person")
    entity("beta-project", "## Summary\nBeta Project is quiet.\n", type="project", last_referenced=_ago(120))
    markdown_parser.write(
        memory / "episodes" / "ep_2026-01-05_001.md",
        {"id": "ep_2026-01-05_001", "timestamp": "2026-01-05T09:00:00+00:00", "processed": True,
         "session_id": "ses_2026-01-05_abcd1234", "harness": "codex", "title": "Alpha kickoff"},
        "user: we will index alpha with sqlite-vec\nassistant: noted",
    )
    markdown_parser.write(
        memory / "inbox" / "inbox-001.md",
        {"kind": "decay", "status": "pending", "entity_id": "beta-project", "entity_name": "Beta Project",
         "title": "Still tracking Beta?", "created_date": _ago(10)},
        "ctx",
    )
    (memory / "hubs" / "projects.md").write_text(
        "---\ntype: hub\nname: Projects\nhub_kind: type\n---\n\n- [[Alpha Project]] — a search index\n"
        "- [[Beta Project]]\n", encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["add", "."], ["commit", "-q", "-m", "seed"]):
        subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True)
    return memory


@pytest.fixture
def server(tmp_path, monkeypatch):
    srv = stdio_server()
    memory = _bank(tmp_path)
    monkeypatch.setattr(srv, "get_memory_path", lambda: memory)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_golden_fixed", "claude-code", None))
    monkeypatch.setattr(srv, "_STATE_HINT_SENT", False)
    monkeypatch.setattr(srv, "_SKIPPED_INBOX_IDS", set())
    monkeypatch.setattr(srv, "_backend_post", lambda path, payload: {"status": "resolved"})
    srv.CLIENT_INFO.clear()

    class _NoIndex:
        def __init__(self, *a, **k):
            raise RuntimeError("no vector index in the golden bank")

    def _offline(*a, **k):
        raise OSError("the golden run never reaches a backend")

    async def _meta(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(title="Example Post", description="", site="example.com", media_type="url")

    monkeypatch.setattr(vector_index, "SqliteVecIndexer", _NoIndex)
    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    monkeypatch.setattr(ask_service, "answer_query", lambda memory_path, query, top_k=6: {
        "answer": "Alpha uses sqlite-vec.", "confidence": 0.8,
        "citations": [{"entity_id": "alpha-project", "entity_name": "Alpha Project",
                       "source_episodes": ["ep_2026-01-05_001"]}],
        "gaps": ["when it shipped"], "used_entities": ["alpha-project"]})
    monkeypatch.setattr(media_ingestor, "enrich", _meta)
    return srv


def _replies(srv) -> dict[str, str]:
    t = srv.handle_tool
    today = date.today().isoformat()
    out = {
        "recall": t("cicada_recall", {"query": "alpha project"}),
        "recall_again": t("cicada_recall", {"query": "alpha project"}),
        "recall_miss": t("cicada_recall", {"query": "zzzz-nothing-matches"}),
        "recall_detail": t("cicada_recall_detail", {"entity_id": "alpha-project"}),
        "recall_detail_missing": t("cicada_recall_detail", {"entity_id": "nobody-here"}),
        "open_hub": t("cicada_open_hub", {"hub": "projects"}),
        "open_hub_missing": t("cicada_open_hub", {"hub": "nothing"}),
        "sources": t("cicada_sources", {"entity_id": "alpha-project"}),
        "check_nudges": t("cicada_check_nudges", {}),
        "check_nudges_ids": t("cicada_check_nudges", {"entity_ids": ["beta-project"]}),
        "check_nudges_topic": t("cicada_check_nudges", {"topic": "beta"}),
        "save_episode": t("cicada_save_episode", {"content": "we picked sqlite-vec for alpha", "title": "Index choice"}),
        "save_episode_dup": t("cicada_save_episode", {"content": "we picked sqlite-vec for alpha", "title": "Index choice"}),
    }
    out["write_claim"] = t("cicada_write_claim", {
        "subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec",
        "evidence": [{"episode": f"ep_{today}_001", "quote": "we picked sqlite-vec"}]})
    out["write_claim_reasoning"] = t("cicada_write_claim", {"subject": "alpha-project", "predicate": "prefers",
                                                             "object": "small indexes"})
    out["get_perspective"] = t("cicada_get_perspective", {"subject": "alpha-project"})
    out["get_perspective_agent"] = t("cicada_get_perspective", {"subject": "alpha-project", "observer": "agent"})
    out["resolve_skip"] = t("cicada_resolve_inbox", {"id": "inbox-001", "skip": True})
    out["check_nudges_after_skip"] = t("cicada_check_nudges", {})
    out["resolve_option"] = t("cicada_resolve_inbox", {"id": "inbox-001", "option_key": "keep"})
    out["resolve_missing_args"] = t("cicada_resolve_inbox", {"id": "inbox-001"})
    out["ask"] = t("cicada_ask", {"query": "what does alpha use?"})
    out["save_url"] = t("cicada_save_url", {"url": "https://example.com/post", "note": "worth keeping"})
    out["save_url_bad"] = t("cicada_save_url", {"url": "ftp://example.com/x"})
    return {k: v.replace(today, "<today>") for k, v in out.items()}


def test_stdio_tool_replies_are_byte_identical(server):
    got = _replies(server)
    if os.environ.get("CICADA_RECORD_GOLDEN") == "1":
        FIXTURE.write_text(json.dumps(got, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    assert got == json.loads(FIXTURE.read_text(encoding="utf-8"))
