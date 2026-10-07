"""G148: page-prose prompts strip whole claims fences before clipping input."""
import asyncio
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import (
    conflict_resolver, dedup_sweep, entity_resolver, markdown_parser, mcp_tools,
    providers, skill_extractor, source_rewrite,
)


BUDGETS = {
    "synthesis": 6000, "contradiction": 4000, "rewrite": 4000,
    "dedup": 2500, "disambiguation": 2000, "patterns": 1200,
}
FENCE = "```claims\n- id: clm_synthetic\n  text: MACHINE_ONLY_SENTINEL\n```\n"


def _page(shape, budget):
    if shape == "large-fence":
        return "## Summary\nPROSE_BEFORE\n\n" + FENCE.replace(
            "MACHINE_ONLY_SENTINEL", "MACHINE_ONLY_SENTINEL" * budget,
        ) + "\n## History\nPROSE_AFTER\n"
    if shape == "cut-opening":
        return "x" * (budget - 3) + "\n" + FENCE
    if shape == "cut-content":
        return "x" * (budget - 45) + "\n" + FENCE
    if shape == "multiple":
        return FENCE + "## Summary\nPROSE_BEFORE\n" + FENCE + "PROSE_AFTER\n"
    if shape == "malformed-closed":
        return "```claims\n- id: [MACHINE_ONLY_SENTINEL\n```\nPROSE_AFTER\n"
    return "## Summary\nPROSE_BEFORE\n" + FENCE + "PROSE_AFTER\n"


@pytest.mark.parametrize("consumer", BUDGETS)
@pytest.mark.parametrize("shape", [
    "short", "large-fence", "cut-opening", "cut-content", "multiple", "malformed-closed",
])
def test_page_prose_prompt_excludes_fences_and_truncated_fragments(
    tmp_path, monkeypatch, consumer, shape,
):
    prompts = []
    body = _page(shape, BUDGETS[consumer])
    settings = Settings(_env_file=None)

    def sync_complete(**call):
        prompts.append(call["messages"][0]["content"])
        return {"choices": [{"message": {"content": "{}"}}]}

    def resolve_async(*args, **kwargs):
        async def complete(**call):
            sync_complete(**call)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="{}"),
            )])
        return complete

    if consumer == "rewrite":
        path = tmp_path / "entities" / "alpha-project.md"
        path.parent.mkdir()
        markdown_parser.write(path, {"name": "alpha-project", "type": "project"}, body)
        monkeypatch.setattr(source_rewrite, "gather_entity_sources", lambda *a, **kw: {
            "episodes": [{"chunk": "Synthetic source excerpt."}],
        })
        source_rewrite.rewrite_entity_from_sources(
            tmp_path, "alpha-project", settings, llm_fn=sync_complete,
        )
    elif consumer == "dedup":
        monkeypatch.setattr(providers, "resolve_llm_fn", lambda *a, **kw: sync_complete)
        dedup_sweep._default_judge_fn(settings)(body, body, "alpha-project", "beta-project")
    elif consumer == "disambiguation":
        monkeypatch.setattr(providers, "resolve_llm_fn", resolve_async)
        asyncio.run(entity_resolver._llm_judge_same_entity(
            "alpha", "project", "New description.", "alpha-project", "project", body, settings,
        ))
    elif consumer == "patterns":
        monkeypatch.setattr(skill_extractor, "resolve_llm_fn", resolve_async)
        asyncio.run(skill_extractor.detect_patterns(
            [{"id": "alpha-project", "action": "update", "entity": {"description": "New description."}}],
            [{"id": "alpha-project", "frontmatter": {"name": "alpha-project"}, "body": body}],
            settings,
        ))
    else:
        monkeypatch.setattr(conflict_resolver, "resolve_llm_fn", resolve_async)
        if consumer == "synthesis":
            asyncio.run(conflict_resolver._synthesize_entity_update(
                "alpha-project", "project", body, "New description.", [], None, settings,
            ))
        else:
            asyncio.run(conflict_resolver._detect_contradiction(
                "alpha-project", body, "New description.", settings,
            ))

    assert len(prompts) == 1
    prompt = prompts[0]
    assert "MACHINE_ONLY_SENTINEL" not in prompt
    assert "clm_synthetic" not in prompt
    assert "``" not in prompt, "even a truncated opening fence must be absent"
    if shape not in {"cut-opening", "cut-content"}:
        assert "PROSE_AFTER" in prompt, "fence bytes must not consume the prose budget"
    if shape in {"short", "large-fence", "multiple"}:
        assert "PROSE_BEFORE" in prompt


@pytest.mark.parametrize("shape", [
    "short", "large-fence", "cut-opening", "cut-content", "multiple", "malformed-closed",
])
def test_related_page_recall_blurb_excludes_fence_fragments(tmp_path, monkeypatch, shape):
    entities = tmp_path / "entities"
    entities.mkdir()
    markdown_parser.write(entities / "alpha-project.md", {
        "name": "alpha-project", "type": "project", "related": ["beta-project"],
    }, "Synthetic project.")
    markdown_parser.write(entities / "beta-project.md", {
        "name": "beta-project", "type": "project",
    }, _page(shape, 240))
    monkeypatch.setattr(mcp_tools, "_leann_search_entities", lambda *a, **kw: [{"entity_id": "alpha-project"}])
    monkeypatch.setattr(mcp_tools, "_keyword_search_entities", lambda *a, **kw: [])
    monkeypatch.setattr(mcp_tools, "_claim_subject_search", lambda *a, **kw: [])
    monkeypatch.setattr(mcp_tools, "_state_hint", lambda *a, **kw: None)
    ctx = mcp_tools.ToolContext(
        memory_path=lambda: tmp_path, session_id="synthetic-session", harness="agent", raw_excerpts=False,
    )
    output = mcp_tools.recall(ctx, "alpha-project")
    blurb = output.split("**Related (one hop out):**\n", 1)[1]
    assert "MACHINE_ONLY_SENTINEL" not in blurb
    assert "clm_synthetic" not in blurb
    assert "``" not in blurb
    if shape not in {"cut-opening", "cut-content"}:
        assert "PROSE_AFTER" in blurb
