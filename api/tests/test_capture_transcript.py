"""G105 R2/R3/R10: the endpoint validates the path, writes ONE episode per
session in the importer's body shape, updates it in place on a later firing,
and records a counts-only ledger row. Synthetic transcripts only."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.services import markdown_parser, telemetry, transcript_capture as tc
from api.services.evidence import speaker_kind

SID = "11111111-2222-4333-8444-555555555555"


def _line(typ, content, ts="2026-09-03T10:00:00.000Z", **extra):
    o = {"type": typ, "uuid": "u", "timestamp": ts, "sessionId": SID, "cwd": "/home/example/alpha-project",
         "message": {"role": typ, "content": content}}
    o.update(extra)
    return json.dumps(o)


def _transcript(turns: list[tuple[str, str]]) -> str:
    lines = []
    for role, text in turns:
        lines.append(_line(role, text if role == "user" else [{"type": "text", "text": text}]))
    return "\n".join(lines) + "\n"


@pytest.fixture(autouse=True)
def _fresh_episode_cache(monkeypatch):
    # The writer's session -> path cache is process-global; every test gets
    # its own bank, so start each from an empty one (without this, test N
    # finds test N-1's episode file — it still exists under pytest's tmp).
    monkeypatch.setattr(tc, "_episode_cache", {})


@pytest.fixture
def roots(tmp_path, monkeypatch):
    claude = tmp_path / "claude-projects" / "-home-example-alpha-project"
    codex = tmp_path / "codex-sessions" / "2026" / "09" / "03"
    claude.mkdir(parents=True)
    codex.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: {"claude-code": claude.parent, "codex": codex.parent.parent.parent}[h])
    return {"claude": claude, "codex": codex}


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --- validation (R2) -----------------------------------------------------------


def test_refuses_paths_outside_the_harness_root(roots, tmp_path):
    stray = _write(tmp_path / f"{SID}.jsonl", _transcript([("user", "hi")]))
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(stray))
    assert e.value.reason == "outside_root"


def test_refuses_symlink_that_escapes_the_root(roots, tmp_path):
    target = _write(tmp_path / "elsewhere.jsonl", _transcript([("user", "hi")]))
    link = roots["claude"] / f"{SID}.jsonl"
    os.symlink(target, link)
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(link))
    assert e.value.reason == "outside_root"


def test_refuses_stem_mismatch_non_jsonl_and_oversize(roots, monkeypatch):
    other = _write(roots["claude"] / "22222222-2222-4333-8444-555555555555.jsonl", "x")
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(other))
    assert e.value.reason == "stem_mismatch"
    txt = _write(roots["claude"] / f"{SID}.txt", "x")
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(txt))
    assert e.value.reason == "not_jsonl"
    big = _write(roots["claude"] / f"{SID}.jsonl", "x")
    monkeypatch.setattr(tc, "MAX_TRANSCRIPT_BYTES", 0)
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", SID, str(big))
    assert e.value.reason == "too_large"


def test_refuses_bad_harness_and_bad_session_id(roots):
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("cursor", SID, "/x.jsonl")
    assert e.value.reason == "bad_harness"
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("claude-code", "../etc", "/x.jsonl")
    assert e.value.reason == "bad_session_id"


def test_codex_path_must_contain_the_session_id(roots):
    good = _write(roots["codex"] / f"rollout-2026-09-03T10-00-00-{SID}.jsonl", "{}")
    assert tc.validate_transcript_path("codex", SID, str(good)) == good.resolve()
    bad = _write(roots["codex"] / "rollout-2026-09-03T10-00-00-other.jsonl", "{}")
    with pytest.raises(tc.TranscriptRefused) as e:
        tc.validate_transcript_path("codex", SID, str(bad))
    assert e.value.reason == "stem_mismatch"


# --- writer (R3, R12, R13) ------------------------------------------------------


def test_first_firing_creates_one_episode_in_the_importer_shape(roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([
        ("user", "Should alpha-project move to sqlite-vec?"),
        ("assistant", "Yes — bob-example agreed last week."),
    ]))
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                              cwd="/home/example/alpha-project", keep_assistant=True)
    assert r.status == "created"
    assert r.episode_id == "ep_2026-09-03_001"
    parsed = markdown_parser.parse(memory / "episodes" / "ep_2026-09-03_001.md")
    fm = parsed.frontmatter
    assert fm["origin"] == "claude-code" and fm["source"] == "claude-code" and fm["harness"] == "claude-code"
    assert fm["session_id"] == SID and fm["project_dir"] == "/home/example/alpha-project"
    assert fm["capture_kind"] == "transcript" and fm["processed"] is False and fm["turns"] == 2
    assert fm["title"] == "Should alpha-project move to sqlite-vec?"
    assert fm["timestamp"] == "2026-09-03T10:00:00+00:00"
    assert "processed_by" not in fm
    body = parsed.body
    assert body == "user: Should alpha-project move to sqlite-vec?\nassistant: Yes — bob-example agreed last week."
    # G118: the marker shape the span endpoint's speaker_kind reads.
    assert speaker_kind(body, body.index("Yes")) == "assistant"
    assert speaker_kind(body, 0) == "user"


def test_second_firing_updates_in_place_and_requeues(roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "Q1")]))
    first = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                                  cwd=None, keep_assistant=True)
    ep = memory / "episodes" / f"{first.episode_id}.md"
    # Sleep consolidated it in between.
    parsed = markdown_parser.parse(ep)
    fm = dict(parsed.frontmatter)
    fm["processed"] = True
    fm["processed_by"] = "sleep"
    markdown_parser.write(ep, fm, parsed.body)
    old_hash = fm["content_hash"]

    path.write_text(_transcript([("user", "Q1"), ("assistant", "A1"), ("user", "Q2")]), encoding="utf-8")
    second = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                                   cwd=None, keep_assistant=True)
    assert second.status == "updated" and second.episode_id == first.episode_id
    assert len(list((memory / "episodes").glob("ep_*.md"))) == 1
    fm2 = markdown_parser.parse(ep).frontmatter
    assert fm2["processed"] is False and "processed_by" not in fm2
    assert fm2["content_hash"] != old_hash and fm2["id"] == first.episode_id
    assert fm2["turns"] == 3

    third = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                                  cwd=None, keep_assistant=True)
    assert third.status == "unchanged"
    assert markdown_parser.parse(ep).frontmatter["processed"] is False


def test_mcp_episode_from_the_same_session_is_never_touched(roots, memory):
    mcp = memory / "episodes" / "ep_2026-09-03_001.md"
    markdown_parser.write(mcp, {"id": "ep_2026-09-03_001", "timestamp": "2026-09-03T09:00:00+00:00",
                                "source": "mcp", "origin": "mcp", "processed": True, "session_id": SID}, "user: saved via MCP")
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "Q1")]))
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                              cwd=None, keep_assistant=True)
    assert r.status == "created" and r.episode_id == "ep_2026-09-03_002"
    assert markdown_parser.parse(mcp).frontmatter["processed"] is True


def test_empty_conversation_writes_nothing(roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _line("user", [{"type": "tool_result", "content": "x"}]) + "\n")
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                              cwd=None, keep_assistant=True)
    assert r.status == "empty" and r.episode_id is None
    assert list((memory / "episodes").glob("*.md")) == []


def test_keep_assistant_false_writes_only_the_person(roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "Q"), ("assistant", "A")]))
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                              cwd=None, keep_assistant=False)
    body = markdown_parser.parse(memory / "episodes" / f"{r.episode_id}.md").body
    assert body == "user: Q"


# --- ledger (R10) ---------------------------------------------------------------


def test_ledger_row_is_counts_only(roots, memory, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "secret words about alpha-project")]))
    tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(path),
                          cwd="/home/example/alpha-project", keep_assistant=True, bank="test-bank")
    events = [e for e in telemetry.read_events() if e.kind == "capture"]
    assert len(events) == 1
    ev = events[0]
    assert ev.stage == "claude-code" and ev.bank == "test-bank" and ev.connection is None
    assert ev.refs["status"] == "created" and ev.refs["turns_user"] == 1 and ev.refs["session_id"] == SID
    raw = ev.to_json()
    assert "secret words" not in raw and "alpha-project" not in raw
    assert "capture" in telemetry.KINDS and "capture" in telemetry.NON_SPEND_KINDS


# --- endpoint --------------------------------------------------------------------


@pytest.fixture
def client(memory, monkeypatch):
    # The suite's established pattern (test_telegram_capture._client): point
    # the env at tmp memory and drop the lru_cache — `memory_path` is a
    # property over `memory_root`, not a constructor field.
    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_endpoint_creates_then_refuses_bad_path(client, roots, memory):
    path = _write(roots["claude"] / f"{SID}.jsonl", _transcript([("user", "Q")]))
    r = client.post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                   "transcript_path": str(path), "cwd": "/home/example/alpha-project"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "created" and r.json()["episodeId"] == "ep_2026-09-03_001"
    bad = client.post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                     "transcript_path": "/etc/passwd"})
    assert bad.status_code == 400 and bad.json()["detail"] in ("outside_root", "not_jsonl")
    assert client.post("/capture/transcript", json={"harness": "cursor", "session_id": SID,
                                                    "transcript_path": str(path)}).status_code == 422


def test_endpoint_requires_bearer_token(memory, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    # Same as test_auth.py's `home` fixture: a developer's shell export must
    # not become the token the request is checked against.
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    from api import config, main
    config.get_settings.cache_clear()
    r = TestClient(main.app).post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                                "transcript_path": "/x.jsonl"})
    config.get_settings.cache_clear()
    assert r.status_code == 401
