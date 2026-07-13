"""Hermetic tests for the keyless Apple Notes one-way import connector.

Covers:
- ``parse_notes_dump`` — the delimited osascript dump format (multiple
  records, malformed records skipped, empty input);
- ``sync_notes`` — new note -> episode, unchanged note -> skipped, modified
  note (changed ``modified`` timestamp) -> re-emitted as an updated episode,
  dedup index persistence across calls;
- note-id fallback (hash of name+creation-date) when a record has no id;
- plaintext truncation for an oversized note body;
- ``sync_from_local_notes`` degrading to an empty sync when ``_run_osascript``
  raises (no Notes.app / automation denied / not macOS) — never touches real
  ``osascript``;
- the ``POST /sources/sync-notes`` endpoint via ``TestClient`` with an inline
  ``notesDump`` payload.

REAL ``osascript`` IS NEVER INVOKED: every test either calls
``parse_notes_dump``/``sync_notes`` directly with an in-memory dump string, or
monkeypatches ``notes_sync._run_osascript`` before touching
``sync_from_local_notes``/the endpoint's no-body path.
"""

from __future__ import annotations

import asyncio

from api.services import notes_sync
from api.services.notes_sync import FIELD_SEP, RECORD_SEP, NoteRecord


def run(coro):
    return asyncio.run(coro)


def _memory(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    return memory


def _record(note_id, name, body, created, modified, folder) -> str:
    return FIELD_SEP.join([note_id, name, body, created, modified, folder])


def _dump(*records: str) -> str:
    return RECORD_SEP.join(records)


NOTE_1 = _record("note-1", "Grocery list", "Milk, eggs, bread", "2026-07-01", "2026-07-01", "Personal")
NOTE_2 = _record("note-2", "Meeting notes", "Discussed Q3 roadmap", "2026-07-02", "2026-07-02", "Work")
NOTE_2_EDITED = _record(
    "note-2", "Meeting notes", "Discussed Q3 roadmap — action items added", "2026-07-02", "2026-07-05", "Work"
)
NOTE_NO_ID = _record("", "Untitled scratch note", "some scratch text", "2026-07-03", "2026-07-03", "")


# --- parse_notes_dump ---------------------------------------------------


def test_parse_notes_dump_extracts_records():
    dump = _dump(NOTE_1, NOTE_2)
    records = notes_sync.parse_notes_dump(dump)

    assert len(records) == 2
    assert records[0] == NoteRecord(
        note_id="note-1",
        name="Grocery list",
        body="Milk, eggs, bread",
        created="2026-07-01",
        modified="2026-07-01",
        folder="Personal",
    )
    assert records[1].name == "Meeting notes"
    assert records[1].folder == "Work"


def test_parse_notes_dump_empty_input():
    assert notes_sync.parse_notes_dump("") == []


def test_parse_notes_dump_skips_malformed_records():
    malformed = FIELD_SEP.join(["note-x", "Too few fields"])  # only 2 of 6 fields
    dump = _dump(NOTE_1, malformed, NOTE_2)

    records = notes_sync.parse_notes_dump(dump)
    assert len(records) == 2
    assert {r.note_id for r in records} == {"note-1", "note-2"}


def test_parse_notes_dump_skips_blank_trailing_chunk():
    dump = _dump(NOTE_1, NOTE_2) + RECORD_SEP  # trailing separator -> empty chunk
    records = notes_sync.parse_notes_dump(dump)
    assert len(records) == 2


# --- sync_notes: new / unchanged / modified ---------------------------------


def test_sync_notes_new_note_creates_episode(tmp_path):
    memory = _memory(tmp_path)
    result = run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1, NOTE_2)))

    assert result == {"new": 2, "updated": 0, "skipped": 0, "total": 2}

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 2

    from api.services import markdown_parser

    parsed = [markdown_parser.parse(p) for p in episodes]
    titles = {p.frontmatter["title"] for p in parsed}
    assert titles == {"Grocery list", "Meeting notes"}
    for p in parsed:
        assert p.frontmatter["origin"] == "apple-notes"
        assert p.frontmatter["source"] == "apple-notes"
        assert p.frontmatter["processed"] is False


def test_sync_notes_unchanged_note_skipped_on_second_sync(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1, NOTE_2)))

    result = run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1, NOTE_2)))
    assert result == {"new": 0, "updated": 0, "skipped": 2, "total": 2}

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 2  # no new episodes written


def test_sync_notes_modified_note_reemits_updated_episode(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1, NOTE_2)))

    result = run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1, NOTE_2_EDITED)))
    assert result == {"new": 0, "updated": 1, "skipped": 1, "total": 2}

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 3  # original 2 + 1 fresh episode for the edit

    from api.services import markdown_parser

    bodies = [markdown_parser.parse(p).body for p in episodes]
    assert any("action items added" in b for b in bodies)


def test_sync_notes_folder_becomes_tag_hint(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=_dump(NOTE_2)))

    from api.services import markdown_parser

    episode = next((memory / "episodes").glob("ep_*.md"))
    fm = markdown_parser.parse(episode).frontmatter
    assert fm["tags"] == ["Work"]
    assert fm["folder"] == "Work"


def test_sync_notes_no_id_falls_back_to_name_created_hash(tmp_path):
    memory = _memory(tmp_path)
    result1 = run(notes_sync.sync_notes(memory, dump=_dump(NOTE_NO_ID)))
    assert result1["new"] == 1

    # Same name+created (no id) again -> treated as the same note, skipped.
    result2 = run(notes_sync.sync_notes(memory, dump=_dump(NOTE_NO_ID)))
    assert result2 == {"new": 0, "updated": 0, "skipped": 1, "total": 1}


def test_sync_notes_empty_dump(tmp_path):
    memory = _memory(tmp_path)
    result = run(notes_sync.sync_notes(memory, dump=""))
    assert result == {"new": 0, "updated": 0, "skipped": 0, "total": 0}
    assert list((memory / "episodes").glob("ep_*.md")) == []


def test_sync_notes_index_persists_across_calls(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1)))

    import json

    idx_path = memory / "sources" / notes_sync.NOTES_INDEX_FILENAME
    assert idx_path.exists()
    idx = json.loads(idx_path.read_text())
    assert "note-1" in idx
    assert idx["note-1"]["modified"] == "2026-07-01"


# --- plaintext truncation ----------------------------------------------------


def test_sync_notes_truncates_oversized_body(tmp_path):
    memory = _memory(tmp_path)
    huge_body = "x" * (notes_sync.MAX_NOTE_BODY_CHARS + 5000)
    record = _record("note-huge", "Huge note", huge_body, "2026-07-01", "2026-07-01", "")

    run(notes_sync.sync_notes(memory, dump=record))

    from api.services import markdown_parser

    episode = next((memory / "episodes").glob("ep_*.md"))
    body = markdown_parser.parse(episode).body
    assert "[truncated]" in body
    assert len(body) < len(huge_body)


def test_sync_notes_short_body_not_truncated(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=NOTE_1))

    from api.services import markdown_parser

    episode = next((memory / "episodes").glob("ep_*.md"))
    body = markdown_parser.parse(episode).body
    assert "[truncated]" not in body
    assert "Milk, eggs, bread" in body


# --- sync_from_local_notes: never touches real osascript ---------------------


def test_sync_from_local_notes_osascript_failure_returns_empty(tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("osascript failed: not authorized")

    monkeypatch.setattr(notes_sync, "_run_osascript", boom)

    result = run(notes_sync.sync_from_local_notes(tmp_path / "memory"))
    assert result == {"new": 0, "updated": 0, "skipped": 0, "total": 0}


def test_sync_from_local_notes_uses_injected_dump(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    monkeypatch.setattr(notes_sync, "_run_osascript", lambda: _dump(NOTE_1, NOTE_2))

    result = run(notes_sync.sync_from_local_notes(memory))
    assert result["new"] == 2


# --- POST /sources/sync-notes endpoint ---------------------------------------


def _make_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = _memory(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_sync_notes_endpoint_inline_dump(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)

    resp = client.post("/sources/sync-notes", json={"notesDump": _dump(NOTE_1, NOTE_2)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new"] == 2
    assert body["updated"] == 0
    assert body["skipped"] == 0
    assert body["total"] == 2

    # Second sync with identical data -> everything already in the index.
    resp2 = client.post("/sources/sync-notes", json={"notesDump": _dump(NOTE_1, NOTE_2)})
    body2 = resp2.json()
    assert body2["new"] == 0
    assert body2["skipped"] == 2


def test_sync_notes_endpoint_no_body_falls_back_to_local_osascript(tmp_path, monkeypatch):
    """No body -> falls back to sync_from_local_notes; monkeypatch the one
    real I/O seam so this stays hermetic and never touches real osascript."""
    client, memory = _make_client(tmp_path, monkeypatch)

    from api.services import notes_sync as ns

    monkeypatch.setattr(ns, "_run_osascript", lambda: _dump(NOTE_1))

    resp = client.post("/sources/sync-notes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new"] == 1


def test_sync_notes_endpoint_empty_dump(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.post("/sources/sync-notes", json={"notesDump": ""})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"new": 0, "updated": 0, "skipped": 0, "total": 0}
