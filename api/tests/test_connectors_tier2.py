"""Ruling 47 tier 2: the shared framework (`connectors/tier2.py`), Readwise and Notion.

Hermetic: no real account and no network. Every reply comes from a fake server that answers with the recorded
shapes in `fixtures/connectors/` (placeholders only) and records every request it was sent.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from api.services import episode_staging, evidence, markdown_parser, sleep_cycle, sync_state
from api.services.connections import base as connections_base
from api.services.connections import secrets
from api.services.connectors import ADAPTERS, notion, readwise, tier2

FIX = Path(__file__).parent / "fixtures" / "connectors"
RW = json.loads((FIX / "readwise_export_full.json").read_text())
RW_CHANGED = json.loads((FIX / "readwise_export_changed.json").read_text())
NO = json.loads((FIX / "notion_api.json").read_text())
TOKEN = "placeholder-token-0123456789abcdef"


class FakeServer:
    """A service's API as recorded: ``routes(method, path, params, body) -> (status, body, headers)``."""

    def __init__(self, routes):
        self.routes = routes
        self.calls: list[dict] = []

    async def __call__(self, method, url, *, headers, params=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "params": dict(params or {}),
                           "json": json})
        status, body, hdrs = self.routes(method, url, params or {}, json)
        return tier2.Response(status, body, hdrs or {})


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    for a in tier2.adapters():
        monkeypatch.delenv(a.TOKEN_ENV, raising=False)
    yield memory
    for a in tier2.adapters():
        os.environ.pop(a.TOKEN_ENV, None)


def _connect(adapter):
    secrets.set_secret(adapter.TOKEN_ENV, TOKEN)


def _episodes(memory) -> dict[str, dict]:
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        out[str(parsed.frontmatter.get("source_id"))] = {"fm": parsed.frontmatter, "body": parsed.body, "path": path}
    return out


def _readwise_routes(pages=RW["pages"], changed=None):
    def routes(method, url, params, body):
        assert method == "GET" and url.startswith(readwise.API_BASE)
        if url.endswith("/auth/"):
            return 204, None, {}
        if "ids" in params:
            return 200, changed["whole_book_101"], {}
        if "updatedAfter" in params:
            return 200, changed["incremental"], {}
        index = 1 if params.get("pageCursor") == "cursor-page-2" else 0
        return 200, pages[index], {}
    return routes


# --- Readwise ------------------------------------------------------------------------------------------------------


def test_readwise_first_sync_stages_one_episode_per_document_and_highlight_day(bank):
    _connect(readwise)
    server = FakeServer(_readwise_routes())
    result = asyncio.run(readwise.sync(bank, http_fn=server))
    assert result["status"] == "ok" and result["new"] == 5, result
    eps = _episodes(bank)
    assert sorted(eps) == ["readwise:101:2026-09-01", "readwise:101:2026-09-05", "readwise:101:doc",
                           "readwise:202:2026-10-02", "readwise:202:doc"]
    day = eps["readwise:101:2026-09-01"]
    assert day["fm"]["origin"] == "readwise" and day["fm"]["connector"] == "readwise"
    assert day["fm"]["timestamp"].startswith("2026-09-01T10:00")       # dated when highlighted, read on time
    body = day["body"]
    assert "> The first highlighted line." in body and "user: This is my own thought." in body
    assert "Deleted before Cicada saw it." not in "".join(e["body"] for e in eps.values())
    # The quote is the document's words (`page`); the note on it is the person's (`user`).
    quote_at = body.index("The first highlighted line.")
    note_at = body.index("This is my own thought.")
    assert evidence.kind_for("ep_x", body, quote_at) == "page"
    assert evidence.kind_for("ep_x", body, note_at) == "user"
    doc = eps["readwise:101:doc"]["body"]
    assert "user: Read this for alpha-project." in doc and "**By:** Author A" in doc
    article = eps["readwise:202:doc"]
    assert article["fm"]["url"] == "https://example.com/an-article"
    assert "[Example Article](https://example.com/an-article)" in article["body"]


def test_readwise_requests_only_its_own_host_with_the_token_header_and_no_names(bank):
    _connect(readwise)
    server = FakeServer(_readwise_routes())
    asyncio.run(readwise.sync(bank, http_fn=server))
    assert server.calls and all(c["url"].startswith("https://readwise.io/api/v2/") for c in server.calls)
    assert all(c["headers"]["Authorization"] == f"Token {TOKEN}" for c in server.calls)
    assert all(c["method"] == "GET" for c in server.calls)          # read only
    assert set().union(*(c["params"] for c in server.calls)) <= {"includeDeleted", "pageCursor", "updatedAfter", "ids"}


def test_the_token_never_reaches_the_bank_and_the_cursor_lives_outside_it(bank, tmp_path):
    _connect(readwise)
    asyncio.run(readwise.sync(bank, http_fn=FakeServer(_readwise_routes())))
    for path in bank.rglob("*"):
        if path.is_file():
            assert TOKEN not in path.read_text(encoding="utf-8", errors="replace"), path
    cursors = list((tmp_path / "home" / "connectors").glob("readwise-*.json"))
    assert len(cursors) == 1 and (cursors[0].stat().st_mode & 0o777) == 0o600
    assert "updated_after" in json.loads(cursors[0].read_text())
    assert sync_state.read_sync_state(bank)["readwise"]["count"] == 5


def test_readwise_incremental_reads_a_changed_book_whole_and_rewrites_its_days_in_place(bank):
    _connect(readwise)
    asyncio.run(readwise.sync(bank, http_fn=FakeServer(_readwise_routes())))
    before = _episodes(bank)
    server = FakeServer(_readwise_routes(changed=RW_CHANGED))
    result = asyncio.run(readwise.sync(bank, http_fn=server))
    assert result["status"] == "ok", result
    assert any("updatedAfter" in c["params"] for c in server.calls)
    assert any(c["params"].get("ids") == "101" for c in server.calls)
    after = _episodes(bank)
    assert after["readwise:101:2026-09-01"]["path"] == before["readwise:101:2026-09-01"]["path"]   # in place
    assert "user: My thought, revised." in after["readwise:101:2026-09-01"]["body"]
    assert after["readwise:101:2026-09-01"]["fm"]["processed"] is False                             # re-queued
    # The day whose one highlight was deleted, and the deleted article, are tombstoned and kept.
    for sid in ("readwise:101:2026-09-05", "readwise:202:doc", "readwise:202:2026-10-02"):
        assert after[sid]["fm"].get("source_deleted_at"), sid
    assert not after["readwise:101:doc"]["fm"].get("source_deleted_at")
    assert sync_state.read_sync_state(bank)["readwise"]["count"] == 2


def test_an_unchanged_resync_writes_nothing(bank):
    _connect(readwise)
    asyncio.run(readwise.sync(bank, http_fn=FakeServer(_readwise_routes())))
    stamps = {p: p.stat().st_mtime_ns for p in (bank / "episodes").glob("*.md")}
    for path in (tier2._cursor_path("readwise", bank),):
        path.unlink()      # forget the cursor: the whole library is read again, and nothing moves
    result = asyncio.run(readwise.sync(bank, http_fn=FakeServer(_readwise_routes())))
    assert result["status"] == "ok" and result["new"] == 0 and result["updated"] == 0
    assert {p: p.stat().st_mtime_ns for p in (bank / "episodes").glob("*.md")} == stamps


def test_a_document_links_only_to_a_page_that_matches_exactly(bank):
    from api.services import media_ingestor

    media_ingestor.save_url_index(bank, {media_ingestor.url_hash("https://example.com/an-article"):
                                         {"media_entity_id": "media-an-article", "episode_id": "ep_1"}})
    (bank / "entities" / "example-book-one.md").write_text(
        "---\nid: example-book-one\ntitle: Example Book One\ntype: concept\n---\n# Example Book One\n")
    (bank / "entities" / "person-with-that-title.md").write_text(
        "---\nid: person-with-that-title\ntitle: Example Article\ntype: person\n---\n# x\n")
    _connect(readwise)
    asyncio.run(readwise.sync(bank, http_fn=FakeServer(_readwise_routes())))
    eps = _episodes(bank)
    assert eps["readwise:202:doc"]["fm"]["media_entity_id"] == "media-an-article"     # by its URL
    assert eps["readwise:101:doc"]["fm"]["media_entity_id"] == "example-book-one"      # by its exact title
    assert sorted(p.name for p in (bank / "entities").glob("*.md")) == ["example-book-one.md",
                                                                         "person-with-that-title.md"]  # none made


def test_two_pages_with_the_title_link_neither(bank):
    for i in (1, 2):
        (bank / "entities" / f"page-{i}.md").write_text(
            f"---\nid: page-{i}\ntitle: Example Book One\ntype: concept\n---\n# x\n")
    _connect(readwise)
    asyncio.run(readwise.sync(bank, http_fn=FakeServer(_readwise_routes())))
    assert _episodes(bank)["readwise:101:doc"]["fm"].get("media_entity_id") is None


def test_a_refused_token_is_said_in_words_and_nothing_is_staged(bank):
    _connect(readwise)
    result = asyncio.run(readwise.sync(bank, http_fn=FakeServer(lambda *a: (401, {"detail": "x"}, {}))))
    assert result["status"] == "error" and "readwise.io/access_token" in result["error"]
    assert not list((bank / "episodes").glob("*.md"))
    entry = sync_state.read_sync_state(bank)["readwise"]
    assert entry["last_error"] == readwise.REFUSED_WORDS and TOKEN not in json.dumps(entry)


def test_a_429_waits_its_retry_after_once(bank, monkeypatch):
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(tier2, "wait", fake_sleep)
    answers = iter([(429, None, {"retry-after": "7"})])
    base_routes = _readwise_routes()

    def routes(*a):
        return next(answers, None) or base_routes(*a)

    _connect(readwise)
    result = asyncio.run(readwise.sync(bank, http_fn=FakeServer(routes)))
    assert result["status"] == "ok" and waits == [7.0]


def test_a_second_429_stops_in_words_without_advancing(bank, monkeypatch):
    async def fake_sleep(s):
        return None

    monkeypatch.setattr(tier2, "wait", fake_sleep)
    _connect(readwise)
    result = asyncio.run(readwise.sync(bank, http_fn=FakeServer(lambda *a: (429, None, {"retry-after": "1"}))))
    assert result["status"] == "error" and "slow down" in result["error"]
    assert not tier2._cursor_path("readwise", bank).exists()


# --- the framework's rails -----------------------------------------------------------------------------------------


def test_a_scheduled_sync_never_starts_while_sleep_holds_the_pages(bank, monkeypatch):
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    _connect(readwise)
    server = FakeServer(_readwise_routes())
    result = asyncio.run(readwise.sync(bank, http_fn=server, scheduled=True))
    assert result["status"] == "skipped" and server.calls == []
    assert sync_state.read_sync_state(bank)["readwise"]["last_skip_reason"] == tier2.WAITED_FOR_SLEEP


def test_a_sync_whose_fetch_overlapped_sleep_writes_nothing_and_keeps_its_cursor(bank, monkeypatch):
    """The person's Refresh fetches (their click), then Sleep opens its window before the staging: the admitted
    transaction is refused, nothing is written, and the cursor stays where it was."""
    _connect(readwise)
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: state["writing"])
    base_routes = _readwise_routes()

    def routes(*a):
        state["writing"] = True        # Sleep starts while the fetch is in flight
        return base_routes(*a)

    result = asyncio.run(readwise.sync(bank, http_fn=FakeServer(routes)))
    assert result["status"] == "skipped" and result["reason"] == tier2.WAITED_FOR_SLEEP
    assert not list((bank / "episodes").glob("*.md"))
    assert not tier2._cursor_path("readwise", bank).exists()


def test_a_scheduled_sync_is_gated_and_a_person_sync_is_not(bank, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    _connect(readwise)
    monkeypatch.setattr(tier2, "http_transport", FakeServer(_readwise_routes()))
    result = asyncio.run(tier2.run(readwise, bank, scheduled=True))
    assert result["status"] == "skipped" and result["reason"] == "network disabled"
    assert sync_state.read_sync_state(bank)["readwise"]["last_skip_reason"] == tier2.GATE_CLOSED
    server = FakeServer(_readwise_routes())
    assert asyncio.run(readwise.sync(bank, http_fn=server, allow_fetch=True))["status"] == "ok"


def test_off_by_default_and_a_demo_bank_takes_nothing(bank, monkeypatch):
    server = FakeServer(_readwise_routes())
    assert asyncio.run(readwise.sync(bank, http_fn=server))["reason"] == "not connected"
    assert server.calls == []
    _connect(readwise)
    from api.services import demo_guard

    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert asyncio.run(readwise.sync(bank, http_fn=server))["status"] == "skipped" and server.calls == []


def test_sleeps_tail_never_runs_a_tier_two_sync(tmp_path, monkeypatch):
    ran = []
    for cid, adapter in ADAPTERS.items():
        async def fake(memory_path, *, _cid=cid, **kw):
            ran.append(_cid)
            return {"status": "ok", "new": 0}
        monkeypatch.setattr(adapter, "sync", fake)
    asyncio.run(sleep_cycle._poll_connectors_safely(tmp_path))
    assert sorted(ran) == ["pinterest", "reddit", "x"]


def test_every_connector_secret_is_kept_from_engine_children():
    for adapter in ADAPTERS.values():
        assert set(adapter.SECRET_NAMES) <= set(connections_base.SCRUBBED_ENV_KEYS), adapter.CHANNEL_ID


def test_a_request_off_the_services_host_is_refused():
    client = tier2.Client(readwise, TOKEN, FakeServer(lambda *a: (200, {}, {})))
    with pytest.raises(Exception) as exc:
        asyncio.run(client.get("https://elsewhere.example/api/v2/"))
    assert "off its own host" in str(exc.value)


# --- the doors: API and CLI ------------------------------------------------------------------------------------------


@pytest.fixture
def api(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_status_says_what_it_reads_and_never_returns_the_token(api, monkeypatch):
    body = api.get("/sources/connectors/readwise").json()
    assert body["tier"] == 2 and body["connected"] is False and "only reads" in body["reads"]
    assert body["tokenHelp"] == "readwise.io/access_token"
    monkeypatch.setattr(tier2, "http_transport", FakeServer(_readwise_routes()))
    saved = api.put("/sources/connectors/readwise/credentials", json={"fields": {readwise.TOKEN_ENV: TOKEN}})
    assert saved.status_code == 200 and saved.json()["connected"] is True
    assert TOKEN not in saved.text and TOKEN not in api.get("/sources/connectors").text
    synced = api.post("/sources/connectors/readwise/sync").json()
    assert synced["status"] == "ok" and synced["new"] == 5 and synced["resourcesRead"] >= 2
    gone = api.delete("/sources/connectors/readwise/credentials").json()
    assert gone["connected"] is False and not secrets.has_secret(readwise.TOKEN_ENV)
    assert not list(tier2._cursor_path("readwise", bank_path(api)).parent.glob("readwise-*.json"))


def bank_path(api) -> Path:
    from api import config

    return config.get_settings().memory_path


def test_a_refused_token_is_never_saved(api, monkeypatch):
    monkeypatch.setattr(tier2, "http_transport", FakeServer(lambda *a: (401, None, {})))
    answer = api.put("/sources/connectors/readwise/credentials", json={"fields": {readwise.TOKEN_ENV: TOKEN}})
    assert answer.status_code == 422 and "readwise.io/access_token" in answer.json()["detail"]
    assert not secrets.has_secret(readwise.TOKEN_ENV)


def test_a_notion_personal_token_is_refused_at_save(api, monkeypatch):
    monkeypatch.setattr(tier2, "http_transport", FakeServer(lambda *a: (200, NO["users_me_person"], {})))
    answer = api.put("/sources/connectors/notion-api/credentials", json={"fields": {notion.TOKEN_ENV: TOKEN}})
    assert answer.status_code == 422 and "internal connection" in answer.json()["detail"]
    assert not secrets.has_secret(notion.TOKEN_ENV)


def test_the_cli_reads_the_token_from_stdin_only(monkeypatch):
    from api import cli_app
    from api.services import cli_map

    rows = {r.name: r for r in cli_map.ROWS}
    assert rows["connector connect"].person and [a.prop for a in rows["connector connect"].args] == ["connector"]
    sent = {}

    def fake_call(boot, method, path, **kw):
        if method == "GET":
            return {"label": "Readwise", "loginMode": "credentials", "reads": "r", "tokenHelp": "h",
                    "fields": [{"name": readwise.TOKEN_ENV, "label": "Token", "secret": True}]}
        sent.update(kw.get("body") or {})
        return {"label": "Readwise", "connected": True}

    monkeypatch.setattr(cli_app, "call", fake_call)
    monkeypatch.setattr(cli_app, "require_person", lambda what: None)
    monkeypatch.setattr(cli_app, "read_token", lambda label: TOKEN)
    from types import SimpleNamespace

    out = cli_app.cmd_connector_connect(SimpleNamespace(probe={}), SimpleNamespace(connector="readwise"))
    assert sent == {"fields": {readwise.TOKEN_ENV: TOKEN}} and TOKEN not in out.text


# --- Notion --------------------------------------------------------------------------------------------------------


def _notion_routes(search=NO["search"], trash=NO["trash"], markdown=NO["markdown"]):
    def routes(method, url, params, body):
        assert url.startswith(notion.API_BASE)
        path = url[len(notion.API_BASE):]
        if path == "users/me":
            return 200, NO["users_me_bot"], {}
        if path == "search":
            assert method == "POST" and "query" not in body           # never a search for a name or subject
            return 200, (trash if body["filter"].get("in_trash") else search), {}
        if path.startswith("pages/") and path.endswith("/markdown"):
            return 200, markdown[path.split("/")[1]], {}
        if path.startswith("data_sources/"):
            return 200, NO["data_source"], {}
        return 404, {"object": "error"}, {}
    return routes


def test_notion_pages_become_episodes_keyed_by_page_id(bank):
    _connect(notion)
    server = FakeServer(_notion_routes())
    result = asyncio.run(notion.sync(bank, http_fn=server))
    assert result["status"] == "ok" and result["new"] == 2, result
    eps = _episodes(bank)
    page = eps["notion:11111111222233334444555555555555"]
    assert page["fm"]["origin"] == "notion-api"
    # A workspace-owned connection never says who the person is: no page is credited to them (B1).
    assert page["fm"]["evidence_kind"] == "assistant" and page["fm"]["notion_by_other"] is True
    assert notion.UNKNOWN_AUTHOR_WORDS in sync_state.read_sync_state(bank)["notion-api"]["words"]
    assert "Ship the first slice." in page["body"] and "A child page" in page["body"] and "<page" not in page["body"]
    assert page["fm"]["timestamp"].startswith("2026-08-01")                     # created, read on time
    row = eps["notion:aaaaaaaabbbbccccddddeeeeeeeeeeee"]["body"]
    assert "**Database:** Project ideas" in row and "**Status:** Someday" in row and "**Tags:** tools, reading" in row
    assert all(c["headers"]["Notion-Version"] == notion.NOTION_VERSION for c in server.calls)
    assert all(c["method"] in ("GET", "POST") for c in server.calls)
    assert {c["url"].split("/v1/")[1] for c in server.calls if c["method"] == "POST"} == {"search"}


def test_notion_an_edit_rewrites_in_place_and_the_trash_tombstones(bank):
    _connect(notion)
    asyncio.run(notion.sync(bank, http_fn=FakeServer(_notion_routes())))
    first = _episodes(bank)
    edited = json.loads(json.dumps(NO["search"]))
    edited["results"] = [dict(edited["results"][0], last_edited_time="2026-10-20T09:00:00.000Z")]
    md = json.loads(json.dumps(NO["markdown"]))
    md["11111111-2222-3333-4444-555555555555"]["markdown"] = "## Goals\n\nShip the second slice."
    trashed = {"object": "list", "has_more": False, "results": [
        dict(NO["search"]["results"][1], in_trash=True)]}
    server = FakeServer(_notion_routes(search=edited, markdown=md, trash=trashed))
    result = asyncio.run(notion.sync(bank, http_fn=server))
    assert result["status"] == "ok"
    pages_read = [c for c in server.calls if c["url"].endswith("/markdown")]
    assert len(pages_read) == 1                       # only the page edited since the high-water mark
    after = _episodes(bank)
    sid = "notion:11111111222233334444555555555555"
    assert after[sid]["path"] == first[sid]["path"] and "second slice" in after[sid]["body"]
    assert after["notion:aaaaaaaabbbbccccddddeeeeeeeeeeee"]["fm"].get("source_deleted_at")


def test_notion_updates_an_exported_page_in_place_never_a_second_copy(bank):
    draft = episode_staging.EpisodeDraft(title="Alpha project plan", source_id="notion:11111111222233334444555555555555",
                                         source="notion-export", origin="notion-export", body="# Alpha project plan\n\nOld",
                                         writer="notion", timestamp="2026-08-01T09:00:00+00:00")
    episode_staging.stage([draft], bank / "episodes")
    _connect(notion)
    asyncio.run(notion.sync(bank, http_fn=FakeServer(_notion_routes())))
    eps = [e for e in _episodes(bank) if e.startswith("notion:1111")]
    assert eps == ["notion:11111111222233334444555555555555"]
    assert len(list((bank / "episodes").glob("*.md"))) == 2


def _owned_by(user_id):
    return {"object": "user", "id": "bot-0001", "type": "bot",
            "bot": {"owner": {"type": "user", "user": {"object": "user", "id": user_id}}}}


def _with_me(routes, me):
    def wrapped(method, url, params, body):
        if url.endswith("/users/me"):
            return 200, me, {}
        return routes(method, url, params, body)
    return wrapped


def test_a_notion_page_is_the_persons_words_only_when_notion_says_they_wrote_it(bank):
    _connect(notion)
    asyncio.run(notion.sync(bank, http_fn=FakeServer(_with_me(_notion_routes(), _owned_by("user-0001")))))
    assert {e["fm"]["evidence_kind"] for e in _episodes(bank).values()} == {"user"}
    assert "words" not in sync_state.read_sync_state(bank)["notion-api"]


def test_a_single_other_creator_is_never_the_person(bank):
    """B1's repro: every page created by one colleague, the connection owned by the person — never `user`."""
    other = json.loads(json.dumps(NO["search"]))
    for page in other["results"]:
        page["created_by"] = {"object": "user", "id": "user-colleague"}
    _connect(notion)
    me = _owned_by("user-0001")
    asyncio.run(notion.sync(bank, http_fn=FakeServer(_with_me(_notion_routes(search=other), me))))
    assert {e["fm"]["evidence_kind"] for e in _episodes(bank).values()} == {"assistant"}


def test_the_live_read_never_turns_an_exported_others_row_into_the_persons(bank):
    """B2's repro: the export marked a row as someone else's; the live read (which believes it is the person's) keeps it
    someone else's."""
    draft = episode_staging.EpisodeDraft(
        title="Idea: a reading log", source_id="notion:aaaaaaaabbbbccccddddeeeeeeeeeeee", source="notion-export",
        origin="notion-export", body="# Idea: a reading log\n\nOld", writer="notion",
        timestamp="2026-07-01T09:00:00+00:00", extra={"evidence_kind": "assistant", "notion_by_other": True})
    episode_staging.stage([draft], bank / "episodes")
    _connect(notion)
    asyncio.run(notion.sync(bank, http_fn=FakeServer(_with_me(_notion_routes(), _owned_by("user-0001")))))
    eps = _episodes(bank)
    row = eps["notion:aaaaaaaabbbbccccddddeeeeeeeeeeee"]
    assert "Keep a log of what I read." in row["body"]                      # the live read did land
    assert row["fm"]["evidence_kind"] == "assistant" and row["fm"]["notion_by_other"] is True
    assert eps["notion:11111111222233334444555555555555"]["fm"]["evidence_kind"] == "user"


def _many_pages(n):
    out = []
    for i in range(n):
        out.append({"object": "page", "id": f"{i:08x}-0000-0000-0000-000000000000",
                    "created_time": "2026-01-01T00:00:00.000Z",
                    "last_edited_time": f"2026-10-{28 - i // 2:02d}T{23 - i % 24:02d}:00:00.000Z",
                    "created_by": {"id": "user-0001"}, "parent": {"type": "workspace"},
                    "properties": {"t": {"type": "title", "title": [{"plain_text": f"Page {i}"}]}}})
    return out


def _paged_routes(pages, size):
    def routes(method, url, params, body):
        path = url[len(notion.API_BASE):]
        if path == "users/me":
            return 200, NO["users_me_bot"], {}
        if path == "search":
            if body["filter"].get("in_trash"):
                return 200, NO["trash"], {}
            start = int(body.get("start_cursor") or 0)
            chunk = pages[start:start + size]
            more = start + size < len(pages)
            return 200, {"results": chunk, "has_more": more, "next_cursor": str(start + size) if more else None}, {}
        if path.endswith("/markdown"):
            return 200, {"markdown": "Text."}, {}
        return 404, {}, {}
    return routes


def test_the_first_sync_walks_the_whole_history_before_the_mark_moves(bank, monkeypatch):
    """Review should-fix: more shared pages than one sync takes are read across syncs, oldest included; the high-water
    mark moves only once the walk is done, and the Sources row says how far it got."""
    monkeypatch.setattr(notion, "MAX_PAGES_PER_SYNC", 4)
    pages = _many_pages(10)
    routes = _paged_routes(pages, 2)
    _connect(notion)
    asyncio.run(notion.sync(bank, http_fn=FakeServer(routes)))
    cursor = tier2.read_cursor("notion-api", bank)
    assert cursor["high_water"] is None and cursor["walk"]["read"] == 4
    assert "so far" in sync_state.read_sync_state(bank)["notion-api"]["words"]
    asyncio.run(notion.sync(bank, http_fn=FakeServer(routes)))
    asyncio.run(notion.sync(bank, http_fn=FakeServer(routes)))
    cursor = tier2.read_cursor("notion-api", bank)
    assert "walk" not in cursor and cursor["high_water"] == pages[0]["last_edited_time"]
    assert len([e for e in _episodes(bank) if e.startswith("notion:")]) == 10       # the oldest too


def test_more_edits_than_one_listing_walk_everything_rather_than_skip(bank, monkeypatch):
    monkeypatch.setattr(notion, "MAX_LIST_PAGES", 1)
    pages = _many_pages(6)
    _connect(notion)
    tier2.write_cursor("notion-api", bank, {"high_water": "2026-01-01T00:00:00.000Z"})
    sync_state.record_sync(bank, "notion-api", count=1)       # a bank that holds the connector's pages already
    asyncio.run(notion.sync(bank, http_fn=FakeServer(_paged_routes(pages, 2))))
    assert len([e for e in _episodes(bank) if e.startswith("notion:")]) == 6
    assert tier2.read_cursor("notion-api", bank)["high_water"] == pages[0]["last_edited_time"]


def test_a_page_the_connection_cannot_read_is_skipped_not_the_sync(bank):
    md = {"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": NO["markdown"]["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]}
    base_routes = _notion_routes(markdown=md)

    def routes(method, url, params, body):
        if "11111111-2222" in url:
            return 404, {"object": "error"}, {}
        return base_routes(method, url, params, body)

    _connect(notion)
    result = asyncio.run(notion.sync(bank, http_fn=FakeServer(routes)))
    assert result["status"] == "ok" and result["new"] == 1
    assert "could not be read" in sync_state.read_sync_state(bank)["notion-api"]["words"]


def test_a_new_bank_reads_the_whole_history_whatever_the_cursor_says(bank):
    _connect(readwise)
    tier2.write_cursor("readwise", bank, {"updated_after": "2026-10-28T00:00:00+00:00"})
    server = FakeServer(_readwise_routes())
    result = asyncio.run(readwise.sync(bank, http_fn=server))
    assert result["new"] == 5 and not any("updatedAfter" in c["params"] for c in server.calls)


def test_cicadas_own_secrets_never_reach_a_child(monkeypatch):
    for name in ("CICADA_API_TOKEN", "CICADA_TELEGRAM_BOT_TOKEN", "CICADA_TELEGRAM_WEBHOOK_SECRET",
                 readwise.TOKEN_ENV, "REDDIT_PASSWORD"):
        monkeypatch.setenv(name, "placeholder-secret")
        assert name not in connections_base.scrubbed_env() and name not in connections_base.secretless_env()
    # The helper children start from the secretless environment, never a copy of the backend's.
    root = Path(__file__).resolve().parents[1] / "services"
    for module in ("embed_worker.py", "pdf_page.py"):
        source = (root / module).read_text()
        assert "dict(os.environ)" not in source and "secretless_env()" in source, module
