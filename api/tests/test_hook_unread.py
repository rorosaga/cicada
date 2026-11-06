"""G207 (2026-11-06): a conversation waiting for Sleep helps the hook too.

Before this, the UserPromptSubmit note read only pages and claims, so nothing unread reached a session unasked. The leg
shows the person's own turn, marked as unread, and holds the note's bar: nothing on an everyday ask, nothing of the
other side's, nothing of this session's own, no save with no reason. Synthetic bank; no model, no embedder.
"""
from __future__ import annotations

import pytest

from api.services import bank_index, evidence, hook_recall, markdown_parser, recall_text, search_index


def _episode(memory, ep_id: str, body: str, *, processed: bool = False, **fm) -> None:
    meta = {"id": ep_id, "timestamp": f"{ep_id[3:13]}T10:00:00+00:00", "processed": processed, "source": "claude-code",
            "content_hash": evidence.body_hash(body), **fm}
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", meta, body)


FILLER = [f"user: an ordinary line about the weekly chores number {i} and nothing else at all\n\nassistant: noted, "
          f"thanks for the update number {i}" for i in range(80)]


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for i, block in enumerate(FILLER):
        _episode(memory, f"ep_2026-09-{(i % 27) + 1:02d}_{i + 1:03d}", block, processed=True)
    _episode(memory, "ep_2026-11-01_001", "user: my landlord wants the plumber invoice before the lease renewal\n\n"
             "assistant: Sure, I can draft a note.", session_id="other-session")
    yield memory
    bank_index.invalidate()
    hook_recall.reset()


def _note(memory, prompt: str, **kw):
    search_index.ensure_fresh(memory, wait=True, max_age_s=0)
    bank_index.invalidate()
    hook_recall.reset()
    return hook_recall.prompt_context(memory, prompt, **kw)


def test_the_persons_unread_turn_reaches_the_note_marked_as_unread(bank):
    note = _note(bank, "did the landlord ever get that plumber invoice?")
    assert note.reason == "unread" and "ep_2026-11-01_001" in note.injected
    assert "plumber invoice before the lease renewal" in note.text
    assert "not yet read by Sleep" in note.text and note.text.startswith(recall_text.INJECTION_PREFIX)
    assert len(note.text) // 4 <= hook_recall.MAX_TOKENS


def test_once_sleep_has_read_it_the_leg_stays_quiet(bank):
    _episode(bank, "ep_2026-11-01_001", "user: my landlord wants the plumber invoice before the lease renewal",
             processed=True)
    assert _note(bank, "did the landlord ever get that plumber invoice?").text is None


def test_this_sessions_own_conversation_is_not_handed_back(bank):
    assert _note(bank, "did the landlord ever get that plumber invoice?", session_id="other-session").text is None
    assert _note(bank, "did the landlord ever get that plumber invoice?", session_id="this-session").text


def test_only_the_person_counts_the_other_side_repeating_the_words_does_not(bank):
    _episode(bank, "ep_2026-11-02_001", "user: tell me about gardens\n\nassistant: An orchard pruning schedule keeps "
             "the quince harvest steady.")
    assert _note(bank, "what orchard pruning schedule keeps the quince harvest steady?").text is None


def test_words_scattered_through_a_long_paste_are_no_match(bank):
    paste = " ".join(["orchard"] + ["padding words of a pasted log"] * 80 + ["quince"] + ["more paste"] * 80 + ["pruning"])
    _episode(bank, "ep_2026-11-02_002", f"user: {paste}")
    assert _note(bank, "orchard pruning for the quince").text is None


def test_a_save_with_no_reason_is_never_quoted_by_this_leg(bank):
    _episode(bank, "ep_2026-11-02_003", "user: quince orchard pruning schedule guide", source="chrome",
             origin="chrome-bookmark", url="https://example.com/quince")
    note = _note(bank, "orchard pruning schedule for the quince")
    assert "not yet read by Sleep" not in (note.text or "")


def test_a_shown_conversation_steps_aside_for_the_session(bank):
    first = _note(bank, "did the landlord ever get that plumber invoice?")
    again = _note(bank, "did the landlord ever get that plumber invoice?", recent=frozenset(first.injected))
    assert again.text is None


def test_an_everyday_ask_gets_nothing(bank):
    for prompt in ("fix the failing test in the parser", "open a pr for this branch", "rename this function"):
        assert _note(bank, prompt).text is None, prompt


def test_a_page_named_keeps_its_note_and_the_unread_line_rides_below(bank):
    markdown_parser.write(bank / "entities" / "landlord.md", {"name": "Landlord", "type": "person", "status": "active"},
                          "## Summary\nThe person renting out the flat.\n")
    note = _note(bank, "did the landlord ever get that plumber invoice?")
    assert "landlord" in note.injected and "plumber invoice before the lease renewal" in note.text
