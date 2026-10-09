"""G183 fix round 1, finding 3 — an inbox conflict answer's prose rewrite (a model call) runs outside the bank's
write admission; the admitted write re-plans on the page as it is then and uses the prose only if nothing moved."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from _synthetic_bank import _bank
from api.models.schemas import InboxResolveRequest
from api.services import conflict_resolver, inbox_service, markdown_parser, sleep_cycle, state_dictionary
from api.services import write_admission


@pytest.fixture
def memory(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    markdown_parser.write(
        memory / "inbox" / "conflict-review.md",
        {"kind": "conflict", "entity_id": "alpha-project", "entity_name": "Alpha Project", "predicate": "uses",
         "options": [{"key": "a", "label": "sqlite-vec", "claim_id": None},
                     {"key": "b", "label": "other", "claim_id": None}], "title": "Synthetic choice"},
        "Synthetic context")

    async def no_refresh(*a, **k):
        return None

    monkeypatch.setattr(state_dictionary, "refresh_and_commit", no_refresh)
    return memory


def _resolve(memory):
    return asyncio.run(inbox_service.resolve(
        "conflict-review", InboxResolveRequest(action="choose", option_key="a"), SimpleNamespace(memory_path=memory)))


def _page(memory) -> str:
    return (memory / "entities" / "alpha-project.md").read_text()


def test_opt_in_inbox_uses_shared_orientation_builder(memory, monkeypatch):
    from api.config import Settings
    from api.services import entity_body
    monkeypatch.setenv('CICADA_MEMORY_PATH', str(memory))
    seen = []
    async def completion(**kw):
        seen.append(kw['messages'][-1]['content'])
        assert write_admission.holders(memory) == 0
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"summary": "A synthetic project using local storage."}'))])
    monkeypatch.setattr(conflict_resolver.litellm, 'acompletion', completion)
    settings = Settings(_env_file=None, summary_synthesis_enabled=True)
    assert asyncio.run(inbox_service.resolve('conflict-review',
        InboxResolveRequest(action='choose', option_key='a'), settings))['status'] == 'resolved'
    assert len(seen) == 1 and 'SECTION-AWARE ORIENTATION' in seen[0]
    assert entity_body.parse_sections(markdown_parser.parse(
        memory / 'entities/alpha-project.md').body)['Summary'] == 'A synthetic project using local storage.'


def test_opt_in_inbox_skips_human_before_call(memory, monkeypatch):
    page = memory / 'entities/alpha-project.md'
    parsed = markdown_parser.parse(page)
    parsed.frontmatter['human_edited'] = True
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    async def synth(**kwargs):
        raise AssertionError('human page must skip model call')
    monkeypatch.setattr(conflict_resolver, '_synthesize_entity_update', synth)
    settings = SimpleNamespace(memory_path=memory, summary_synthesis_enabled=True)
    assert asyncio.run(inbox_service.resolve('conflict-review',
        InboxResolveRequest(action='choose', option_key='a'), settings))['status'] == 'resolved'


def test_the_model_call_holds_no_admission_and_its_prose_is_used(memory, monkeypatch):
    seen = []

    async def synth(**kw):
        seen.append(write_admission.holders(memory))
        return "## Summary\nRewritten prose about sqlite-vec.\n"

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", synth)
    assert _resolve(memory)["status"] == "resolved"
    assert seen == [0], "no admission while the model answers"
    assert "Rewritten prose about sqlite-vec." in _page(memory)


def test_a_page_that_moved_during_the_model_call_gets_the_fallback_not_stale_prose(memory, monkeypatch):
    async def synth(**kw):
        page = memory / "entities" / "alpha-project.md"
        parsed = markdown_parser.parse(page)
        markdown_parser.write(page, parsed.frontmatter, parsed.body + "\nAn edit made meanwhile.\n")
        return "## Summary\nStale prose.\n"

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", synth)
    assert _resolve(memory)["status"] == "resolved"
    page = _page(memory)
    assert "Stale prose." not in page
    assert "An edit made meanwhile." in page, "the edit made during the call survives"
    assert "sqlite-vec" in page, "the answer still lands (the fallback sentence)"


def test_a_window_that_opens_during_the_model_call_refuses_the_write(memory, monkeypatch):
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: state["writing"])
    before = _page(memory)

    async def synth(**kw):
        state["writing"] = True
        assert await asyncio.to_thread(write_admission.wait_for_writers, memory, give_up_after=1) is True, \
            "Sleep opens at once: the model call holds nothing"
        return "## Summary\nProse.\n"

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", synth)
    with pytest.raises(HTTPException) as err:
        _resolve(memory)
    assert err.value.status_code == 409
    assert _page(memory) == before and (memory / "inbox" / "conflict-review.md").exists()


def test_prose_made_for_a_different_answer_is_never_used(memory, monkeypatch):
    """Fix round 2, finding 2: the option's label changed while the model wrote — same page body, different answer."""
    item = memory / "inbox" / "conflict-review.md"

    async def synth(**kw):
        parsed = markdown_parser.parse(item)
        fm = dict(parsed.frontmatter)
        fm["options"] = [{"key": "a", "label": "postgres-example", "claim_id": None},
                         {"key": "b", "label": "other", "claim_id": None}]
        markdown_parser.write(item, fm, parsed.body)
        return "## Summary\nUses sqlite-vec (confirmed by user).\n"

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", synth)
    assert _resolve(memory)["status"] == "resolved"
    page = _page(memory)
    assert "sqlite-vec (confirmed by user)" not in page, "prose for the old answer"
    assert "postgres-example" in page, "the answer the item holds now lands (the fallback)"


def test_an_answer_on_an_article_page_lands_as_a_key_fact_and_survives_the_next_merge(memory, monkeypatch):
    """Review B4 (G194): on a stamped article page the answer was appended as free text inside the last section,
    which the next merge rebuilds from bullets — losing the only record of a pick with no claim."""
    from api.services import entity_article, entity_body

    page = memory / "entities/alpha-project.md"
    parsed = markdown_parser.parse(page)
    prose = ("## Summary\nAlpha Project is a synthetic project.\n\n## Article\n### What it is\n\n"
             "Alpha Project stores vectors locally.\n\n## Key Facts\n- Uses local storage.\n\n"
             "## Open Questions\n- Which index?")
    entity_article.stamp(parsed.frontmatter, entity_body.parse_sections(prose))
    markdown_parser.write(page, parsed.frontmatter, prose)

    async def synth(**kwargs):
        raise AssertionError("an article page gets no prose rewrite")

    monkeypatch.setattr(conflict_resolver, "_synthesize_entity_update", synth)
    assert _resolve(memory)["status"] == "resolved"
    from api.services.claims import strip_claims_block

    after = markdown_parser.parse(page)
    sections = entity_body.parse_sections(strip_claims_block(after.body))
    facts = entity_body._bullet_lines(sections["Key Facts"])
    assert any("sqlite-vec" in f for f in facts)
    assert sections["Open Questions"] == "- Which index?"
    assert entity_article.stamped(after.frontmatter, sections)
    # The next deterministic merge keeps it.
    merged = entity_body.merge_sections_fallback(sections, {"key_facts": ["Another fact."]})
    assert any("sqlite-vec" in f for f in entity_body._bullet_lines(merged["Key Facts"]))


def test_an_answer_as_a_key_fact_keeps_free_text_in_the_record():
    """Review N1 (G194): the answer is one appended Key Facts bullet; no section is rebuilt from its bullets, so free
    text a legacy writer left in Key Facts or History stays."""
    from api.services import entity_body

    prose = ("## Summary\nA synthetic page.\n\n## Article\n### What it is\n\nA synthetic project.\n\n"
             "## Key Facts\nThe deploy target moved to beta-host in 2025.\n- Uses SQLite.\n\n"
             "## History\nStarted as a side project.\n- 2026-01-10: First.")
    out = inbox_service._answer_as_key_fact(prose, "The person chose sqlite-vec.")
    sections = entity_body.parse_sections(out)
    assert "The deploy target moved to beta-host in 2025." in sections["Key Facts"]
    assert "Started as a side project." in sections["History"] and "- 2026-01-10: First." in sections["History"]
    assert entity_body._bullet_lines(sections["Key Facts"]) == ["Uses SQLite.", "The person chose sqlite-vec."]
    assert sections["Summary"] == "A synthetic page." and sections["Article"].endswith("A synthetic project.")
    assert inbox_service._answer_as_key_fact(out, "The person chose sqlite-vec.") == out   # once only
