"""Hermetic tests for the keyless Apple Notes one-way import connector.

Covers:
- ``parse_notes_dump`` — the delimited dump format the app's AppleScript emits (multiple
  records, malformed records skipped, empty input);
- ``sync_notes`` — new note -> episode, unchanged note -> skipped, modified
  note (changed ``modified`` timestamp) -> re-emitted as an updated episode,
  dedup index persistence across calls;
- note-id fallback (hash of name+creation-date) when a record has no id;
- plaintext truncation for an oversized note body;
- the backend never running ``osascript`` itself (the ``~/Library`` rail);
- the ``POST /sources/sync-notes`` endpoint via ``TestClient`` with an inline
  ``notesDump`` payload, and a 422 without one.

Every test passes an in-memory dump string; nothing here reads Notes.app.
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

    assert result == {"new": 2, "updated": 0, "skipped": 0, "total": 2, "excluded": 0, "locked": 0, "retired": 0}

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
    assert result == {"new": 0, "updated": 0, "skipped": 2, "total": 2, "excluded": 0, "locked": 0, "retired": 0}

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 2  # no new episodes written


def test_sync_notes_modified_note_reemits_updated_episode(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1, NOTE_2)))
    before = {p.name for p in (memory / "episodes").glob("ep_*.md")}

    result = run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1, NOTE_2_EDITED)))
    assert result == {"new": 0, "updated": 1, "skipped": 1, "total": 2, "excluded": 0, "locked": 0, "retired": 0}

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert {p.name for p in episodes} == before   # the edit is the same episode in place (G104), never a third

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
    assert result2 == {"new": 0, "updated": 0, "skipped": 1, "total": 1, "excluded": 0, "locked": 0, "retired": 0}


def test_sync_notes_empty_dump(tmp_path):
    memory = _memory(tmp_path)
    result = run(notes_sync.sync_notes(memory, dump=""))
    assert result == {"new": 0, "updated": 0, "skipped": 0, "total": 0, "excluded": 0, "locked": 0, "retired": 0}
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


# --- The backend never reads Notes itself --------------------------------------


def test_the_backend_never_runs_osascript():
    """Run from the launchd backend, macOS asked whether "python3.12" may
    control Notes. The app reads Notes; this module only parses the dump."""
    import inspect

    source = inspect.getsource(notes_sync)
    assert "subprocess" not in source
    assert "tell application" not in source
    assert not hasattr(notes_sync, "sync_from_local_notes")


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


def test_sync_notes_endpoint_without_a_dump_is_refused_unread(tmp_path, monkeypatch):
    """No dump -> 422: the backend has no local read to fall back to."""
    client, memory = _make_client(tmp_path, monkeypatch)

    assert client.post("/sources/sync-notes").status_code == 422
    assert client.post("/sources/sync-notes", json={}).status_code == 422
    assert not (memory / "episodes").exists() or not any((memory / "episodes").iterdir())


def test_sync_notes_endpoint_empty_dump(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.post("/sources/sync-notes", json={"notesDump": ""})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"new": 0, "updated": 0, "skipped": 0, "total": 0, "excluded": 0, "locked": 0, "retired": 0}


# --- Folder exclusion (CICADA_NOTES_EXCLUDE_FOLDERS) -------------------------


def _dump_record(note_id, name, body, folder):
    from api.services.notes_sync import FIELD_SEP
    return FIELD_SEP.join([note_id, name, body, "Monday, 1 January 2026 at 10:00:00", "Monday, 1 January 2026 at 10:00:00", folder])


def test_excluded_folder_notes_never_ingested(tmp_path, monkeypatch):
    import asyncio
    from api.services import notes_sync
    from api.services.notes_sync import RECORD_SEP

    monkeypatch.setenv("CICADA_NOTES_EXCLUDE_FOLDERS", "Contraseñas, Secrets")
    dump = RECORD_SEP.join([
        _dump_record("n1", "wifi password", "hunter2", "Contraseñas"),
        _dump_record("n2", "grocery list", "eggs", "Notes"),
    ])
    result = asyncio.run(notes_sync.sync_notes(tmp_path, dump=dump))

    assert result["new"] == 1
    assert result["excluded"] == 1
    bodies = " ".join(p.read_text() for p in (tmp_path / "episodes").glob("*.md"))
    assert "hunter2" not in bodies
    assert "grocery list" in bodies
    # excluded note never entered the dedup index: lifting the exclusion later ingests it fresh
    monkeypatch.setenv("CICADA_NOTES_EXCLUDE_FOLDERS", "")
    result2 = asyncio.run(notes_sync.sync_notes(tmp_path, dump=dump))
    assert result2["new"] == 1 and result2["excluded"] == 0


def test_exclusion_defaults_off(tmp_path, monkeypatch):
    import asyncio
    from api.services import notes_sync
    from api.services.notes_sync import RECORD_SEP

    monkeypatch.delenv("CICADA_NOTES_EXCLUDE_FOLDERS", raising=False)
    dump = RECORD_SEP.join([_dump_record("n1", "a", "b", "Anything")])
    result = asyncio.run(notes_sync.sync_notes(tmp_path, dump=dump))
    assert result["new"] == 1 and result["excluded"] == 0


# --- read on time (2026-10-23) -------------------------------------------------------------------------------------


def _dated(note_id, name, modified_human, modified_iso, offset):
    return FIELD_SEP.join([note_id, name, "body text", "Monday, March 2, 2026 at 10:00:00 AM", modified_human,
                           "Notes", modified_iso, offset])


def test_a_note_is_dated_when_it_was_last_modified_not_the_day_it_was_synced(tmp_path):
    """Read on time (owner 2026-10-16): the app now sends the modification date as Notes' locale-free ISO local time
    plus the Mac's UTC offset; a first sync of an old library was a library of mentions today."""
    from api.services import markdown_parser

    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=_dated(
        "n1", "Old idea", "Tuesday, March 3, 2026 at 11:30:00 AM", "2026-03-03T11:30:00", "3600")))
    (path,) = (memory / "episodes").glob("ep_*.md")
    fm = markdown_parser.parse(path).frontmatter
    assert fm["timestamp"] == "2026-03-03T10:30:00+00:00"
    assert path.name.startswith("ep_2026-03-03_")


def test_an_older_apps_six_field_record_still_parses_and_is_dated_now(tmp_path):
    from datetime import datetime, timezone

    from api.services import markdown_parser

    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=_record("n1", "Plain", "x", "2026-03-02", "2026-03-03", "Notes")))
    (path,) = (memory / "episodes").glob("ep_*.md")
    stamp = datetime.fromisoformat(markdown_parser.parse(path).frontmatter["timestamp"])
    assert abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


def test_the_human_modified_string_stays_the_dedup_key(tmp_path):
    """An older sync kept `modified` as Notes' own words; the dated record keeps that key, so upgrading never
    re-emits every note as edited."""
    memory = _memory(tmp_path)
    human = "Tuesday, March 3, 2026 at 11:30:00 AM"
    run(notes_sync.sync_notes(memory, dump=_record("n1", "Same", "body text", "c", human, "Notes")))
    out = run(notes_sync.sync_notes(memory, dump=_dated("n1", "Same", human, "2026-03-03T11:30:00", "3600")))
    assert (out["new"], out["updated"], out["skipped"]) == (0, 0, 1)


def test_an_unreadable_or_future_date_falls_back_to_now():
    assert notes_sync._aware("not a date", "3600") == ""
    assert notes_sync._aware("2026-03-03T11:30:00", "x") == ""
    assert notes_sync._aware("2999-01-01T00:00:00", "0") == ""
    assert notes_sync._aware("2026-03-03T11:30:00", "-18000") == "2026-03-03T16:30:00+00:00"


# --- An edited note is a revision of its one episode (G104, 2026-11-23) --------------------------------------------


def _episodes(memory):
    from api.services import markdown_parser

    return {p.name: markdown_parser.parse(p) for p in sorted((memory / "episodes").glob("ep_*.md"))}


def _sleep_read(path):
    """Sleep consolidated it: `processed: true` by sleep, the file as Sleep leaves it."""
    from api.services import markdown_parser

    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "processed": True, "processed_by": "sleep"}, parsed.body)


def _again(record: str, old: str, new: str) -> str:
    return record.replace(old, new)


def test_an_edit_is_one_episode_revised_in_place_and_requeued(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=NOTE_2))
    ((name, first),) = _episodes(memory).items()
    _sleep_read(memory / "episodes" / name)
    first = _episodes(memory)[name]

    run(notes_sync.sync_notes(memory, dump=NOTE_2_EDITED))
    ((name2, edited),) = _episodes(memory).items()
    assert name2 == name and edited.frontmatter["id"] == first.frontmatter["id"]
    fm = edited.frontmatter
    assert fm["processed"] is False and "processed_by" not in fm
    assert fm["revised"]["count"] == 1 and fm["revised"]["previous_hash"] == first.frontmatter["content_hash"]
    # Sleep read the first body, so the revision names it: only what changed is read again.
    assert fm["revised"]["consolidated_hash"] == first.frontmatter["content_hash"]
    assert fm["source_id"] == "apple-notes:note-2" and fm["note_id"] == "note-2" and fm["folder"] == "Work"
    assert fm["received_at"] == first.frontmatter["received_at"]   # stamped once, at creation
    assert "action items added" in edited.body

    again_edit = _again(_again(NOTE_2_EDITED, "2026-07-05", "2026-07-06"), "added", "added, owners named")
    run(notes_sync.sync_notes(memory, dump=again_edit))
    ((_, again),) = _episodes(memory).items()
    assert again.frontmatter["revised"]["count"] == 2 and again.frontmatter["id"] == first.frontmatter["id"]


def test_the_modification_date_is_never_in_the_body_so_a_revision_changes_only_the_edit(tmp_path):
    """`**Modified:**` changed on every edit: in the body it was a changed line of every revision."""
    from api.services import episode_revision

    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=NOTE_2))
    ((_, first),) = _episodes(memory).items()
    run(notes_sync.sync_notes(memory, dump=NOTE_2_EDITED))
    ((_, edited),) = _episodes(memory).items()
    assert "Modified" not in first.body and "Modified" not in edited.body
    assert edited.frontmatter["source_updated_at"] == "2026-07-05"
    changed, removed, _blocks = episode_revision.diff(first.body, edited.body)
    assert [edited.body[a:b].strip() for a, b in changed] == ["Discussed Q3 roadmap — action items added"]
    assert [first.body[a:b].strip() for a, b in removed] == ["Discussed Q3 roadmap"]


def test_an_unchanged_note_is_not_written_at_all(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1, NOTE_2)))
    files = [*(memory / "episodes").glob("ep_*.md"), memory / "sources" / notes_sync.NOTES_INDEX_FILENAME]
    stamps = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in files}
    run(notes_sync.sync_notes(memory, dump=_dump(NOTE_1, NOTE_2)))
    assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in files} == stamps


def test_a_note_notes_touched_with_the_same_words_is_not_requeued(tmp_path):
    """The date moved and no word did: the index takes the date, Sleep reads nothing again."""
    import json

    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=NOTE_2))
    ((name, first),) = _episodes(memory).items()
    _sleep_read(memory / "episodes" / name)
    touched = _record("note-2", "Meeting notes", "Discussed Q3 roadmap", "2026-07-02", "2026-07-09", "Work")
    result = run(notes_sync.sync_notes(memory, dump=touched))
    assert (result["updated"], result["skipped"]) == (0, 1)
    ((_, after),) = _episodes(memory).items()
    assert after.frontmatter["processed"] is True and "revised" not in after.frontmatter
    idx = json.loads((memory / "sources" / notes_sync.NOTES_INDEX_FILENAME).read_text())
    assert idx["note-2"]["modified"] == "2026-07-09" and idx["note-2"]["episode_id"] == first.frontmatter["id"]
    assert run(notes_sync.sync_notes(memory, dump=touched))["skipped"] == 1   # and it stays skipped


def test_the_notes_own_date_follows_its_edits_while_its_id_keeps_its_day(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=_dated("n1", "Idea", "d1", "2026-03-03T11:30:00", "0")))
    ((name, _first),) = _episodes(memory).items()
    assert name.startswith("ep_2026-03-03_")
    edited = FIELD_SEP.join(["n1", "Idea", "body text, more", "c", "d2", "Notes", "2026-03-05T09:00:00", "0"])
    run(notes_sync.sync_notes(memory, dump=edited))
    ((name2, after),) = _episodes(memory).items()
    assert name2 == name   # ruling 34: an id is never renamed
    assert after.frontmatter["timestamp"] == "2026-03-05T09:00:00+00:00"
    assert after.frontmatter["redated_from"] == "2026-03-03T11:30:00+00:00"


def _old_shape_bank(memory, *, processed=True):
    """A bank an earlier version synced: the episode has `note_id` and no `source_id`, its `content_hash` is a hash of
    the key and the date (never of the words), its body carries the `**Modified:**` line, and the index points at it."""
    import json

    from api.services import markdown_parser

    fm = {"id": "ep_2026-07-02_001", "timestamp": "2026-07-02T10:00:00+00:00", "source": "apple-notes",
          "origin": "apple-notes", "title": "Meeting notes", "processed": processed, "content_hash": "0ld5hash0000",
          "note_id": "note-2", "folder": "Work", "tags": ["Work"]}
    if processed:
        fm["processed_by"] = "sleep"
    path = memory / "episodes" / "ep_2026-07-02_001.md"
    markdown_parser.write(
        path, fm, "# Meeting notes\n\n**Folder:** Work\n**Modified:** 2026-07-02\n\nDiscussed Q3 roadmap")
    (memory / "sources" / notes_sync.NOTES_INDEX_FILENAME).write_text(json.dumps(
        {"note-2": {"episode_id": fm["id"], "modified": "2026-07-02", "note_id": "note-2", "account": None,
                    "folder": "Work"}}))
    return path


def test_upgrading_rewrites_no_unchanged_note(tmp_path):
    memory = _memory(tmp_path)
    path = _old_shape_bank(memory)
    index = memory / "sources" / notes_sync.NOTES_INDEX_FILENAME
    before = (path.stat().st_mtime_ns, path.read_bytes(), index.stat().st_mtime_ns, index.read_bytes())
    old = _record("note-2", "Meeting notes", "Discussed Q3 roadmap", "2026-07-02", "2026-07-02", "Work")
    result = run(notes_sync.sync_notes(memory, dump=old))
    assert (result["new"], result["updated"], result["skipped"]) == (0, 0, 1)
    assert (path.stat().st_mtime_ns, path.read_bytes(), index.stat().st_mtime_ns, index.read_bytes()) == before


def test_the_first_edit_after_upgrading_revises_the_latest_old_episode(tmp_path):
    from api.services import markdown_parser

    memory = _memory(tmp_path)
    path = _old_shape_bank(memory)
    result = run(notes_sync.sync_notes(memory, dump=NOTE_2_EDITED))
    assert (result["new"], result["updated"]) == (0, 1)
    assert [p.name for p in (memory / "episodes").glob("ep_*.md")] == [path.name]   # not one more
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    assert fm["id"] == "ep_2026-07-02_001" and fm["source_id"] == "apple-notes:note-2"
    assert fm["processed"] is False and fm["revised"]["count"] == 1
    assert fm["revised"]["consolidated_hash"] == "0ld5hash0000"   # git's copy of the version Sleep read is the prior
    assert "action items added" in parsed.body and "Modified" not in parsed.body
    # and the next edit finds it by its identity like any other
    run(notes_sync.sync_notes(memory, dump=_again(NOTE_2_EDITED, "2026-07-05", "2026-07-06")))
    assert len(list((memory / "episodes").glob("ep_*.md"))) == 1


def test_an_unread_old_episode_edited_is_simply_replaced_in_place(tmp_path):
    from api.services import markdown_parser

    memory = _memory(tmp_path)
    path = _old_shape_bank(memory, processed=False)
    run(notes_sync.sync_notes(memory, dump=NOTE_2_EDITED))
    fm = markdown_parser.parse(path).frontmatter
    assert fm["processed"] is False and "consolidated_hash" not in fm["revised"]


def test_an_edit_and_a_pin_moved_together_both_land(tmp_path):
    memory = _memory(tmp_path)
    run(notes_sync.sync_notes(memory, dump=NOTE_2, pinned_ids=["note-2"]))
    run(notes_sync.sync_notes(memory, dump=NOTE_2_EDITED, pinned_ids=["note-2"]))
    ((_, ep),) = _episodes(memory).items()
    assert ep.frontmatter["pinned"] is True   # kept through the edit
    run(notes_sync.sync_notes(memory, dump=_again(NOTE_2_EDITED, "2026-07-05", "2026-07-06"), pinned_ids=[]))
    ((_, ep),) = _episodes(memory).items()
    assert "pinned" not in ep.frontmatter


# --- End to end: Sleep reads only what the edit changed ---------------------------------------------------------


def test_sleep_rereads_only_what_an_edit_of_a_note_changed(tmp_path, monkeypatch):
    from api.services import entity_extractor, markdown_parser
    from api.tests.test_episode_revision_sleep import _claims, _git, _run
    from api.tests.test_sleep_cycle_hold import _bank

    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "status": "active", "confidence": 0.9},
                          "## Summary\nalpha-project is a synthetic project.\n")
    filler = "\n".join(f"Filler line {i} about nothing in particular." for i in range(25))
    v1 = f"{filler}\nalpha-project uses tokio for async work."
    v2 = f"The alpha-project design review meeting is on Thursday.\n{v1}"
    run(notes_sync.sync_notes(memory, dump=_record("n-alpha", "Alpha notes", v1, "c", "d1", "Work")))
    commit = ["-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    _git(memory, "init", "-q")
    _git(memory, *commit, "add", "-A")
    _git(memory, *commit, "commit", "-qm", "capture")
    first: list[str] = []
    _run(memory, monkeypatch, first)
    (name,) = [p.name for p in (memory / "episodes").glob("ep_*.md")]
    assert markdown_parser.parse(memory / "episodes" / name).frontmatter["processed"] is True
    _git(memory, *commit, "add", "-A")
    _git(memory, *commit, "commit", "-qm", "Sleep cycle")
    assert any("tokio" in p for p in first)

    run(notes_sync.sync_notes(memory, dump=_record("n-alpha", "Alpha notes", v2, "c", "d2", "Work")))
    assert [p.name for p in (memory / "episodes").glob("ep_*.md")] == [name]   # still one conversation
    second: list[str] = []
    _run(memory, monkeypatch, second)
    assert len(second) == 1 and entity_extractor.episode_revision.REVISION_NOTE in second[0]
    assert "design review meeting is on Thursday" in second[0] and "tokio" not in second[0]
    claims = {(c.predicate, c.object): c for c in _claims(memory)}
    assert ("value-of-design-review-day", "Thursday") in claims
    tokio = claims[("uses", "tokio")]
    assert len(tokio.evidence) == 1 and set(tokio.source_episodes) == {name.removesuffix(".md")}
