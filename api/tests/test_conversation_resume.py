"""G48 §5 — the resume endpoint validates; the app launches.

Hermetic: a tmp_path bank plus an injected `transcript_exists`. The real
~/.claude is never probed, and nothing here ever opens a transcript.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import conversations as conv
from api.services import bank_index

UUID_A = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
UUID_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def _episode(memory, episode_id, *, session_id, project_dir=None, timestamp="2026-08-30T10:00:00Z"):
    episodes_dir = memory / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {episode_id}", f"timestamp: '{timestamp}'",
             "title: A chat", "processed: true", f"session_id: {session_id}",
             "harness: claude-code"]
    if project_dir is not None:
        lines.append(f"project_dir: {project_dir}")
    lines += ["---", "", "body"]
    (episodes_dir / f"{episode_id}.md").write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(conv, "transcript_exists", lambda pd, sid, root=None: True)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()
    bank_index.invalidate()


def test_malformed_id_is_400(client):
    c, _ = client
    assert c.post("/conversations/not-a-uuid/resume").status_code == 400


def test_a_minted_ses_id_is_400_by_construction(client):
    c, memory = client
    _episode(memory, "ep_1", session_id="ses_2026-08-31_deadbeef", project_dir=str(memory))
    bank_index.invalidate()
    assert c.post("/conversations/ses_2026-08-31_deadbeef/resume").status_code == 400


def test_an_unknown_conversation_is_404(client):
    c, _ = client
    assert c.post(f"/conversations/{UUID_B}/resume").status_code == 404


def test_a_retention_cleaned_transcript_is_409_transcript_gone(client, monkeypatch):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir=str(memory))
    bank_index.invalidate()
    monkeypatch.setattr(conv, "transcript_exists", lambda pd, sid, root=None: False)

    resp = c.post(f"/conversations/{UUID_A}/resume")
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "transcript_gone"


def test_a_live_session_returns_the_argv_descriptor(client):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir=str(memory))
    bank_index.invalidate()

    body = c.post(f"/conversations/{UUID_A}/resume").json()
    assert body["mode"] == "terminal"
    assert body["argv"] == ["claude", "--resume", UUID_A]
    assert body["cwd"] == str(memory)
    assert body["displayCommand"] == f"claude --resume {UUID_A}"


def test_a_cwd_failing_the_charset_gate_is_omitted(client):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir="/Users/x/weird$dir")
    bank_index.invalidate()

    body = c.post(f"/conversations/{UUID_A}/resume").json()
    assert body["cwd"] is None
    assert body["argv"] == ["claude", "--resume", UUID_A]


def test_a_cwd_that_no_longer_exists_is_omitted(client):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir=str(memory / "gone"))
    bank_index.invalidate()

    assert c.post(f"/conversations/{UUID_A}/resume").json()["cwd"] is None


def test_a_relative_cwd_is_refused(client):
    c, memory = client
    _episode(memory, "ep_1", session_id=UUID_A, project_dir="relative/path")
    bank_index.invalidate()

    assert c.post(f"/conversations/{UUID_A}/resume").json()["cwd"] is None
