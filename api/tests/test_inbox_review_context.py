"""The quick review's context (owner 2026-10-19): a decay or fold card carries enough to decide without opening the
page — what the page is, in how many conversations it was said and when last, and a fold's two names. Derived at read
on `GET /inbox`, additive and camelCase; every other kind carries neither field; a failure never costs the card; the
read writes nothing. Synthetic data only."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, inbox_review, inbox_service, markdown_parser
from api.services.claims import Claim, write_claims


def _bank(root: Path) -> Path:
    memory = root / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    # Three dated conversations and one memory-export entry: the export is no conversation and says no day.
    for stem in ("ep_2026-03-02_001", "ep_2026-05-20_001", "ep_2026-05-20_002"):
        markdown_parser.write(memory / "episodes" / f"{stem}.md", {"id": stem, "source": "mcp"}, "user: hi")
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md",
                          {"id": "ep_2026-09-01_001", "source": "claude_memory"}, "memory entry")
    markdown_parser.write(memory / "entities" / "alpha-project.md", {
        "name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.35,
        "last_referenced": "2026-05-20",
        "source_episodes": ["ep_2026-03-02_001", "ep_2026-05-20_001", "ep_2026-05-20_002", "ep_2026-09-01_001",
                            "ep_2026-05-20_001"],
    }, "## Summary\nA synthetic side project about example datasets. It has a second sentence.\n")
    body = write_claims("## Summary\nA synthetic library.\n", [
        Claim(id="clm_fold", text="Beta Library is built with Example Toolkit", subject="beta-library",
              predicate="uses", object="example-toolkit", recorded_at="2026-06-01"),
    ])
    markdown_parser.write(memory / "entities" / "beta-library.md", {
        "name": "Beta Library", "type": "tool", "status": "active", "summary": "A synthetic library.",
        "source_episodes": ["ep_2026-03-02_001"]}, body)
    markdown_parser.write(memory / "entities" / "gamma-tool.md", {
        "name": "Gamma Tool", "type": "tool", "status": "active"}, "## Summary\nAnother.\n")
    markdown_parser.write(memory / "inbox" / "inbox-001.md", {
        "kind": "decay", "required_input": "choice", "status": "pending", "priority": 0.35,
        "entity_id": "alpha-project", "entity_name": "Alpha Project",
        "title": "No recent mentions of Alpha Project", "created_date": "2026-10-01"}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-002.md", {
        "kind": "normalization", "required_input": "choice", "status": "pending", "priority": 0.3,
        "entity_id": "beta-library", "entity_name": "Beta Library", "claim_id": "clm_fold",
        "title": "Confirm a predicate fold for Beta Library", "created_date": "2026-10-01",
        "options": ["Correct fold", "Wrong fold — keep separate"],
        "raw_predicate": "built with", "canonical_predicate": "uses",
        "covered_claims": [{"entity_id": "gamma-tool", "claim_id": "clm_other"},
                           {"entity_id": "beta-library", "claim_id": "clm_more"}],
    }, "Predicate 'built with' was auto-folded to canonical 'uses'.")
    markdown_parser.write(memory / "inbox" / "inbox-003.md", {
        "kind": "clarification", "required_input": "freetext", "status": "pending", "priority": 0.5,
        "entity_id": "delta-example", "entity_name": "Delta Example", "title": "Who is Delta Example?",
        "question": "Who is Delta Example?", "created_date": "2026-10-01"}, "ctx")
    return memory


@pytest.fixture
def memory(tmp_path):
    bank_index.invalidate()
    return _bank(tmp_path)


def test_a_decay_card_says_what_the_page_is_and_how_often_it_was_said(memory):
    item = {i.id: i for i in inbox_service.load_inbox(memory)}["inbox-001"]
    assert item.subject is not None
    assert item.subject.conversations == 3          # the export entry and the repeat are not conversations
    assert item.subject.last_said == "2026-05-20"   # the export's later day says nothing about when
    assert item.subject.summary == "A synthetic side project about example datasets."
    assert item.fold is None


def test_a_fold_card_names_both_predicates_and_what_it_covers(memory):
    item = {i.id: i for i in inbox_service.load_inbox(memory)}["inbox-002"]
    assert item.fold is not None
    assert (item.fold.raw, item.fold.canonical) == ("built with", "uses")
    assert (item.fold.claims, item.fold.pages) == (3, 2)
    assert item.fold.example == "Beta Library is built with Example Toolkit"
    assert item.subject is not None and item.subject.summary == "A synthetic library."
    # The answers the review maps to Same / Different are the item's own keys.
    assert [o.key for o in item.options] == ["0", "1"]


def test_other_kinds_carry_neither_field(memory):
    item = {i.id: i for i in inbox_service.load_inbox(memory)}["inbox-003"]
    assert item.subject is None and item.fold is None


def test_a_legacy_fold_with_no_pair_has_no_fold_block(memory):
    path = memory / "inbox" / "inbox-002.md"
    parsed = markdown_parser.parse(path)
    fm = {k: v for k, v in parsed.frontmatter.items() if k not in ("raw_predicate", "canonical_predicate")}
    markdown_parser.write(path, fm, parsed.body)
    bank_index.invalidate()
    item = {i.id: i for i in inbox_service.load_inbox(memory)}["inbox-002"]
    assert item.fold is None and item.subject is not None


def test_a_failure_costs_the_field_never_the_card(memory, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(inbox_review, "subject_for", broken)
    items = {i.id: i for i in inbox_service.load_inbox(memory)}
    assert set(items) == {"inbox-001", "inbox-002", "inbox-003"}
    assert items["inbox-001"].subject is None


def test_clip_keeps_the_first_sentence_and_cuts_on_a_word():
    assert inbox_review.clip("One.  Two.") == "One."
    long = "word " * 80
    out = inbox_review.clip(long, limit=40)
    assert out.endswith("…") and len(out) <= 40 and not out[:-1].endswith(" ")
    assert inbox_review.clip("   ") is None


def test_get_inbox_carries_the_review_context_in_camel_case_and_writes_nothing(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(memory.parent / "home"))
    config.get_settings.cache_clear()
    def files():
        # The bank's own files; startup's derived indexes (disposable, built in the background) are not the read's.
        return sorted((p.relative_to(memory), p.stat().st_mtime_ns)
                      for sub in ("entities", "episodes", "inbox") for p in (memory / sub).rglob("*") if p.is_file())

    try:
        with TestClient(main.app) as c:
            before = files()    # after startup's own one-time migrations
            by_id = {i["id"]: i for i in c.get("/inbox").json()}
            after = files()
    finally:
        config.get_settings.cache_clear()
    assert by_id["inbox-001"]["subject"] == {
        "summary": "A synthetic side project about example datasets.", "conversations": 3, "lastSaid": "2026-05-20"}
    assert by_id["inbox-002"]["fold"]["raw"] == "built with"
    assert by_id["inbox-002"]["fold"]["canonical"] == "uses"
    assert by_id["inbox-003"]["subject"] is None
    assert before == after
