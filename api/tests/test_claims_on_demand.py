"""Stage 5.56's question refresh reads only the pages its open questions name (F7, benchmarks/scale).

`refresh_open_questions` looks up the claims of each open conflict question's subject, but was handed every page's
claims, parsed again right after the claim pipeline read and wrote them: one full-bank YAML pass a batch (~3.5 s on a
2,000-page synthetic bank), and another on every idle cycle.
"""
from __future__ import annotations

from api.services import claim_pipeline, inbox_questions, markdown_parser, sleep_cycle
from api.services.claims import Claim, write_claims
from api.tests.test_claim_pipeline import _seed_workspace, _write_entity


def _page(memory, stem, n):
    rows = [Claim(id=f"clm_{stem}_{i}", text=f"{stem} fact {i}.", subject=stem, predicate="runs-on",
                  object=f"machine-{i}", valid_from="2026-09-01") for i in range(n)]
    _write_entity(memory, stem, {"name": stem.title(), "type": "tool"}, write_claims("## Summary\nSynthetic.", rows))


def test_on_demand_view_equals_the_full_load(tmp_path):
    memory = _seed_workspace(tmp_path)
    for i, stem in enumerate(("alpha-tool", "beta-tool", "gamma-tool")):
        _page(memory, stem, i + 1)
    _write_entity(memory, "no-fence", {"name": "No Fence", "type": "concept"}, "## Summary\nProse only.")
    full = claim_pipeline._load_existing_claims_by_subject(memory)
    lazy = claim_pipeline.claims_on_demand(memory)
    for subject in [*full, "missing-page", "../episodes/x", ""]:
        assert lazy.get(subject, []) == full.get(subject, []), subject


def test_refresh_parses_only_the_subjects_of_open_questions(tmp_path, monkeypatch):
    memory = _seed_workspace(tmp_path)
    for stem in ("alpha-tool", "beta-tool", "gamma-tool"):
        _page(memory, stem, 2)
    (memory / "inbox").mkdir()
    markdown_parser.write(memory / "inbox" / "inbox-001.md", {
        "kind": "conflict", "status": "pending", "entity_id": "beta-tool", "predicate": "runs-on",
        "options": [{"key": "a", "claim_id": "clm_beta-tool_0"}, {"key": "b", "claim_id": "clm_beta-tool_1"}],
        "created_date": "2026-09-01"}, "Which machine?")
    opened = []
    original = markdown_parser.parse

    def spying(path):
        if path.parent.name == "entities":
            opened.append(path.stem)
        return original(path)

    monkeypatch.setattr(markdown_parser, "parse", spying)
    inbox_questions.refresh_open_questions(memory, claim_pipeline.claims_on_demand(memory), "2026-09-02",
                                           stale_after_days=30)
    assert opened == ["beta-tool"]


def test_sleep_never_loads_every_page_for_the_question_refresh(tmp_path, monkeypatch):
    import asyncio
    from api.config import Settings

    memory = _seed_workspace(tmp_path)
    _page(memory, "alpha-tool", 2)
    monkeypatch.setattr(claim_pipeline, "_load_existing_claims_by_subject",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("full-bank load")))
    calls = []
    monkeypatch.setattr(inbox_questions, "refresh_open_questions",
                        lambda memory_path, claims_by_subject, today, **kw: calls.append(claims_by_subject) or
                        {"bumped": 0, "escalated": 0, "organic_resolutions": 0, "resolved_paths": []})
    asyncio.run(sleep_cycle._refresh_questions_safely(memory, Settings(_env_file=None, CICADA_MEMORY_PATH=str(memory))))
    assert len(calls) == 1 and calls[0].get("alpha-tool", [])
