"""G110 gate B2 (ruling 2026-10-07): an over-cap session keeps its head and
its tail. The body holds the head's turns, one marker line for the dropped
middle, then the tail's turns; every offset the episode records (the G118
sidecar, `tail_turns`) stays exact around the marker; the marker is never
anyone's words; and the G104 costs are what the ruling accepted (a turn past
the cap re-queues the episode). Synthetic transcripts only."""
from __future__ import annotations

import pytest

from api.services import continuity, episode_ids, evidence, markdown_parser, sleep_cycle, transcript_extract
from api.tests.test_capture_metadata import _capture, _episode, _fresh, memory, roots  # noqa: F401 - fixtures

CAP = 1_000


@pytest.fixture(autouse=True)
def _small_cap(monkeypatch):
    monkeypatch.setattr(transcript_extract, "SESSION_CAP_CHARS", CAP)
    monkeypatch.setattr(transcript_extract, "TAIL_BLOCK_TURNS", 2)


def _turns(n: int) -> list[tuple[str, str]]:
    return [("user" if i % 2 == 0 else "assistant", f"step {i:03d} of the alpha-project parser work, noted")
            for i in range(n)]


def _parts(body: str) -> tuple[str, str, str]:
    lines = body.split("\n")
    at = next(i for i, line in enumerate(lines) if line.startswith("[Cicada: "))
    return "\n".join(lines[:at]), lines[at], "\n".join(lines[at + 1:])


def test_the_body_is_head_marker_tail_and_every_offset_is_exact(roots, memory):
    turns = _turns(40)                                   # 40 x 48 chars = 1,920 > 1,000
    r = _capture(roots, memory, turns)
    doc = markdown_parser.parse(_episode(memory, r))
    fm, body = doc.frontmatter, doc.body
    head, marker, tail = _parts(body)
    gap = fm["capture_gap"]
    kept_head = head.count("\n") + 1
    kept_tail = tail.count("\n") + 1
    assert kept_head + gap["dropped_turns"] + kept_tail == 40 and fm["turn_count"] == kept_head + kept_tail
    assert marker == evidence.gap_line(gap["dropped_turns"], gap["first_dropped_at"], gap["last_dropped_at"])
    assert body[gap["offset"]:gap["offset"] + len(marker)] == marker
    assert gap["first_dropped_at"] == "2026-09-03T10:00:%02d+00:00" % kept_head
    assert tail.endswith(turns[-1][1]) and head.startswith("user: " + turns[0][1])
    # tail_turns: exact pieces of the body.
    offsets = [e["offset"] for e in fm["tail_turns"]] + [len(body) + 1]
    pieces = [body[offsets[i]:offsets[i + 1] - 1] for i in range(len(fm["tail_turns"]))]
    assert pieces == [f"{role}: {text}" for role, text in turns[-8:]]
    # The G118 sidecar: every entry starts its own turn, head and tail alike.
    by_text = {f"{role}: {text}": i for i, (role, text) in enumerate(turns)}
    for e in fm["turns"]:
        line = body[e["offset"]:].split("\n", 1)[0]
        i = by_text[line]
        assert e["speaker"] == turns[i][0] and e["ts"] == "2026-09-03T10:00:%02d+00:00" % i
    assert len(fm["turns"]) == fm["turn_count"]


def test_the_marker_is_never_anyones_words(roots, memory):
    r = _capture(roots, memory, _turns(40))
    body = markdown_parser.parse(_episode(memory, r)).body
    _, marker, tail = _parts(body)
    ev = evidence.verify(None, r.episode_id, marker[1:30], text=body)
    assert ev.kind == "reasoning"                         # degraded, and the claim is still written by its caller
    assert evidence.verify(None, r.episode_id, "step 038 of the alpha-project", text=body).kind == "user"
    assert evidence.verify(None, r.episode_id, "step 039 of the alpha-project", text=body).kind == "assistant"
    assert evidence.is_gap_line(marker) and not evidence.is_gap_line("user: " + marker)


def test_the_head_bytes_are_stable_and_the_tail_moves_in_blocks(roots, memory):
    r1 = _capture(roots, memory, _turns(40))
    head1, marker1, _ = _parts(markdown_parser.parse(_episode(memory, r1)).body)
    for n in (41, 42, 43):
        r = _capture(roots, memory, _turns(n))
        head, marker, tail = _parts(markdown_parser.parse(_episode(memory, r)).body)
        assert head == head1
        assert tail.endswith(_turns(n)[-1][1])


def test_a_turn_past_the_cap_requeues_the_episode(roots, memory):
    """The G104 cost ruling B2 accepted: while an over-cap session is active,
    every Stop with a new turn changes the body and re-queues the episode."""
    r1 = _capture(roots, memory, _turns(40))
    fp = _episode(memory, r1)
    doc = markdown_parser.parse(fp)
    sleep_cycle._mark_episodes_processed([{"filepath": fp, "id": r1.episode_id,
                                            "revision": episode_ids.body_revision(doc.body)}])
    r2 = _capture(roots, memory, _turns(41))
    fm = markdown_parser.parse(fp).frontmatter
    assert r2.status == "updated" and fm["processed"] is False and "processed_by" not in fm
    assert _capture(roots, memory, _turns(41)).status == "unchanged"


def test_continuity_turns_do_not_carry_the_marker(roots, memory):
    r = _capture(roots, memory, _turns(40))
    fm = markdown_parser.parse(_episode(memory, r)).frontmatter
    body = markdown_parser.parse(_episode(memory, r)).body
    ts = continuity.split_turns(body, [{"offset": o, **e} for o, e in evidence.turn_stamps(fm).items()],
                                fm["tail_turns"], fm["turn_count"],
                                gap_at=continuity.gap_offset(body, fm["capture_gap"]))
    assert len(ts) == fm["turn_count"] and all("[Cicada:" not in t.text for t in ts)
    assert ts[-1].text == _turns(40)[-1][1] and all(t.exact for t in ts)


# --- fix round 1 (review blocker 2): a delayed capture never overwrites a newer one ---


def test_an_older_flush_that_finishes_after_a_newer_stop_does_not_replace_it(roots, memory, monkeypatch):
    """Deterministic, with events (no timing guesses): a PreCompact flush reads
    the transcript at 41 turns and stalls before the writer lock; the transcript
    grows and a Stop commits 45 turns; the flush then reaches the lock. It read
    less of the transcript than what is stored, so it writes nothing."""
    import threading
    from api.services import transcript_capture as tc
    from api.tests.test_capture_metadata import SID, _transcript, CWD

    path = roots / f"{SID}.jsonl"
    entered, release, out = threading.Event(), threading.Event(), {}
    real = tc.extract

    def delayed(*a, **kw):
        conv = real(*a, **kw)
        if threading.current_thread().name == "old-flush":
            entered.set()
            assert release.wait(10)
        return conv

    def flush():
        out["flush"] = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                                             cwd=CWD, keep_assistant=True, hook_event="PreCompact")

    _capture(roots, memory, _turns(40))
    path.write_text(_transcript(_turns(41)), encoding="utf-8")
    monkeypatch.setattr(tc, "extract", delayed)
    t = threading.Thread(target=flush, name="old-flush")
    t.start()
    assert entered.wait(10)
    newer = _capture(roots, memory, _turns(45))
    fp = _episode(memory, newer)
    after_stop = fp.read_bytes()
    release.set()
    t.join(10)
    assert not t.is_alive()
    assert out["flush"].status == "superseded" and fp.read_bytes() == after_stop
    assert markdown_parser.parse(fp).body.endswith(_turns(45)[-1][1])
    assert len(list((memory / "episodes").glob("ep_*.md"))) == 1


def test_a_transcript_that_really_shrank_is_still_captured(roots, memory):
    """Superseded means a STALE read (the file now holds at least what is
    stored), not a smaller file — a replaced transcript is never stuck."""
    _capture(roots, memory, _turns(45))
    r = _capture(roots, memory, _turns(41))
    assert r.status == "updated"
    assert markdown_parser.parse(_episode(memory, r)).body.endswith(_turns(41)[-1][1])


# --- fix round 1 (review should-fix 3): model/effort stay on the reply they belong to ---


def test_a_sliding_tail_never_moves_effort_or_model_to_another_reply(roots, memory, monkeypatch):
    monkeypatch.setattr(transcript_extract, "SESSION_CAP_CHARS", 100_000)
    monkeypatch.setattr(transcript_extract, "TAIL_BLOCK_TURNS", 10)
    turns = [("user" if i % 2 == 0 or i == 59 else "assistant", (f"turn {i:03d} " + "word " * 220)[:1000])
             for i in range(150)]
    r1 = _capture(roots, memory, turns[:140], effort="high")             # the hook's effort lands on turn 139
    fp = _episode(memory, r1)
    doc = markdown_parser.parse(fp)
    last = doc.frontmatter["turns"][-1]
    assert last["speaker"] == "assistant" and last["effort"] == "high"
    # A model only the stored sidecar knew (the transcript line never said it) — the same carry-over rule.
    fm = dict(doc.frontmatter)
    fm["turns"] = [*fm["turns"][:-1], {**last, "model": "claude-opus-4-1"}]
    markdown_parser.write(fp, fm, doc.body)
    old_offset = last["offset"]
    _capture(roots, memory, turns[:150])                                 # no effort from the hook this time
    new = markdown_parser.parse(fp)
    by_offset = {e["offset"]: e for e in new.frontmatter["turns"]}
    stamp_139 = next(e for e in new.frontmatter["turns"]
                     if new.body.startswith("assistant: turn 139", e["offset"]))
    assert stamp_139["effort"] == "high" and stamp_139.get("model") == "claude-opus-4-1"   # remapped, same reply
    assert by_offset.get(old_offset, {}).get("effort") is None or new.body.startswith("assistant: turn 139", old_offset)
    newest = new.frontmatter["turns"][-1]
    assert new.body.startswith("assistant: turn 149", newest["offset"])
    assert "effort" not in newest and "model" not in newest


def test_the_first_crossing_of_the_cap_keeps_effort_on_its_own_reply(roots, memory, monkeypatch):
    monkeypatch.setattr(transcript_extract, "SESSION_CAP_CHARS", 100_000)
    monkeypatch.setattr(transcript_extract, "TAIL_BLOCK_TURNS", 10)
    turns = [("user" if i % 2 == 0 else "assistant", (f"turn {i:03d} " + "word " * 220)[:1000]) for i in range(110)]
    r = _capture(roots, memory, turns[:100], effort="high")              # 99,900 chars: under the cap, no gap
    fp = _episode(memory, r)
    assert "capture_gap" not in markdown_parser.parse(fp).frontmatter
    _capture(roots, memory, turns[:110])                                 # crosses the cap: head + marker + tail
    new = markdown_parser.parse(fp)
    assert new.frontmatter["capture_gap"]["dropped_turns"] > 0
    efforts = {new.body[e["offset"]:e["offset"] + 19]: e.get("effort") for e in new.frontmatter["turns"]}
    assert efforts.get("assistant: turn 099") == "high"
    assert [k for k, v in efforts.items() if v] == ["assistant: turn 099"]
