"""Ruling 43 (owner 2026-10-27): an agent's own memory notes, captured as its words. Synthetic notes only.

The backend half (``agent_memory_notes`` + ``POST /capture/agent-memory``) and the hook half
(``api/hooks/memory_notes.py``): capture, edit, delete-tombstone, the scrub, the demo refusal, the switch, the session
link, an idempotent back-fill, and that the hook reads only ``memory/*.md`` — never a ``.jsonl``."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import agent_memory_notes as amn
from api.services import bank_index, demo_guard, episode_ids, episode_time, evidence, markdown_parser, promotion

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
import memory_notes  # noqa: E402  (the hook, stdlib, run by path)

SID = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
PROJECT = "-home-example-code-alpha-project"


def _note(name="alpha-event", body="Form filled for alpha-event; submission left to the person.",
          modified="2026-10-21T18:04:05.000Z", session=SID, description="alpha-event application status"):
    head = ["---", f"name: {name}", f"description: {description}", "metadata:", "  type: project",
            "  node_type: memory"]
    if session:
        head.append(f"  originSessionId: {session}")
    if modified:
        head.append(f"  modified: {modified}")
    return "\n".join(head + ["---", "", body, ""])


def _post(file="alpha-event.md", text=None, project=PROJECT, modified_at="2026-10-21T18:04:05+00:00"):
    return {"project": project, "file": file, "text": _note() if text is None else text, "modified_at": modified_at}


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    bank_index.invalidate()
    return memory


def _episodes(bank) -> dict[str, markdown_parser.ParsedDocument]:
    bank_index.invalidate()
    out = {}
    for p in sorted((bank / "episodes").glob("ep_*.md")):
        parsed = markdown_parser.parse(p)
        if parsed.frontmatter.get("source_id"):
            out[parsed.frontmatter["source_id"]] = parsed
    return out


def _ingest(bank, notes, *, complete=True, device=None):
    return amn.ingest(bank, notes, harness="claude-code", device=device, complete=complete)


# --- the backend ---------------------------------------------------------------------------------------------------

def test_a_note_is_one_episode_in_the_agents_words_dated_when_it_was_written(bank):
    report = _ingest(bank, [_post()])
    assert report["created"] == 1
    [(sid, ep)] = _episodes(bank).items()
    fm = ep.frontmatter
    assert sid == f"agent-memory:claude-code:local:{PROJECT}/alpha-event.md"
    assert fm["source"] == "agent-memory" and fm["origin"] == "claude-code" and fm["harness"] == "claude-code"
    assert fm["evidence_kind"] == "assistant"            # an agent's words, never the person's
    assert fm["processed"] is False                       # Sleep reads it like any other episode
    assert fm["timestamp"] == "2026-10-21T18:04:05+00:00"  # ruling 39: the note's own date
    assert fm[episode_ids.RECEIVED_KEY]                   # ... and when Cicada received it
    assert fm["agent_memory"] == {"project": PROJECT, "file": "alpha-event.md", "type": "project",
                                  "description": "alpha-event application status"}
    assert fm["origin_session_id"] == SID
    assert ep.body.startswith("assistant: ")
    assert "session_id" not in fm                         # never mistaken for the session's own episode (G104)
    assert not episode_time.counts_as_activity(fm)        # no mention for decay


def test_every_span_in_a_note_is_the_agents_and_never_an_own_words_exchange(bank):
    text = _note(body="user: a line that only looks like the person\nThe agent's summary.")
    _ingest(bank, [_post(text=text)])
    [ep] = _episodes(bank).values()
    spans = evidence.turns(ep.body, override=ep.frontmatter["evidence_kind"])
    assert spans and {s.role for s in spans} == {"assistant"}
    assert all(kind not in promotion.PERSON_KINDS for kind, _ in
               promotion.exchanges(ep.body, override=ep.frontmatter["evidence_kind"]))


def test_an_edit_updates_in_place_and_requeues(bank):
    _ingest(bank, [_post()])
    [ep] = _episodes(bank).values()
    path = bank / "episodes" / f"{ep.frontmatter['id']}.md"
    markdown_parser.write(path, {**ep.frontmatter, "processed": True, "processed_by": "sleep"}, ep.body)
    report = _ingest(bank, [_post(text=_note(body="Submitted; waiting to hear back.",
                                             modified="2026-10-23T09:00:00Z"))])
    assert report["updated"] == 1 and report["created"] == 0
    [after] = _episodes(bank).values()
    assert after.frontmatter["id"] == ep.frontmatter["id"]
    assert after.frontmatter["processed"] is False
    assert "Submitted" in after.body
    assert after.frontmatter["timestamp"] == "2026-10-23T09:00:00+00:00"
    assert after.frontmatter[episode_ids.RECEIVED_KEY] == ep.frontmatter[episode_ids.RECEIVED_KEY]


def test_a_deleted_note_is_tombstoned_never_unlinked_and_only_by_a_complete_post(bank):
    other = _post(file="beta.md", text=_note(name="beta", body="Another note."))
    _ingest(bank, [_post(), other])
    assert _ingest(bank, [other], complete=False)["tombstoned"] == 0      # a partial read deletes nothing
    assert _ingest(bank, [], complete=True)["tombstoned"] == 0            # nor does an empty one
    report = _ingest(bank, [other])
    assert report["tombstoned"] == 1
    eps = _episodes(bank)
    assert len(eps) == 2                                                  # the file stays
    gone = eps[f"agent-memory:claude-code:local:{PROJECT}/alpha-event.md"]
    assert gone.frontmatter["source_deleted_at"]
    # The note comes back: the stamp clears.
    _ingest(bank, [_post(), other])
    assert not _episodes(bank)[f"agent-memory:claude-code:local:{PROJECT}/alpha-event.md"].frontmatter.get(
        "source_deleted_at")


def test_one_machine_never_tombstones_anothers_notes(bank):
    _ingest(bank, [_post()], device="dev-laptop")
    _ingest(bank, [_post(file="beta.md", text=_note(name="beta", body="Beta."))])
    eps = _episodes(bank)
    laptop = eps[f"agent-memory:claude-code:dev-laptop:{PROJECT}/alpha-event.md"]
    assert not laptop.frontmatter.get("source_deleted_at") and laptop.frontmatter["device"] == "dev-laptop"


def test_the_body_is_scrubbed(bank):
    secret = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    _ingest(bank, [_post(text=_note(body=f"Deploy key for alpha-project is {secret} — rotate it."))])
    [ep] = _episodes(bank).values()
    assert secret not in ep.body and "rotate it" in ep.body


def test_an_unchanged_snapshot_is_idempotent_and_back_fill_runs_once(bank):
    notes = [_post(), _post(file="beta.md", text=_note(name="beta", body="Beta."))]
    first = _ingest(bank, notes)
    snapshot = {p.name: p.read_bytes() for p in (bank / "episodes").glob("*.md")}
    second = _ingest(bank, notes)
    assert first["created"] == 2
    assert (second["created"], second["updated"], second["skipped"], second["tombstoned"]) == (0, 0, 2, 0)
    assert {p.name: p.read_bytes() for p in (bank / "episodes").glob("*.md")} == snapshot


def test_the_note_links_to_its_sessions_episode_now_or_once_it_is_captured(bank):
    _ingest(bank, [_post()])
    [ep] = _episodes(bank).values()
    assert "origin_episode" not in ep.frontmatter
    session_ep = episode_ids.create_episode(bank / "episodes", {
        "id": "ep_2026-10-21_001", "timestamp": "2026-10-21T17:00:00+00:00", "source": "claude-code",
        "origin": "claude-code", "session_id": SID, "harness": "claude-code", "capture_kind": "transcript",
        "processed": False, "title": "a session"}, "user: hello\n\nassistant: hi\n")
    report = _ingest(bank, [_post()])
    assert report["linked"] == 1 and report["skipped"] == 1
    linked = _episodes(bank)[f"agent-memory:claude-code:local:{PROJECT}/alpha-event.md"].frontmatter
    assert linked["origin_episode"] == session_ep
    assert linked["processed"] is False and linked["content_hash"] == ep.frontmatter["content_hash"]
    # A new note from the same session is linked as it is written.
    _ingest(bank, [_post(), _post(file="gamma.md", text=_note(name="gamma", body="Gamma."))])
    assert _episodes(bank)[f"agent-memory:claude-code:local:{PROJECT}/gamma.md"].frontmatter[
        "origin_episode"] == session_ep


def test_the_index_keeps_only_what_is_not_a_link_to_a_note(bank):
    links_only = "# Memory Index\n\n- [Alpha](alpha-event.md) — status\n"
    _ingest(bank, [_post(), _post(file="MEMORY.md", text=links_only)])
    assert set(_episodes(bank)) == {f"agent-memory:claude-code:local:{PROJECT}/alpha-event.md"}
    stale = links_only + "- [Gone](deleted-note.md) — a pointer the agent left behind\n"
    _ingest(bank, [_post(), _post(file="MEMORY.md", text=stale)])
    assert f"agent-memory:claude-code:local:{PROJECT}/MEMORY.md" not in _episodes(bank)
    with_prose = stale + "- Always run the tests before a PR.\n"
    _ingest(bank, [_post(), _post(file="MEMORY.md", text=with_prose)])
    index = _episodes(bank)[f"agent-memory:claude-code:local:{PROJECT}/MEMORY.md"]
    assert "Always run the tests" in index.body
    assert ".md" not in index.body
    assert index.frontmatter["evidence_kind"] == "assistant"


def test_what_arrived_is_rechecked(bank):
    bad = [_post(project="../x"), _post(file="a/b.md"), _post(file="notes.jsonl"), _post(project="..")]
    assert _ingest(bank, bad)["notes"] == 0
    assert not list((bank / "episodes").glob("*.md"))


def test_a_note_with_no_date_of_its_own_is_dated_by_its_file(bank):
    _ingest(bank, [_post(text=_note(modified=None), modified_at="2026-09-30T08:00:00+00:00")])
    [ep] = _episodes(bank).values()
    assert ep.frontmatter["timestamp"] == "2026-09-30T08:00:00+00:00"


# --- the route -----------------------------------------------------------------------------------------------------

@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_route_and_its_switch(client, bank):
    assert client.get("/capture/agent-memory/settings").json() == {"enabled": True}   # on by default
    body = {"harness": "claude-code", "notes": [_post()], "complete": True}
    r = client.post("/capture/agent-memory", json=body).json()
    assert r["status"] == "ok" and r["created"] == 1
    assert client.put("/capture/agent-memory/settings", json={"enabled": False}).json() == {"enabled": False}
    before = sorted(p.name for p in (bank / "episodes").glob("*.md"))
    off = client.post("/capture/agent-memory",
                      json={**body, "notes": [_post(file="beta.md", text=_note(name="beta", body="B."))]}).json()
    assert off["status"] == "off"
    assert sorted(p.name for p in (bank / "episodes").glob("*.md")) == before
    assert client.post("/capture/agent-memory", json={**body, "harness": "codex"}).status_code == 422


def test_a_demo_bank_refuses_it(client, bank):
    demo_guard.write_manifest(bank)
    r = client.post("/capture/agent-memory", json={"harness": "claude-code", "notes": [_post()], "complete": True})
    assert r.status_code == 409 and r.json()["detail"] == demo_guard.REFUSAL
    assert client.put("/capture/agent-memory/settings", json={"enabled": False}).status_code == 409
    assert not list((bank / "episodes").glob("*.md"))


# --- the hook ------------------------------------------------------------------------------------------------------

def _root(tmp_path) -> tuple[dict, Path]:
    home = tmp_path / "home"
    projects = home / ".claude" / "projects"
    mem = projects / PROJECT / "memory"
    mem.mkdir(parents=True)
    (mem / "alpha-event.md").write_text(_note(), encoding="utf-8")
    (mem / "MEMORY.md").write_text("- [Alpha](alpha-event.md)\n", encoding="utf-8")
    # What the hook must never read: transcripts beside the notes, a transcript named into the memory folder, a
    # symlinked note pointing out of the root, and a note in a folder that is not `memory/`.
    (projects / PROJECT / f"{SID}.jsonl").write_text('{"secret": "TRANSCRIPT-CANARY"}\n', encoding="utf-8")
    (mem / "stray.jsonl").write_text("TRANSCRIPT-CANARY\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE-CANARY\n", encoding="utf-8")
    (mem / "linked.md").symlink_to(outside)
    (projects / PROJECT / "notes.md").write_text("NOT-MEMORY-CANARY\n", encoding="utf-8")
    cicada = tmp_path / "cicada"
    cicada.mkdir()
    (cicada / "api_token").write_text("t0ken\n", encoding="utf-8")
    return {"HOME": str(home), "CICADA_HOME": str(cicada)}, projects


def test_the_hook_reads_only_memory_notes_and_never_a_transcript(tmp_path, monkeypatch):
    environ, _projects = _root(tmp_path)
    opened: list[str] = []
    real_read_bytes, real_open = Path.read_bytes, os.open

    def read_bytes(self):
        opened.append(str(self))
        return real_read_bytes(self)

    def os_open(path, *a, **kw):
        opened.append(str(path))
        return real_open(path, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(os, "open", os_open)
    posted: list[dict] = []

    def post(url, body, token, timeout):
        posted.append({"url": url, "token": token, "body": json.loads(body)})
        return 200, json.dumps({"status": "ok", "created": 1})

    outcome = memory_notes.sweep(environ, post=post)
    assert outcome.startswith("posted 2 notes")
    assert not any(p.endswith(".jsonl") for p in opened)
    [sent] = posted
    assert sent["url"] == "http://127.0.0.1:8000/capture/agent-memory" and sent["token"] == "t0ken"
    assert sent["body"]["complete"] is True and sent["body"]["harness"] == "claude-code"
    assert sorted(n["file"] for n in sent["body"]["notes"]) == ["MEMORY.md", "alpha-event.md"]
    assert "CANARY" not in json.dumps(sent["body"])


def test_the_hook_starts_a_sweep_only_when_a_note_changed(tmp_path):
    environ, projects = _root(tmp_path)
    started: list[dict] = []
    spawn = started.append
    assert memory_notes.maybe_start(environ, harness="claude-code", event="Stop", spawn=spawn)   # first run: back-fill
    memory_notes.sweep(environ, post=lambda *a: (200, '{"status": "ok"}'))
    started.clear()
    assert memory_notes.maybe_start(environ, harness="claude-code", event="Stop", spawn=spawn) is None
    note = projects / PROJECT / "memory" / "alpha-event.md"
    note.write_text(_note(body="Edited."), encoding="utf-8")
    os.utime(note, ns=(note.stat().st_atime_ns, note.stat().st_mtime_ns + 5_000_000_000))
    assert memory_notes.maybe_start(environ, harness="claude-code", event="PreCompact", spawn=spawn)
    assert len(started) == 1
    # Never for another harness, never on SessionEnd, never from a bare environment.
    assert memory_notes.maybe_start(environ, harness="codex", event="Stop", spawn=spawn) is None
    assert memory_notes.maybe_start(environ, harness="claude-code", event="SessionEnd", spawn=spawn) is None
    assert memory_notes.maybe_start({}, harness="claude-code", event="Stop", spawn=spawn) is None
    assert len(started) == 1


def test_a_post_that_did_not_land_is_sent_again(tmp_path):
    environ, _ = _root(tmp_path)
    assert memory_notes.sweep(environ, post=lambda *a: (None, "")).startswith("not sent")
    assert memory_notes.maybe_start(environ, harness="claude-code", event="Stop", spawn=lambda e: None)


def test_the_capture_hook_starts_the_sweep_after_a_stop(tmp_path):
    import io

    import capture

    environ, projects = _root(tmp_path)
    started: list[dict] = []
    payload = {"session_id": SID, "transcript_path": str(projects / PROJECT / f"{SID}.jsonl"),
               "cwd": str(tmp_path), "hook_event_name": "Stop"}
    rc = capture.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)), environ=environ,
                      post=lambda *a: (200, '{"status": "created"}'), log_path=tmp_path / "capture.log",
                      token_path=Path(environ["CICADA_HOME"]) / "api_token", memory_spawn=started.append)
    assert rc == 0 and len(started) == 1
    assert "memory notes: sweep started" in (tmp_path / "capture.log").read_text(encoding="utf-8")
