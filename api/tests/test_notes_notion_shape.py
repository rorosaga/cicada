"""A.4 (G245) — Apple Notes and Notion keep their shape: a Notes folder tree in Notes' own order, notes by the modified
instant, a one-line snippet; Notion pages filed by database or parent page and listed by last edited.

Synthetic banks under tmp_path, placeholder names only; nothing real is read.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_items, markdown_parser, notes_sync, sleep_cycle, sync_state
from api.services.connections import secrets
from api.services.connectors import notion, notion_mcp, scope, tier2

FS, RS = notes_sync.FIELD_SEP, notes_sync.RECORD_SEP


def run(coro):
    return asyncio.run(coro)


def _record(note_id, name, body, folder, *, modified="Mon 1 Jan 2026 at 10:00", local="2026-01-01T10:00:00", account="iCloud"):
    return FS.join([note_id, name, body, "created", modified, folder, local, "0", account])


def _dump(*records):
    return RS.join(records)


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    (m / "sources").mkdir()
    bank_index.invalidate()
    return m


def _episode_of(memory, note_id):
    index = json.loads((memory / "sources" / notes_sync.NOTES_INDEX_FILENAME).read_text())
    return index[note_id]


def _fm(memory, episode_id):
    return markdown_parser.parse(memory / "episodes" / f"{episode_id}.md")


# --- Notes: the folder path -----------------------------------------------------------------------------------------


def test_a_path_is_kept_beside_the_leaf_and_two_same_named_folders_are_two_collections(memory):
    dump = _dump(_record("n1", "Alpha plan", "Alpha plan\nline two", "Ideas"),
                 _record("n2", "Beta plan", "Beta plan\nline two", "Ideas"))
    paths = {"n1": ["Work", "Ideas"], "n2": ["Ideas"]}
    run(notes_sync.sync_notes(memory, dump=dump, folder_paths=paths))
    nested, top = _episode_of(memory, "n1"), _episode_of(memory, "n2")
    assert nested[notes_sync.FOLDER_PATH_KEY] == ["Work", "Ideas"] and top[notes_sync.FOLDER_PATH_KEY] == ["Ideas"]
    assert nested["folder"] == top["folder"] == "Ideas", "the leaf stays what it was"
    fm = _fm(memory, nested["episode_id"])
    assert fm.frontmatter["folder_path"] == ["Work", "Ideas"]
    assert "**Folder:** Ideas" in fm.body and "Work" not in fm.body, "the body names the leaf only, so no hash moves"
    bank_index.invalidate()
    tree = channel_items.collections(memory, "notes")
    ids = [c["id"] for a in tree["accounts"] for c in a["collections"]]
    assert len(ids) == len(set(ids)) == 3          # Work, Work > Ideas, Ideas


def test_a_top_level_folder_keeps_the_id_it_always_had(memory):
    run(notes_sync.sync_notes(memory, dump=_dump(_record("n1", "Alpha plan", "Alpha plan\nx", "Ideas")),
                              folder_paths={"n1": ["Ideas"]}))
    bank_index.invalidate()
    assert channel_items.items(memory, "notes", collection=channel_items.note_collection_id("iCloud", "Ideas"))["total"] == 1


def test_an_unchanged_note_is_placed_not_restaged_and_never_requeued(memory):
    dump = _dump(_record("n1", "Alpha plan", "Alpha plan\nline two", "Ideas"))
    run(notes_sync.sync_notes(memory, dump=dump))                       # an older app: the leaf only
    before = _episode_of(memory, "n1")
    ep = memory / "episodes" / f"{before['episode_id']}.md"
    fm = markdown_parser.parse(ep)
    markdown_parser.write(ep, {**fm.frontmatter, "processed": True, "processed_by": "sleep"}, fm.body)   # Sleep read it
    body_before = markdown_parser.parse(ep).body
    result = run(notes_sync.sync_notes(memory, dump=dump, folder_paths={"n1": ["Work", "Ideas"]}))
    assert (result["new"], result["updated"], result["skipped"]) == (0, 0, 1)
    after = _episode_of(memory, "n1")
    assert after["episode_id"] == before["episode_id"] and after["folder_path"] == ["Work", "Ideas"]
    now = markdown_parser.parse(ep)
    assert now.frontmatter["folder_path"] == ["Work", "Ideas"]
    assert now.frontmatter["processed"] is True and "revised" not in now.frontmatter and now.body == body_before
    assert len(list((memory / "episodes").glob("*.md"))) == 1, "no second episode"


def test_a_path_that_does_not_end_in_the_dumps_folder_names_nothing(memory):
    run(notes_sync.sync_notes(memory, dump=_dump(_record("n1", "Alpha plan", "Alpha plan\nx", "Ideas")),
                              folder_paths={"n1": ["Work", "Something else"]}))
    assert notes_sync.FOLDER_PATH_KEY not in _episode_of(memory, "n1")


def test_a_locked_note_is_given_no_path_and_a_folder_below_an_excluded_one_is_left_out(memory, monkeypatch):
    dump = _dump(_record("n1", "Alpha plan", "Alpha plan\nx", "Ideas"), _record("n2", "Beta plan", "Beta plan\nx", "Ideas"))
    run(notes_sync.sync_notes(memory, dump=dump, locked_ids=["n2"], folder_paths={"n1": ["Work", "Ideas"],
                                                                                  "n2": ["Work", "Ideas"]}))
    index = json.loads((memory / "sources" / notes_sync.NOTES_INDEX_FILENAME).read_text())
    assert "n2" not in index and "n1" in index
    monkeypatch.setenv("CICADA_NOTES_EXCLUDE_FOLDERS", "Secrets")
    out = run(notes_sync.sync_notes(memory, dump=_dump(_record("n3", "Gamma plan", "Gamma plan\nx", "Deep")),
                                    folder_paths={"n3": ["Secrets", "Deep"]}))
    assert out["excluded"] == 1 and "n3" not in json.loads((memory / "sources" / notes_sync.NOTES_INDEX_FILENAME).read_text())
    kept = notes_sync.state_extra(0, True, [{"account": "iCloud", "path": ["Secrets", "Deep"]},
                                             {"account": "iCloud", "path": ["Work"]}])
    assert kept[notes_sync.FOLDERS_KEY] == [{"account": "iCloud", "path": ["Work"]}]


# --- Notes: the tree, the order, the snippet ------------------------------------------------------------------------


def _client(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(memory.parent / "home"))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def test_the_tree_follows_notes_own_order_even_when_a_child_is_listed_before_its_parent(memory, monkeypatch):
    client = _client(memory, monkeypatch)
    dump = _dump(_record("n1", "Alpha plan", "Alpha plan\nx", "Plans"), _record("n2", "Beta plan", "Beta plan\nx", "Zebra"))
    folders = [{"account": "iCloud", "path": ["Zebra"]},               # Notes' order, not the alphabet
               {"account": "iCloud", "path": ["Work", "Plans"]},        # a child listed BEFORE its parent
               {"account": "iCloud", "path": ["Work"]},
               {"account": "iCloud", "path": ["Empty"]}]
    resp = client.post("/sources/sync-notes", json={"notesDump": dump, "noteFolders": folders, "pinnedNoteIds": [],
                                                    "noteFolderPaths": {"n1": ["Work", "Plans"], "n2": ["Zebra"]}})
    assert resp.status_code == 200
    tree = client.get("/sources/channels/notes/collections").json()
    assert tree["pinsRead"] is True
    cols = tree["accounts"][0]["collections"]
    assert [c["path"] for c in cols] == [["Zebra"], ["Work"], ["Work", "Plans"], ["Empty"]]
    work, plans = cols[1], cols[2]
    assert work["parent"] is None and work["children"] == [plans["id"]] and plans["parent"] == work["id"]
    assert (plans["depth"], work["count"], work["total"], plans["count"]) == (1, 0, 1, 1)
    assert cols[3]["count"] == 0, "an empty folder is still a folder"
    assert tree["accounts"][0]["count"] == 2


def test_a_library_with_no_paths_yet_is_the_flat_list_by_name_and_says_pins_were_never_read(memory, monkeypatch):
    client = _client(memory, monkeypatch)
    client.post("/sources/sync-notes", json={"notesDump": _dump(_record("n1", "Alpha plan", "Alpha plan\nx", "Zed"),
                                                                _record("n2", "Beta plan", "Beta plan\nx", "Alpha"))})
    tree = client.get("/sources/channels/notes/collections").json()
    assert [c["name"] for c in tree["accounts"][0]["collections"]] == ["Alpha", "Zed"]
    assert tree["pinsRead"] is False and tree["locked"] == 0
    assert client.get("/sources/channels/notes/items").json()["pinsRead"] is False


def test_same_day_notes_order_by_the_modified_instant_and_pinned_come_first(memory):
    dump = _dump(_record("n1", "Alpha plan", "Alpha plan\nx", "Ideas", modified="m1", local="2026-01-01T09:00:00"),
                 _record("n2", "Beta plan", "Beta plan\nx", "Ideas", modified="m2", local="2026-01-01T17:30:00"),
                 _record("n3", "Gamma plan", "Gamma plan\nx", "Ideas", modified="m3", local="2026-01-01T12:00:00"))
    run(notes_sync.sync_notes(memory, dump=dump, pinned_ids=["n1"]))
    bank_index.invalidate()
    rows = channel_items.items(memory, "notes")["items"]
    assert [r["title"] for r in rows] == ["Alpha plan", "Beta plan", "Gamma plan"]    # pinned, then newest first
    assert rows[0]["pinned"] is True
    assert rows[1]["modifiedAt"] > rows[2]["modifiedAt"] and rows[1]["day"] == rows[2]["day"]


def test_a_snippet_is_the_first_line_after_the_title_and_one_line_notes_have_none(memory):
    dump = _dump(_record("n1", "Alpha plan", "Alpha plan\n\nFirst real line.\nSecond line stays home.", "Ideas"),
                 _record("n2", "Beta plan", "Beta plan", "Ideas"))
    run(notes_sync.sync_notes(memory, dump=dump))
    bank_index.invalidate()
    rows = {r["title"]: r for r in channel_items.items(memory, "notes")["items"]}
    assert rows["Alpha plan"]["snippet"] == "First real line."
    assert "snippet" not in rows["Beta plan"]
    assert "Second line" not in json.dumps(channel_items.items(memory, "notes"))


def test_a_note_locked_later_has_no_snippet_and_no_row(memory):
    dump = _dump(_record("n1", "Alpha plan", "Alpha plan\nthe secret line", "Ideas"))
    run(notes_sync.sync_notes(memory, dump=dump))
    run(notes_sync.sync_notes(memory, dump="", locked_ids=["n1"]))
    bank_index.invalidate()
    wire = json.dumps(channel_items.items(memory, "notes"))
    assert "secret line" not in wire and channel_items.items(memory, "notes")["total"] == 0


def test_the_shape_was_bumped():
    assert int(channel_items.SHAPE.rsplit("-", 1)[1]) >= 23


# --- Notion --------------------------------------------------------------------------------------------------------

PAGE_A, PAGE_B, ROOT, TEAM, DB = "a" * 32, "b" * 32, "c" * 32, "d" * 32, "e" * 32


def _ancestors(*pairs):
    """``pairs`` outermost first, printed nearest first the way the server does."""
    tags = []
    for depth, (rid, title) in enumerate(reversed(pairs), start=1):
        name = "parent-page" if depth == 1 else f"ancestor-{depth}-page"
        tags.append(f'<{name} url="https://www.notion.so/{rid}" title="{title}"/>')
    return "<ancestor-path>" + "".join(tags) + "</ancestor-path>"


def test_ancestors_are_read_from_the_pages_own_reply_outermost_first():
    raw = "<page>" + _ancestors((TEAM, "Team home"), (ROOT, "Projects &amp; plans")) + "<content>x</content></page>"
    assert notion_mcp.ancestors(raw) == [(TEAM, "Team home"), (ROOT, "Projects & plans")]
    assert notion_mcp.ancestors("<content>x</content>") == []


def _run(chosen):
    sel = {"mode": scope.CHOSEN, "items": [{"id": ROOT, "title": "Projects", "kind": "page"}]} if chosen \
        else {"mode": scope.EVERYTHING, "items": []}
    r = notion_mcp._Run({}, sel)
    r.tree = {ROOT: [PAGE_A]}
    return r


def test_a_chosen_scope_never_keeps_a_parent_above_what_the_person_chose():
    raw = _ancestors((TEAM, "Team home"), (ROOT, "Projects"))
    assert notion_mcp._chain(_run(True), PAGE_A, raw) == [(ROOT, "Projects")]
    assert notion_mcp._chain(_run(False), PAGE_A, raw) == [(TEAM, "Team home"), (ROOT, "Projects")]


def test_a_row_is_filed_under_its_database_once():
    run_ = _run(False)
    run_.titles[PAGE_A], run_.dbs[PAGE_A] = "Reading list", DB
    assert notion_mcp._chain(run_, PAGE_A, _ancestors((ROOT, "Projects"))) == [(ROOT, "Projects"), (DB, "Reading list")]
    assert notion_mcp._chain(run_, PAGE_A, _ancestors((ROOT, "Projects"), (DB, "Reading list")))[-1] == (DB, "Reading list")


class _Mcp:
    def __init__(self):
        self.messages = []

    async def __call__(self, method, url, *, headers, params=None, json=None):
        self.messages.append(json)
        if json["method"] == "initialize":
            return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"], "result": {}}, {"mcp-session-id": "s"})
        if json["method"] == "notifications/initialized":
            return tier2.Response(202, None)
        name, args = json["params"]["name"], json["params"]["arguments"]
        if name == "notion-fetch":
            page = args["id"]
            title = {ROOT: "Projects", PAGE_A: "Alpha", PAGE_B: "Beta"}[page]
            edited = {ROOT: "2026-10-01T10:00:00Z", PAGE_A: "2025-01-01T10:00:00Z", PAGE_B: "2026-10-02T10:00:00Z"}[page]
            link = f'<page url="https://www.notion.so/{PAGE_A}">Alpha</page>' if page == ROOT else ""
            anc = _ancestors((TEAM, "Team home"), (ROOT, "Projects")) if page == PAGE_A else \
                (_ancestors((TEAM, "Team home")) if page == ROOT else "")
            result = {"title": title, "page_last_edited_at": edited,
                      "text": f"{anc}<content>\nBody of {title}. {link}\n</content>"}
        else:
            result = {"results": []}
        return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"], "result": {
            "content": [{"type": "text", "text": json_dumps(result)}]}})


def json_dumps(value):
    return json.dumps(value)


@pytest.fixture
def notion_bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    for name in notion_mcp.SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    secrets.set_secret(notion_mcp.TOKEN_ENV, "access-1")
    secrets.set_secret(notion_mcp.REFRESH_ENV, "refresh-1")
    secrets.set_secret(notion_mcp.CLIENT_ENV, "client-placeholder")
    secrets.set_secret(notion_mcp.EXPIRES_ENV, str(int(time.time()) + 3600))
    secrets.set_secret(notion_mcp.HOW_ENV, notion_mcp.HOW_APP)
    bank_index.invalidate()
    yield memory
    for name in notion_mcp.SECRET_NAMES:
        import os
        os.environ.pop(name, None)


def test_a_chosen_notion_page_keeps_its_parents_and_is_listed_by_last_edited(notion_bank):
    scope.write("notion-api", "chosen", [{"id": ROOT, "title": "Projects", "kind": "page"},
                                         {"id": PAGE_B, "title": "Beta", "kind": "page"}])
    result = asyncio.run(notion.sync(notion_bank, http_fn=_Mcp()))
    assert result["status"] == "ok"
    stored = {}
    for path in (notion_bank / "episodes").glob("*.md"):
        p = markdown_parser.parse(path)
        stored[str(p.frontmatter["source_id"])] = p
    alpha = stored[f"notion:{PAGE_A}"]
    assert alpha.frontmatter["notion_path"] == ["Projects"], "the team page above the chosen root is never kept"
    assert alpha.frontmatter["notion_path_ids"] == [ROOT]
    assert notion.SOURCE_PREFIX + PAGE_B in stored and "notion_path" not in stored[notion.SOURCE_PREFIX + PAGE_B].frontmatter
    bank_index.invalidate()
    page = channel_items.items(notion_bank, "notion-api")
    # Alpha was created long ago and edited in 2025; Beta and the root were edited in 2026: last edited decides.
    assert [r["title"] for r in page["items"]][-1] == "Alpha"
    tree = channel_items.collections(notion_bank, "notion-api")
    acct = tree["accounts"][0]
    (folder,) = acct["collections"]
    assert folder["name"] == "Projects" and folder["count"] == 1 and folder["path"] == ["Projects"]
    assert acct["unfiled"] == 2
    assert channel_items.items(notion_bank, "notion-api", collection=folder["id"])["total"] == 1


def test_a_page_already_in_the_bank_learns_its_parents_with_no_word_moved(notion_bank, monkeypatch):
    scope.write("notion-api", "chosen", [{"id": ROOT, "title": "Projects", "kind": "page"}])
    real_chain = notion_mcp._chain
    monkeypatch.setattr(notion_mcp, "_chain", lambda *a, **k: [])
    asyncio.run(notion.sync(notion_bank, http_fn=_Mcp()))

    def stored():
        out = {}
        for path in (notion_bank / "episodes").glob("*.md"):
            p = markdown_parser.parse(path)
            out[str(p.frontmatter["source_id"])] = p.frontmatter
        return out

    before = stored()[f"notion:{PAGE_A}"]
    assert "notion_path" not in before
    monkeypatch.setattr(notion_mcp, "_chain", real_chain)
    tier2.forget_cursor("notion-api", notion_bank)
    asyncio.run(notion.sync(notion_bank, http_fn=_Mcp()))
    after = stored()[f"notion:{PAGE_A}"]
    assert after["notion_path"] == ["Projects"] and after["notion_path_ids"] == [ROOT]
    assert after["processed"] == before["processed"] and after["content_hash"] == before["content_hash"]


def test_the_cursor_of_an_older_format_reads_every_page_once_more():
    assert notion_mcp.FORMAT >= 3
    assert notion_mcp._Run({"fmt": 2, "known": {PAGE_A: "x"}}, {"mode": scope.EVERYTHING, "items": []}).known == {}
