"""G110 A2: synthetic first-message retention and authoritative reply gaps."""
import json

import pytest

from api.services import evidence, markdown_parser, provenance, transcript_capture as tc, transcript_extract as tx

SID = "aaaaaaaa-2222-4333-8444-555555555555"
CWD = "/home/example/alpha-project"
MARKER = "[Cicada: part of this reply was not kept]"


def lines(harness, turns):
    out = []
    if harness == "codex":
        out.append(json.dumps({"type": "session_meta", "payload": {"id": SID, "cwd": CWD}}))
        out.append(json.dumps({"type": "turn_context", "payload": {"model": "synthetic-model", "effort": "high"}}))
    for i, (role, text) in enumerate(turns):
        ts = f"2026-10-07T10:{i // 60:02d}:{i % 60:02d}+00:00"
        if harness == "claude-code":
            obj = {"type": role, "sessionId": SID, "cwd": CWD, "timestamp": ts,
                   "message": {"role": role, "content": [{"type": "text", "text": text}]}}
            if role == "assistant":
                obj["message"]["model"] = "synthetic-model"
                obj["effort"] = "high"
        else:
            obj = {"type": "response_item", "timestamp": ts, "payload": {"type": "message", "role": role,
                   "channel": "final" if role == "assistant" else None,
                   "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}}
        out.append(json.dumps(obj))
    return out


def capture(tmp_path, monkeypatch, harness, turns):
    root, memory = tmp_path / "transcripts", tmp_path / "memory"
    root.mkdir(exist_ok=True)
    (memory / "episodes").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: root)
    monkeypatch.setattr(tc, "_episode_cache", {})
    path = root / f"{SID}.jsonl"
    path.write_text("\n".join(lines(harness, turns)) + "\n")
    result = tc.capture_transcript(memory, harness=harness, session_id=SID, transcript_path=str(path), cwd=CWD,
                                   keep_assistant=True)
    return memory, result, markdown_parser.parse(memory / "episodes" / f"{result.episode_id}.md")


@pytest.mark.parametrize("harness", tx.HARNESSES)
def test_first_person_message_uses_16k_then_later_person_turns_stay_2k(harness):
    first = "brief " * 2500 + "near-end-role-sentinel"
    conv = tx.extract(harness, lines(harness, [("user", first), ("assistant", "ok"), ("user", "later " * 700)]))
    assert conv.turns[0].text == first and "near-end-role-sentinel" in conv.turns[0].text
    assert len(conv.turns[2].text) == 2000 and conv.turns[2].text.endswith("…")
    clipped = tx.extract(harness, lines(harness, [("user", "brief " * 2700)]))
    assert len(clipped.turns[0].text) == 16000 and clipped.turns[0].text.endswith("…")


@pytest.mark.parametrize("harness", tx.HARNESSES)
def test_first_message_cap_is_after_the_same_scrub_and_fence_removal(harness):
    secret = "sk-" + "A" * 48
    text = "first " * 700 + "```\ncode-secret-sentinel\n```\n" + secret + " tail-role-sentinel"
    conv = tx.extract(harness, lines(harness, [("user", text)]))
    assert "tail-role-sentinel" in conv.turns[0].text
    assert secret not in conv.turns[0].text and "code-secret-sentinel" not in conv.turns[0].text
    assert tx.CODE_OMITTED in conv.turns[0].text and conv.summary["scrubbed"] > 0


@pytest.mark.parametrize("command", ["/clear", "/model x", "/config"])
def test_local_housekeeping_does_not_consume_first_message_allowance(command):
    prefix = lines("claude-code", [("user", f"<command-name>{command}</command-name>"),
                                   ("user", "<local-command-stdout>ok</local-command-stdout>")])
    first = "role " * 1200 + "role-end"
    conv = tx.extract_claude_code(prefix + lines("claude-code", [("user", first)]))
    assert [t.text for t in conv.turns] == [first]


@pytest.mark.parametrize("harness", tx.HARNESSES)
def test_long_final_reply_keeps_scrubbed_head_tail_and_non_speaker_gap(tmp_path, monkeypatch, harness):
    secret = "sk-" + "B" * 48
    reply = "head-reply-sentinel " + "context " * 600 + "```code-interior``` " + secret + "\nState: blocked; next: alpha tests."
    memory, result, doc = capture(tmp_path, monkeypatch, harness, [("user", "first role"), ("assistant", reply)])
    conv = tx.extract(harness, lines(harness, [("user", "first role"), ("assistant", reply)]))
    kept = conv.turns[1].text
    assert len(kept) <= 2000 and "head-reply-sentinel" in kept and kept.endswith("State: blocked; next: alpha tests.")
    assert MARKER in kept and secret not in doc.body and "code-interior" not in doc.body
    gaps = evidence.gap_ranges(doc.frontmatter, doc.body)
    assert len(gaps) == 1
    g0, g1 = gaps[0]
    assert doc.body[g0:g1] == MARKER and doc.frontmatter["reply_gaps"][0]["omitted_chars"] > 0
    assert evidence.speaker_kind(doc.body, g0 + 2, gaps=gaps) == "gap"
    assert evidence.verify(memory, result.episode_id, MARKER).kind == "reasoning"
    tail = evidence.verify(memory, result.episode_id, "State: blocked; next: alpha tests.")
    assert tail.kind == "assistant" and doc.body[tail.start:tail.end] == "State: blocked; next: alpha tests."
    hit = evidence.turn_at(doc.body, tail.start, evidence.turn_stamps(doc.frontmatter), gaps=gaps)
    assert hit == {"number": 2, "of": 2, "ts": "2026-10-07T10:00:01+00:00", "speaker": "assistant"}
    crossing = doc.body[g0 - 8:g1 + 8]
    assert evidence.verify(memory, result.episode_id, crossing).kind == "reasoning"
    view = provenance.episode_document(memory, result.episode_id)
    assert any(t.role == "gap" and doc.body[t.content_start:t.end] == MARKER for t in view.turns)
    fragments = [t for t in view.turns if t.role == "assistant"]
    assert [(t.model, t.effort) for t in fragments] == [("synthetic-model", "high")] * 2
    assert view.agent.model == "synthetic-model" and view.agent.effort == "high"
    assert len(evidence.mask_gaps(doc.body, gaps)) == len(doc.body)
    _, again, same = capture(tmp_path, monkeypatch, harness, [("user", "first role"), ("assistant", reply)])
    assert again.status == "unchanged" and same.body == doc.body and same.frontmatter == doc.frontmatter


@pytest.mark.parametrize("harness", tx.HARNESSES)
def test_reply_gap_and_session_gap_coexist_without_masking_persons_literal_marker(tmp_path, monkeypatch, harness):
    first = MARKER + "\n" + "role " * 2700 + "first-role-end"
    turns = [("user", first)] + [("assistant" if i % 2 else "user", "context " * 600 + f"\nState: next-{i}")
                                for i in range(1, 100)]
    memory, result, doc = capture(tmp_path, monkeypatch, harness, turns)
    assert "first-role-end" in doc.body and "State: next-99" in doc.body
    assert doc.frontmatter["capture_gap"]["dropped_turns"] > 0 and doc.frontmatter["reply_gaps"]
    conv = tx.extract(harness, lines(harness, turns))
    assert sum(len(t.text) for t in conv.turns) <= 100000
    gaps = evidence.gap_ranges(doc.frontmatter, doc.body)
    assert len(gaps) == len(doc.frontmatter["reply_gaps"]) + 1
    assert evidence.verify(memory, result.episode_id, MARKER, window=(0, len(first) + 6)).kind == "user"
    assert evidence.mask_gaps(doc.body, gaps).startswith("user: " + MARKER)
    for stamp in doc.frontmatter["turns"]:
        assert doc.body[stamp["offset"]:].startswith(stamp["speaker"] + ": ")


@pytest.mark.parametrize("harness", tx.HARNESSES)
def test_short_replies_and_persons_marker_words_remain_whole(harness):
    conv = tx.extract(harness, lines(harness, [("user", MARKER), ("assistant", "short reply")]))
    assert [t.text for t in conv.turns] == [MARKER, "short reply"]


@pytest.mark.parametrize("harness", tx.HARNESSES)
def test_reply_gap_reaches_sleep_search_and_continuity_as_nobodys_words(tmp_path, monkeypatch, harness):
    from api.services import continuity, search_index, search_service
    from api.tests.test_capture_gap_consumers import _sleep_prompts

    reply = "head-reply " + "context " * 700 + "\nState: next: alpha tests."
    memory, result, doc = capture(tmp_path, monkeypatch, harness, [("user", "first role"), ("assistant", reply)])
    sent = _sleep_prompts(memory)
    assert sent and all(MARKER not in text for text in sent)
    assert any(text.startswith("[Cicada's note, not part of the conversation and nobody's words:") for text in sent)
    assert any("State: next: alpha tests." in text for text in sent)
    search_index.rebuild(memory)
    hits = search_service.search(memory, "kept", kinds=["episode"], mode="prefix").results
    assert not any(h.episode_id == result.episode_id for h in hits)
    row = continuity._row(doc.frontmatter)
    v = continuity.view(memory, (f"{result.episode_id}.md", row))
    assert MARKER not in v.turns()[1].text and "nobody's words" in v.turns()[1].text
    assert v.turns()[1].text.endswith("State: next: alpha tests.")


def test_reply_gap_metadata_requires_its_exact_offset_and_omitted_count():
    text = "assistant: head\n" + MARKER + "\ntail"
    at = text.index(MARKER)
    entry = {"offset": at, "omitted_chars": 100}
    assert evidence.gap_ranges({"reply_gaps": [entry]}, text) == ((at, at + len(MARKER)),)
    for invalid in ({**entry, "offset": at + 1}, {**entry, "offset": True},
                    {**entry, "omitted_chars": False}, {**entry, "omitted_chars": 0}):
        assert evidence.gap_ranges({"reply_gaps": [invalid]}, text) == ()
    assert evidence.gap_ranges({}, text) == ()


@pytest.mark.parametrize("harness", tx.HARNESSES)
@pytest.mark.parametrize("keep_assistant", [True, False])
def test_empty_person_record_and_earlier_agent_reply_do_not_consume_first_allowance(harness, keep_assistant):
    first = "first role " * 1300 + "role-end"
    conv = tx.extract(harness, lines(harness, [("assistant", "earlier reply"), ("user", ""), ("user", first)]),
                      keep_assistant=keep_assistant)
    assert [t.text for t in conv.turns if t.role == "user"] == [first]
    assert bool([t for t in conv.turns if t.role == "assistant"]) == keep_assistant


def test_untimed_reply_tail_keeps_original_turn_speaker_when_other_turns_are_timed():
    text = "user: question\nassistant: head\n" + MARKER + "\ntail"
    at = text.index(MARKER)
    gaps = evidence.gap_ranges({"reply_gaps": [{"offset": at, "omitted_chars": 100}]}, text)
    stamps = {0: {"ts": "2026-10-07T10:00:00+00:00", "speaker": "user"}}
    assert evidence.turn_at(text, text.index("tail"), stamps, gaps) == {
        "number": 2, "of": 2, "ts": None, "speaker": "assistant"}


def test_zero_turn_cap_override_keeps_legacy_default_instead_of_removing_first_limit():
    conv = tx.extract_claude_code(lines("claude-code", [("user", "first role " * 1700)]), turn_cap=0)
    assert len(conv.turns[0].text) == tx.TURN_CAP_CHARS


@pytest.mark.parametrize("harness", tx.HARNESSES)
@pytest.mark.parametrize("marker", ["user: ", "assistant: ", "speaker:x: ", "video [01:23]: "])
def test_reply_tail_cut_cannot_manufacture_a_turn_marker(tmp_path, monkeypatch, harness, marker):
    # No original newline: the cut would manufacture column one at this marker.
    tail_chars = (tx.TURN_CAP_CHARS - len(MARKER) - 2) // 2
    tail_text = (marker + "probe-tail-sentinel " + "more context " * 100)[:tail_chars - 1] + "."
    reply = "agent report: " + "context " * 400 + "see the field " + tail_text
    assert "\n" not in reply and reply[-tail_chars:] == tail_text
    memory, result, doc = capture(tmp_path, monkeypatch, harness, [("user", "first role"), ("assistant", reply)])
    gaps = evidence.gap_ranges(doc.frontmatter, doc.body)
    (g0, g1), = gaps
    at = doc.body.index("probe-tail-sentinel")
    assert evidence.speaker_kind(doc.body, at, gaps=gaps) == "assistant"
    assert evidence.turn_at(doc.body, at, evidence.turn_stamps(doc.frontmatter), gaps) == {
        "number": 2, "of": 2, "ts": "2026-10-07T10:00:01+00:00", "speaker": "assistant"}
    ev = evidence.verify(memory, result.episode_id, "probe-tail-sentinel")
    assert ev.kind == "assistant" and ev.start == at and doc.body[ev.start:ev.end] == "probe-tail-sentinel"
    reader = provenance.episode_document(memory, result.episode_id)
    assert [t.role for t in reader.turns] == ["user", "assistant", "gap", "assistant"]
    assert reader.turns[-1].model == "synthetic-model" and reader.turns[-1].effort == "high"
    conv = tx.extract(harness, lines(harness, [("user", "first role"), ("assistant", reply)]))
    assert len(conv.turns[1].text) == 2000 and doc.frontmatter["turn_count"] == 2
    assert doc.body[g0:g1] == MARKER and doc.frontmatter["reply_gaps"][0]["offset"] == g0
    assert doc.body[g1 + 1:].startswith("…" + tail_text)
    omitted = doc.frontmatter["reply_gaps"][0]["omitted_chars"]
    assert omitted == len(reply) - (2000 - len(MARKER) - 2 - 1)


@pytest.mark.parametrize("cap", [len(MARKER) + 3, len(MARKER) + 4])
def test_tiny_reply_cap_does_not_overflow_when_safe_tail_prefix_cannot_fit(cap):
    conv = tx.extract_claude_code(lines("claude-code", [("user", "brief"), ("assistant", "context " * 400)]),
                                 turn_cap=cap)
    assert len(conv.turns[1].text) == cap and conv.turns[1].text.endswith("…")
    assert conv.turns[1].reply_gap is None
