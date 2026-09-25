"""G141 PJ-4 (R-PJ16, R-CS6..R-CS9): the Stop hook writes G118's per-turn
sidecar ``turns: [{offset, ts, speaker}]`` instead of a count, so a Claude Code
turn is dated by its own time and a resumed session's day-3 turn reads day 3.
Synthetic transcripts only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from api.services import episode_staging, evidence, markdown_parser, transcript_capture as tc

SID = "33333333-2222-4333-8444-555555555555"
REPO = Path(__file__).resolve().parents[2]
D1, D3 = "2026-09-03T10:00:00.000Z", "2026-09-05T08:30:00.000Z"


def _line(role: str, text: str, ts: str) -> str:
    content = text if role == "user" else [{"type": "text", "text": text}]
    return json.dumps({"type": role, "uuid": "u", "timestamp": ts, "sessionId": SID,
                       "cwd": "/home/example/alpha-project", "message": {"role": role, "content": content}})


@pytest.fixture(autouse=True)
def _fresh_episode_cache(monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    folder = tmp_path / "claude-projects" / "-home-example-alpha-project"
    folder.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: folder.parent)
    return folder / f"{SID}.jsonl"


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


def _capture(memory: Path, transcript: Path, turns: list[tuple[str, str, str]]) -> tuple[dict, str]:
    transcript.write_text("\n".join(_line(*t) for t in turns) + "\n", encoding="utf-8")
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                              cwd="/home/example/alpha-project", keep_assistant=True)
    assert r.status in ("created", "updated"), r
    parsed = markdown_parser.parse(memory / "episodes" / f"{r.episode_id}.md")
    return dict(parsed.frontmatter), parsed.body


def test_a_capture_writes_the_sidecar_shape_last_and_outside_the_hash(memory, transcript):
    fm, body = _capture(memory, transcript, [("user", "Q1 about alpha-project", D1), ("assistant", "A1", D1)])
    assert list(fm)[-1] == "turns"
    assert fm["turns"] == [
        {"offset": 0, "ts": "2026-09-03T10:00:00+00:00", "speaker": "user"},
        {"offset": len("user: Q1 about alpha-project") + 1, "ts": "2026-09-03T10:00:00+00:00",
         "speaker": "assistant"},
    ]
    assert all(tuple(e)[:3] == episode_staging.TURN_STAMP_REQUIRED and set(e) <= set(episode_staging.TURN_STAMP_KEYS)
               for e in fm["turns"])
    assert fm["content_hash"] == hashlib.sha256(body.encode()).hexdigest()[:12]  # the body alone


def test_offsets_are_turn_starts_over_the_hooks_own_body(memory, transcript):
    # A person's message can hold a line that only LOOKS like a turn marker.
    question = "Plan:\nassistant: this line is part of the question"
    fm, body = _capture(memory, transcript, [("user", question, D1), ("assistant", "A1", D1)])
    offsets = [e["offset"] for e in fm["turns"]]
    assert offsets == [0, len(f"user: {question}") + 1]  # the rendering's own line starts
    assert set(offsets) < set(evidence.turn_starts(body))  # each one a turn start the reader finds
    quoted = body.index("assistant: this line")
    assert evidence.turn_at(body, quoted, evidence.turn_stamps(fm))["ts"] is None  # never an inferred time


def test_a_grown_session_keeps_a_head_stable_list(memory, transcript):
    first, _ = _capture(memory, transcript, [("user", "Q1", D1), ("assistant", "A1", D1)])
    second, _ = _capture(memory, transcript, [("user", "Q1", D1), ("assistant", "A1", D1),
                                              ("user", "Q2", D3), ("assistant", "A2", D3)])
    assert second["turns"][:2] == first["turns"]
    assert len(second["turns"]) == 4 and list(second)[-1] == "turns"
    assert second["processed"] is False


def test_a_resumed_sessions_day_three_turn_anchors_to_day_three(memory, transcript):
    fm, body = _capture(memory, transcript, [
        ("user", "Started the rover arm plan", D1), ("assistant", "Noted.", D1),
        ("user", "Day three: connecting to lab-cluster-example now", D3), ("assistant", "Good luck.", D3),
    ])
    assert fm["timestamp"].startswith("2026-09-03")  # the session's start, unchanged (R-CS8)
    stamps = evidence.turn_stamps(fm)
    assert evidence.turn_at(body, body.index("Day three"), stamps)["ts"].startswith("2026-09-05")
    assert evidence.turn_at(body, body.index("Started"), stamps)["ts"].startswith("2026-09-03")


def test_a_turn_past_the_cap_has_no_stamp(memory, transcript):
    n = episode_staging.MAX_TURN_STAMPS + 1
    fm, body = _capture(memory, transcript, [("user", f"q{i:04d}", D1) for i in range(1, n + 1)])
    assert len(fm["turns"]) == episode_staging.MAX_TURN_STAMPS == 500
    hit = evidence.turn_at(body, body.index(f"q{n:04d}"), evidence.turn_stamps(fm))
    # R-CS9: nothing stored, so PJ-3's resolver falls back to the episode (basis `episode`).
    assert hit["number"] == n and hit["ts"] is None
    assert fm["timestamp"].startswith("2026-09-03")


def test_an_integer_count_episode_still_reads_as_no_stamps(memory):
    legacy = memory / "episodes" / "ep_2026-09-01_001.md"
    markdown_parser.write(legacy, {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T09:00:00+00:00",
                                   "capture_kind": "transcript", "session_id": "other", "turns": 2},
                          "user: Q\nassistant: A")
    fm = markdown_parser.parse(legacy).frontmatter
    assert evidence.turn_stamps(fm) == {}
    assert evidence.turn_at("user: Q\nassistant: A", 0, evidence.turn_stamps(fm)) is None


def test_a_legacy_count_becomes_the_list_on_the_sessions_next_rewrite(memory, transcript):
    fm, _ = _capture(memory, transcript, [("user", "Q1", D1)])
    path = memory / "episodes" / f"{fm['id']}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "turns": 1}, parsed.body)  # the pre-PJ-4 shape
    grown, _ = _capture(memory, transcript, [("user", "Q1", D1), ("assistant", "A1", D1)])
    assert isinstance(grown["turns"], list) and len(grown["turns"]) == 2


def test_the_turns_key_has_one_shape_owner_and_one_reader():
    """R-PJ16 re-grepped (R-CS7): nothing reads a count. A reader that ever
    needs one gets `turn_count:`, never a second meaning for `turns`."""
    found: set[str] = set()
    for root in (REPO / "api", REPO / "mcp"):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".venv", "tests", "__pycache__"}]
            for name in filenames:
                if name.endswith(".py"):
                    text = (Path(dirpath) / name).read_text(encoding="utf-8")
                    if '"turns"' in text or "'turns'" in text:
                        found.add(name)
    # Round 4 C1: `agent_turns.stamps` is the tolerant reader of the two agent
    # keys (model/effort). It reads a non-list as no stamps, so "nothing reads a
    # count" still holds; `evidence.turn_stamps` stays the reader of ts/speaker.
    assert found == {"episode_staging.py", "evidence.py", "transcript_capture.py", "agent_turns.py"}
