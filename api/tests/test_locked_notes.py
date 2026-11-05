"""G234: a locked Apple Note is never stored, whatever a post carries, and nothing per note stays in the bank.

Every note here is synthetic. The app's half (never requesting the body) is `AppleNotesReaderTests`.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from api.services import (
    channel_items,
    claims,
    evidence,
    history_index,
    inbox_context,
    markdown_parser,
    mcp_tools,
    notes_sync,
    provenance,
    search_index,
    search_service,
    sleep_cycle,
    sync_state,
)
from api.services.notes_sync import FIELD_SEP, RECORD_SEP

SECRET = "canary-secret-7f3a"
TITLE = "canary-title-locked"
FOLDER = "canary-folder-private"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def memory(tmp_path):
    bank = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (bank / sub).mkdir(parents=True)
    return bank


def _record(note_id, body, name="A note", modified="m1", folder="Notes", account="iCloud"):
    return FIELD_SEP.join([note_id, name, body, "c1", modified, folder, "2026-01-02T10:00:00", "3600", account])


def _dump(*records):
    return RECORD_SEP.join(records)


def _everything(bank):
    """Every byte in the bank but its git store."""
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in bank.rglob("*")
                     if p.is_file() and ".git" not in p.parts)


def _episodes(bank):
    return sorted((bank / "episodes").glob("*.md"))


def _stub(bank):
    """What an older app left: a locked note's title and folder around no text."""
    run(notes_sync.sync_notes(bank, dump=_dump(_record("kept", "kept text"))))
    fm = {"id": "ep_2026-01-02_900", "timestamp": "2026-01-02T09:00:00+00:00", "source": "apple-notes",
          "origin": "apple-notes", "title": TITLE, "processed": False, "content_hash": "abc", "note_id": "n-locked",
          "folder": FOLDER, "tags": [FOLDER]}
    path = bank / "episodes" / "ep_2026-01-02_900.md"
    markdown_parser.write(path, fm, f"# {TITLE}\n\n**Folder:** {FOLDER}\n**Modified:** m1\n\n")
    index = json.loads((bank / "sources" / "notes_index.json").read_text())
    index["n-locked"] = {"episode_id": fm["id"], "modified": "m1", "note_id": "n-locked", "account": "iCloud",
                         "folder": FOLDER}
    (bank / "sources" / "notes_index.json").write_text(json.dumps(index))
    return path


def test_a_body_flagged_locked_is_dropped_and_only_a_count_remains(memory):
    result = run(notes_sync.sync_notes(memory, dump=_dump(_record("n-locked", SECRET, name=TITLE, folder=FOLDER),
                                                          _record("open", "open text")),
                                       locked_ids=["n-locked"], accounts={"n-locked": "iCloud"}))
    assert (result["new"], result["total"], result["locked"]) == (1, 1, 1)
    held = _everything(memory)
    assert SECRET not in held and TITLE not in held and FOLDER not in held and "n-locked" not in held


def test_the_posted_ids_are_never_stored(memory, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    resp = TestClient(main.app).post("/sources/sync-notes", json={"notesDump": _dump(_record("open", "open text")),
                                                                  "lockedNoteIds": ["n-locked", "n-locked-2"]})
    assert resp.status_code == 200 and resp.json()["locked"] == 2
    assert "n-locked" not in _everything(memory)
    assert sync_state.read_sync_state(memory)["notes"]["locked"] == 2
    assert notes_sync.locked_count(memory) == 2
    tree = TestClient(main.app).get("/sources/channels/notes/collections")
    assert tree.status_code == 200 and tree.json()["locked"] == 2
    # The count moves the page's validator, so the one line is never stale.
    etag = tree.headers["etag"]
    TestClient(main.app).post("/sources/sync-notes", json={"notesDump": "", "lockedNoteIds": ["n-locked"]})
    again = TestClient(main.app).get("/sources/channels/notes/collections", headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.json()["locked"] == 1


def test_an_older_apps_blank_record_is_taken_as_locked_and_never_staged(memory):
    result = run(notes_sync.sync_notes(memory, dump=_record("n-locked", "", name=TITLE, folder=FOLDER)))
    assert (result["new"], result["locked"]) == (0, 1)
    assert not _episodes(memory)
    assert TITLE not in _everything(memory)


def test_an_older_app_sends_no_ids_so_text_it_read_cannot_be_told_apart(memory):
    """Stated, not wished away: a locked note open at read time looks like any other note to the backend."""
    result = run(notes_sync.sync_notes(memory, dump=_record("n-open", "looks ordinary")))
    assert result["new"] == 1


def test_a_new_apps_blank_record_is_dropped_without_counting_as_locked(memory):
    result = run(notes_sync.sync_notes(memory, dump=_record("n-empty", ""), locked_ids=[]))
    assert (result["new"], result["locked"]) == (0, 0)
    assert not _episodes(memory)


def test_a_sync_retires_a_stub_leaving_no_title_or_folder(memory):
    path = _stub(memory)
    result = run(notes_sync.sync_notes(memory, dump=_record("kept", "kept text"), locked_ids=["n-locked"]))
    assert result["locked"] == 1 and result["retired"] == 1
    assert path.exists()   # never unlinked
    parsed = markdown_parser.parse(path)
    assert parsed.frontmatter[evidence.LOCKED_NOTE_KEY] is True
    assert parsed.frontmatter["source_deleted_at"]
    assert parsed.frontmatter["processed"] is True and parsed.frontmatter["processed_by"] == history_index.INDEXED_BY
    assert parsed.frontmatter["title"] == notes_sync.LOCKED_TITLE
    assert parsed.body.strip() == ""
    held = _everything(memory)
    assert TITLE not in held and FOLDER not in held and "n-locked" not in held


def test_a_note_locked_after_it_was_read_leaves_episodes_and_its_text_waits_for_the_persons_call(memory):
    run(notes_sync.sync_notes(memory, dump=_record("n-later", SECRET, name=TITLE, folder=FOLDER)))
    path = _episodes(memory)[0]
    result = run(notes_sync.sync_notes(memory, dump="", locked_ids=["n-later"]))
    assert result["retired"] == 1
    parsed = markdown_parser.parse(path)
    assert parsed.body.strip() == ""
    assert parsed.frontmatter["title"] == notes_sync.LOCKED_TITLE
    assert parsed.frontmatter[evidence.LOCKED_NOTE_KEY] is True
    assert parsed.frontmatter["processed"] is True
    kept = notes_sync.kept_path(memory, path.stem)
    assert SECRET in kept.read_text(encoding="utf-8")   # destruction is the person's call
    assert kept.suffix not in (".md", ".json", ".jsonl", ".yaml", ".yml")   # nothing that walks a bank's text reaches it
    assert evidence.source_document(memory, parsed.frontmatter["id"]) is None
    assert evidence.source_text(memory, parsed.frontmatter["id"]) is None
    assert "n-later" not in (memory / "sources" / "notes_index.json").read_text()


def test_every_episode_of_a_locked_note_is_retired_not_only_the_latest(memory):
    run(notes_sync.sync_notes(memory, dump=_record("n-later", "first", modified="m1")))
    run(notes_sync.sync_notes(memory, dump=_record("n-later", "second", modified="m2")))
    assert len(_episodes(memory)) == 2
    assert run(notes_sync.sync_notes(memory, dump="", locked_ids=["n-later"]))["retired"] == 2


def test_a_note_unlocked_later_is_simply_new(memory):
    run(notes_sync.sync_notes(memory, dump=_record("n-later", "before", modified="m1")))
    run(notes_sync.sync_notes(memory, dump="", locked_ids=["n-later"]))
    result = run(notes_sync.sync_notes(memory, dump=_record("n-later", "after", modified="m1"), locked_ids=[]))
    assert result["new"] == 1
    fresh = [p for p in _episodes(memory) if not markdown_parser.parse(p).frontmatter.get(evidence.LOCKED_NOTE_KEY)]
    assert len(fresh) == 1 and "after" in markdown_parser.parse(fresh[0]).body


def test_sleep_guard_retires_a_stub_before_a_run_freezes_it_with_no_sync_first(memory):
    path = _stub(memory)
    fm = markdown_parser.parse(path).frontmatter
    assert history_index.waits_for_model(fm)
    assert fm["id"] in [e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory, with_body=False)]
    run(sleep_cycle._index_without_model_safely(memory))
    assert fm["id"] not in [e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory, with_body=False)]
    held = _everything(memory)
    assert TITLE not in held and FOLDER not in held
    assert not history_index.waits_for_model(markdown_parser.parse(path).frontmatter)


def test_sleep_guard_commits_alone_naming_only_paths(memory):
    subprocess.run(["git", "init", "-q"], cwd=memory, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "0"],
                   cwd=memory, check=True)
    _stub(memory)
    (memory / "untouched.txt").write_text("someone else's")
    run(notes_sync.retire_stubs_safely(memory))
    log = subprocess.run(["git", "log", "-1", "--format=%B"], cwd=memory, capture_output=True, text=True).stdout
    assert "Locked notes retired" in log
    assert TITLE not in log and FOLDER not in log
    assert "Cicada-Author: cicada" in log
    status = subprocess.run(["git", "status", "--short", "--", "untouched.txt"], cwd=memory, capture_output=True,
                            text=True).stdout
    assert status.startswith("??")


def test_sleep_guard_leaves_a_note_with_text_and_other_sources_alone(memory):
    run(notes_sync.sync_notes(memory, dump=_record("n-open", "real words")))
    other = memory / "episodes" / "ep_2026-01-02_901.md"
    markdown_parser.write(other, {"id": "ep_2026-01-02_901", "origin": "imessage", "source": "imessage",
                                  "processed": False, "timestamp": "2026-01-02T09:00:00+00:00"}, "")
    assert notes_sync.retire_locked(memory, set()).paths == []
    assert markdown_parser.parse(other).frontmatter.get(evidence.LOCKED_NOTE_KEY) is None


@pytest.mark.parametrize("body", ["", "\n\n", "# T\n\n**Folder:** F\n**Modified:** m\n\n", "# T\n\n"])
def test_is_stub_true(body):
    assert notes_sync.is_stub(body)


@pytest.mark.parametrize("body", ["# T\n\n**Folder:** F\n**Modified:** m\n\nT\nwords", "# T\n\nT", "words"])
def test_is_stub_false(body):
    assert not notes_sync.is_stub(body)


def test_a_retired_note_lists_nowhere_and_the_page_gets_the_count(memory):
    run(notes_sync.sync_notes(memory, dump=_dump(_record("open", "open text", folder="Kept"),
                                                 _record("n-later", SECRET, name=TITLE, folder=FOLDER))))
    run(notes_sync.sync_notes(memory, dump=_record("open", "open text", folder="Kept"), locked_ids=["n-later"]))
    sync_state.record_sync(memory, "notes", count=1, extra={"locked": 12})
    page = channel_items.items(memory, "notes")
    assert page["total"] == 1 and TITLE not in json.dumps(page)
    tree = channel_items.collections(memory, "notes")
    assert tree["locked"] == 12
    assert FOLDER not in json.dumps(tree)
    assert [c["count"] for a in tree["accounts"] for c in a["collections"]] == [1]
    assert all(row.frontmatter.get("title") != TITLE for row in sleep_cycle.episode_headers(memory))


def test_no_other_channel_says_anything_about_locks(memory):
    assert "locked" not in channel_items.collections(memory, "reminders-local")
    assert "locked" not in channel_items.collections(memory, "calendar-local")


def test_a_retired_note_is_never_indexed_for_words(memory):
    if not search_index.fts5_available():
        pytest.skip("no FTS5")
    run(notes_sync.sync_notes(memory, dump=_record("n-later", SECRET, name=TITLE)))
    run(notes_sync.sync_notes(memory, dump="", locked_ids=["n-later"]))
    search_index.rebuild(memory)
    db = search_index.db_path(memory)
    conn = search_index._open(db)
    try:
        rows = conn.execute("SELECT doc_key FROM docs WHERE doc_key LIKE 'episodes/%'").fetchall()
    finally:
        conn.close()
    assert rows == []


def test_a_retired_notes_words_leave_the_index_on_refresh_and_its_vectors_never_reach_a_search(memory):
    from api.services.vector_index import SqliteVecIndexer

    run(notes_sync.sync_notes(memory, dump=_record("n-later", SECRET, name=TITLE)))
    episode = markdown_parser.parse(_episodes(memory)[0]).frontmatter["id"]
    indexer = SqliteVecIndexer.__new__(SqliteVecIndexer)
    indexer.memory_path = memory
    hit = {"metadata": {"episode_id": episode}, "text": SECRET}
    assert indexer._without_locked_notes([hit]) == [hit]
    if search_index.fts5_available():
        search_index.rebuild(memory)
    run(notes_sync.sync_notes(memory, dump="", locked_ids=["n-later"]))
    assert indexer._without_locked_notes([hit]) == []
    if search_index.fts5_available():
        search_index.refresh(memory)
        conn = search_index._open(search_index.db_path(memory))
        try:
            assert conn.execute("SELECT doc_key FROM docs WHERE doc_key LIKE 'episodes/%'").fetchall() == []
        finally:
            conn.close()


def test_a_note_locked_after_it_was_read_is_found_though_locking_gave_it_a_new_id(memory):
    """Measured on real Notes: the id changes at the lock; the name does not."""
    run(notes_sync.sync_notes(memory, dump=_record("id-before", SECRET, name=TITLE)))
    path = _episodes(memory)[0]
    result = run(notes_sync.sync_notes(memory, dump="", locked_ids=["id-after"], locked_keys=[notes_sync.locked_key(TITLE)]))
    assert result["retired"] == 1
    assert markdown_parser.parse(path).frontmatter[evidence.LOCKED_NOTE_KEY] is True
    assert not history_index.waits_for_model(markdown_parser.parse(path).frontmatter)
    assert TITLE not in (memory / "sources" / "notes_index.json").read_text()


def test_a_note_edited_before_it_was_locked_is_found_too(memory):
    """The usual way a secret reaches a note: no date Cicada kept matches any more."""
    run(notes_sync.sync_notes(memory, dump=_record("id-before", "before", name=TITLE, modified="an older day")))
    result = run(notes_sync.sync_notes(memory, dump="", locked_ids=["id-after"], locked_keys=[notes_sync.locked_key(TITLE)]))
    assert result["retired"] == 1


def test_older_episodes_of_the_same_old_id_go_with_it(memory):
    run(notes_sync.sync_notes(memory, dump=_record("id-before", "first", name="Old title", modified="m1")))
    run(notes_sync.sync_notes(memory, dump=_record("id-before", SECRET, name=TITLE, modified="m2")))
    result = run(notes_sync.sync_notes(memory, dump="", locked_ids=["id-after"], locked_keys=[notes_sync.locked_key(TITLE)]))
    assert result["retired"] == 2


def test_a_note_this_read_saw_unlocked_stays_whatever_its_title(memory):
    run(notes_sync.sync_notes(memory, dump=_record("other", "kept words", name=TITLE)))
    path = _episodes(memory)[0]
    result = run(notes_sync.sync_notes(memory, dump=_record("other", "kept words", name=TITLE), locked_ids=["id-after"],
                                       locked_keys=[notes_sync.locked_key(TITLE)]))
    assert result["retired"] == 0 and result["skipped"] == 1
    assert markdown_parser.parse(path).frontmatter.get(evidence.LOCKED_NOTE_KEY) is None


def test_a_false_match_in_a_partial_read_comes_back_on_the_next_read(memory):
    """A folder that waited this read looks like a gone note: same title, retired, then simply new when it is seen."""
    run(notes_sync.sync_notes(memory, dump=_record("waiting", "its words", name=TITLE)))
    run(notes_sync.sync_notes(memory, dump="", locked_ids=["id-after"], locked_keys=[notes_sync.locked_key(TITLE)]))
    result = run(notes_sync.sync_notes(memory, dump=_record("waiting", "its words", name=TITLE), locked_ids=["id-after"],
                                       locked_keys=[notes_sync.locked_key(TITLE)]))
    assert result["new"] == 1 and result["retired"] == 0


def test_the_keys_are_never_stored(memory):
    key = notes_sync.locked_key(TITLE)
    run(notes_sync.sync_notes(memory, dump=_record("id-before", "words", name=TITLE), locked_ids=[], locked_keys=[key]))
    assert key not in _everything(memory)
    run(notes_sync.sync_notes(memory, dump="", locked_ids=["id-after"], locked_keys=[key]))
    assert key not in _everything(memory)


def test_the_key_is_the_apps_hash_byte_for_byte():
    """`AppleNotesReaderTests.testALockedKeyMatchesTheBackendsHash` pins the same digest."""
    digest = "1fc84b3abc2277e7d078a0b58f2dbf8e84f5d5d91e30059993db72f3e0999314"
    assert notes_sync.locked_key(" Cafe\u0301 note\n") == digest


def test_an_episode_an_earlier_version_only_stamped_is_finished_before_sleep_reads_anything(memory):
    run(notes_sync.sync_notes(memory, dump=_record("n-old", SECRET, name=TITLE, folder=FOLDER)))
    path = _episodes(memory)[0]
    parsed = markdown_parser.parse(path)
    stamped = {**parsed.frontmatter, evidence.LOCKED_NOTE_KEY: True, "source_deleted_at": "2026-11-04T00:00:00Z"}
    markdown_parser.write(path, stamped, parsed.body)
    run(notes_sync.retire_stubs_safely(memory))
    after = markdown_parser.parse(path)
    assert after.body.strip() == "" and after.frontmatter["title"] == notes_sync.LOCKED_TITLE
    assert after.frontmatter["source_deleted_at"] == "2026-11-04T00:00:00Z"
    assert SECRET in notes_sync.kept_path(memory, path.stem).read_text(encoding="utf-8")


def test_nothing_but_the_retirement_names_where_the_text_waits():
    """The class guard: every other module reads `episodes/` and finds an empty record, so a new reader cannot leak."""
    services = Path(__file__).resolve().parents[1]
    named = [p.name for folder in ("services", "routers") for p in (services / folder).rglob("*.py")
             if ("KEPT_DIRNAME" in p.read_text(encoding="utf-8") or "kept_path" in p.read_text(encoding="utf-8")
                 or "locked_notes/" in p.read_text(encoding="utf-8"))]
    assert named == ["notes_sync.py"]


# --- Every door, after a note the bank had already read was locked -------------------------------------------------


@pytest.fixture
def read_then_locked(memory):
    """A note read and cited by a claim and an inbox question, then locked under a new id."""
    run(notes_sync.sync_notes(memory, dump=_record("id-before", f"{SECRET} is what this says", name=TITLE, folder=FOLDER)))
    path = _episodes(memory)[0]
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "processed": True, "processed_by": "sleep"}, parsed.body)
    ep = path.stem
    span = evidence.verify(memory, ep, SECRET)
    assert span.is_span() and span.start == parsed.body.index(SECRET)
    claim = claims.Claim(id="c-one", text="a safe summary", subject="alpha-project", evidence=[span])
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"id": "alpha-project", "name": "Alpha project", "type": "project", "status": "active",
                                 "source_episodes": [ep]}, claims.write_claims("Alpha project.\n", [claim]))
    (memory / "inbox").mkdir(exist_ok=True)
    markdown_parser.write(memory / "inbox" / "q-one.md",
                          {"id": "q-one", "kind": "clarification", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha project", "source_episode": ep, "question": "Which one?"}, "Which one?\n")
    if search_index.fts5_available():
        search_index.rebuild(memory)
    run(notes_sync.sync_notes(memory, dump="", locked_ids=["id-after"], locked_keys=[notes_sync.locked_key(TITLE)]))
    return memory, ep, page


def _clean(value) -> None:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    for canary in (SECRET, TITLE, FOLDER):
        assert canary not in text


def test_the_words_exist_only_in_the_kept_file(read_then_locked):
    memory, ep, _page = read_then_locked
    holders = [p.relative_to(memory).as_posix() for p in memory.rglob("*")
               if p.is_file() and ".git" not in p.parts and not p.name.startswith("search_index")
               and (SECRET in (text := p.read_text(encoding="utf-8", errors="replace")) or TITLE in text)]
    assert holders == [f"sources/{notes_sync.KEPT_DIRNAME}/{ep}{notes_sync.KEPT_SUFFIX}"]


def test_the_reader_and_the_card_read_nothing(read_then_locked):
    memory, ep, page = read_then_locked
    assert provenance.episode_document(memory, ep) is None
    _clean(repr(provenance.entity_provenance(memory, page)))
    _clean(repr(provenance.episode_citations(memory, ep)))


def test_an_inbox_card_reads_nothing(read_then_locked):
    memory, ep, _page = read_then_locked
    ctx = inbox_context.InboxContext(memory, today=date(2026, 11, 5))
    indexed = ctx.episode(ep)
    assert ctx._body(indexed).strip() == ""
    _clean(str(ctx._excerpt(indexed, ep, None, TITLE, "alpha-project")))


@pytest.mark.skipif(not search_index.fts5_available(), reason="no FTS5")
def test_search_finds_nothing_at_once_with_no_wait_for_the_index(read_then_locked):
    memory, _ep, _page = read_then_locked
    conn = search_index._open(search_index.db_path(memory))
    try:
        assert conn.execute("SELECT doc_key FROM docs WHERE doc_key LIKE 'episodes/%'").fetchall() == []
    finally:
        conn.close()
    for query in (SECRET, TITLE):
        found = search_service.search(memory, query, kinds=("entity", "episode"), mode="lexical", vectors=False)
        _clean(repr(found))


def test_the_vectors_are_dropped_at_the_retirement_not_at_the_next_sleep(memory, monkeypatch):
    from api.services import vector_index

    asked = []
    monkeypatch.setattr(vector_index, "forget_passages", lambda bank, values, episodes: asked.append((values, episodes)))
    run(notes_sync.sync_notes(memory, dump=_record("id-before", SECRET, name=TITLE)))
    stem = _episodes(memory)[0].stem
    run(notes_sync.sync_notes(memory, dump="", locked_ids=["id-before"]))
    assert asked == [((), (stem,))]


def test_what_sleep_already_derived_stays_until_the_person_decides(read_then_locked):
    """The limit, pinned: a retirement touches no page. A claim's own text is the bank's words (`capture-and-sleep.md`)."""
    _memory, _ep, page = read_then_locked
    assert "a safe summary" in page.read_text(encoding="utf-8")


def test_the_retirement_commit_carries_the_kept_file_and_names_nothing(memory):
    subprocess.run(["git", "init", "-q"], cwd=memory, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "0"],
                   cwd=memory, check=True)
    run(notes_sync.sync_notes(memory, dump=_record("id-before", SECRET, name=TITLE)))
    run(notes_sync.sync_notes(memory, dump="", locked_ids=["id-after"], locked_keys=[notes_sync.locked_key(TITLE)]))
    stem = _episodes(memory)[0].stem
    log = subprocess.run(["git", "log", "-1", "--format=%B", "--name-only"], cwd=memory, capture_output=True, text=True).stdout
    assert f"sources/{notes_sync.KEPT_DIRNAME}/{stem}{notes_sync.KEPT_SUFFIX}" in log and f"episodes/{stem}.md" in log
    assert TITLE not in log and SECRET not in log
    assert subprocess.run(["git", "status", "--short"], cwd=memory, capture_output=True, text=True).stdout == ""


def test_mcp_sources_says_locked(read_then_locked):
    memory, ep, _page = read_then_locked
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_l", harness="claude-code")
    _clean(str(mcp_tools.sources(ctx, ep)))
    _clean(str(mcp_tools.recall_detail(ctx, "alpha-project")))
    assert "No entities found" in str(mcp_tools.recall(ctx, SECRET))   # the reply repeats only the query
