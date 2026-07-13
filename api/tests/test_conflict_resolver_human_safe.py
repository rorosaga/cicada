"""M5e review MUST-FIX: the LIVE Stage-5 write path must not overwrite human prose.

The adversarial review found that ``conflict_resolver.apply_changes`` ran the LLM
synthesis path UNCONDITIONALLY and replaced page sections wholesale with the
synthesized body (and otherwise fell back to bare ``merge_sections_fallback`` with
no ``human_edited`` gate). A hand-edited Summary on a real page could therefore be
silently rewritten by a live Sleep cycle — the prose-level twin of "an agent claim
closing a human claim", which the spec (§8 / rule 3c) forbids.

These tests pin the live path: on a human-edited page (``human_edited: true`` in
frontmatter, or a non-canonical hand-added section), the agent merge is
ADDITIVE-ONLY — every existing human line survives verbatim, the agent may only ADD.
Agent-only pages keep full synthesis/merge behavior (no regression).

Hermetic: no LLM, no network. ``synthesized_body`` is injected directly into the
change dict (it would otherwise come from ``_synthesize_entity_update``), so the
guard is exercised without a live model call.
"""

from __future__ import annotations

from api.services import conflict_resolver, markdown_parser


def _write_entity(memory_path, stem, frontmatter, body):
    entities_dir = memory_path / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(entities_dir / f"{stem}.md", frontmatter, body)


def test_human_edited_summary_not_overwritten_by_synthesis(tmp_path):
    # A page the human edited (frontmatter flag) with their own Summary.
    _write_entity(
        tmp_path,
        "cicada",
        {"name": "Cicada", "type": "project", "status": "active", "human_edited": True},
        "## Summary\nRodrigo's own words about the project.\n",
    )
    # The synthesis LLM produced an entirely different Summary — this MUST NOT
    # wipe the human sentence on a human-edited page.
    change = {
        "id": "cicada",
        "action": "update",
        "entity": {"name": "Cicada", "type": "project", "summary": "Agent rewrite."},
        "synthesized_body": "## Summary\nAn entirely different agent summary.\n",
    }
    conflict_resolver.apply_changes([change], tmp_path)

    body = markdown_parser.parse(tmp_path / "entities" / "cicada.md").body
    assert "Rodrigo's own words about the project." in body, (
        "live Stage-5 must not regenerate-away a human-edited Summary"
    )


def test_non_canonical_human_section_survives_live_update(tmp_path):
    # No frontmatter flag, but a hand-added "## My Notes" heading marks the page
    # as human-edited (non-canonical section present).
    _write_entity(
        tmp_path,
        "cicada",
        {"name": "Cicada", "type": "project", "status": "active"},
        "## Summary\nA project.\n\n## My Notes\n- Private note: ship by Friday.\n",
    )
    change = {
        "id": "cicada",
        "action": "update",
        "entity": {
            "name": "Cicada",
            "type": "project",
            "summary": "Agent rewrite.",
            "key_facts": ["Uses FastAPI."],
        },
        "synthesized_body": "## Summary\nAgent rewrite, no My Notes.\n",
    }
    conflict_resolver.apply_changes([change], tmp_path)

    body = markdown_parser.parse(tmp_path / "entities" / "cicada.md").body
    assert "## My Notes" in body, "hand-added human section must survive a live update"
    assert "Private note: ship by Friday." in body


def test_agent_only_page_still_merges_synthesis(tmp_path):
    # An agent-only page (no human edit, only canonical sections) keeps the
    # existing behavior: the synthesized body is adopted. No regression.
    _write_entity(
        tmp_path,
        "fastapi",
        {"name": "FastAPI", "type": "tool", "status": "active"},
        "## Summary\nOld agent summary.\n",
    )
    change = {
        "id": "fastapi",
        "action": "update",
        "entity": {"name": "FastAPI", "type": "tool", "summary": "New."},
        "synthesized_body": "## Summary\nA refreshed agent summary about FastAPI.\n",
    }
    conflict_resolver.apply_changes([change], tmp_path)

    body = markdown_parser.parse(tmp_path / "entities" / "fastapi.md").body
    assert "A refreshed agent summary about FastAPI." in body


def test_agent_only_page_no_synthesis_merges_key_facts(tmp_path):
    # The common live update path: an agent-only page, no synthesized_body. The
    # deterministic section merge must still union new Key Facts (no regression
    # from the restructured branch).
    _write_entity(
        tmp_path,
        "fastapi",
        {"name": "FastAPI", "type": "tool", "status": "active"},
        "## Summary\nA web framework.\n\n## Key Facts\n- Async-first.\n",
    )
    change = {
        "id": "fastapi",
        "action": "update",
        "entity": {
            "name": "FastAPI",
            "type": "tool",
            "key_facts": ["Built on Starlette."],
        },
    }
    conflict_resolver.apply_changes([change], tmp_path)

    body = markdown_parser.parse(tmp_path / "entities" / "fastapi.md").body
    assert "Async-first." in body, "existing fact preserved"
    assert "Built on Starlette." in body, "new fact merged in"
