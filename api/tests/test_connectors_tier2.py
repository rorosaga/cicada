"""Ruling 47 tier 2: the shared framework (`connectors/tier2.py`) and Notion (Readwise removed 2026-11-03).

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
from api.services.connectors import ADAPTERS, notion, tier2

FIX = Path(__file__).parent / "fixtures" / "connectors"
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


# Readwise was removed by owner direction (2026-11-03: "yeah remove readwise"); the framework's rails below run on
# Notion, the tier-2 source that remains.


def test_the_token_never_reaches_the_bank_and_the_cursor_lives_outside_it(bank, tmp_path):
    _connect(notion)
    asyncio.run(notion.sync(bank, http_fn=FakeServer(_notion_routes())))
    for path in bank.rglob("*"):
        if path.is_file():
            assert TOKEN not in path.read_text(encoding="utf-8", errors="replace"), path
    cursors = list((tmp_path / "home" / "connectors").glob("notion-api-*.json"))
    assert len(cursors) == 1 and (cursors[0].stat().st_mode & 0o777) == 0o600


def test_a_429_waits_its_retry_after_once(bank, monkeypatch):
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(tier2, "wait", fake_sleep)
    answers = iter([(429, None, {"retry-after": "7"})])
    base_routes = _notion_routes()

    def routes(*a):
        return next(answers, None) or base_routes(*a)

    _connect(notion)
    result = asyncio.run(notion.sync(bank, http_fn=FakeServer(routes)))
    assert result["status"] == "ok" and waits == [7.0]


def test_a_second_429_stops_in_words_without_advancing(bank, monkeypatch):
    async def fake_sleep(s):
        return None

    monkeypatch.setattr(tier2, "wait", fake_sleep)
    _connect(notion)
    result = asyncio.run(notion.sync(bank, http_fn=FakeServer(lambda *a: (429, None, {"retry-after": "1"}))))
    assert result["status"] == "error" and "slow down" in result["error"]
    assert not tier2._cursor_path("notion-api", bank).exists()


# --- the framework's rails -----------------------------------------------------------------------------------------


def test_a_scheduled_sync_never_starts_while_sleep_holds_the_pages(bank, monkeypatch):
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    _connect(notion)
    server = FakeServer(_notion_routes())
    result = asyncio.run(notion.sync(bank, http_fn=server, scheduled=True))
    assert result["status"] == "skipped" and server.calls == []
    assert sync_state.read_sync_state(bank)["notion-api"]["last_skip_reason"] == tier2.WAITED_FOR_SLEEP


def test_a_sync_whose_fetch_overlapped_sleep_writes_nothing_and_keeps_its_cursor(bank, monkeypatch):
    """The person's Refresh fetches (their click), then Sleep opens its window before the staging: the admitted
    transaction is refused, nothing is written, and the cursor stays where it was."""
    _connect(notion)
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: state["writing"])
    base_routes = _notion_routes()

    def routes(*a):
        state["writing"] = True        # Sleep starts while the fetch is in flight
        return base_routes(*a)

    result = asyncio.run(notion.sync(bank, http_fn=FakeServer(routes)))
    assert result["status"] == "skipped" and result["reason"] == tier2.WAITED_FOR_SLEEP
    assert not list((bank / "episodes").glob("*.md"))
    assert not tier2._cursor_path("notion-api", bank).exists()


def test_a_scheduled_sync_is_gated_and_a_person_sync_is_not(bank, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    _connect(notion)
    monkeypatch.setattr(tier2, "http_transport", FakeServer(_notion_routes()))
    result = asyncio.run(tier2.run(notion, bank, scheduled=True))
    assert result["status"] == "skipped" and result["reason"] == "network disabled"
    assert sync_state.read_sync_state(bank)["notion-api"]["last_skip_reason"] == tier2.GATE_CLOSED
    server = FakeServer(_notion_routes())
    assert asyncio.run(notion.sync(bank, http_fn=server, allow_fetch=True))["status"] == "ok"


def test_off_by_default_and_a_demo_bank_takes_nothing(bank, monkeypatch):
    server = FakeServer(_notion_routes())
    assert asyncio.run(notion.sync(bank, http_fn=server))["reason"] == "not connected"
    assert server.calls == []
    _connect(notion)
    from api.services import demo_guard

    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert asyncio.run(notion.sync(bank, http_fn=server))["status"] == "skipped" and server.calls == []


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
    client = tier2.Client(notion, TOKEN, FakeServer(lambda *a: (200, {}, {})))
    with pytest.raises(Exception) as exc:
        asyncio.run(client.get("https://elsewhere.example/v1/users/me"))
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


def bank_path(api) -> Path:
    from api import config

    return config.get_settings().memory_path


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
            return {"label": "Notion", "loginMode": "credentials", "reads": "r", "tokenHelp": "h",
                    "fields": [{"name": notion.TOKEN_ENV, "label": "Token", "secret": True}]}
        sent.update(kw.get("body") or {})
        return {"label": "Notion", "connected": True}

    monkeypatch.setattr(cli_app, "call", fake_call)
    monkeypatch.setattr(cli_app, "require_person", lambda what: None)
    monkeypatch.setattr(cli_app, "read_token", lambda label: TOKEN)
    from types import SimpleNamespace

    out = cli_app.cmd_connector_connect(SimpleNamespace(probe={}), SimpleNamespace(connector="notion-api"))
    assert sent == {"fields": {notion.TOKEN_ENV: TOKEN}} and TOKEN not in out.text


# --- Notion --------------------------------------------------------------------------------------------------------


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


def test_a_first_notion_sync_that_finds_nothing_shared_says_how_to_share_a_page(bank):
    """Review of #587: a first connection reads 0 pages until one is shared with it — said in words, never silence."""
    assert "Connections" in notion.NOTHING_SHARED_WORDS      # a token pasted before the sign-in existed
    _connect(notion)
    result = asyncio.run(notion.sync(bank, http_fn=FakeServer(_notion_routes(search=NO["trash"]))))
    assert result["status"] == "ok" and result["new"] == 0, result
    words = sync_state.read_sync_state(bank)["notion-api"]["words"]
    assert words == notion.NOTHING_SHARED_WORDS and "Connections" in words      # no "which pages you wrote" either
    # Shared pages: the line is gone.
    asyncio.run(notion.sync(bank, http_fn=FakeServer(_notion_routes())))
    assert notion.NOTHING_SHARED_WORDS not in (sync_state.read_sync_state(bank)["notion-api"].get("words") or "")


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


def test_cicadas_own_secrets_never_reach_a_child(monkeypatch):
    for name in ("CICADA_API_TOKEN", "CICADA_TELEGRAM_BOT_TOKEN", "CICADA_TELEGRAM_WEBHOOK_SECRET",
                 notion.TOKEN_ENV, "REDDIT_PASSWORD"):
        monkeypatch.setenv(name, "placeholder-secret")
        assert name not in connections_base.scrubbed_env() and name not in connections_base.secretless_env()
    # The helper children start from the secretless environment, never a copy of the backend's.
    root = Path(__file__).resolve().parents[1] / "services"
    for module in ("embed_worker.py", "pdf_page.py"):
        source = (root / module).read_text()
        assert "dict(os.environ)" not in source and "secretless_env()" in source, module


def test_a_403_with_the_limit_signals_is_a_rate_limit_and_any_other_403_is_a_refused_account():
    from types import SimpleNamespace

    from api.services.connectors import github, tier2

    adapter = SimpleNamespace(LABEL="GitHub", REFUSED_WORDS=github.REFUSED_WORDS, RATE_WORDS=github.RATE_WORDS)
    with pytest.raises(tier2.Refused) as limited:
        tier2._answer(adapter, tier2.Response(403, headers={"x-ratelimit-remaining": "0"}))
    assert limited.value.kind == "rate"
    with pytest.raises(tier2.Refused) as refused:
        tier2._answer(adapter, tier2.Response(403))
    assert refused.value.kind == "sign-in"
