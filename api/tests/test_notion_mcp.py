"""Connect Notion by signing in (owner 2026-11-05): the OAuth round trip, the read-only MCP session, the sync.

Hermetic: a fake Notion (discovery, registration, token, revocation, and an MCP server) answers every request and
records it. Placeholder ids only.
"""

from __future__ import annotations

import asyncio
import os
import time
from urllib.parse import parse_qs, urlparse

import pytest

from api.services import auth, markdown_parser, sleep_cycle, sync_state
from api.services.connections import secrets
from api.services.connectors import ADAPTERS, base, notion, notion_mcp, tier2

PAGE_A = "a" * 32
PAGE_B = "b" * 32
CHILD = "c" * 32
REDIRECT_BASE = "http://127.0.0.1:8000"
META = {"issuer": notion_mcp.ORIGIN, "authorization_endpoint": notion_mcp.ORIGIN + "/authorize",
        "token_endpoint": notion_mcp.ORIGIN + "/token", "registration_endpoint": notion_mcp.ORIGIN + "/register",
        "revocation_endpoint": notion_mcp.ORIGIN + "/token", "code_challenge_methods_supported": ["S256"]}


class FakeNotionAuth:
    """Discovery, registration, token and revocation."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self.refresh_error = False

    async def __call__(self, method, url, *, data=None, json=None):
        self.calls.append((method, url, data, json))
        if url == notion_mcp.METADATA_URL:
            return tier2.Response(200, META)
        if url == META["registration_endpoint"]:
            return tier2.Response(201, {"client_id": "client-placeholder"})
        if url == META["token_endpoint"] and data and data["grant_type"] == "authorization_code":
            return tier2.Response(200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600})
        if url == META["token_endpoint"] and data and data["grant_type"] == "refresh_token":
            if self.refresh_error:
                return tier2.Response(400, {"error": "invalid_grant"})
            return tier2.Response(200, {"access_token": "access-2", "expires_in": 3600})
        if url == META["token_endpoint"]:
            return tier2.Response(200, {})         # revocation
        return tier2.Response(404, None)


class FakeMcp:
    """Notion's hosted MCP server: records every JSON-RPC message; answers the read tools."""

    def __init__(self, tools=None):
        self.messages: list[dict] = []
        self.headers: list[dict] = []
        self.tools = tools or {
            "notion-list-private-pages": {"results": [{"id": PAGE_A, "type": "page", "title": "Alpha"}]},
            "notion-list-shared-pages": {"results": [{"id": PAGE_B, "type": "page", "title": "Beta"}]},
            "notion-search": {"results": [{"id": PAGE_B, "type": "page"}]},
            "notion-fetch": None,
        }

    def fetch_result(self, page_id):
        link = f"<page url=\"https://www.notion.so/{CHILD}\">Child</page>" if page_id == PAGE_A else ""
        title = {PAGE_A: "Alpha", PAGE_B: "Beta", CHILD: "Child"}[page_id]
        return {"title": title, "url": f"https://www.notion.so/{page_id}", "page_last_edited_at": "2026-10-01T10:00:00Z",
                "text": f"<properties>{{\"Status\": \"Open\"}}</properties>\n<content>\nBody of {title}. {link}\n</content>"}

    async def __call__(self, method, url, *, headers, params=None, json=None):
        assert url == notion_mcp.MCP_URL and method == "POST"
        self.messages.append(json)
        self.headers.append(dict(headers))
        if json["method"] == "initialize":
            return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"], "result": {}}, {"mcp-session-id": "s-1"})
        if json["method"] == "notifications/initialized":
            return tier2.Response(202, None)
        name, args = json["params"]["name"], json["params"]["arguments"]
        result = self.fetch_result(args["id"]) if name == "notion-fetch" else self.tools[name]
        return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"], "result": {
            "content": [{"type": "text", "text": __import__("json").dumps(result)}]}})

    def tool_names(self):
        return [m["params"]["name"] for m in self.messages if m["method"] == "tools/call"]


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    for name in notion_mcp.SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield memory
    for name in notion_mcp.SECRET_NAMES:
        os.environ.pop(name, None)


def _signed_in():
    secrets.set_secret(notion_mcp.TOKEN_ENV, "access-1")
    secrets.set_secret(notion_mcp.REFRESH_ENV, "refresh-1")
    secrets.set_secret(notion_mcp.CLIENT_ENV, "client-placeholder")
    secrets.set_secret(notion_mcp.EXPIRES_ENV, str(int(time.time()) + 3600))
    secrets.set_secret(notion_mcp.HOW_ENV, notion_mcp.HOW_APP)


# --- the sign-in -----------------------------------------------------------------------------------------------------


def test_connect_registers_a_public_client_and_asks_with_pkce(bank, monkeypatch):
    fake = FakeNotionAuth()
    monkeypatch.setattr(notion_mcp, "TRANSPORT", fake)
    url = asyncio.run(notion.authorize_url("state-1", base_url=REDIRECT_BASE))
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith(META["authorization_endpoint"] + "?")
    assert q["code_challenge_method"] == "S256" and q["client_id"] == "client-placeholder" and q["state"] == "state-1"
    assert q["redirect_uri"] == REDIRECT_BASE + "/sources/connectors/notion-api/callback"
    register = next(c for c in fake.calls if c[1] == META["registration_endpoint"])
    assert register[3]["token_endpoint_auth_method"] == "none" and register[3]["redirect_uris"] == [q["redirect_uri"]]
    assert not notion.is_connected()


def test_the_callback_exchanges_the_code_and_keeps_the_tokens_in_secrets_only(bank, monkeypatch, tmp_path):
    fake = FakeNotionAuth()
    monkeypatch.setattr(notion_mcp, "TRANSPORT", fake)
    asyncio.run(notion.authorize_url("state-2", base_url=REDIRECT_BASE))
    asyncio.run(notion.exchange_code("code-1", state="state-2", base_url=REDIRECT_BASE))
    exchange = next(c for c in fake.calls if c[2] and c[2].get("grant_type") == "authorization_code")
    assert exchange[2]["code_verifier"] and exchange[2]["client_id"] == "client-placeholder"
    assert notion.is_connected() and notion.how() == "app"
    with pytest.raises(base.ConnectorError):          # a state is single use
        asyncio.run(notion.exchange_code("code-1", state="state-2", base_url=REDIRECT_BASE))
    assert "access-1" not in " ".join(p.read_text() for p in (tmp_path / "memory").rglob("*") if p.is_file())


def test_the_callback_route_is_open_for_notion_but_a_state_is_still_required():
    assert auth._is_oauth_callback_path("/sources/connectors/notion-api/callback")
    assert base.signs_in(ADAPTERS["notion-api"])


def test_an_untrusted_endpoint_is_refused(bank, monkeypatch):
    class Evil(FakeNotionAuth):
        async def __call__(self, method, url, *, data=None, json=None):
            if url == notion_mcp.METADATA_URL:
                return tier2.Response(200, {**META, "token_endpoint": "https://evil.example/token"})
            return await super().__call__(method, url, data=data, json=json)

    monkeypatch.setattr(notion_mcp, "TRANSPORT", Evil())
    with pytest.raises(base.ConnectorError):
        asyncio.run(notion.authorize_url("s", base_url=REDIRECT_BASE))


def test_a_lapsing_token_is_renewed_and_a_refused_refresh_marks_the_sign_in_lapsed(bank, monkeypatch):
    fake = FakeNotionAuth()
    monkeypatch.setattr(notion_mcp, "TRANSPORT", fake)
    _signed_in()
    secrets.set_secret(notion_mcp.EXPIRES_ENV, str(int(time.time()) + 10))
    asyncio.run(notion.prepare())
    assert secrets.load_secrets()[notion_mcp.TOKEN_ENV] == "access-2"
    assert secrets.load_secrets()[notion_mcp.REFRESH_ENV] == "refresh-1"
    secrets.set_secret(notion_mcp.EXPIRES_ENV, str(int(time.time()) + 10))
    fake.refresh_error = True
    with pytest.raises(tier2.Refused):
        asyncio.run(notion.prepare())
    assert notion.needs_reconnect()
    assert not notion.is_connected(), "the page offers Sign in again, and nothing syncs on the old token"


def test_disconnect_revokes_then_forgets_everything(bank, monkeypatch):
    fake = FakeNotionAuth()
    monkeypatch.setattr(notion_mcp, "TRANSPORT", fake)
    _signed_in()
    asyncio.run(notion.revoke())
    assert fake.calls[-1][2]["token"] == "refresh-1"
    notion.forget()
    assert not notion.is_connected() and notion.how() is None
    assert all(not secrets.has_secret(n) for n in notion_mcp.SECRET_NAMES)


# --- the read-only session -------------------------------------------------------------------------------------------


def test_no_write_tool_can_be_called_and_nothing_is_sent_for_one(bank):
    _signed_in()
    server = FakeMcp()
    session = notion_mcp.Session(tier2.Client(notion, "access-1", server))
    for name in ("notion-create-pages", "notion-update-page", "notion-move-pages", "notion-duplicate-page",
                 "notion-create-comment", "notion-create-database", "notion-update-data-source", "anything"):
        with pytest.raises(notion_mcp.WriteToolRefused):
            asyncio.run(session.call(name, {}))
    assert server.messages == []
    assert notion_mcp.ALLOWED_TOOLS == {"notion-search", "notion-fetch", "notion-list-private-pages",
                                        "notion-list-shared-pages",
                                        "notion-query-data-sources"}


def test_a_sync_reads_through_the_allow_list_only_and_stages_one_episode_per_page(bank):
    _signed_in()
    server = FakeMcp()
    result = asyncio.run(notion.sync(bank, http_fn=server))
    assert result["status"] == "ok" and result["seen"] == 3          # Alpha, Beta and Alpha's linked child
    assert set(server.tool_names()) <= notion_mcp.ALLOWED_TOOLS
    assert {m["method"] for m in server.messages} == {"initialize", "notifications/initialized", "tools/call"}
    assert server.headers[-1]["Mcp-Session-Id"] == "s-1" and server.headers[0]["Authorization"] == "Bearer access-1"
    stored = {}
    for path in (bank / "episodes").glob("*.md"):
        fm = markdown_parser.parse(path)
        stored[str(fm.frontmatter.get("source_id"))] = fm
    assert set(stored) == {f"notion:{PAGE_A}", f"notion:{PAGE_B}", f"notion:{CHILD}"}
    # Only a page the person created (the search for "me") is their own words; every other is kept as another's.
    assert stored[f"notion:{PAGE_B}"].frontmatter.get("evidence_kind") == "user"
    assert stored[f"notion:{PAGE_A}"].frontmatter.get("evidence_kind") == "assistant"
    assert "**Status:** Open" in stored[f"notion:{PAGE_A}"].body and "Body of Alpha" in stored[f"notion:{PAGE_A}"].body


def test_a_second_sync_reads_no_page_again_that_has_not_changed(bank):
    _signed_in()
    first = FakeMcp()
    asyncio.run(notion.sync(bank, http_fn=first))
    again = FakeMcp()
    for tool in ("notion-list-private-pages", "notion-list-shared-pages"):
        again.tools[tool] = {"results": [{**r, "last_edited_time": "2026-10-01T10:00:00Z"}
                                         for r in first.tools[tool]["results"]]}
    again.tools["notion-search"] = {"results": []}
    result = asyncio.run(notion.sync(bank, http_fn=again))
    assert result["status"] == "ok" and again.tool_names().count("notion-fetch") == 0


def test_a_token_pasted_before_still_reads_through_the_rest_api(bank):
    secrets.set_secret(notion_mcp.TOKEN_ENV, "pasted")
    assert notion.how() == "token" and not notion_mcp.is_app_token()
    assert notion.auth_headers("pasted")["Notion-Version"] == notion.NOTION_VERSION
    assert tier2.Client(notion, "pasted", lambda *a, **k: None).adapter.API_BASE.startswith("https://api.notion.com")


def test_a_sync_that_lost_its_sign_in_says_so_in_words(bank):
    _signed_in()

    async def refused(method, url, *, headers, params=None, json=None):
        return tier2.Response(401, None)

    result = asyncio.run(notion.sync(bank, http_fn=refused))
    assert result["status"] == "error" and "Connect Notion again" in result["error"]
    assert "Connect Notion again" in sync_state.read_sync_state(bank)["notion-api"]["last_error"]
