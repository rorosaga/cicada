"""ROR-15: an Apple Note the person pinned in Notes (owner 2026-11-05).

A pin is frontmatter metadata: it reaches the note's row and Stage 1's source note, and it never touches the content
hash, `processed` or `revised`, so a pin moving costs Sleep nothing. Every id here is invented.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from api.services import channel_items, entity_extractor, episode_staging, markdown_parser, notes_sync
from api.services.notes_sync import FIELD_SEP, RECORD_SEP


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def memory(tmp_path):
    bank = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (bank / sub).mkdir(parents=True)
    return bank


def _record(note_id, body="words", name="A note", modified="m1", folder="Notes", account="iCloud"):
    return FIELD_SEP.join([note_id, name, body, "c1", modified, folder, "2026-01-02T10:00:00", "3600", account])


def _dump(*records):
    return RECORD_SEP.join(records)


def _only(bank):
    files = sorted((bank / "episodes").glob("*.md"))
    assert len(files) == 1
    return files[0]


def _sync(bank, *records, **kw):
    return run(notes_sync.sync_notes(bank, dump=_dump(*records), **kw))


def test_a_pin_is_a_frontmatter_flag_on_the_notes_episode_and_its_index_entry(memory):
    _sync(memory, _record("n1"), _record("n2"), pinned_ids=["n1"])
    fms = {markdown_parser.parse(p).frontmatter["note_id"]: markdown_parser.parse(p).frontmatter
           for p in (memory / "episodes").glob("*.md")}
    assert fms["n1"]["pinned"] is True and "pinned" not in fms["n2"]
    index = json.loads((memory / "sources" / "notes_index.json").read_text())
    assert index["n1"]["pinned"] is True and "pinned" not in index["n2"]


def test_pinning_then_unpinning_changes_nothing_sleep_reads(memory):
    _sync(memory, _record("n1"), pinned_ids=[])
    path = _only(memory)
    # Sleep has read it.
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "processed": True, "processed_by": "sleep"}, parsed.body)
    before = markdown_parser.parse(path)

    pinned = _sync(memory, _record("n1"), pinned_ids=["n1"])
    assert (pinned["new"], pinned["updated"], pinned["skipped"]) == (0, 0, 1)
    during = markdown_parser.parse(path)
    assert during.frontmatter["pinned"] is True
    for key in ("processed", "processed_by", "content_hash"):
        assert during.frontmatter[key] == before.frontmatter[key]
    assert "revised" not in during.frontmatter and during.body == before.body

    _sync(memory, _record("n1"), pinned_ids=[])
    after = markdown_parser.parse(path)
    assert after.frontmatter == before.frontmatter and after.body == before.body
    assert len(list((memory / "episodes").glob("*.md"))) == 1


def test_a_post_that_could_not_read_pins_leaves_every_pin_as_it_was(memory):
    _sync(memory, _record("n1"), pinned_ids=["n1"])
    _sync(memory, _record("n1"))   # no list: the app had no Full Disk Access this time
    assert markdown_parser.parse(_only(memory)).frontmatter["pinned"] is True
    _sync(memory, _record("n1"), pinned_ids=[])   # an empty list is the whole truth
    assert "pinned" not in markdown_parser.parse(_only(memory)).frontmatter


def test_an_edited_pinned_note_keeps_its_pin_on_the_new_episode(memory):
    _sync(memory, _record("n1"), pinned_ids=["n1"])
    _sync(memory, _record("n1", body="more words", modified="m2"))
    newest = sorted((memory / "episodes").glob("*.md"))[-1]
    assert markdown_parser.parse(newest).frontmatter["pinned"] is True


def test_an_id_that_names_no_readable_note_is_ignored(memory):
    _sync(memory, _record("n1"), pinned_ids=["x-coredata://nothing/ICNote/p9", "n1"])
    assert len(list((memory / "episodes").glob("*.md"))) == 1


def test_a_locked_note_is_never_pinned(memory):
    _sync(memory, _record("locked", body=""), _record("n1"), locked_ids=["locked"], pinned_ids=["locked", "n1"])
    index = json.loads((memory / "sources" / "notes_index.json").read_text())
    assert "locked" not in index and index["n1"]["pinned"] is True
    assert "locked" not in "".join(p.read_text() for p in (memory / "episodes").glob("*.md"))


def test_the_row_carries_the_pin_and_pinned_rows_list_first(memory):
    _sync(memory, _record("n1", modified="m1"), _record("n2", modified="m2"), pinned_ids=["n1"])
    page = channel_items.items(memory, "notes", limit=10)
    rows = page["items"]
    assert rows[0].get("pinned") is True and "pinned" not in rows[1]
    assert channel_items.SHAPE == "g161-21"


def test_the_pin_is_one_line_in_stage_ones_source_note():
    assert entity_extractor.pinned_note({"origin": "apple-notes", "pinned": True}) == entity_extractor.PINNED_NOTE
    assert "pinned" in entity_extractor.PINNED_NOTE and entity_extractor.PINNED_NOTE.startswith("[Source:")
    for other in ({"origin": "apple-notes"}, {"origin": "apple-notes", "pinned": False},
                  {"origin": "mcp", "pinned": True}, {"origin": "apple-notes", "pinned": "yes"}):
        assert entity_extractor.pinned_note(other) is None


def test_set_pinned_reports_whether_the_file_changed(memory):
    _sync(memory, _record("n1"))
    path = _only(memory)
    assert episode_staging.set_pinned(path, False) is False
    assert episode_staging.set_pinned(path, True) is True
    assert episode_staging.set_pinned(path, True) is False


def test_the_endpoint_takes_pinned_note_ids(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    bank = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (bank / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    resp = TestClient(main.app).post("/sources/sync-notes",
                                     json={"notesDump": _dump(_record("n1")), "pinnedNoteIds": ["n1"]})
    assert resp.status_code == 200, resp.text
    assert markdown_parser.parse(_only(bank)).frontmatter["pinned"] is True
