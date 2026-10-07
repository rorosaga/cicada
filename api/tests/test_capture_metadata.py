"""G110 slice 1a T2: capture records where it stopped (plan C7).

`last_turn_at`, `turn_count`, exact `tail_turns`, `capture_gap` while the
session cap refuses turns, `capture_flags` for note-like person turns, and a
single `continues` from the continuity registry — all outside `content_hash`
and before `turns`. An unchanged body whose metadata moved is rewritten in
place (status `metadata`) with the same body, hash and `processed` state.
Synthetic transcripts only."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import continuity_sessions, episode_ids, markdown_parser, recall_text, sleep_cycle, telemetry
from api.services import transcript_capture as tc
from api.services import transcript_extract

SID = "11111111-2222-4333-8444-555555555555"
CWD = "/home/example/alpha-project"


def _line(typ, content, ts):
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": SID, "cwd": CWD,
                       "message": {"role": typ, "content": content}})


def _ts(i: int) -> str:
    return f"2026-09-03T{10 + i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}.000Z"


def _transcript(turns, *, timed=True) -> str:
    out = []
    for i, (role, text) in enumerate(turns):
        ts = _ts(i) if timed else None
        content = text if role == "user" else [{"type": "text", "text": text}]
        obj = json.loads(_line(role, content, ts or ""))
        if not timed:
            obj.pop("timestamp")
        out.append(json.dumps(obj))
    return "\n".join(out) + "\n"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})


@pytest.fixture
def roots(tmp_path, monkeypatch):
    claude = tmp_path / "claude-projects" / "-home-example-alpha-project"
    claude.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: claude.parent)
    return claude


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


def _capture(roots, memory, turns, **kw):
    path = roots / f"{SID}.jsonl"
    path.write_text(_transcript(turns, timed=kw.pop("timed", True)), encoding="utf-8")
    return tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                                 cwd=CWD, keep_assistant=True, **kw)


def _episode(memory, r):
    return memory / "episodes" / f"{r.episode_id}.md"


def test_metadata_is_recorded_before_turns_and_outside_the_hash(roots, memory):
    r = _capture(roots, memory, [("user", "make the parser strict"), ("assistant", "done; one test fails")])
    fp = _episode(memory, r)
    doc = markdown_parser.parse(fp)
    fm = doc.frontmatter
    assert fm["turn_count"] == 2 and fm["last_turn_at"] == "2026-09-03T10:00:01+00:00"
    assert fm["tail_turns"] == [{"offset": 0, "speaker": "user", "at": "2026-09-03T10:00:00+00:00"},
                                {"offset": len("user: make the parser strict") + 1, "speaker": "assistant",
                                 "at": "2026-09-03T10:00:01+00:00"}]
    assert "capture_gap" not in fm and "capture_flags" not in fm and "continues" not in fm
    keys = list(fm)
    assert keys[-1] == "turns" and keys.index("tail_turns") < keys.index("turns")
    head = fp.read_text().split("\nturns:")[0]
    assert "last_turn_at:" in head and "project_dir:" in head and "session_id:" in head
    import hashlib
    assert fm["content_hash"] == hashlib.sha256(doc.body.encode()).hexdigest()[:12]


def test_tail_turns_are_exact_past_the_500_entry_sidecar(roots, memory, monkeypatch):
    monkeypatch.setattr(transcript_extract, "SESSION_CAP_CHARS", 10_000_000)
    turns = [("user" if i % 2 == 0 else "assistant", f"turn {i}\nuser: not a boundary {i}") for i in range(502)]
    r = _capture(roots, memory, turns)
    doc = markdown_parser.parse(_episode(memory, r))
    fm, body = doc.frontmatter, doc.body
    assert len(fm["turns"]) == 500 and fm["turn_count"] == 502
    offsets = [e["offset"] for e in fm["tail_turns"]] + [len(body) + 1]
    pieces = [body[offsets[i]:offsets[i + 1] - 1] for i in range(len(fm["tail_turns"]))]
    expected = [f"{role}: {text}" for role, text in turns[-8:]]
    assert pieces == expected
    assert [e["speaker"] for e in fm["tail_turns"]] == [role for role, _ in turns[-8:]]
    assert fm["tail_turns"][-1]["at"] == tc._utc(_ts(501))


def test_untimed_turns_record_no_time(roots, memory):
    r = _capture(roots, memory, [("user", "a"), ("assistant", "b")], timed=False)
    fm = markdown_parser.parse(_episode(memory, r)).frontmatter
    assert "last_turn_at" not in fm and all("at" not in e for e in fm["tail_turns"])


def test_a_refused_turn_on_an_unchanged_body_is_a_metadata_write(roots, memory, monkeypatch):
    monkeypatch.setattr(transcript_extract, "SESSION_CAP_CHARS", 60)
    base = [("user", "u" * 20), ("assistant", "a" * 20), ("user", "x" * 30)]   # the third is refused
    r1 = _capture(roots, memory, base)
    fp = _episode(memory, r1)
    fm1 = markdown_parser.parse(fp).frontmatter
    assert fm1["capture_gap"] == {"dropped_turns": 1, "last_seen_at": "2026-09-03T10:00:02+00:00"}
    # Sleep consolidated it meanwhile.
    doc = markdown_parser.parse(fp)
    sleep_cycle._mark_episodes_processed([{"filepath": fp, "id": r1.episode_id,
                                            "revision": episode_ids.body_revision(doc.body)}])
    body_before = markdown_parser.parse(fp).body
    r2 = _capture(roots, memory, base + [("assistant", "y" * 30)])
    assert r2.status == "metadata"
    doc2 = markdown_parser.parse(fp)
    assert doc2.body == body_before and doc2.frontmatter["content_hash"] == fm1["content_hash"]
    assert doc2.frontmatter["processed"] is True and doc2.frontmatter["processed_by"] == "sleep"
    assert doc2.frontmatter["capture_gap"] == {"dropped_turns": 2, "last_seen_at": "2026-09-03T10:00:03+00:00"}
    assert list(doc2.frontmatter)[-1] == "turns"
    # Nothing moved: unchanged, no write.
    assert _capture(roots, memory, base + [("assistant", "y" * 30)]).status == "unchanged"
    # Capture fits again: an ordinary update, and the gap is gone.
    monkeypatch.setattr(transcript_extract, "SESSION_CAP_CHARS", 10_000)
    r4 = _capture(roots, memory, base + [("assistant", "y" * 30)])
    assert r4.status == "updated" and "capture_gap" not in markdown_parser.parse(fp).frontmatter


def test_note_like_person_turns_are_kept_and_counted(roots, memory):
    turns = [("user", "here is what I saw:\n" + recall_text.INJECTION_PREFIX + " at session start ...\nfix it"),
             ("assistant", "ok")]
    r = _capture(roots, memory, turns)
    doc = markdown_parser.parse(_episode(memory, r))
    assert doc.frontmatter["capture_flags"] == {"note_like_turns": 1}
    assert "fix it" in doc.body and "here is what I saw" in doc.body


def test_continues_comes_from_the_registry_and_is_stamped_once(roots, memory, tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    paths = (memory,)
    turns = [("user", "continue"), ("assistant", "on it")]
    r1 = _capture(roots, memory, turns, bank_paths=paths)
    fp = _episode(memory, r1)
    assert "continues" not in markdown_parser.parse(fp).frontmatter          # the row is not there yet
    assert continuity_sessions.apply(memory, bank_paths=paths, harness="claude-code", session_id=SID,
                                     events={"continues": "ep_2026-09-01_004",
                                             "started_at": episode_ids.utc_now_iso()}, deadline=None) == "ok"
    r2 = _capture(roots, memory, turns, bank_paths=paths)                     # same body
    assert r2.status == "metadata"
    assert markdown_parser.parse(fp).frontmatter["continues"] == "ep_2026-09-01_004"
    # Never rewritten: hand the episode another value and recapture.
    doc = markdown_parser.parse(fp)
    fm = dict(doc.frontmatter)
    fm["continues"] = "ep_2026-09-01_009"
    markdown_parser.write(fp, fm, doc.body)
    assert _capture(roots, memory, turns + [("user", "more")], bank_paths=paths).status == "updated"
    assert markdown_parser.parse(fp).frontmatter["continues"] == "ep_2026-09-01_009"


def test_without_bank_paths_the_registry_is_not_read(roots, memory, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("registry read without the bank guard")
    monkeypatch.setattr(continuity_sessions, "get", boom)
    assert _capture(roots, memory, [("user", "q")]).status == "created"


def test_ledger_refs_carry_counts_only(roots, memory, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(transcript_extract, "SESSION_CAP_CHARS", 30)
    _capture(roots, memory, [("user", "u" * 20), ("assistant", "secret words " * 3)], bank="b")
    ev = [e for e in telemetry.read_events() if e.kind == "capture"][-1]
    assert ev.refs["refused_turns"] == 1 and ev.refs["note_like_turns"] == 0
    assert "secret words" not in ev.to_json()
