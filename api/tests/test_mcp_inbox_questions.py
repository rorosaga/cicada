"""G60 §2.7 — the MCP surface renders question objects and can resolve them."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def server():
    spec = importlib.util.spec_from_file_location(
        "cicada_mcp_server", REPO_ROOT / "mcp" / "server.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server"] = module
    spec.loader.exec_module(module)
    return module


QUESTION_FM = {
    "kind": "conflict",
    "status": "pending",
    "entity_id": "rodrigo",
    "entity_name": "Rodrigo",
    "title": "Where does Rodrigo work now?",
    "question": "Where does Rodrigo work now?",
    "predicate": "works-at",
    "allow_other": True,
    "allow_defer": True,
    "created_date": "2026-06-18",
    "hint": "You said https://linkedin.example/rodrigo is where to check this",
    "options": [
        {"key": "a", "label": "MongoDB", "observed_at": "2026-02-18",
         "last_referenced": "2026-02-18"},
        {"key": "b", "label": "Supahost", "observed_at": "2026-08-25",
         "last_referenced": "2026-08-25"},
        {"key": "both", "label": "Both are true (different contexts)"},
    ],
}


def test_render_question_lists_keyed_options_with_ages(server):
    out = server.render_question(QUESTION_FM, "Conflicting beliefs.", today="2026-08-30")
    assert "Where does Rodrigo work now?" in out
    assert "a) MongoDB — 6 months ago" in out
    assert "b) Supahost — 5 days ago" in out
    assert "both) Both are true (different contexts)" in out
    assert "Other / Later" in out
    assert "linkedin.example" in out


def test_render_question_falls_back_to_the_body(server):
    fm = {"kind": "clarification", "entity_name": "Franco",
          "uncertainty_type": "who is this", "options": []}
    out = server.render_question(fm, "Who is Franco?", today="2026-08-30")
    assert "Who is Franco?" in out
    assert "Other / Later" not in out  # allow_other/allow_defer are off


def test_check_nudges_hides_deferred_items(server, tmp_path, monkeypatch):
    from api.services import markdown_parser

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    markdown_parser.write(memory / "inbox" / "inbox-001.md", dict(QUESTION_FM), "ctx")
    deferred = dict(QUESTION_FM)
    deferred["predicate"] = "uses"
    deferred["remind_after"] = "2099-01-01"
    markdown_parser.write(memory / "inbox" / "inbox-002.md", deferred, "ctx")

    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    out = server.handle_check_nudges(None)
    assert "inbox-001" in out
    assert "inbox-002" not in out
    assert "Found 1 pending inbox item" in out


def test_resolve_inbox_posts_the_option_key(server, monkeypatch):
    seen = {}

    def fake_post(path: str, payload: dict) -> dict:
        seen["path"] = path
        seen["payload"] = payload
        return {"status": "resolved", "id": "inbox-001"}

    monkeypatch.setattr(server, "_backend_post", fake_post)
    out = server.handle_resolve_inbox("inbox-001", "b", None, False, None)

    assert seen["path"] == "/inbox/inbox-001/resolve"
    assert seen["payload"] == {"action": "resolve", "optionKey": "b"}
    assert "resolved" in out


def test_resolve_inbox_defer_sends_remind_days(server, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        server, "_backend_post",
        lambda path, payload: seen.update(payload) or {"status": "deferred", "remindAfter": "2026-09-29"},
    )
    out = server.handle_resolve_inbox("inbox-001", None, None, True, 30)
    assert seen == {"action": "defer", "remindDays": 30}
    assert "2026-09-29" in out


def test_resolve_inbox_free_text(server, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        server, "_backend_post",
        lambda path, payload: seen.update(payload) or {"status": "resolved"},
    )
    server.handle_resolve_inbox("inbox-001", "neither", "Acme Robotics", False, None)
    assert seen == {"action": "resolve", "optionKey": "neither", "answer": "Acme Robotics"}


def test_resolve_inbox_reject_posts_reject_action(server, monkeypatch):
    """G113 slice 3b: reject=true is a real, remembered verdict — unlike
    skip, it IS posted to the backend (which records the pair)."""
    seen = {}
    monkeypatch.setattr(
        server, "_backend_post",
        lambda path, payload: seen.update(payload) or {"status": "resolved"},
    )
    out = server.handle_resolve_inbox("inbox-001", None, None, False, None, reject=True)
    assert seen == {"action": "reject"}
    assert "resolved" in out


def test_resolve_inbox_tool_is_registered(server):
    names = {t["name"] for t in server.TOOLS}
    assert "cicada_resolve_inbox" in names
    tool = next(t for t in server.TOOLS if t["name"] == "cicada_resolve_inbox")
    assert tool["inputSchema"]["required"] == ["id"]
    assert set(tool["inputSchema"]["properties"]) == {
        "id", "option_key", "answer", "defer", "remind_days", "skip", "reject",
    }


def test_relevant_inbox_hides_deferred_items(server, tmp_path):
    """L3 — the proactive recall block honours a deferral just like
    `cicada_check_nudges` does: "remind me later" means everywhere.
    """
    from api.services import markdown_parser

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    markdown_parser.write(memory / "inbox" / "inbox-001.md", dict(QUESTION_FM), "ctx")
    deferred = dict(QUESTION_FM)
    deferred["remind_after"] = "2099-01-01"
    markdown_parser.write(memory / "inbox" / "inbox-002.md", deferred, "ctx")

    blurbs = server._relevant_inbox(memory, "Rodrigo")
    assert len(blurbs) == 1
    assert all("Rodrigo" in b for b in blurbs)


# --------------------------------------------------------------------------- #
# G115 Phase 1 (R9) — render_question v2: the cause, (Recommended), the header
# line the next `cicada_check_nudges(entity_ids=…)` needs, and the skip hint.
# --------------------------------------------------------------------------- #

CAUSE = {"tier": "item", "episode_id": "ep_2026-08-20_001", "timestamp": "2026-08-20T10:00:00+00:00",
         "conversation_id": "ses_x", "harness": "claude-code", "origin": "claude-code",
         "conversation_title": "Parser planning", "excerpt": "user: Bob Example moved to beta-corp last week.",
         "mention_offsets": [[6, 17]], "start": 0, "end": 47, "span_kind": "derived"}


def test_render_question_v2_header_cause_and_recommended(server):
    out = server.render_question(QUESTION_FM, "ctx", today="2026-08-30", cause=CAUSE, recommended_key="b")
    lines = out.splitlines()
    assert lines[0] == "Where does Rodrigo work now?"
    assert lines[1].strip() == "entity_id=rodrigo · predicate=works-at"
    assert lines[2].strip().startswith('Cause: “user: Bob Example moved to beta-corp last week.” — from "Parser planning" · claude-code · ')
    assert "a) MongoDB — 6 months ago" in out and "(Recommended)" not in lines[3 + 0]
    assert "b) Supahost — 5 days ago (Recommended)" in out
    assert "skip=true" in out


def test_render_question_no_source_recorded_is_printed_not_dropped(server):
    out = server.render_question(QUESTION_FM, "ctx", today="2026-08-30", cause={"tier": "none", "excerpt": "[ no source recorded ]"})
    assert "Cause: [ no source recorded ]" in out


def test_check_nudges_renders_decay_as_a_question_with_cause(server, tmp_path, monkeypatch):
    from api.services import bank_index, markdown_parser
    bank_index.invalidate()
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True); (memory / "entities").mkdir(); (memory / "episodes").mkdir()
    markdown_parser.write(memory / "episodes" / "ep_2026-08-20_001.md",
                          {"id": "ep_2026-08-20_001", "timestamp": "2026-08-20T10:00:00+00:00", "title": "Parser planning"},
                          "user: alpha-project is mostly the parser.\n")
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active", "last_referenced": "2026-02-18",
                           "source_episodes": ["ep_2026-08-20_001"]}, "# A\n")
    markdown_parser.write(memory / "inbox" / "inbox-003.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project", "entity_name": "Alpha Project",
                           "title": "No recent mentions of Alpha Project", "created_date": "2026-08-01"}, "body")
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "_SKIPPED_INBOX_IDS", set())
    out = server.handle_check_nudges(None)
    assert "Still tracking Alpha Project?" in out
    assert "archive) Archive" in out and "(Recommended)" in out and "keep) Keep active" in out
    assert 'Cause: “user: alpha-project is mostly the parser.” — from "Parser planning"' in out
    assert 'cicada_resolve_inbox(id="inbox-003", option_key=…)' in out


def test_relevant_inbox_carries_the_cause(server, tmp_path):
    """New fixtures use the synthetic names (`bob-example`, `beta-corp`) — the
    privacy rail: no real name may enter a test this plan adds."""
    from api.services import bank_index, markdown_parser
    bank_index.invalidate()
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True); (memory / "entities").mkdir(); (memory / "episodes").mkdir()
    markdown_parser.write(memory / "episodes" / "ep_2026-08-20_001.md",
                          {"id": "ep_2026-08-20_001", "timestamp": "2026-08-20T10:00:00+00:00", "title": "Jobs"},
                          "user: Bob Example moved to beta-corp last week.\n")
    fm = dict(QUESTION_FM,
              entity_id="bob-example", entity_name="Bob Example",
              title="Where does Bob Example work now?",
              question="Where does Bob Example work now?",
              source_episode="ep_2026-08-20_001")
    markdown_parser.write(memory / "inbox" / "inbox-001.md", fm, "ctx")
    [blurb] = server._relevant_inbox(memory, "Bob Example")
    assert 'Cause: “user: Bob Example moved to beta-corp last week.” — from "Jobs"' in blurb


# --------------------------------------------------------------------------- #
# Final review H1 — the `Other / Later` line is gated per flag.
# --------------------------------------------------------------------------- #


def test_decay_card_never_invites_free_text(server):
    """A decay question sets `allow_other: False`, and the invitation must go
    with it (final review H1).

    Before this, `render_question` printed "reply with any other answer" on a
    decay card because the line was gated on `allow_other OR allow_defer`. An
    agent taking the invitation hit `_resolve_decay`'s `else` branch: the answer
    prose was appended to the entity body, the page stayed `decaying` at its
    decayed confidence, and the item was deleted — a "yes, still relevant"
    inverted with no error. The `defer` half must still print, since decay does
    allow it.
    """
    from api.services import inbox_questions

    q = inbox_questions.decay_question("Alpha Project", "2026-02-18", "2026-08-30")
    fm = dict(q, kind="decay", entity_id="alpha-project", entity_name="Alpha Project")
    out = server.render_question(fm, "body", today="2026-08-30")
    assert "reply with any other answer" not in out
    assert "Other / Later — ask to be reminded later; skip=true if unanswered" in out


def test_conflict_card_still_prints_both_halves(server):
    """The conflict sentence is byte-identical to v2's — only the gating changed."""
    out = server.render_question(QUESTION_FM, "ctx", today="2026-08-30")
    assert (
        "Other / Later — reply with any other answer, or ask to be reminded later; "
        "skip=true if unanswered"
    ) in out


def test_render_question_with_neither_flag_prints_no_other_line(server):
    fm = dict(QUESTION_FM, allow_other=False, allow_defer=False)
    out = server.render_question(fm, "ctx", today="2026-08-30")
    assert "Other / Later" not in out


# --------------------------------------------------------------------------- #
# Final review H3 — one InboxContext per reader loop, not one per item.
# --------------------------------------------------------------------------- #


def test_check_nudges_builds_one_inbox_context_for_the_whole_loop(server, tmp_path, monkeypatch):
    """`InboxContext` scandirs `episodes/` AND `entities/` on first use; one per
    item put ~400 ms into a call that sits in the conversation loop."""
    from api.services import bank_index, inbox_context, markdown_parser

    bank_index.invalidate()
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True); (memory / "entities").mkdir(); (memory / "episodes").mkdir()
    for n in range(4):
        markdown_parser.write(
            memory / "entities" / f"alpha-project-{n}.md",
            {"name": f"Alpha Project {n}", "type": "project", "status": "active",
             "last_referenced": "2026-02-18", "source_episodes": []}, "# A\n")
        markdown_parser.write(
            memory / "inbox" / f"inbox-10{n}.md",
            {"kind": "decay", "status": "pending", "entity_id": f"alpha-project-{n}",
             "entity_name": f"Alpha Project {n}", "title": f"No recent mentions {n}",
             "created_date": "2026-08-01"}, "body")

    built = []
    real = inbox_context.InboxContext

    class Counting(real):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **kw):
            built.append(1)
            super().__init__(*a, **kw)

    monkeypatch.setattr(inbox_context, "InboxContext", Counting)
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "_SKIPPED_INBOX_IDS", set())
    out = server.handle_check_nudges(None)
    assert out.count("Still tracking") == 4
    assert len(built) == 1


def test_relevant_inbox_builds_one_inbox_context_for_the_whole_loop(server, tmp_path, monkeypatch):
    from api.services import bank_index, inbox_context, markdown_parser

    bank_index.invalidate()
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True); (memory / "entities").mkdir(); (memory / "episodes").mkdir()
    for n in range(3):
        markdown_parser.write(
            memory / "inbox" / f"inbox-20{n}.md",
            dict(QUESTION_FM, entity_id="bob-example", entity_name="Bob Example",
                 title="Where does Bob Example work now?",
                 question="Where does Bob Example work now?"), "ctx")

    built = []
    real = inbox_context.InboxContext

    class Counting(real):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **kw):
            built.append(1)
            super().__init__(*a, **kw)

    monkeypatch.setattr(inbox_context, "InboxContext", Counting)
    assert len(server._relevant_inbox(memory, "Bob Example")) == 3
    assert len(built) == 1
