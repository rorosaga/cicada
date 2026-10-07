"""Stage-5 prose rewrites retain disk claim fences without authoring claims."""
import asyncio
import re
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import claims, conflict_resolver, markdown_parser

FENCE = "```claims\n- id: clm_old\n  text: Synthetic fact.\n  subject: alpha-project\n  predicate: uses\n  object: sqlite\n  future_field: retained\n```\n"
SECOND = FENCE.replace("clm_old", "clm_second").replace("sqlite", "queue-tool")
MALFORMED = "```claims\n- id: [unterminated\n```\n"
RAW_FENCES = re.compile(r"^```claims[^\r\n]*\r?\n.*?^```[ \t]*\r?$", re.M | re.S)
SHAPES = {
    "related-tail": "## Summary\nOriginal.\n\n## Related\n- [[primary-machine]]\n\n" + FENCE,
    "facts-tail": "## Summary\nOriginal.\n\n## Key Facts\n- Existing fact.\n\n" + FENCE,
    "mid-page": "## Summary\nOriginal.\n\n" + FENCE + "\n## Links\n- https://example.com\n",
    "two-fences": "## Summary\nOriginal.\n\n" + FENCE + "\n## Key Facts\n- Existing fact.\n\n" + SECOND,
    "malformed-related": "## Summary\nOriginal.\n\n## Related\n- [[primary-machine]]\n\n" + MALFORMED,
    "malformed-facts": "## Summary\nOriginal.\n\n## Key Facts\n- Existing fact.\n\n" + MALFORMED,
    "malformed-mid-page": "## Summary\nOriginal.\n\n" + MALFORMED + "\n## Links\n- https://example.com\n",
    "raw-spacing": "## Summary\nOriginal.\n\n" + FENCE.replace("```claims\n", "```claims \t\n").replace("\n```\n", "\n``` \t\n") + "\n## Links\n- https://example.com\n",
}


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("mode", ["synthesis-prose", "synthesis-foreign", "fallback", "human"])
def test_entity_update_preserves_raw_disk_fences(tmp_path, shape, mode):
    bank = tmp_path / "bank"
    path = bank / "entities" / "alpha-project.md"
    path.parent.mkdir(parents=True)
    body = SHAPES[shape]
    markdown_parser.write(path, {
        "id": "alpha-project", "name": "alpha-project", "type": "project",
        "confidence": 0.8, "related": ["primary-machine"], "human_edited": mode == "human",
    }, body)
    original = RAW_FENCES.findall(markdown_parser.parse(path).body)
    synthesis = "## Summary\nUpdated prose.\n\n## Key Facts\n- New fact.\n"
    if mode == "synthesis-foreign":
        synthesis += "\n```claims\n- id: invented\n```\n"
    conflict_resolver.apply_changes([{
        "id": "alpha-project", "action": "update",
        "entity": {"name": "alpha-project", "type": "project", "confidence": 0.8},
        "synthesized_body": synthesis if mode.startswith("synthesis") else None,
    }], bank)
    actual = path.read_text()
    assert RAW_FENCES.findall(actual) == original
    assert "invented" not in actual
    if shape.startswith("malformed"):
        with pytest.raises(claims.MalformedClaimsBlockError):
            claims.parse_claims(actual, strict=True)
    else:
        assert [claim.id for claim in claims.parse_claims(actual, strict=True)] == (
            ["clm_old"]
        )


def test_synthesis_prompt_strips_fences_before_prose_budget(monkeypatch):
    prompts = []

    def resolve(*args, **kwargs):
        async def complete(**call):
            prompts.append(call["messages"][0]["content"])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="## Summary\nUpdated."))])
        return complete

    monkeypatch.setattr(conflict_resolver, "resolve_llm_fn", resolve)
    body = "## Summary\nOriginal.\n\n```claims\n" + "private_machine_field: x\n" * 400 + "```\n\n## Links\nPROSE_AFTER_FENCE\n"
    asyncio.run(conflict_resolver._synthesize_entity_update(
        "alpha-project", "project", body, "New description.", [], None, Settings(_env_file=None),
    ))
    assert "PROSE_AFTER_FENCE" in prompts[0]
    assert "private_machine_field" not in prompts[0]
    assert "```claims" not in prompts[0]
