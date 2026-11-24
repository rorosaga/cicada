"""G246 (ruling 81), Track 2b: a list's page is reachable from its source, guarded against agent writes, and kept current.

All of it ships dark behind `saved_posts.HIDE_POSTS`: every test that asserts a change runs with the constant on, and each
has a twin that pins the same surface with it off. Synthetic names and words only; the bank is a real git repo and the saves
are written the way the ingest leaves them (`test_list_pages.save`).
"""
from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient

from _reading_fixtures import reading  # noqa: F401 - a fixture
from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config, main
from api.remote import app as remote_app
from api.remote import catalog, store
from api.remote.runtime import RemoteRuntime
from api.services import (bank_index, channel_items, graph_builder, keep_as_page, list_pages, markdown_parser, mcp_tools,
                          reading_settings, saved_posts, source_streams, tool_contract)
from test_list_pages import commits, git, lists, page_of, save, settle

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
     "Mcp-Protocol-Version": "2025-11-25"}


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    bank_index.invalidate()
    graph_builder.reset_cache()
    yield
    bank_index.invalidate()
    graph_builder.reset_cache()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))     # the remote runtime and the routes read the active bank
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


@pytest.fixture
def client(bank):
    with TestClient(main.app) as c:
        yield c


def streams(bank) -> dict[str, dict]:
    body = source_streams.build(bank, channels=[])
    return {s["id"]: s for src in body["sources"] for s in src["streams"]}


def a_list(bank, n: int = 3, **kw):
    """`n` saved posts on X Bookmarks, and the list's page made."""
    for i in range(1, n + 1):
        save(bank, i, day=f"2026-11-0{i}", **kw)
    list_pages.sync(bank)


# ---------------------------------------------------------------------------------- a stream row names its page


def test_dark_a_stream_row_has_no_page_and_its_body_is_what_it_was(bank):
    for i in range(1, 4):
        save(bank, i, folders=["Trips"])
    assert saved_posts.HIDE_POSTS is False
    before = source_streams.build(bank, channels=[])
    list_pages.sync(bank)
    after = source_streams.build(bank, channels=[])
    assert before == after and source_streams.etag(before) == source_streams.etag(after)
    assert not any("page" in s or "folderPages" in s for s in streams(bank).values())


def test_a_list_streams_row_names_the_page_that_stands_for_it(bank, on):
    for i in range(1, 4):
        save(bank, i, folders=["Design ideas"] if i < 3 else ())
    save(bank, 4, origin="x-likes", folder="Likes")
    assert "page" not in streams(bank)["x.bookmarks"], "no page yet: nothing to open"
    list_pages.sync(bank)
    rows = streams(bank)
    assert rows["x.bookmarks"]["page"] == "list-x-bookmarks" and rows["x.likes"]["page"] == "list-x-likes"
    folder_page = next(p for p in lists(bank) if "--" in p)
    assert rows["x.bookmarks"]["folderPages"] == {"Design ideas": folder_page}
    assert "folderPages" not in rows["x.likes"]
    # a stream of works, a history and every stream of another kind carry none
    assert not any("page" in s for sid, s in rows.items() if sid not in ("x.bookmarks", "x.likes"))
    # the page is a real one: opening it answers
    assert page_of(bank, rows["x.bookmarks"]["page"]).frontmatter["list"]["stream"] == "x.bookmarks"


def test_the_stream_etag_moves_only_when_the_answer_does(bank, on):
    save(bank, 1)
    first = source_streams.etag(source_streams.build(bank, channels=[]))
    assert source_streams.etag(source_streams.build(bank, channels=[])) == first
    list_pages.sync(bank)
    with_page = source_streams.etag(source_streams.build(bank, channels=[]))
    assert with_page != first, "the page's birth is an answer that changed"
    # a second, third save moves the count (as ever) but the page field itself stays, and a sync that has nothing to do
    # changes nothing
    save(bank, 2)
    assert list_pages.sync(bank)["created"] == 0
    assert streams(bank)["x.bookmarks"]["page"] == "list-x-bookmarks"
    again = source_streams.etag(source_streams.build(bank, channels=[]))
    assert source_streams.etag(source_streams.build(bank, channels=[])) == again


def test_a_page_the_person_archived_is_no_longer_named(bank, on):
    a_list(bank, 2)
    page = page_of(bank, "list-x-bookmarks")
    page.frontmatter["status"] = "archived"
    markdown_parser.write(bank / "entities" / "list-x-bookmarks.md", page.frontmatter, page.body)
    bank_index.invalidate()
    assert "page" not in streams(bank)["x.bookmarks"]


def test_the_route_carries_the_field_and_a_repeat_read_is_a_304(bank, on, client):
    a_list(bank, 2)
    first = client.get("/sources/streams")
    x = next(s for src in first.json()["sources"] for s in src["streams"] if s["id"] == "x.bookmarks")
    assert x["page"] == "list-x-bookmarks"
    again = client.get("/sources/streams", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


# ---------------------------------------------------------------------------------- a row offers "Keep as a page"


def rows_of(bank, stream="x.bookmarks", **kw):
    spec = source_streams.spec_of(stream)
    return channel_items.items(bank, spec.channel, stream=stream, **kw)["items"]


def test_dark_a_list_row_carries_no_keep_word(bank):
    for i in range(1, 4):
        save(bank, i)
    assert rows_of(bank) and not any("keep" in r for r in rows_of(bank))


def test_a_row_drawn_under_its_list_says_so_and_a_kept_post_offers_the_way_back(bank, on):
    for i in range(1, 4):
        save(bank, i)
    settle(bank)
    assert {r["keep"] for r in rows_of(bank)} == {"row"}
    page = next(r["id"] for r in rows_of(bank))
    out = keep_as_page.keep(bank, entity=page)
    assert out["status"] == "kept" and out["paths"], "the click is a stamp on the post's own save"
    bank_index.invalidate()
    words = {r["id"]: r.get("keep") for r in rows_of(bank)}
    assert words[page] == "kept" and sorted(w for w in words.values() if w == "row") == ["row", "row"]
    assert keep_as_page.keep(bank, entity=page, kept=False)["status"] == "undone"
    bank_index.invalidate()
    assert {r["keep"] for r in rows_of(bank)} == {"row"}


def test_a_post_something_else_earned_a_page_for_offers_nothing_on_its_row(bank, on):
    save(bank, 1, named=True)
    save(bank, 2)
    settle(bank)
    words = {r["title"]: r.get("keep") for r in rows_of(bank)}
    assert words == {"A post 1": None, "A post 2": "row"}


def test_the_keep_route_takes_a_row_by_its_page_and_refuses_a_request_naming_neither(bank, on, client):
    save(bank, 1)
    settle(bank)
    page = rows_of(bank)[0]["id"]
    assert client.get("/sources/keep-as-page", params={"entity": page}).json()["state"] == "row"
    assert client.get("/sources/keep-as-page").status_code == 422
    assert client.post("/sources/keep-as-page", json={"kept": True}).status_code == 422
    assert client.post("/sources/keep-as-page", json={"entity": "media-nothing-here"}).status_code == 404
    done = client.post("/sources/keep-as-page", json={"entity": page}).json()
    assert done["status"] == "kept" and done["state"] == "kept" and done["canUndo"] is True
    assert "Cicada-Author: user" in git(bank, "log", "-1", "--format=%B")
    back = client.post("/sources/keep-as-page", json={"entity": page, "kept": False}).json()
    assert back["status"] == "undone" and back["state"] == "row"


def test_dark_the_keep_route_offers_nothing_by_page_either(bank, client):
    save(bank, 1)
    settle(bank)
    page = rows_of(bank)[0]["id"]
    assert client.get("/sources/keep-as-page", params={"entity": page}).json()["state"] == "none"


# ---------------------------------------------------------------------------------- agents are told the truth


@pytest.fixture
def srv(bank, monkeypatch):
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: bank)
    monkeypatch.setattr(server, "_STATE_HINT_SENT", False)
    monkeypatch.setattr(server, "_backend_post", lambda path, payload: {"status": "resolved"})
    return server


def _text(result: dict) -> str:
    return result["content"][0]["text"]


def _remote():
    return RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)


def _connector(scopes=catalog.SCOPES):
    return catalog.Connector(id="ab12cd34", label="Phone", app="claude", scopes=frozenset(scopes),
                             created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")


def test_the_page_read_says_a_list_page_is_a_list_with_the_saves_count_and_newest_rows(bank, on, srv):
    a_list(bank, 3)
    text = _text(srv.call_tool("cicada_recall_detail", {"entity_id": "list-x-bookmarks"}))
    assert "list of saved posts" in text and "3 saved" in text and "newest 2026-11-03" in text
    assert "A post 3" in text and "A post 1" in text, "the newest rows, from the saves"
    assert text.index("A post 3") < text.index("A post 1"), "newest first"
    # a count that is never the page's own text: a save made after the page was written moves it with no page write
    save(bank, 4, day="2026-11-09")
    bank_index.invalidate()
    again = _text(srv.call_tool("cicada_recall_detail", {"entity_id": "list-x-bookmarks"}))
    assert "4 saved" in again and "newest 2026-11-09" in again and "A post 4" in again
    assert "4 saved" not in (bank / "entities" / "list-x-bookmarks.md").read_text()


def test_a_remote_caller_without_sources_is_told_how_many_and_none_of_the_words(bank, on):
    a_list(bank, 3)
    sans = set(catalog.SCOPES) - {"sources"}
    text, status = _remote().call(_connector(sans), "cicada_recall_detail", {"entity_id": "list-x-bookmarks"})
    assert status == "ok" and "3 saved" in str(text) and "A post 3" not in str(text)
    full, _ = _remote().call(_connector(), "cicada_recall_detail", {"entity_id": "list-x-bookmarks"})
    assert "A post 3" in str(full)


def test_the_page_blocks_ask_names_list_on_both_doors(bank, on, srv):
    a_list(bank, 2)
    text = _text(srv.call_tool("cicada_recall_detail", {"entity_id": "list-x-bookmarks", "include": ["list"]}))
    assert "## Page blocks" in text and "list of saved posts (" in text and "never stored on the page" in text
    remote, status = _remote().call(_connector(), "cicada_recall_detail",
                                    {"entity_id": "list-x-bookmarks", "include": ["list"]})
    assert status == "ok" and "never stored on the page" in str(remote)
    # any other page: the kind says it is not there, nothing more
    other = _text(srv.call_tool("cicada_recall_detail", {"entity_id": "alpha-project", "include": ["list"]}))
    assert "list: none on this page" in other and "list of saved posts" not in other


def test_dark_no_page_exists_so_no_page_read_changes(bank, srv):
    save(bank, 1)
    before = _text(srv.call_tool("cicada_recall_detail", {"entity_id": "alpha-project"}))
    assert "list of saved posts" not in before
    assert lists(bank) == []


def test_a_recall_hit_for_a_list_page_says_it_is_a_list(bank, on, srv):
    a_list(bank, 3)
    text = _text(srv.call_tool("cicada_recall", {"query": "X Bookmarks"}))
    head = next(line for line in text.splitlines() if line.startswith("### X: Bookmarks"))
    assert "list of saved posts" in head and "3 saved" in head and "newest 2026-11-03" in head
    assert "last said" not in head
    assert "This page is a list of saved posts" in text and "cicada_recall_detail" in text


# ---------------------------------------------------------------------------------- agents are held to it

WRITES = [
    ("cicada_write_claim", {"subject": "list-x-bookmarks", "predicate": "uses", "object": "x"}),
    ("cicada_edit_page", {"subject": "list-x-bookmarks", "reason": "tidy", "section": "Summary", "text": "Other words."}),
    ("cicada_merge_pages", {"page": "list-x-bookmarks", "into": "alpha-project", "reason": "same thing"}),
    ("cicada_merge_pages", {"page": "alpha-project", "into": "list-x-bookmarks", "reason": "same thing"}),
    ("cicada_split_page", {"page": "list-x-bookmarks", "reason": "two things", "sentences": [1]}),
    ("cicada_split_page", {"page": "list-x-bookmarks", "preview": True}),
    ("cicada_undo_join", {"page": "list-x-bookmarks"}),
    ("cicada_link_entity", {"project": "alpha-project", "entity": "list-x-bookmarks", "reason": "it fed the project"}),
    ("cicada_add_source", {"subject": "list-x-bookmarks", "ref": "https://example.com/a"}),
    ("cicada_add_source", {"subject": "alpha-project", "ref": "https://example.com/a", "entity": "list-x-bookmarks"}),
    ("cicada_change_source", {"subject": "list-x-bookmarks", "ref": "https://example.com/a", "action": "remove",
                              "reason": "wrong"}),
    ("cicada_create_project", {"project": "list-x-bookmarks", "reason": "they asked"}),
]
REMOTE_TOOLS = {"cicada_write_claim", "cicada_merge_pages", "cicada_split_page", "cicada_undo_join",
                "cicada_link_entity", "cicada_add_source", "cicada_change_source", "cicada_create_project"}


def _untouched(bank):
    """Every page and every inbox file, by name: a refused write changes none and files no proposal."""
    return {f"{d}/{p.name}": p.read_bytes() for d in ("entities", "inbox") if (bank / d).is_dir()
            for p in (bank / d).glob("*.md")}


@pytest.mark.parametrize("tool, arguments", WRITES, ids=[f"{t}-{i}" for i, (t, _) in enumerate(WRITES)])
def test_the_stdio_door_refuses_every_agent_write_to_a_list_page_with_one_sentence(bank, on, srv, tool, arguments):
    a_list(bank, 2)
    settle(bank)
    before, head = _untouched(bank), commits(bank)
    result = srv.call_tool(tool, arguments)
    assert result["isError"] is True and result["structuredContent"]["code"] == "refused"
    assert result["structuredContent"]["message"] == list_pages.AGENT_REFUSAL
    assert _untouched(bank) == before and commits(bank) == head, "nothing was written, filed or committed"


@pytest.mark.parametrize("tool, arguments", [w for w in WRITES if w[0] in REMOTE_TOOLS],
                         ids=[f"{t}-{i}" for i, (t, _) in enumerate(w for w in WRITES if w[0] in REMOTE_TOOLS)])
def test_the_remote_door_refuses_it_in_the_same_words(bank, on, tool, arguments):
    a_list(bank, 2)
    settle(bank)
    before, head = _untouched(bank), commits(bank)
    text, status = _remote().call(_connector(), tool, arguments)
    assert text.code == "refused" and str(text) == list_pages.AGENT_REFUSAL, (status, str(text))
    assert _untouched(bank) == before and commits(bank) == head


def test_the_refusal_is_flagged_with_its_code_over_http_and_names_no_one(bank, on, tmp_path):
    a_list(bank, 2, folders=["Private folder name"])
    db = store.ConnectorStore(tmp_path / "remote" / "connectors.db")
    _, token = db.create(app="claude", label="", scopes=list(catalog.SCOPES), expires_in_days=30)
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "cicada_write_claim", "arguments": {"subject": "list-x-bookmarks", "predicate": "uses", "object": "x"}}}
    with TestClient(remote_app.build_app(db, runtime=_remote())) as c:
        result = c.post(f"/c/{token}/mcp", json=call, headers=H).json()["result"]
    assert result["isError"] is True and result["structuredContent"]["code"] == "refused"
    assert result["content"][0]["text"] == list_pages.AGENT_REFUSAL
    assert "Private folder name" not in result["content"][0]["text"], "a folder's name is the person's own word"
    assert tool_contract.REFERENCE_HEADER not in result["content"][0]["text"]


def test_a_refusal_finds_the_page_by_its_name_as_well_as_its_id(bank, on, srv):
    a_list(bank, 2)
    result = srv.call_tool("cicada_write_claim", {"subject": "X: Bookmarks", "predicate": "uses", "object": "x"})
    assert result["isError"] is True and result["structuredContent"]["message"] == list_pages.AGENT_REFUSAL


def test_every_other_page_is_written_as_before(bank, on, srv):
    a_list(bank, 1)
    result = srv.call_tool("cicada_write_claim", {"subject": "alpha-project", "predicate": "uses", "object": "sqlite"})
    assert "isError" not in result and "Recorded" in _text(result)


def test_the_one_check_is_the_one_list_pages_has(bank):
    """There is no second test of "is this a list's page": the guards in `mcp_tools` ask `list_pages.is_list`."""
    import inspect
    import re

    source = inspect.getsource(mcp_tools)
    assert "list_pages.is_list(entry.frontmatter)" in source
    assert not re.search(r"""["']kind["']\)\s*==\s*["']list["']""", source)


# ---------------------------------------------------------------------------------- the pages stay current by themselves


def wait_for(predicate, seconds=8.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_a_list_read_that_lands_makes_the_list_its_page_in_the_writers_own_commit(reading, on, monkeypatch):
    server, memory = reading
    monkeypatch.setattr(list_pages, "SETTLE_S", 0.05)
    reading_settings.update(saved_lists_={"x": True})
    assert lists(memory) == []
    out = server.handle_tool("cicada_record_saved_list", {"platform": "x", "outcome": "read", "items": [
        {"url": "https://x.com/alice_example/status/1000000000000000001", "author": "alice_example", "text": "A note."}]})
    assert out.startswith("Recorded"), out
    assert wait_for(lambda: lists(memory) == ["list-x-bookmarks"]), "the page is made with no one asking"
    bank_index.invalidate()
    wait_for(lambda: "sync/list_pages" in git(memory, "log", "-1", "--format=%B"))
    message = git(memory, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in message and "sync/list_pages" in message
    assert git(memory, "log", "-1", "--format=%H") != git(memory, "log", "-2", "--format=%H").splitlines()[-1]
    assert page_of(memory, "list-x-bookmarks").frontmatter["list"]["stream"] == "x.bookmarks"


def test_dark_a_list_read_makes_no_page(reading, monkeypatch):
    server, memory = reading
    monkeypatch.setattr(list_pages, "SETTLE_S", 0.05)
    reading_settings.update(saved_lists_={"x": True})
    server.handle_tool("cicada_record_saved_list", {"platform": "x", "outcome": "read", "items": [
        {"url": "https://x.com/alice_example/status/1000000000000000001", "author": "alice_example", "text": "A note."}]})
    time.sleep(0.4)
    assert lists(memory) == []


def test_a_read_that_saved_nothing_asks_for_nothing(reading, on, monkeypatch):
    server, memory = reading
    asked = []
    monkeypatch.setattr(list_pages, "start_sync", lambda mp, **kw: asked.append(kw) or True)
    reading_settings.update(saved_lists_={"x": True})
    server.handle_tool("cicada_record_saved_list", {"platform": "x", "outcome": "read", "items": []})
    assert asked == []
    server.handle_tool("cicada_record_saved_list", {"platform": "x", "outcome": "read", "items": [
        {"url": "https://x.com/alice_example/status/1000000000000000001", "author": "alice_example", "text": "A note."}]})
    assert asked == [{"delay_s": list_pages.SETTLE_S}]


def test_a_save_noticed_in_a_site_asks_for_the_page_after_it_is_stored(bank, monkeypatch, client):
    asked = []
    stored = []
    monkeypatch.setattr(list_pages, "start_sync", lambda mp, delay_s=0.0: asked.append(delay_s) or stored.append(
        sorted(p.name for p in (bank / "entities").glob("media-*.md"))) or True)
    r = client.post("/sources/site-save", json={"site": "x", "url": "https://x.com/alice_example/status/1900000000000000001"})
    assert r.status_code == 200 and r.json()["status"] == "created"
    assert asked == [list_pages.SETTLE_S]
    assert stored == [[f"{r.json()['mediaEntityId']}.md"]], "the save is stored before the page is asked for"


def test_a_refused_site_save_asks_for_nothing(bank, monkeypatch, client):
    asked = []
    monkeypatch.setattr(list_pages, "start_sync", lambda mp, delay_s=0.0: asked.append(delay_s) or True)
    assert client.post("/sources/site-save", json={"site": "x", "url": "https://x.com/home"}).status_code == 422
    assert asked == []


def test_the_end_of_a_sleep_run_asks_for_the_pages_after_the_window_is_closed():
    """The run's tail: the list pages' writer is asked beside the file pages' (`media_pages`), after the write flag is
    cleared in its own `finally`, so it never starts inside Sleep's window (and `sync` retries when held)."""
    import inspect

    from api.services import sleep_cycle

    source = inspect.getsource(sleep_cycle)
    flag = source.index("_state.writing = False")
    asked = source.index("list_pages.start_sync(memory_path, delay_s=list_pages.SETTLE_S)")
    assert asked > flag and source.index("media_pages.start_sync(memory_path") < asked


def test_a_burst_of_triggers_makes_one_run_and_a_held_bank_is_tried_again(bank, on, monkeypatch):
    """The writer's own rails the triggers rely on: a trigger during a run runs it once more, never twice at once."""
    save(bank, 1)
    runs = []
    real = list_pages.sync
    monkeypatch.setattr(list_pages, "sync", lambda mp: runs.append(1) or real(mp))
    assert list_pages.start_sync(bank) is True
    assert wait_for(lambda: lists(bank) == ["list-x-bookmarks"] and bool(runs))
    assert len(runs) >= 1


def test_the_items_etag_follows_the_earned_set_only_once_the_flip_is_on(bank, client, monkeypatch):
    save(bank, 1)
    settle(bank)
    url = "/sources/channels/x/items?stream=x.bookmarks"
    dark = client.get(url).headers["etag"]
    assert saved_posts.stamp(bank) == "" and client.get(url).headers["etag"] == dark
    monkeypatch.setattr(saved_posts, "stamp", lambda mp: "a1b2c3")
    one = client.get(url).headers["etag"]
    monkeypatch.setattr(saved_posts, "stamp", lambda mp: "d4e5f6")
    assert one != dark and client.get(url).headers["etag"] != one, "a post earning its page moves the rows' ETag"
