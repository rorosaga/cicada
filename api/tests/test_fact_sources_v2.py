"""G61 phase 2 S0 — truthful hints and three small truths.

Spec: docs/superpowers/specs/2026-09-23-g61-agent-first-clarification-design.md
§2 (the pre-existing defects), §5.5 (the derived, voiced hint), §12
(`test_fact_sources_v2.py`); plan R-AC20…R-AC26. Synthetic names only
(bob-example, company-a, company-b, example.com); nothing reads a real bank or
the network.
"""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest

from api.services import (bank_index, fact_sources, inbox_generator, inbox_questions, inbox_service,
                          logo_service, markdown_parser, mcp_tools, search_index, text_fold)
from api.services.claim_reconciler import _conflict_nudge
from api.services.claims import Claim

TODAY = str(date.today())
TEAM = "https://example.com/staff-directory"


@pytest.fixture(autouse=True)
def _fresh_indexes():
    bank_index.invalidate()
    search_index.reset()
    yield
    search_index.reset()
    bank_index.invalidate()


def _bank(tmp_path: Path, *, sources: list[dict] | None = None) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    fm = {"name": "Bob Example", "type": "person", "status": "active", "confidence": 0.7,
          "created": "2026-01-01", "last_referenced": "2026-09-01", "source_episodes": [],
          "tags": [], "related": [], "version": 1}
    if sources is not None:
        fm["sources"] = sources
    markdown_parser.write(memory / "entities" / "bob-example.md", fm, "## Summary\nA synthetic person.\n")
    return memory


def _conflict(memory: Path, item_id: str = "inbox-001", **extra) -> Path:
    fm = {"kind": "conflict", "required_input": "choice", "status": "pending", "priority": 0.8,
          "entity_id": "bob-example", "entity_name": "Bob Example",
          "title": "Where does Bob Example work now?", "question": "Where does Bob Example work now?",
          "predicate": "works-at", "created_date": "2026-09-01", "allow_other": True,
          "allow_defer": True, "claim_id": "clm_b",
          "options": [{"key": "a", "label": "company-a", "claim_id": "clm_a"},
                      {"key": "b", "label": "company-b", "claim_id": "clm_b"}]}
    fm.update(extra)
    path = memory / "inbox" / f"{item_id}.md"
    markdown_parser.write(path, fm, "Conflicting beliefs.")
    return path


def _served(memory: Path, item_id: str = "inbox-001") -> str | None:
    bank_index.invalidate()
    return {i.id: i for i in inbox_service.load_inbox(memory)}[item_id].hint


# ---------- add_source is keyed on (ref, predicate) — R-AC20 ----------


def test_one_link_can_serve_two_facts(tmp_path):
    memory = _bank(tmp_path)
    for predicate in ("works-at", "located-in", "Works-At", None, None):
        fact_sources.add_source(memory, "bob-example", TEAM, predicate=predicate, added_at=TODAY)
    listed = fact_sources.list_sources(memory, "bob-example")
    assert [(s["ref"], s.get("predicate")) for s in listed] == [
        (TEAM, "works-at"), (TEAM, "located-in"), (TEAM, None)]


def test_a_repeat_add_returns_the_stored_entry_unchanged(tmp_path):
    memory = _bank(tmp_path)
    first = fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at",
                                    added_by="user", added_at="2026-09-01")
    again = fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at",
                                    added_by="claude-code", added_at="2026-09-02")
    assert again == first and again["added_by"] == "user"


# ---------- the voice follows added_by — R-AC22 ----------


@pytest.mark.parametrize("added_by, sentence", [
    ("user", f"You said {TEAM} is where to check this"),
    (None, f"You said {TEAM} is where to check this"),
    ("claude-code", f"Claude Code added {TEAM} as where to check this"),
    ("claude-web", f"Claude added {TEAM} as where to check this"),
    ("cicada", f"Cicada found {TEAM} as where to check this"),
    ("gpt-5.4-mini", f"An agent found {TEAM} as where to check this"),
    ("agent", f"An agent found {TEAM} as where to check this"),
    ("unknown", f"An agent found {TEAM} as where to check this"),
])
def test_the_hint_says_who_added_the_source_and_always_carries_the_ref(added_by, sentence):
    source = {"ref": TEAM, "kind": "url", "predicate": "works-at"}
    if added_by is not None:
        source["added_by"] = added_by
    assert fact_sources.hint_from([source], "works-at") == sentence


def test_the_user_voice_is_byte_identical_to_the_minimal_slice():
    assert fact_sources.hint_from([{"ref": TEAM, "kind": "url", "added_by": "user"}], "uses") == (
        "You said https://example.com/staff-directory is where to check this")


# ---------- derived at read, three readers — R-AC23 ----------


def test_a_source_added_after_the_item_opened_reaches_the_wire(tmp_path):
    memory = _bank(tmp_path)
    _conflict(memory)
    assert _served(memory) is None
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="claude-code")
    assert _served(memory) == f"Claude Code added {TEAM} as where to check this"


def test_a_source_added_after_the_item_opened_reaches_the_mcp_render(tmp_path):
    memory = _bank(tmp_path)
    path = _conflict(memory)
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at")
    parsed = markdown_parser.parse(path)
    fm, cause, rec = mcp_tools._agent_question(memory, parsed.frontmatter, TODAY)
    out = mcp_tools.render_question(fm, parsed.body, cause=cause, recommended_key=rec)
    assert f"Source to check: You said {TEAM} is where to check this" in out


def test_a_source_reaches_the_lexical_row_at_the_next_rebuild(tmp_path):
    memory = _bank(tmp_path)
    _conflict(memory)
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at")
    search_index.rebuild(memory)
    with search_index.Reader(memory) as r:
        hits = r.ranked("inb", search_index.match_expression(text_fold.query_tokens("directory")), 5)
        refs = sorted(d.ref for d in r.docs([d for d, _ in hits]).values())
    assert refs == ["inbox-001"]


def test_a_pre_s0_stored_hint_is_served_when_no_source_matches(tmp_path):
    memory = _bank(tmp_path)
    _conflict(memory, hint="You said https://example.com/old is where to check this")
    assert _served(memory) == "You said https://example.com/old is where to check this"


def test_a_current_source_replaces_a_stored_hint(tmp_path):
    memory = _bank(tmp_path, sources=[{"ref": TEAM, "kind": "url", "predicate": "works-at",
                                       "added_by": "cicada"}])
    _conflict(memory, hint="You said https://example.com/old is where to check this")
    assert _served(memory) == f"Cicada found {TEAM} as where to check this"


@pytest.mark.parametrize("raw", [5, TEAM, {"ref": TEAM}])
def test_a_malformed_sources_value_reads_as_none_and_never_hides_a_card(tmp_path, raw):
    """R-AC23: the hint is derived on every read and `load_inbox` skips an item
    whose read raises, so a hand-edited non-list `sources:` must read as none."""
    memory = _bank(tmp_path, sources=raw)
    _conflict(memory, hint="You said https://example.com/old is where to check this")
    assert fact_sources.as_sources(raw) == []
    assert _served(memory) == "You said https://example.com/old is where to check this"


def test_only_a_conflict_derives_its_hint():
    source = [{"ref": TEAM, "kind": "url"}]
    assert fact_sources.served_hint({"kind": "removal", "hint": "Also saved via safari-bookmark"},
                                    source) == "Also saved via safari-bookmark"
    assert fact_sources.served_hint({"kind": "decay"}, source) is None


def test_the_sleep_writers_no_longer_store_a_hint(tmp_path):
    memory = _bank(tmp_path, sources=[{"ref": TEAM, "kind": "url", "predicate": "works-at",
                                       "added_by": "user"}])
    inbox_generator.write_claim_nudges([{
        "id": "bob-example", "action": "conflict_nudge", "entity": {"name": "Bob Example"},
        "predicate": "works-at", "question": "Where does Bob Example work now?",
        "allow_other": True, "allow_defer": True, "conflict_context": "conflict",
        "options": [{"key": "a", "label": "company-a", "claim_id": "clm_a"}], "claim_id": "clm_a",
    }], memory)
    asyncio.run(inbox_generator.generate([{
        "id": "bob-example", "action": "conflict_nudge", "entity": {"name": "Bob Example"},
        "question": "What is currently true about Bob Example?",
        "options": [{"key": "a", "label": "a synthetic person"}],
    }], [], memory))
    for path in sorted((memory / "inbox").glob("inbox-*.md")):
        assert "hint" not in markdown_parser.parse(path).frontmatter, path.name
    bank_index.invalidate()
    served = {i.predicate: i.hint for i in inbox_service.load_inbox(memory)}
    assert served["works-at"] == served["description"] == f"You said {TEAM} is where to check this"


def test_logo_service_still_reads_the_first_url_source():
    fm = {"sources": [{"ref": "ask me", "kind": "note"},
                      {"ref": TEAM, "kind": "url", "predicate": "works-at"},
                      {"ref": TEAM, "kind": "url", "predicate": "located-in"}]}
    assert logo_service._first_source_url(fm) == TEAM


# ---------- _conflict_nudge cites the freshest episode — R-AC24 ----------


def test_a_conflict_nudge_cites_the_newest_claims_freshest_episode():
    old = Claim(id="clm_a", text="bob-example works at company-a", subject="bob-example",
                predicate="works-at", object="company-a", valid_from="2026-05-01",
                source_episodes=["ep_2026-05-01_001"])
    new = Claim(id="clm_b", text="bob-example works at company-b", subject="bob-example",
                predicate="works-at", object="company-b", valid_from="2026-09-01",
                source_episodes=["ep_2026-08-30_002", "ep_2026-09-01_004"])
    assert _conflict_nudge(old, new, "2026-09-02")["source_episode"] == "ep_2026-09-01_004"


# ---------- organic resolution is the person's, not a label — R-AC25 ----------


def _organic(tmp_path, answer: Claim):
    memory = _bank(tmp_path)
    path = _conflict(memory, created_date="2026-08-01", options=[
        {"key": "a", "label": "company-a", "claim_id": "clm_a",
         "observed_at": "2026-05-01", "last_referenced": "2026-05-01"},
        {"key": "b", "label": "company-b", "claim_id": "clm_b",
         "observed_at": "2026-07-01", "last_referenced": "2026-07-01"}])
    claims = {"bob-example": [
        Claim(id="clm_a", text="a", subject="bob-example", predicate="works-at", object="company-a",
              valid_from="2026-05-01", recorded_at="2026-05-01"),
        Claim(id="clm_b", text="b", subject="bob-example", predicate="works-at", object="company-b",
              valid_from="2026-07-01", recorded_at="2026-07-01"),
        answer,
    ]}
    return inbox_questions.refresh_open_questions(memory, claims, "2026-09-02"), path


def _answer(origin: str | None) -> Claim:
    return Claim(id="clm_u", text="c", subject="bob-example", predicate="works-at", object="company-c",
                 source_trust="user_stated", origin=origin, valid_from="2026-09-01",
                 recorded_at="2026-09-01")


@pytest.mark.parametrize("origin", [None, "claude-code", "mcp", "papers"])
def test_a_user_stated_label_without_a_human_origin_leaves_the_question_open(tmp_path, origin):
    result, path = _organic(tmp_path, _answer(origin))
    assert result["organic_resolutions"] == 0 and path.exists()


@pytest.mark.parametrize("origin", ["manual_edit", "clarification"])
def test_the_persons_own_answer_still_closes_it(tmp_path, origin):
    result, path = _organic(tmp_path, _answer(origin))
    assert result["organic_resolutions"] == 1 and not path.exists()
