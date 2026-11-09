"""Choosing what a signed-in service may be read for (owner 2026-11-09): the choice store, the sync honouring it, Notion
databases read as rows, Notion markup cleaned, the picker's listing and routes, Linear's team/project filters.

Hermetic: fakes only, placeholder ids, no live Notion or Linear.
"""

from __future__ import annotations

import asyncio
import json as jsonlib
import time

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import connectors as connectors_router
from api.services import markdown_parser, sleep_cycle
from api.services.connections import secrets
from api.services.connectors import linear, linear_mcp, notion, notion_mcp, scope, tier2
from api.tests.test_notion_mcp import FakeNotionAuth, REDIRECT_BASE, _signed_in

PAGE_A, PAGE_B, DB, ROW1, ROW2, CHILD = ("a" * 32, "b" * 32, "d" * 32, "1" * 32, "2" * 32, "c" * 32)
COLLECTION = "dddddddd-dddd-dddd-dddd-dddddddddddd"


class Server:
    """A Notion MCP server with a page, a child page, and a two-row database."""

    def __init__(self):
        self.messages: list[dict] = []
        self.pages = {
            PAGE_A: ("Alpha", f'Alpha body. <page url="https://www.notion.so/{CHILD}">Child</page> '
                              f'and a mention <mention-page url="https://www.notion.so/{PAGE_B}">Beta</mention-page>'),
            PAGE_B: ("Beta", "Beta body."),
            CHILD: ("Child", "Child body."),
            ROW1: ("Idea one", "First idea in words.\n<p />\n- a point"),
            ROW2: ("Idea two", "Second idea."),
        }

    def result(self, name, args):
        if name == "notion-fetch":
            rid = args["id"]
            if rid == DB:
                return {"title": "Ideas", "page_last_edited_at": "2026-10-02T10:00:00Z",
                        "text": f'title: Ideas\n<database url="https://www.notion.so/{DB}" '
                                f'data-source-url="collection://{COLLECTION}">Ideas</database>'}
            title, body = self.pages[rid]
            props = '<properties>{"Status": "Open"}</properties>\n' if rid in (ROW1, ROW2) else ""
            return {"title": title, "page_last_edited_at": "2026-10-01T10:00:00Z",
                    "text": f"title: {title}\n{props}<content>\n{body}\n</content>"}
        if name == "notion-query-data-sources":
            assert args["data_source_url"] == f"collection://{COLLECTION}"
            return {"results": [{"url": f"https://www.notion.so/{ROW1}", "Name": "Idea one"},
                                {"url": f"https://www.notion.so/{ROW2}", "Name": "Idea two"}], "has_more": False}
        if name == "notion-list-private-pages":
            return {"results": [{"id": PAGE_A, "type": "page", "title": "Alpha"},
                                {"id": DB, "type": "database", "title": "Ideas"}]}
        if name == "notion-list-shared-pages":
            return {"results": [{"id": PAGE_B, "type": "page", "title": "Beta"}]}
        if name == "notion-search":
            q = args.get("query")
            return {"results": [{"id": PAGE_B, "type": "page", "title": "Beta"}]} if q else {"results": []}
        raise AssertionError(name)

    async def __call__(self, method, url, *, headers, params=None, json=None):
        self.messages.append(json)
        if json["method"] == "initialize":
            return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"], "result": {}}, {"mcp-session-id": "s"})
        if json["method"] == "notifications/initialized":
            return tier2.Response(202, None)
        out = self.result(json["params"]["name"], json["params"]["arguments"])
        return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"],
                                    "result": {"content": [{"type": "text", "text": jsonlib.dumps(out)}]}})

    def calls(self):
        return [m["params"]["name"] for m in self.messages if m["method"] == "tools/call"]


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def _stored(bank):
    out = {}
    for path in (bank / "episodes").glob("*.md"):
        fm = markdown_parser.parse(path)
        out[str(fm.frontmatter.get("source_id"))] = (fm.frontmatter, fm.body)
    return out


# --- the store ---------------------------------------------------------------------------------------------------------


def test_no_file_is_everything_and_a_fresh_sign_in_is_pending_but_a_lapsed_one_keeps_its_choice(bank, monkeypatch):
    assert scope.read("notion-api") == {"mode": "everything", "items": []}      # a connection from before choosing
    fake = FakeNotionAuth()
    monkeypatch.setattr(notion_mcp, "TRANSPORT", fake)
    asyncio.run(notion.authorize_url("s1", base_url=REDIRECT_BASE))
    asyncio.run(notion.exchange_code("code", state="s1", base_url=REDIRECT_BASE))
    assert scope.read("notion-api")["mode"] == "pending"
    scope.write("notion-api", "chosen", [{"id": PAGE_A, "title": "Alpha", "kind": "page"}])
    secrets.set_secret(notion_mcp.HOW_ENV, notion_mcp.HOW_RECONNECT)       # the sign-in lapsed; signing in again
    asyncio.run(notion.authorize_url("s2", base_url=REDIRECT_BASE))
    asyncio.run(notion.exchange_code("code", state="s2", base_url=REDIRECT_BASE))
    assert scope.read("notion-api")["mode"] == "chosen"
    with pytest.raises(ValueError):
        scope.write("notion-api", "chosen", [])
    notion.forget()
    assert not scope.exists("notion-api")


def test_nothing_is_read_before_the_person_chooses(bank):
    _signed_in()
    scope.mark_pending("notion-api")
    server = Server()
    result = asyncio.run(notion.sync(bank, http_fn=server))
    assert result["status"] == "skipped" and server.messages == [] and _stored(bank) == {}


# --- reading what was chosen ---------------------------------------------------------------------------------------------


def test_a_chosen_page_brings_its_sub_pages_but_not_pages_it_only_mentions_and_unchoosing_keeps_what_was_saved(bank):
    _signed_in()
    scope.write("notion-api", "chosen", [{"id": PAGE_A, "title": "Alpha", "kind": "page"}])
    server = Server()
    result = asyncio.run(notion.sync(bank, http_fn=server))
    assert result["status"] == "ok"
    assert set(_stored(bank)) == {f"notion:{PAGE_A}", f"notion:{CHILD}"}          # Beta is only mentioned
    assert "notion-list-private-pages" not in server.calls()                       # nothing outside the choice is listed
    scope.write("notion-api", "chosen", [{"id": PAGE_B, "title": "Beta", "kind": "page"}])
    asyncio.run(notion.sync(bank, http_fn=Server()))
    assert set(_stored(bank)) == {f"notion:{PAGE_A}", f"notion:{CHILD}", f"notion:{PAGE_B}"}, "nothing taken away"


def test_a_chosen_database_is_read_as_rows_with_its_title_and_properties(bank):
    _signed_in()
    scope.write("notion-api", "chosen", [{"id": DB, "title": "Ideas", "kind": "database"}])
    server = Server()
    result = asyncio.run(notion.sync(bank, http_fn=server))
    assert result["status"] == "ok" and "notion-query-data-sources" in server.calls()
    stored = _stored(bank)
    assert set(stored) == {f"notion:{ROW1}", f"notion:{ROW2}"}                     # the database itself is no episode
    fm, text = stored[f"notion:{ROW1}"]
    assert "**Database:** Ideas" in text and "**Status:** Open" in text and "First idea in words." in text
    assert fm.get("notion_kind") == "row"
    assert "<p />" not in text and "title:" not in text.lower().replace("**database:**", "")


def test_everything_reads_a_listed_database_too(bank):
    _signed_in()
    asyncio.run(notion.sync(bank, http_fn=Server()))
    assert {f"notion:{ROW1}", f"notion:{ROW2}", f"notion:{PAGE_A}"} <= set(_stored(bank))


# --- clean text ----------------------------------------------------------------------------------------------------------


def test_the_servers_markup_becomes_readable_text():
    raw = ('title: Ideas\n<p />\n<page url="https://www.notion.so/x">Idea</page> <mention-user url="user://1">Ana'
           '</mention-user> <mention-date start="2026-10-01"/>\n<table><tr><td>A</td><td>B</td></tr><tr><td>1</td>'
           '<td>2</td></tr></table>\n<details><summary>More</summary>\n- point {color="gray"}\n</details>')
    text = notion.page_text({"markdown": raw})
    assert "<" not in text and "title:" not in text
    assert "[Idea](https://www.notion.so/x)" in text and "Ana 2026-10-01" in text
    assert "| A | B |" in text and "| --- | --- |" in text and "- point" in text and "{color" not in text


# --- the picker -----------------------------------------------------------------------------------------------------------


def test_the_picker_lists_pages_and_databases_and_searches():
    server = Server()
    listed = asyncio.run(notion.containers(tier2.Client(notion, "t", server), ""))
    assert {(i["id"], i["kind"]) for i in listed["items"]} == {(PAGE_A, "page"), (DB, "database"), (PAGE_B, "page")}
    found = asyncio.run(notion.containers(tier2.Client(notion, "t", server), "beta"))
    assert [i["id"] for i in found["items"]] == [PAGE_B]


def test_the_routes_choose_and_refuse_an_empty_choice(bank, monkeypatch):
    _signed_in()
    scope.mark_pending("notion-api")
    monkeypatch.setattr(connectors_router, "_client", lambda adapter: tier2.Client(adapter, "t", Server()))
    api = TestClient(main.app)
    status = api.get("/sources/connectors/notion-api").json()
    assert status["chooses"] is True and status["scope"] == "pending" and status["chooseNoun"] == "pages and databases"
    assert api.get("/sources/connectors/notion-api/containers", params={"q": "beta"}).json()["items"][0]["id"] == PAGE_B
    assert api.put("/sources/connectors/notion-api/scope", json={"mode": "chosen", "items": []}).status_code == 422
    done = api.put("/sources/connectors/notion-api/scope", json={
        "mode": "chosen", "items": [{"id": PAGE_B, "title": "Beta", "kind": "page"}]}).json()
    assert done["mode"] == "chosen" and "stays" in done["unchooseWords"]
    assert api.get("/sources/connectors/notion-api").json()["scopeCount"] == 1
    assert api.put("/sources/connectors/notion-api/scope", json={"mode": "everything"}).json()["mode"] == "everything"
    assert api.get("/sources/connectors/pinterest/scope").status_code == 400      # nothing to choose from


# --- Linear ------------------------------------------------------------------------------------------------------------------


def test_linear_filters_follow_the_choice_and_the_picker_lists_teams_and_projects():
    assert linear.filters_for({"mode": "everything", "items": []}) == [{"creator": "me"}, {"assignee": "me"}]
    chosen = {"mode": "chosen", "items": [{"id": "t1", "title": "T", "kind": "team"},
                                          {"id": "p1", "title": "P", "kind": "project"}]}
    assert linear.filters_for(chosen) == [{"creator": "me", "team": "t1"}, {"assignee": "me", "team": "t1"},
                                          {"creator": "me", "project": "p1"}, {"assignee": "me", "project": "p1"}]

    async def server(method, url, *, headers, params=None, json=None):
        if json["method"] == "initialize":
            return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"], "result": {}})
        if json["method"] == "notifications/initialized":
            return tier2.Response(202, None)
        name = json["params"]["name"]
        data = {"list_teams": {"teams": [{"id": "t1", "name": "Platform", "key": "PLT"}]},
                "list_projects": {"projects": [{"id": "p1", "name": "Launch"}]}}[name]
        return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"],
                                    "result": {"content": [{"type": "text", "text": jsonlib.dumps(data)}]}})

    found = asyncio.run(linear.containers(tier2.Client(linear, "t", server), ""))
    assert found["items"] == [{"id": "t1", "title": "Platform (PLT)", "kind": "team"},
                              {"id": "p1", "title": "Launch", "kind": "project"}]
    narrowed = asyncio.run(linear.containers(tier2.Client(linear, "t", server), "launch"))
    assert [i["id"] for i in narrowed["items"]] == ["p1"]
