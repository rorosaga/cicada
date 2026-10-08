"""The claim write-back renders only the pages whose claims changed (F6, benchmarks/scale).

`reconcile_stage3` returns every subject in the bank, and the write-back rendered each one's fence (pure-Python
`yaml.dump`) to find that ~1,940 of 2,006 were byte-identical: 8 s a batch on a 2,000-page synthetic bank, 1.4 s of it
the owner's page alone. The counts the cycle reports, and every byte on disk, are unchanged.
"""
from __future__ import annotations

from api.services import claim_pipeline, markdown_parser
from api.services.claims import Claim, parse_claims, write_claims
from api.tests.test_claim_pipeline import _extracted, _seed_workspace, _settings, _write_entity


def _seed(memory, day="2026-06-16"):
    _write_entity(memory, "cicada", {"name": "Cicada", "type": "project", "status": "active"}, "## Summary\nA memory system.")
    for stem in ("alpha-tool", "beta-tool"):
        rows = [Claim(id=f"clm_{stem}_{i}", text=f"{stem} fact {i}.", subject=stem, predicate="supports",
                      object=f"gamma-{i}", valid_from=day, recorded_at=day, decayed_through=day, confidence=0.8)
                for i in range(3)]
        _write_entity(memory, stem, {"name": stem.title(), "type": "tool", "status": "active",
                                     "last_referenced": day, "decayed_through": day},
                      write_claims("## Summary\nA synthetic tool.", rows))


def _spy(monkeypatch):
    rendered = []
    original = claim_pipeline.write_claims

    def spying(body, claims):
        rendered.append(claims[0].subject if claims else None)
        return original(body, claims)

    monkeypatch.setattr(claim_pipeline, "write_claims", spying)
    return rendered


def test_only_the_page_that_gained_a_claim_is_rendered(tmp_path, monkeypatch):
    memory = _seed_workspace(tmp_path)
    _seed(memory)
    before = {p.name: p.read_bytes() for p in (memory / "entities").glob("*.md")}
    rendered = _spy(monkeypatch)
    result = claim_pipeline.run_claim_pipeline(
        _extracted([{"source": "Cicada", "target": "sqlite-vec", "label": "uses"}]), [], memory, _settings(memory),
        now_date="2026-06-17", decay=False)
    assert rendered == ["cicada"]
    # What the cycle reports is unchanged: every subject with claims counts as written, as before.
    assert result["subjects_written"] == 3
    assert result["claims_written"] == 7
    after = {p.name: p.read_bytes() for p in (memory / "entities").glob("*.md")}
    assert after["alpha-tool.md"] == before["alpha-tool.md"] and after["beta-tool.md"] == before["beta-tool.md"]
    assert any(c.object == "sqlite-vec" for c in parse_claims(markdown_parser.parse(memory / "entities" / "cicada.md").body))


def test_a_page_decay_changed_is_still_written(tmp_path, monkeypatch):
    memory = _seed_workspace(tmp_path)
    _seed(memory, day="2025-01-01")
    before = (memory / "entities" / "alpha-tool.md").read_bytes()
    rendered = _spy(monkeypatch)
    claim_pipeline.run_claim_pipeline(
        _extracted([{"source": "Cicada", "target": "sqlite-vec", "label": "uses"}]), [], memory, _settings(memory),
        now_date="2026-06-17", decay=True)
    assert sorted(rendered) == ["alpha-tool", "beta-tool", "cicada"]
    # The decay pass changed these claims: the page is written even though no claim was added.
    assert (memory / "entities" / "alpha-tool.md").read_bytes() != before
