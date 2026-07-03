"""Tests for the agentic write path (``api.services.agentic_write``).

Hermetic: everything happens under ``tmp_path``; no LLM, no network, no live
memory. Covers:
1. ``write_claim`` creates a subject page + claim with the right
   observer/source_trust.
2. The trust invariant end-to-end: a second, later agent claim never
   overwrites an earlier user_stated (observer=rodrigo) claim on the same
   single-valued predicate — it coexists instead (reused from
   ``claim_reconciler.reconcile_stage3``, not reimplemented here).
3. ``list_unprocessed_episodes`` / ``mark_episodes_processed``.
4. MCP registration + dispatch of ``cicada_write_claim``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from api.services import agentic_write, markdown_parser, predicates
from api.services.claims import Claim, parse_claims, write_claims

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_server():
    spec = importlib.util.spec_from_file_location(
        "cicada_mcp_server_agentic", _REPO_ROOT / "mcp" / "server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server_agentic"] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# write_claim — creates page + claim, correct observer/source_trust
# --------------------------------------------------------------------------- #


def test_write_claim_creates_subject_page_and_claim(tmp_path):
    result = agentic_write.write_claim(
        tmp_path,
        "Rodrigo",
        "works-at",
        "Acme Robotics",
        observer="agent",
        confidence=0.6,
        source_episode="ep_2026-07-01_001",
    )

    assert result["action"] == "written"
    assert result["entity_id"] == "rodrigo"
    assert result["observer"] == "agent"
    assert result["claim_id"].startswith("clm_rodrigo_works-at_")

    page = tmp_path / "entities" / "rodrigo.md"
    assert page.exists()

    parsed = markdown_parser.parse(page)
    assert parsed.frontmatter["type"] == "person"  # inferred from 'works-at'
    assert parsed.frontmatter["status"] == "active"
    assert "ep_2026-07-01_001" in parsed.frontmatter.get("source_episodes", [])

    claims = parse_claims(parsed.body)
    assert len(claims) == 1
    c = claims[0]
    assert c.subject == "rodrigo"
    assert c.predicate == "works-at"
    assert c.object == "Acme Robotics"
    assert c.observer == "agent"
    assert c.source_trust == "agent_extracted"
    assert c.origin == "mcp"
    assert c.epistemic == "explicit"
    assert c.source_episodes == ["ep_2026-07-01_001"]
    assert c.valid_from == "2026-07-01"


def test_write_claim_rodrigo_observer_is_user_stated_and_human_origin(tmp_path):
    result = agentic_write.write_claim(
        tmp_path,
        "Rodrigo",
        "prefers",
        "concise summaries",
        observer="rodrigo",
    )
    assert result["action"] == "written"
    page = tmp_path / "entities" / "rodrigo.md"
    claims = parse_claims(markdown_parser.parse(page).body)
    c = claims[0]
    assert c.source_trust == "user_stated"
    assert c.origin == "manual_edit"  # the human-protection origin gate


def test_write_claim_reuses_existing_page_without_duplicating(tmp_path):
    entities_dir = tmp_path / "entities"
    entities_dir.mkdir(parents=True)
    markdown_parser.write(
        entities_dir / "rodrigo.md",
        {"name": "Rodrigo", "type": "person", "status": "active"},
        "Some existing prose about Rodrigo.",
    )

    result = agentic_write.write_claim(
        tmp_path, "Rodrigo", "uses", "sqlite-vec", observer="agent"
    )
    assert result["entity_id"] == "rodrigo"
    assert len(list(entities_dir.glob("*.md"))) == 1

    parsed = markdown_parser.parse(entities_dir / "rodrigo.md")
    assert "Some existing prose about Rodrigo." in parsed.body


# --------------------------------------------------------------------------- #
# Trust invariant — agent claim must NOT overwrite a user_stated claim
# --------------------------------------------------------------------------- #


def test_agent_claim_never_overwrites_user_stated_claim(tmp_path):
    """The load-bearing trust invariant, exercised through the real reconciler.

    Seed a page with a pre-existing user_stated + manual-edit-origin claim
    (the shape a companion-app clarification/manual edit produces — see
    claim_reconciler.is_human) in the SAME belief slot (subject, predicate,
    context, observer) an incoming agentic write will target. Then call
    ``write_claim`` as an agent (source_trust=agent_extracted) with a
    conflicting object on a single-valued predicate. reconcile_stage3 must
    COEXIST-flag the agent claim rather than closing the human one.
    """
    predicates.install_predicate_map(tmp_path)  # 'works-at' is single_valued

    entities_dir = tmp_path / "entities"
    entities_dir.mkdir(parents=True)
    human_claim = Claim(
        id="clm_seed_human",
        text="Rodrigo works-at Acme Robotics",
        subject="rodrigo",
        predicate="works-at",
        object="Acme Robotics",
        observer="agent",  # matches the K-slot entities_to_claims/write_claim use
        context="general",
        source_trust="user_stated",
        origin="manual_edit",  # the origin-gated human-protection marker
        valid_from="2026-01-01",
    )
    markdown_parser.write(
        entities_dir / "rodrigo.md",
        {"name": "Rodrigo", "type": "person", "status": "active"},
        write_claims("Some prose about Rodrigo.", [human_claim]),
    )

    result = agentic_write.write_claim(
        tmp_path,
        "Rodrigo",
        "works-at",
        "Globex Corp",
        observer="agent",
        source_episode="ep_2026-06-01_001",
    )
    # The agent claim is not silently dropped, but it must not close the
    # human claim — coexist (flagged) is the contract here.
    assert result["action"] == "coexist"

    page = tmp_path / "entities" / "rodrigo.md"
    claims = {c.id: c for c in parse_claims(markdown_parser.parse(page).body)}

    human = claims["clm_seed_human"]
    assert human.valid_to is None, "the user-stated claim must stay OPEN"
    assert human.superseded_by is None, "the user-stated claim must never be closed by an agent"
    assert human.object == "Acme Robotics"

    agent_claim = claims[result["claim_id"]]
    assert agent_claim.object == "Globex Corp"
    assert agent_claim.valid_to is None  # coexists, also open


def test_write_claim_with_observer_rodrigo_lands_in_its_own_perspective_slot(tmp_path):
    """observer='rodrigo' vs observer='agent' are different K-slots (perspectival
    claims) — a later agent write about the same fact never even collides with,
    let alone touches, what Rodrigo stated about himself."""
    first = agentic_write.write_claim(
        tmp_path, "Rodrigo", "works-at", "Acme Robotics", observer="rodrigo",
    )
    second = agentic_write.write_claim(
        tmp_path, "Rodrigo", "works-at", "Globex Corp", observer="agent",
    )
    assert first["action"] == "written"
    assert second["action"] == "written"

    page = tmp_path / "entities" / "rodrigo.md"
    claims = {c.id: c for c in parse_claims(markdown_parser.parse(page).body)}
    human = claims[first["claim_id"]]
    assert human.object == "Acme Robotics"
    assert human.valid_to is None
    assert human.superseded_by is None


# --------------------------------------------------------------------------- #
# list_unprocessed_episodes / mark_episodes_processed
# --------------------------------------------------------------------------- #


def _write_episode(memory_path, ep_id, title, content, processed):
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(
        episodes_dir / f"{ep_id}.md",
        {"id": ep_id, "title": title, "processed": processed},
        content,
    )


def test_list_unprocessed_episodes_returns_only_unprocessed(tmp_path):
    _write_episode(tmp_path, "ep_2026-01-01_001", "First", "raw chunk one", False)
    _write_episode(tmp_path, "ep_2026-01-02_001", "Second", "raw chunk two", True)
    _write_episode(tmp_path, "ep_2026-01-03_001", "Third", "raw chunk three", False)

    result = agentic_write.list_unprocessed_episodes(tmp_path)
    ids = {ep["id"] for ep in result}
    assert ids == {"ep_2026-01-01_001", "ep_2026-01-03_001"}
    for ep in result:
        assert "content" in ep and "title" in ep


def test_list_unprocessed_episodes_respects_limit(tmp_path):
    for i in range(5):
        _write_episode(tmp_path, f"ep_2026-01-0{i+1}_001", f"Ep {i}", "chunk", False)
    result = agentic_write.list_unprocessed_episodes(tmp_path, limit=2)
    assert len(result) == 2


def test_mark_episodes_processed_flips_flag(tmp_path):
    _write_episode(tmp_path, "ep_2026-01-01_001", "First", "raw chunk one", False)
    _write_episode(tmp_path, "ep_2026-01-02_001", "Second", "raw chunk two", False)

    count = agentic_write.mark_episodes_processed(tmp_path, ["ep_2026-01-01_001"])
    assert count == 1

    fm1 = markdown_parser.parse(tmp_path / "episodes" / "ep_2026-01-01_001.md").frontmatter
    fm2 = markdown_parser.parse(tmp_path / "episodes" / "ep_2026-01-02_001.md").frontmatter
    assert fm1["processed"] is True
    assert fm2["processed"] is False

    remaining = agentic_write.list_unprocessed_episodes(tmp_path)
    assert {ep["id"] for ep in remaining} == {"ep_2026-01-02_001"}


def test_mark_episodes_processed_missing_ids_returns_zero(tmp_path):
    _write_episode(tmp_path, "ep_2026-01-01_001", "First", "raw chunk one", False)
    count = agentic_write.mark_episodes_processed(tmp_path, ["ep_does_not_exist"])
    assert count == 0


# --------------------------------------------------------------------------- #
# write_claim never raises on bad input
# --------------------------------------------------------------------------- #


def test_write_claim_missing_fields_returns_error_not_raise(tmp_path):
    result = agentic_write.write_claim(tmp_path, "", "", "", observer="agent")
    assert result["action"] == "error"
    assert "error" in result


# --------------------------------------------------------------------------- #
# MCP-level: registration + dispatch
# --------------------------------------------------------------------------- #


def test_cicada_write_claim_registered_in_tools():
    server = _load_server()
    names = {t["name"] for t in server.TOOLS}
    assert "cicada_write_claim" in names
    assert "cicada_pending" in names
    assert "cicada_mark_processed" in names

    tool = {t["name"]: t for t in server.TOOLS}["cicada_write_claim"]
    desc = tool["description"].lower()
    assert "observer='rodrigo'" in desc or "observer= 'rodrigo'" in desc or "rodrigo" in desc
    assert "agent" in desc
    assert set(tool["inputSchema"]["required"]) == {"subject", "predicate", "object"}


def test_cicada_write_claim_dispatches_via_handle_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    server = _load_server()

    out = server.handle_tool(
        "cicada_write_claim",
        {
            "subject": "Rodrigo",
            "predicate": "prefers",
            "object": "dark mode",
            "observer": "rodrigo",
        },
    )
    assert "Recorded" in out
    assert "rodrigo" in out.lower()

    page = tmp_path / "entities" / "rodrigo.md"
    assert page.exists()


def test_cicada_pending_and_mark_processed_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    server = _load_server()

    _write_episode(tmp_path, "ep_2026-02-01_001", "Standup", "we discussed X", False)

    pending_out = server.handle_tool("cicada_pending", {})
    assert "ep_2026-02-01_001" in pending_out

    mark_out = server.handle_tool(
        "cicada_mark_processed", {"episode_ids": ["ep_2026-02-01_001"]}
    )
    assert "Marked 1" in mark_out

    fm = markdown_parser.parse(tmp_path / "episodes" / "ep_2026-02-01_001.md").frontmatter
    assert fm["processed"] is True
