# api/tests/test_transcript_extract.py
"""G105: the block-level extractor, on synthetic transcripts only.

Every fixture is built here from placeholder content (alpha-project,
bob-example, example.com). No real transcript is ever read by this suite.
"""
from __future__ import annotations

import json

import pytest

from api.services import recall_text
from api.services import transcript_extract as tx

SID = "11111111-2222-4333-8444-555555555555"


# --- Claude Code fixture builders --------------------------------------------


def _line(typ: str, content, *, ts: str = "2026-09-03T10:00:00.000Z", **extra) -> str:
    obj = {
        "type": typ,
        "uuid": f"u-{len(json.dumps(content))}",
        "parentUuid": None,
        "timestamp": ts,
        "sessionId": SID,
        "cwd": "/home/example/alpha-project",
        "message": {"role": typ, "content": content},
    }
    obj.update(extra)
    return json.dumps(obj)


def user(text: str, **extra) -> str:
    return _line("user", text, **extra)


def user_blocks(blocks: list[dict], **extra) -> str:
    return _line("user", blocks, **extra)


def asst_text(text: str, **extra) -> str:
    return _line("assistant", [{"type": "text", "text": text}], **extra)


def asst_tool(name: str = "Bash", **extra) -> str:
    return _line("assistant", [{"type": "tool_use", "id": "t1", "name": name, "input": {"command": "ls"}}], **extra)


def asst_thinking(**extra) -> str:
    return _line("assistant", [{"type": "thinking", "thinking": "private"}], **extra)


def tool_result(text: str = "file contents", **extra) -> str:
    return _line("user", [{"type": "tool_result", "tool_use_id": "t1", "content": text}], **extra)


def attachment_line() -> str:
    # A non-turn line whose body contains the user/assistant substring the
    # prefilter keys on — must be parsed-then-dropped, never kept (R6).
    return json.dumps({"type": "attachment", "attachment": {"text": '"type":"user" quoted'}})


# --- Claude Code: what is kept ----------------------------------------------


def test_person_turn_and_final_reply_kept_interstitial_and_tools_dropped():
    lines = [
        user("What did bob-example say about alpha-project?"),
        asst_text("Let me look that up."),          # interstitial narration
        asst_tool(),
        tool_result("bob-example: ship it"),         # tool output wearing the user role
        asst_thinking(),
        asst_text("bob-example said to ship alpha-project."),  # the final reply
        user("Thanks."),
    ]
    conv = tx.extract_claude_code(lines)
    assert conv.session_id == SID
    assert conv.cwd == "/home/example/alpha-project"
    assert [(t.role, t.text) for t in conv.turns] == [
        ("user", "What did bob-example say about alpha-project?"),
        ("assistant", "bob-example said to ship alpha-project."),
        ("user", "Thanks."),
    ]
    s = conv.summary
    assert s["kept"] == {"user": 2, "assistant": 1}
    assert s["dropped_blocks"]["tool_use"] == 1
    assert s["dropped_blocks"]["tool_result"] == 1
    assert s["dropped_blocks"]["thinking"] == 1
    assert s["dropped_blocks"]["interstitial"] == 1


def test_final_reply_may_span_several_text_lines_after_the_last_tool_call():
    lines = [
        user("Summarise."),
        asst_text("Narration one."),
        asst_tool(),
        tool_result(),
        asst_text("Part one of the answer."),
        asst_text("Part two of the answer."),
    ]
    conv = tx.extract_claude_code(lines)
    assert conv.turns[-1].role == "assistant"
    assert conv.turns[-1].text == "Part one of the answer.\n\nPart two of the answer."
    assert conv.summary["dropped_blocks"]["interstitial"] == 1


def test_user_message_with_text_blocks_is_kept_and_image_counted():
    lines = [user_blocks([{"type": "text", "text": "Look at this."}, {"type": "image", "source": {}}])]
    conv = tx.extract_claude_code(lines)
    assert [t.text for t in conv.turns] == ["Look at this."]
    assert conv.summary["dropped_blocks"]["image"] == 1


# --- Claude Code: what is never kept (R5) ------------------------------------


@pytest.mark.parametrize("body", [
    "<task-notification>\n<task-id>x</task-id>\n</task-notification>",
    "<command-name>/clear</command-name>",
    "<local-command-stdout>ok</local-command-stdout>",
    "<local-command-caveat>Caveat.</local-command-caveat>",
    "<command-message>x</command-message>",
])
def test_harness_tagged_user_bodies_are_dropped(body):
    conv = tx.extract_claude_code([user(body)])
    assert conv.turns == []
    assert conv.summary["dropped_messages"]["harness_tag"] == 1


def test_meta_sidechain_compact_and_api_error_lines_are_dropped():
    lines = [
        user("meta text", isMeta=True),
        user("sidechain text", isSidechain=True),
        user("compact text", isCompactSummary=True),
        _line("assistant", [{"type": "text", "text": "API error"}], isApiErrorMessage=True),
        user("real text"),
    ]
    conv = tx.extract_claude_code(lines)
    assert [t.text for t in conv.turns] == ["real text"]
    dm = conv.summary["dropped_messages"]
    assert dm["meta"] == 1 and dm["sidechain"] == 1 and dm["compact_summary"] == 1 and dm["api_error"] == 1


def test_system_reminder_span_is_stripped_from_real_user_text():
    body = "Please rename alpha-project.<system-reminder>\ninjected\n</system-reminder>"
    conv = tx.extract_claude_code([user(body)])
    assert [t.text for t in conv.turns] == ["Please rename alpha-project."]


def test_tag_filter_is_per_block_not_per_message():
    lines = [user_blocks([
        {"type": "text", "text": "<ide_opened_file>x.py</ide_opened_file>"},
        {"type": "text", "text": "Real question about alpha-project."},
    ])]
    conv = tx.extract_claude_code(lines)
    assert [t.text for t in conv.turns] == ["Real question about alpha-project."]


def test_tool_result_is_not_a_turn_boundary_but_a_meta_user_line_is():
    # Narration → tool → result → final: the result must NOT flush the
    # narration as a reply; a meta user line between two replies must.
    lines = [
        user("Q1"),
        asst_text("narration"), asst_tool(), tool_result(),
        asst_text("A1"),
        user("meta", isMeta=True),
        asst_text("A2"),
    ]
    conv = tx.extract_claude_code(lines)
    assert [(t.role, t.text) for t in conv.turns] == [("user", "Q1"), ("assistant", "A1"), ("assistant", "A2")]


def test_prefilter_changes_cost_never_output():
    lines = [attachment_line(), user("kept"), json.dumps({"type": "file-history-snapshot", "snapshot": {}})]
    conv = tx.extract_claude_code(lines)
    assert [t.text for t in conv.turns] == ["kept"]
    assert conv.summary["dropped_messages"]["other_type"] == 2


def test_bad_json_and_blank_lines_are_counted_not_raised():
    # The broken line carries the prefilter substring so it reaches the
    # parser (a line without it is counted as other_type, never parsed).
    conv = tx.extract_claude_code(["", '{"type":"user", not json', user("ok")])
    assert [t.text for t in conv.turns] == ["ok"]
    assert conv.summary["dropped_messages"]["bad_json"] == 1


# --- Cleaning (R6) -------------------------------------------------------------


def test_code_fences_are_stripped_including_an_unterminated_one():
    text = "Use this:\n```python\nprint('x')\n```\nthen done.\n```\ntrailing"
    assert tx.strip_code_fences(text) == "Use this:\n[code omitted]\nthen done.\n[code omitted]"


@pytest.mark.parametrize("secret", [
    "sk-abcdefghijklmnopqrstuvwxyz123456",
    "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123",
    "xoxb-123456789012-abcdefghijkl",
    "AKIAABCDEFGHIJKLMNOP",
    "Bearer abcdefghijklmnopqrstuvwxyz0123456789",
    "api_key=abcdefghijklmnop1234",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnopqrstuv",
    "0123456789abcdef0123456789abcdef0123456789abcdef",
    "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----",
])
def test_scrubber_redacts_secret_shapes(secret):
    out, n = tx.scrub_secrets(f"here: {secret} end")
    assert secret.split()[0] not in out and secret[-8:] not in out
    assert "[redacted]" in out
    assert n >= 1


def test_scrubber_leaves_prose_paths_and_short_hashes_alone():
    text = "See https://example.com/alpha-project/docs/getting-started/install-guide-for-users at commit abc1234 with bob-example."
    out, n = tx.scrub_secrets(text)
    assert out == text and n == 0


def test_per_turn_cap_truncates_and_counts():
    # Prose, not a single-character run: 5,000 x's IS a 64+ char base64 run
    # and the scrubber would (correctly) redact it to "[redacted]" before
    # the cap is ever reached.
    conv = tx.extract_claude_code([user("word " * 1000)], turn_cap=100)
    assert len(conv.turns[0].text) == 100
    assert conv.turns[0].text.endswith("…")
    assert conv.summary["truncated_turns"] == 1


def _numbered(n: int, width: int = 10) -> list[str]:
    """``n`` turns of exactly ``width`` characters, alternating speakers, one second apart."""
    out = []
    for i in range(n):
        text = f"turn {i:03d} " + "w" * width
        ts = f"2026-09-03T10:{i // 60:02d}:{i % 60:02d}.000Z"
        out.append(user(text[:width], ts=ts) if i % 2 == 0 else asst_text(text[:width], ts=ts))
    return out


def test_under_the_session_cap_everything_is_kept_and_there_is_no_gap():
    conv = tx.extract_claude_code(_numbered(10), session_cap=100)
    assert len(conv.turns) == 10 and conv.gap is None
    assert conv.summary["session_cap_hit"] is False and conv.summary["refused_turns"] == 0


def test_session_cap_keeps_the_head_and_the_tail_and_marks_the_middle():
    """Gate B2 (ruling 2026-10-07): the first 3/5 of the cap is the head, the
    rest the tail; the tail starts on a block boundary; the middle is dropped,
    counted, and described by its first and last times."""
    conv = tx.extract_claude_code(_numbered(20), session_cap=100, tail_block=2)
    texts = [t.text[:8] for t in conv.turns]
    assert texts == [f"turn {i:03d}" for i in (*range(6), *range(16, 20))]
    g = conv.gap
    assert (g.after, g.dropped) == (6, 10)
    assert g.first_at == "2026-09-03T10:00:06.000Z" and g.last_at == "2026-09-03T10:00:15.000Z"
    assert conv.summary["session_cap_hit"] is True and conv.summary["refused_turns"] == 10
    assert conv.ended_at == "2026-09-03T10:00:19.000Z"          # the latest turn is kept


def test_the_head_is_stable_and_the_tail_advances_in_blocks():
    heads, starts = set(), []
    for n in range(12, 40):
        conv = tx.extract_claude_code(_numbered(n), session_cap=100, tail_block=4)
        heads.add(tuple(t.text for t in conv.turns[: conv.gap.after]))
        start = conv.gap.after + conv.gap.dropped
        assert start % 4 == 0 and sum(len(t.text) for t in conv.turns[conv.gap.after:]) <= 40
        assert conv.turns[-1].text.startswith(f"turn {n - 1:03d}")
        starts.append(start)
    assert len(heads) == 1                                          # head offsets never move
    moves = [b - a for a, b in zip(starts, starts[1:]) if b != a]
    assert moves and all(m == 4 for m in moves)                     # whole blocks, never one turn at a time


def test_the_last_turn_is_always_kept_even_when_the_tail_cannot_hold_a_block():
    conv = tx.extract_claude_code(_numbered(12), session_cap=100)  # default block of 10
    assert conv.turns[-1].text.startswith("turn 011") and conv.gap.dropped >= 1


def test_a_note_like_turn_in_the_dropped_middle_is_not_counted():
    lines = _numbered(20)
    lines[10] = user("see:\n" + recall_text.INJECTION_PREFIX + " x", ts="2026-09-03T10:00:10.000Z")
    conv = tx.extract_claude_code(lines, session_cap=100, tail_block=2)
    assert conv.gap.dropped == 10 and conv.summary["note_like_turns"] == 0


def test_secrets_inside_code_fences_never_survive_and_scrub_runs_before_cap():
    body = "Token:\n```\nsk-abcdefghijklmnopqrstuvwxyz123456\n```\nand also sk-zyxwvutsrqponmlkjihgfedcba654321 here"
    conv = tx.extract_claude_code([user(body)], turn_cap=40)
    assert "sk-" not in conv.turns[0].text
    assert conv.summary["scrubbed"] == 1


def test_keep_assistant_false_drops_replies_only():
    lines = [user("Q"), asst_text("A")]
    conv = tx.extract_claude_code(lines, keep_assistant=False)
    assert [t.role for t in conv.turns] == ["user"]
    assert conv.summary["dropped_messages"]["assistant_by_flag"] == 1


def test_timestamps_bracket_the_kept_turns():
    lines = [user("Q", ts="2026-09-03T10:00:00.000Z"), asst_text("A", ts="2026-09-03T10:05:00.000Z")]
    conv = tx.extract_claude_code(lines)
    assert conv.started_at == "2026-09-03T10:00:00.000Z"
    assert conv.ended_at == "2026-09-03T10:05:00.000Z"
    assert conv.turns[1].ts == "2026-09-03T10:05:00.000Z"


# --- Codex ---------------------------------------------------------------------


def _cx(typ: str, payload: dict, ts: str = "2026-09-03T10:00:00.000Z") -> str:
    return json.dumps({"timestamp": ts, "type": typ, "payload": payload})


def cx_msg(role: str, texts: list[str]) -> str:
    kind = "output_text" if role == "assistant" else "input_text"
    return _cx("response_item", {"type": "message", "role": role, "content": [{"type": kind, "text": t} for t in texts]})


def test_codex_same_ruling_same_shape():
    lines = [
        _cx("session_meta", {"id": SID, "cwd": "/home/example/alpha-project", "timestamp": "2026-09-03T09:59:00Z"}),
        cx_msg("developer", ["<permissions>x</permissions>"]),
        cx_msg("user", ["<environment_context>cwd</environment_context>", "Rename alpha-project?"]),
        _cx("event_msg", {"type": "user_message", "message": "Rename alpha-project?"}),
        cx_msg("assistant", ["Checking."]),
        _cx("response_item", {"type": "function_call", "name": "shell", "arguments": "{}", "call_id": "c1"}),
        _cx("response_item", {"type": "function_call_output", "call_id": "c1", "output": "ok"}),
        _cx("response_item", {"type": "reasoning", "summary": []}),
        cx_msg("assistant", ["Yes — rename it."]),
        _cx("event_msg", {"type": "agent_message", "message": "Yes — rename it."}),
    ]
    conv = tx.extract_codex(lines)
    assert conv.harness == "codex"
    assert conv.session_id == SID
    assert conv.cwd == "/home/example/alpha-project"
    assert [(t.role, t.text) for t in conv.turns] == [("user", "Rename alpha-project?"), ("assistant", "Yes — rename it.")]
    s = conv.summary
    assert s["dropped_blocks"]["function_call"] == 1
    assert s["dropped_blocks"]["function_call_output"] == 1
    assert s["dropped_blocks"]["reasoning"] == 1
    assert s["dropped_blocks"]["interstitial"] == 1
    assert s["dropped_messages"]["developer"] == 1
    assert s["dropped_messages"]["other_type"] == 2  # the two event_msg duplicates


def test_extract_dispatch_and_unknown_harness():
    assert tx.extract("claude-code", [user("hi")]).turns[0].text == "hi"
    with pytest.raises(ValueError):
        tx.extract("cursor", [])


def test_a_cicada_note_in_the_persons_own_text_is_kept_and_counted():
    """G110 T2b (gate C, ruling 2026-10-07): capture drops a Cicada note only
    when the harness marks it as injected — a whole non-person record. Text in
    the person's own block is their words, whatever it looks like: kept, and
    counted as note-like so the next note can say so. G105 R5 (the
    ``<system-reminder>`` span strip) is a tool-output rail and stays."""
    note = recall_text.RECALL_HEADER + "\n- Alpha Project (project, `alpha-project`): x"
    lines = [
        user("How is the Alpha Project going?"),
        user(note),                                                # a whole note, pasted
        user_blocks([{"type": "text", "text": "  " + note}, {"type": "text", "text": "and Bob?"}]),
        user(f"<system-reminder>{note}</system-reminder>What changed?"),
        user(f"<user-prompt-submit-hook>{note}</user-prompt-submit-hook>"),
        user(f"And the budget?\n<user-prompt-submit-hook>{note}</user-prompt-submit-hook>"),
        user(f"<session-start-hook>{note}"),
        asst_text("It is on track."),
    ]
    conv = tx.extract_claude_code(lines)
    kept = [t.text for t in conv.turns if t.role == "user"]
    assert kept[0] == "How is the Alpha Project going?"
    assert kept[1] == note
    assert kept[2] == note + "\nand Bob?"
    assert kept[3] == "What changed?"                              # R5's span strip is untouched
    assert kept[4] == f"<user-prompt-submit-hook>{note}</user-prompt-submit-hook>"
    assert kept[5].startswith("And the budget?") and recall_text.INJECTION_PREFIX in kept[5]
    assert kept[6] == f"<session-start-hook>{note}"
    assert conv.summary["note_like_turns"] == 5


def test_a_person_quoting_a_header_line_then_asking_keeps_both():
    text = recall_text.PRIMER_HEADER + "\nWhy did this show up? Please turn it off for alpha-project."
    conv = tx.extract_claude_code([user(text), asst_text("Done.")])
    assert conv.turns[0].text == text and conv.summary["note_like_turns"] == 1


def test_a_note_the_harness_marks_as_injected_is_dropped_whole():
    """Hook context Claude Code records as its own (non-user) record, or as an
    ``isMeta`` user record, is not the person's — dropped, never counted."""
    note = recall_text.PRIMER_HEADER + "\n\n# Cicada — personal memory for this person"
    lines = [
        json.dumps({"type": "attachment", "attachment": {"type": "hook_additional_context", "content": [note]}}),
        user(note, isMeta=True),
        user("Rename alpha-project?"),
        asst_text("Yes."),
    ]
    conv = tx.extract_claude_code(lines)
    assert [t.text for t in conv.turns] == ["Rename alpha-project?", "Yes."]
    assert conv.summary["note_like_turns"] == 0


def test_codex_drops_a_developer_note_and_keeps_one_in_the_persons_text():
    note = recall_text.PRIMER_HEADER + "\n\n# Cicada — personal memory for this person"
    lines = [cx_msg("developer", [note]), cx_msg("user", [note, "Rename alpha-project?"]),
             cx_msg("user", [f"<session-start-hook>{note}</session-start-hook>"]), cx_msg("assistant", ["Yes."])]
    conv = tx.extract_codex(lines)
    assert [(t.role, t.text) for t in conv.turns] == [
        ("user", note + "\nRename alpha-project?"),
        ("user", f"<session-start-hook>{note}</session-start-hook>"),
        ("assistant", "Yes.")]
    assert conv.summary["dropped_messages"]["developer"] == 1
    assert conv.summary["note_like_turns"] == 2


def test_codex_harness_tags_are_still_skipped():
    lines = [cx_msg("user", ["<environment_context>cwd</environment_context>", "hi"]), cx_msg("assistant", ["ok"])]
    assert [t.text for t in tx.extract_codex(lines).turns] == ["hi", "ok"]


# --- G110 slice 1a: refused turns and note-like person turns are counted -------


def test_a_note_like_line_inside_a_person_turn_is_kept_and_counted():
    text = "I pasted this:\n" + recall_text.INJECTION_PREFIX + " at session start ...\nplease fix it"
    conv = tx.extract_claude_code([_line("user", text)])
    assert conv.summary["note_like_turns"] == 1 and "please fix it" in conv.turns[0].text


# --- fix round 1, finding 9: only text that reaches the body is counted ----------


def test_a_note_header_removed_by_cleaning_is_not_counted():
    fenced = "look:\n```\n" + recall_text.INJECTION_PREFIX + " at session start\n```\nthanks"
    truncated = "x " * 1100 + "\n" + recall_text.INJECTION_PREFIX + " at session start"
    conv = tx.extract_claude_code([_line("user", fenced), _line("user", truncated)])
    assert all(recall_text.INJECTION_PREFIX not in t.text for t in conv.turns)
    assert conv.summary["note_like_turns"] == 0
