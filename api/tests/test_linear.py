"""Linear as a source (ROR-115): the browser sign-in, the read-only session, and whose words each turn is.

Hermetic: a fake Linear (discovery, registration, token, and an MCP server shaped from Linear's public docs and tool
descriptions) answers every request and records it. Every id, name and text is invented. The real sign-in and the real
response shapes are NOT exercised here (see the PR).
"""

from __future__ import annotations

import asyncio
import json as jsonlib
import os
import time
from urllib.parse import parse_qs, urlparse

import pytest

from api.services import auth, markdown_parser, sleep_cycle, sync_state
from api.services.connections import secrets
from api.services.connectors import ADAPTERS, base, linear, linear_mcp, tier2

REDIRECT_BASE = "http://127.0.0.1:8000"
ME = {"id": "u-me", "name": "Me Example"}
META = {"issuer": linear_mcp.ORIGIN, "authorization_endpoint": linear_mcp.ORIGIN + "/authorize",
        "token_endpoint": linear_mcp.ORIGIN + "/token", "registration_endpoint": linear_mcp.ORIGIN + "/register",
        "revocation_endpoint": linear_mcp.ORIGIN + "/token", "code_challenge_methods_supported": ["S256"]}


class FakeAuth:
    def __init__(self):
        self.calls: list[tuple] = []
        self.refresh_error = False

    async def __call__(self, method, url, *, data=None, json=None):
        self.calls.append((method, url, data, json))
        if url == linear_mcp.METADATA_URL:
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
            return tier2.Response(200, {})
        return tier2.Response(404, None)


ISSUES = {
    "issue-1": {"id": "ABC-1", "uuid": "issue-1", "title": "Alpha plan", "description": "We should do alpha first.",
                "createdAt": "2026-10-01T10:00:00Z", "updatedAt": "2026-10-03T10:00:00Z",
                "createdBy": {"id": "u-me", "name": "Me Example"}},
    "issue-2": {"id": "ABC-2", "uuid": "issue-2", "title": "Beta from a colleague", "description": "Beta needs a review.",
                "createdAt": "2026-10-02T10:00:00Z", "updatedAt": "2026-10-04T10:00:00Z",
                "createdBy": {"id": "u-ana", "name": "Ana Example"}},
}
COMMENTS = {
    "issue-1": [
        {"id": "c1", "body": "Typed under the account.", "createdAt": "2026-10-01T11:00:00Z",
         "author": {"id": "u-me", "name": "Me Example"}, "onBehalfOf": None},
        {"id": "c2", "body": "Posted by the Linear assistant.", "createdAt": "2026-10-01T12:00:00Z",
         "author": {"id": "u-app", "name": "Helper"}, "onBehalfOf": {"id": "u-me", "name": "Me Example"}},
        {"id": "c3", "body": "A colleague agrees.", "createdAt": "2026-10-01T13:00:00Z",
         "author": {"id": "u-ana", "name": "Ana Example"}, "onBehalfOf": None},
        {"id": "c4", "body": "Done.\n\n+++ Agent notes\n\ndetails\n\n+++", "createdAt": "2026-10-01T14:00:00Z",
         "author": {"id": "u-me", "name": "Me Example"}},
        {"id": "c5", "body": "A bot says hi.", "createdAt": "2026-10-01T15:00:00Z",
         "author": {"id": "u-ci", "name": "CI", "type": "app"}},
    ],
    "issue-2": [],
}


class FakeMcp:
    """Linear's read-only MCP endpoint: records every JSON-RPC message; answers the three read tools."""

    def __init__(self, issues=None, comments=None, pages=None):
        self.messages: list[dict] = []
        self.urls: list[str] = []
        self.issues = issues or dict(ISSUES)
        self.comments = comments or COMMENTS
        self.pages = pages          # optional: list of lists of issue ids, served one per cursor

    def tool_names(self):
        return [m["params"]["name"] for m in self.messages if m["method"] == "tools/call"]

    def _issues(self, args):
        who = "creator" if "creator" in args else "assignee"
        if self.pages is not None:
            index = int(args.get("cursor") or 0)
            ids = self.pages[index] if who == "creator" else []
            more = index + 1 < len(self.pages) and who == "creator"
            return {"issues": [self.issues[i] for i in ids], "hasNextPage": more, "cursor": str(index + 1)}
        ids = ["issue-1"] if who == "creator" else ["issue-2"]
        return {"issues": [self.issues[i] for i in ids], "hasNextPage": False}

    async def __call__(self, method, url, *, headers, params=None, json=None):
        assert method == "POST" and url == linear_mcp.MCP_URL, url
        self.urls.append(url)
        self.messages.append(json)
        if json["method"] == "initialize":
            return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"], "result": {}}, {"mcp-session-id": "s-1"})
        if json["method"] == "notifications/initialized":
            return tier2.Response(202, None)
        name, args = json["params"]["name"], json["params"]["arguments"]
        result = {"user": ME} if name == "whoami" else self._issues(args) if name == "list_issues" \
            else {"comments": self.comments.get(args["issueId"], [])}
        return tier2.Response(200, {"jsonrpc": "2.0", "id": json["id"], "result": {
            "content": [{"type": "text", "text": jsonlib.dumps(result)}]}})


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    for name in linear_mcp.SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield memory
    for name in linear_mcp.SECRET_NAMES:
        os.environ.pop(name, None)


def _signed_in():
    secrets.set_secret(linear_mcp.TOKEN_ENV, "access-1")
    secrets.set_secret(linear_mcp.REFRESH_ENV, "refresh-1")
    secrets.set_secret(linear_mcp.CLIENT_ENV, "client-placeholder")
    secrets.set_secret(linear_mcp.EXPIRES_ENV, str(int(time.time()) + 3600))
    secrets.set_secret(linear_mcp.HOW_ENV, linear_mcp.HOW_APP)


def _stored(bank):
    out = {}
    for path in (bank / "episodes").glob("*.md"):
        parsed = markdown_parser.parse(path)
        out[str(parsed.frontmatter.get("source_id"))] = parsed
    return out


# --- the sign-in -----------------------------------------------------------------------------------------------------


def test_connect_asks_for_the_read_scope_on_the_read_only_resource_with_pkce(bank, monkeypatch):
    fake = FakeAuth()
    monkeypatch.setattr(linear_mcp, "TRANSPORT", fake)
    url = asyncio.run(linear.authorize_url("state-1", base_url=REDIRECT_BASE))
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert q["scope"] == "read" and q["resource"] == "https://mcp.linear.app/mcp/readonly"
    assert q["code_challenge_method"] == "S256" and q["redirect_uri"] == REDIRECT_BASE + linear_mcp.CALLBACK_PATH
    register = next(c for c in fake.calls if c[1] == META["registration_endpoint"])
    assert register[3]["token_endpoint_auth_method"] == "none"
    assert not linear.is_connected()


def test_the_callback_stores_tokens_in_secrets_and_the_route_is_open_with_a_state(bank, monkeypatch):
    monkeypatch.setattr(linear_mcp, "TRANSPORT", FakeAuth())
    asyncio.run(linear.authorize_url("state-2", base_url=REDIRECT_BASE))
    asyncio.run(linear.exchange_code("code-1", state="state-2", base_url=REDIRECT_BASE))
    assert linear.is_connected() and linear.how() == "app"
    with pytest.raises(base.ConnectorError):
        asyncio.run(linear.exchange_code("code-1", state="state-2", base_url=REDIRECT_BASE))
    assert auth._is_oauth_callback_path("/sources/connectors/linear-api/callback")
    assert base.signs_in(ADAPTERS["linear-api"])


def test_nothing_accepts_a_pasted_token(bank):
    assert linear.FIELDS == () and linear.credential_fields() == []
    assert linear.TOKEN_HELP is None


def test_an_expired_sign_in_needs_a_reconnect_and_disconnect_forgets_everything(bank, monkeypatch):
    fake = FakeAuth()
    monkeypatch.setattr(linear_mcp, "TRANSPORT", fake)
    _signed_in()
    secrets.set_secret(linear_mcp.EXPIRES_ENV, str(int(time.time()) + 10))
    fake.refresh_error = True
    with pytest.raises(tier2.Refused):
        asyncio.run(linear.prepare())
    assert linear.needs_reconnect() and not linear.is_connected()
    _signed_in()
    asyncio.run(linear.revoke())
    assert fake.calls[-1][2]["token"] == "refresh-1"
    linear.forget()
    assert not linear.is_connected() and all(not secrets.has_secret(n) for n in linear_mcp.SECRET_NAMES)


# --- the read-only session -------------------------------------------------------------------------------------------


def test_no_write_tool_can_be_called_and_nothing_is_sent_for_one(bank):
    _signed_in()
    server = FakeMcp()
    session = linear_mcp.Session(tier2.Client(linear, "access-1", server))
    for name in ("save_issue", "save_comment", "delete_comment", "create_attachment", "save_project", "save_document",
                 "create_attachment_from_upload", "share_issue", "merge_diff", "get_issue", "list_users", "anything"):
        with pytest.raises(linear_mcp.WriteToolRefused):
            asyncio.run(session.call(name, {}))
    assert server.messages == []
    assert linear_mcp.ALLOWED_TOOLS == {"whoami", "list_issues", "list_comments"}


def test_only_the_read_only_endpoint_can_be_a_target(bank):
    client = tier2.Client(linear, "access-1", FakeMcp())
    with pytest.raises(base.ConnectorError):
        asyncio.run(client.request("POST", "https://mcp.linear.app/mcp", json={}))     # the read-write endpoint
    with pytest.raises(base.ConnectorError):
        asyncio.run(client.request("POST", "https://mcp.linear.app/sse", json={}))


# --- whose words -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("author,kw,text,marker,why", [
    ({"id": "u-me", "name": "Me Example"}, {}, "plain", "assistant", "account"),                  # not provably typed
    ({"id": "u-me", "name": "Me Example"}, {"on_behalf_of": {"id": "u-me"}}, "plain", "assistant", "agent"),
    ({"id": "u-app", "name": "Helper", "isBot": True}, {}, "plain", "assistant", "agent"),
    ({"id": "u-x", "name": "Helper", "type": "app"}, {}, "plain", "assistant", "agent"),
    ({"id": "u-ana", "name": "Ana Example"}, {"bot_actor": {"name": "x"}}, "plain", "assistant", "agent"),
    ({"id": "u-ana", "name": "Ana Example"}, {"external_user": {"name": "x"}}, "plain", "assistant", "agent"),
    ({"id": "u-ana", "name": "Ana Example"}, {}, "ok\n+++ Agent notes\nx\n+++", "assistant", "agent-mark"),
    ({"id": "u-ana", "name": "Ana Example"}, {}, "🤖 Generated with [Claude Code](https://x)", "assistant", "agent-mark"),
    ({"id": "u-ana", "name": "Ana Example"}, {}, "plain", "speaker:ana-example", "other"),
    ("Ana Example", {}, "plain", "speaker:ana-example", "other"),                            # a bare name
    ("Me Example", {}, "plain", "assistant", "account"),                                      # a bare name, ours
    (None, {}, "plain", "assistant", "unknown"),
    ({"name": ""}, {}, "plain", "assistant", "unknown"),
])
def test_attribute_never_credits_the_person(author, kw, text, marker, why):
    assert linear.attribute(author, me=ME, text=text, **kw) == (marker, why)


def test_a_name_that_matches_only_when_ids_are_missing_never_becomes_the_person():
    # ids present and different: a namesake is another person, not us
    assert linear.attribute({"id": "u-zed", "name": "Me Example"}, me=ME)[1] == "other"
    # ids absent on our side: the name decides, and a miss reads as another person
    assert linear.attribute({"name": "Someone Else"}, me={"id": "", "name": "Me Example"})[1] == "other"


def test_a_sync_keeps_each_author_apart_and_marks_nothing_as_the_persons(bank):
    _signed_in()
    server = FakeMcp()
    result = asyncio.run(linear.sync(bank, http_fn=server))
    assert result["status"] == "ok" and result["seen"] == 2
    assert set(server.tool_names()) <= linear_mcp.ALLOWED_TOOLS and set(server.urls) == {linear_mcp.MCP_URL}
    stored = _stored(bank)
    assert set(stored) == {"linear:issue-1", "linear:issue-2"}
    one = stored["linear:issue-1"]
    lines = [ln for ln in one.body.splitlines() if ln.startswith(("user:", "assistant:", "speaker:"))]
    assert not any(ln.startswith("user:") for ln in lines), "no Linear text is ever the person's own words"
    assert [ln.split(":")[0] + ":" + (ln.split(":")[1] if ln.startswith("speaker:") else "") for ln in lines] == [
        "assistant:", "assistant:", "assistant:", "speaker:ana-example", "assistant:", "assistant:"]
    assert "A colleague agrees." in one.body and one.frontmatter.get("origin") == "linear-api"
    assert not one.frontmatter.get("evidence_kind") and not any(k.endswith("_by_other") for k in one.frontmatter)
    two = stored["linear:issue-2"]
    assert "speaker:ana-example: Beta needs a review." in two.body
    assert "under your account" in sync_state.read_sync_state(bank)["linear-api"]["words"]


def test_a_second_sync_writes_nothing_new_for_an_unchanged_thread(bank):
    _signed_in()
    asyncio.run(linear.sync(bank, http_fn=FakeMcp()))
    result = asyncio.run(linear.sync(bank, http_fn=FakeMcp()))
    assert result["status"] == "ok" and result["new"] == 0 and result["updated"] == 0


def test_an_edited_comment_rewrites_the_thread_in_place(bank):
    _signed_in()
    asyncio.run(linear.sync(bank, http_fn=FakeMcp()))
    changed = {k: [dict(c) for c in v] for k, v in COMMENTS.items()}
    changed["issue-1"][2]["body"] = "A colleague changed their mind."
    result = asyncio.run(linear.sync(bank, http_fn=FakeMcp(comments=changed)))
    assert result["updated"] == 1 and "changed their mind" in _stored(bank)["linear:issue-1"].body


def test_a_walk_larger_than_one_sync_resumes_from_its_cursor_without_skipping(bank, monkeypatch):
    _signed_in()
    monkeypatch.setattr(linear, "PAGE_SIZE", 2)
    monkeypatch.setattr(linear, "MAX_ISSUES_PER_SYNC", 3)
    many = {f"i{n}": {"id": f"ABC-{n}", "uuid": f"i{n}", "title": f"T{n}", "description": f"Body {n}",
                      "createdAt": "2026-10-01T10:00:00Z", "updatedAt": f"2026-10-0{n}T10:00:00Z",
                      "createdBy": {"id": "u-ana", "name": "Ana Example"}} for n in range(1, 6)}
    pages = [["i1", "i2"], ["i3", "i4"], ["i5"]]
    seen = 0
    for _ in range(5):
        result = asyncio.run(linear.sync(bank, http_fn=FakeMcp(issues=many, comments={}, pages=pages)))
        seen += result["seen"]
        if "walk" not in tier2.read_cursor("linear-api", bank):
            break
    assert {s for s in _stored(bank)} == {f"linear:i{n}" for n in range(1, 6)}
    cursor = tier2.read_cursor("linear-api", bank)
    assert cursor["high_water"] and "walk" not in cursor
    assert "Body" not in jsonlib.dumps(cursor), "the cursor holds ids and times only"


def test_a_scheduled_sync_waits_for_the_connector_gate(bank):
    _signed_in()
    server = FakeMcp()
    result = asyncio.run(tier2.run(linear, bank, allow_fetch=False, scheduled=True))
    assert result["status"] == "skipped" and server.messages == []
    assert sync_state.read_sync_state(bank)["linear-api"]["last_skip_reason"] == tier2.GATE_CLOSED
    assert not _stored(bank)


def test_a_demo_bank_takes_in_nothing(bank, monkeypatch):
    from api.services import demo_guard

    _signed_in()
    monkeypatch.setattr(demo_guard, "is_demo", lambda _p: True)
    server = FakeMcp()
    result = asyncio.run(linear.sync(bank, http_fn=server))
    assert result["status"] == "skipped" and server.messages == [] and not _stored(bank)


def test_a_sync_that_lost_its_sign_in_says_so_in_words(bank):
    _signed_in()

    async def refused(method, url, *, headers, params=None, json=None):
        return tier2.Response(401, None)

    result = asyncio.run(linear.sync(bank, http_fn=refused))
    assert result["status"] == "error" and "Connect Linear again" in result["error"]
    assert "Connect Linear again" in sync_state.read_sync_state(bank)["linear-api"]["last_error"]


def test_stage_one_is_told_whose_lines_these_are_and_a_claim_on_them_is_the_accounts():
    from api.services import entity_extractor

    episode = {"origin": "linear-api"}
    assert entity_extractor.assistant_observer(episode) == "external:linear"
    note = entity_extractor.linear_note(episode)
    assert note and "not marked as the person's own words" in note and "never the person's" in note
    assert entity_extractor.linear_note({"origin": "notion-api"}) is None
