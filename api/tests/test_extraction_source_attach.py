"""G61 phase 2 S1 — a link the cited words already contain becomes a source
for that fact at extraction: zero LLM, no prompt change (spec §5.2, plan R-AC33)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from api.services import claim_pipeline, evidence, fact_sources, markdown_parser, predicates
from api.services.claims import parse_claims

EP = "ep_2026-09-20_001"
LINK = "https://example.com/company-b/team"


def _settings(memory: Path):
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano",
                           archive_threshold=0.2, decay_nudge_threshold=0.4)


def _bank(tmp_path: Path, line: str) -> tuple[Path, str]:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    for eid, etype in (("bob-example", "person"), ("alpha-project", "project")):
        markdown_parser.write(memory / "entities" / f"{eid}.md",
                              {"name": eid.replace("-", " ").title(), "type": etype, "status": "active"},
                              "## Summary\nA synthetic fixture.\n")
    markdown_parser.write(memory / "episodes" / f"{EP}.md",
                          {"id": EP, "timestamp": "2026-09-20T10:00:00+00:00", "processed": False},
                          f"user: {line}\n")
    return memory, evidence.source_text(memory, EP)


def _span(text: str, quote: str, *, hash_: str | None = None) -> dict:
    start = text.index(quote)
    return {"episode": EP, "start": start, "end": start + len(quote), "kind": "user",
            "hash": evidence.body_hash(text) if hash_ is None else hash_}


def _run(memory: Path, rels: list[dict]) -> None:
    claim_pipeline.run_claim_pipeline([{
        "episode_id": EP, "origin": "claude-code",
        "relationships": [{**r, "source_episode": EP, "source_episode_timestamp": "2026-09-20T10:00:00"}
                          for r in rels],
    }], [], memory, _settings(memory))


def _claim(memory: Path, subject: str, predicate: str):
    body = markdown_parser.parse(memory / "entities" / f"{subject}.md").body
    return next(c for c in parse_claims(body) if c.predicate == predicate)


def test_a_link_in_the_cited_words_becomes_a_source_for_that_fact(tmp_path):
    line = f"bob-example moved to company-b; the team page {LINK} lists him."
    memory, text = _bank(tmp_path, line)
    rel = {"source": "bob-example", "target": "company-b", "label": "works at", "evidence": [_span(text, line)]}
    _run(memory, [rel])
    claim = _claim(memory, "bob-example", "works-at")
    assert claim.authored_by and claim.authored_by != "user"
    assert fact_sources.list_sources(memory, "bob-example") == [{
        "ref": LINK, "kind": "url", "predicate": "works-at",
        "added_by": claim.authored_by, "added_at": str(date.today())}]
    _run(memory, [rel])
    assert len(fact_sources.list_sources(memory, "bob-example")) == 1, "the next cycle adds nothing"


def test_an_artifact_fact_gets_one_too(tmp_path):
    line = f"alpha-project runs on tool-b, see {LINK}"
    memory, text = _bank(tmp_path, line)
    _run(memory, [{"source": "alpha-project", "target": "tool-b", "label": "runs on",
                   "evidence": [_span(text, line)]}])
    assert [s["predicate"] for s in fact_sources.list_sources(memory, "alpha-project")] == ["runs-on"]


def test_a_person_or_unknown_fact_gets_none(tmp_path):
    line = f"bob-example is considering company-b ({LINK}) and relates to https://example.com/other."
    memory, text = _bank(tmp_path, line)
    _run(memory, [
        {"source": "bob-example", "target": "company-b", "label": "considering", "evidence": [_span(text, line)]},
        {"source": "bob-example", "target": "alpha-project", "label": "relates to",
         "evidence": [_span(text, line)]},
    ])
    assert fact_sources.list_sources(memory, "bob-example") == []


def test_a_stale_span_or_a_reasoning_entry_attaches_nothing(tmp_path):
    line = f"bob-example moved to company-b; the team page {LINK} lists him."
    memory, text = _bank(tmp_path, line)
    _run(memory, [
        {"source": "bob-example", "target": "company-b", "label": "works at",
         "evidence": [_span(text, line, hash_="000000000000")]},
        {"source": "bob-example", "target": "company-a", "label": "works at",
         "evidence": [{"episode": EP, "start": -1, "end": -1, "kind": "reasoning", "hash": ""}]},
    ])
    assert fact_sources.list_sources(memory, "bob-example") == []


def test_at_most_three_links_per_claim_in_the_order_said(tmp_path):
    links = [f"https://example.com/p{i}" for i in range(5)]
    line = "bob-example works at company-b: " + ", ".join(links) + "."
    memory, text = _bank(tmp_path, line)
    _run(memory, [{"source": "bob-example", "target": "company-b", "label": "works at",
                   "evidence": [_span(text, line)]}])
    assert [s["ref"] for s in fact_sources.list_sources(memory, "bob-example")] == links[:3]
