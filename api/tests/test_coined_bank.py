"""`benchmarks/consolidation/coined_bank.py`: counts of names nobody said in a bank, read only, no name printed (G148/G98).
Made-up names only."""
from __future__ import annotations

import hashlib
import json

from api.services import markdown_parser, pending_store
from api.services.pending_store import PendingEntity
from benchmarks.consolidation import coined_bank

CHAT, NOTE = "ep_2026-10-20_001", "ep_2026-10-21_001"


def _tree(path) -> dict:
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.rglob("*")) if p.is_file()}


def _bank(tmp_path):
    for sub in ("entities", "episodes", "inbox"):
        (tmp_path / sub).mkdir()
    markdown_parser.write(tmp_path / "episodes" / f"{CHAT}.md", {"id": CHAT, "source": "import", "origin": "chatgpt"},
                          "user: Lanternbook has a feedback form I keep postponing.\nassistant: Ship the form first.\n")
    markdown_parser.write(tmp_path / "episodes" / f"{NOTE}.md",
                          {"id": NOTE, "source": "mcp", "origin": "mcp", "harness": "claude-code", "session_id": "s1"},
                          "Session notes. Lanternbook weekly digest layout is done.\n")
    markdown_parser.write(tmp_path / "entities" / "lanternbook.md",
                          {"id": "lanternbook", "name": "Lanternbook", "type": "concept", "status": "active", "aliases": [],
                           "source_episodes": [CHAT]}, "Lanternbook is a recipe app.\n")
    markdown_parser.write(tmp_path / "entities" / "pantry-widget.md",
                          {"id": "pantry-widget", "name": "Pantry widget plan", "type": "concept", "status": "active",
                           "aliases": [], "source_episodes": [CHAT]}, "A widget.\n")
    line = dict(type="concept", description="", confidence=0.6, tags=[], history_entries=[])
    pending_store.save(tmp_path, [
        PendingEntity(name="Lanternbook feedback form", source_episode=CHAT, **line),          # said nowhere
        PendingEntity(name="Feedback form", source_episode=CHAT, **line),                      # said in the person's turn
        PendingEntity(name="Weekly digest layout", source_episode=NOTE, **line),               # said only in an agent's note
    ])
    markdown_parser.write(tmp_path / "inbox" / "q1.md",
                          {"id": "q1", "kind": "merge_suggestion", "status": "pending", "entity_name": "Lanternbook feedback form",
                           "merge_target_hint": "lanternbook", "source_episode": CHAT}, "")
    return tmp_path


def test_the_report_counts_what_nobody_said_and_writes_nothing(tmp_path):
    bank = _bank(tmp_path)
    before = _tree(bank)
    r = coined_bank.report(bank)
    assert _tree(bank) == before, "a read-only report"
    assert r["held"]["where_said"] == {"nowhere": 1, "person": 1, "others": 1}
    assert r["held"]["nowhere_by_kind"] == {"chat_export": 1} and r["held"]["nowhere_by_type"] == {"concept": 1}
    assert r["held"]["nowhere_by_words"] == {"all": 1}, "its words are all there, the phrase is not"
    assert r["pages"]["where_said"] == {"person": 1, "nowhere": 1}
    assert r["questions"]["about_a_name_with_no_page_where_said"] == {"nowhere": 1}
    assert r["questions"]["most_on_one_target"] == 1


def test_the_report_prints_no_name_and_no_conversation_text(tmp_path):
    bank = _bank(tmp_path)
    shown = coined_bank.render(coined_bank.report(bank)) + json.dumps(coined_bank.report(bank))
    for private in ("Lanternbook", "feedback form", "Pantry", "postponing", "digest", CHAT, NOTE, "q1"):
        assert private not in shown, private


def test_an_agents_note_is_its_own_kind_and_a_ticked_chat_another():
    assert coined_bank.kind_of({"source": "mcp", "harness": "claude-code"}) == "agent_note"
    assert coined_bank.kind_of({"source": "agent-memory"}) == "agent_memory"
    assert coined_bank.kind_of({"capture_kind": "transcript", "harness": "claude-code"}) == "session"
    assert coined_bank.kind_of({"correspondent": {"name": "x", "kind": "person"}}) == "ticked_chat"
    assert coined_bank.kind_of({"source": "import", "origin": "chatgpt"}) == "chat_export"
