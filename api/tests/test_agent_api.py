"""G213 — the HTTP agent API, and G212 — pairing a device with a one-time code.

The backend door (`/v1/*` on the backend's own port) and the listener door (the same operations on the G135 listener,
owner 2026-10-22) run the same remote tool bodies through `agent_api.call`. Synthetic bank and placeholder names only;
nothing reaches the network.
"""
from __future__ import annotations

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api.remote import agent_api, catalog, store as remote_store
from api.services import device_tokens


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A backend with auth ON, one synthetic bank, its own CICADA_HOME, Sleep idle."""
    from api import config
    from api.main import app
    from api.remote import runtime as remote_runtime
    from api.routers import agent_api as agent_router
    from api.remote.app import Limits

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(remote_runtime, "_SHARED", None)
    monkeypatch.setattr(agent_router, "LIMITS", Limits())
    from api.remote import reach

    # G212: no test ever runs the real tailscale CLI (its macOS binary is the GUI app's).
    monkeypatch.setattr(reach, "tailnet_backend", lambda port, **kw: reach.TailnetBackend("missing", None))
    config.get_settings.cache_clear()
    from api.services.auth import get_token

    master = get_token()
    with TestClient(app) as client:
        yield client, master, memory
    config.get_settings.cache_clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _agent(client, master, name="Texting Agent", scopes=("search", "read", "record")):
    made = client.post("/agent-api/tokens", json={"name": name, "scopes": list(scopes), "expiresInDays": 30,
                                                  "baseUrl": "https://cicada.example.ts.net"},
                       headers=_auth(master))
    assert made.status_code == 201, made.text
    return made.json()


# --- tokens ----------------------------------------------------------------------------------------------------------

def test_an_agent_token_is_made_by_the_person_shown_once_and_handed_off_in_one_paragraph(server):
    client, master, _ = server
    made = _agent(client, master)
    token = made["token"]
    assert catalog.API_TOKEN_RE.match(token)
    assert made["agent"]["author"] == "api:texting-agent" and made["agent"]["state"] == "active"
    prompt = made["prompt"]
    assert token in prompt and "https://cicada.example.ts.net/v1/llms.txt" in prompt and "\n" not in prompt
    listed = client.get("/agent-api/tokens", headers=_auth(master)).json()["tokens"]
    assert [t["id"] for t in listed] == [made["agent"]["id"]] and token not in json.dumps(listed)
    # Never listed as a G135 connector (it opens /v1 only).
    assert client.get("/remote/connectors", headers=_auth(master)).json() == []


def test_a_device_never_mints_an_agent_token(server):
    client, master, _ = server
    device = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()["token"]
    assert client.post("/agent-api/tokens", json={"name": "x"}, headers=_auth(device)).status_code == 403
    assert client.get("/agent-api/tokens", headers=_auth(device)).status_code == 200


def test_only_a_connector_token_opens_v1(server):
    client, master, _ = server
    device = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()["token"]
    for headers in ({}, _auth(master), _auth(device), _auth("cic_api_abcdefgh_" + "b" * 43)):
        answer = client.post("/v1/recall", json={"query": "alpha"}, headers=headers)
        assert answer.status_code == 401 and answer.json()["code"] == "invalid_token"
        assert answer.json()["isError"] is True


def test_a_revoked_or_expired_agent_token_is_refused_at_once(server):
    client, master, _ = server
    made = _agent(client, master)
    assert client.post("/v1/recall", json={"query": "alpha"}, headers=_auth(made["token"])).status_code == 200
    assert client.delete(f"/agent-api/tokens/{made['agent']['id']}", headers=_auth(master)).status_code == 200
    answer = client.post("/v1/recall", json={"query": "alpha"}, headers=_auth(made["token"]))
    assert answer.status_code == 401 and "revoked" in answer.json()["text"]


def test_an_agent_token_never_opens_mcp_and_a_link_secret_of_its_row_is_no_key(tmp_path):
    db = remote_store.ConnectorStore(tmp_path / "c.db")
    connector, token = db.create(app="other", label="Agent", scopes=["search"], expires_in_days=7, auth="api")
    assert db.verify_agent(token)[1] == "ok"
    assert db.verify(token) == (None, "malformed")
    secret = token.split("_", 3)[3]
    assert db.verify(f"cic_rc_{connector.id}_{secret}") == (None, "unknown")
    with pytest.raises(ValueError):
        db.rotate(connector.id)
    with pytest.raises(ValueError):
        db.create(app="other", label="  ", scopes=["search"], expires_in_days=7, auth="api")


def test_a_link_connector_secret_also_opens_v1(server):
    client, _, _ = server
    _, token = remote_store.ConnectorStore().create(app="grok", label="Grok", scopes=["search"], expires_in_days=7)
    answer = client.post("/v1/recall", json={"query": "alpha"}, headers=_auth(token))
    assert answer.status_code == 200


# --- operations ------------------------------------------------------------------------------------------------------

def test_recall_answers_the_envelope_with_a_fenced_reply(server):
    client, master, _ = server
    token = _agent(client, master)["token"]
    answer = client.post("/v1/recall", json={"query": "alpha project"}, headers=_auth(token))
    assert answer.status_code == 200
    body = answer.json()
    assert set(body) == {"text", "isError", "code", "data"} and body["isError"] is False
    assert "<<<cicada-reference" in body["text"]


def test_a_save_carries_the_agent_s_provenance_and_a_claim_is_never_the_person_s_words(server):
    client, master, memory = server
    made = _agent(client, master)
    token, cid = made["token"], made["agent"]["id"]
    saved = client.post("/v1/save_note", json={"content": "Decided to ship alpha on Friday.", "title": "Ship"},
                        headers=_auth(token))
    assert saved.status_code == 200 and saved.json()["isError"] is False, saved.text
    from api.services import markdown_parser

    episodes = [(markdown_parser.parse(p).frontmatter, None) for p in sorted((memory / "episodes").glob("ep_*.md"))]
    fm = next(fm for fm, _ in episodes if fm.get("connector") == cid)
    assert fm["harness"] == catalog.API_HARNESS
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True).stdout
    assert "Cicada-Author: api:texting-agent" in log
    # The remote schema's observer is agent | external: the person's own words are refused, by field.
    owner = client.post("/v1/write_claim", json={"subject": "alpha-project", "predicate": "uses", "object": "x",
                                                 "observer": "owner"}, headers=_auth(token))
    assert owner.status_code == 400 and owner.json()["code"] == "invalid_arguments" and "observer" in owner.json()["text"]
    claim = client.post("/v1/write_claim", json={"subject": "alpha-project", "predicate": "uses",
                                                 "object": "sqlite-vec"}, headers=_auth(token))
    assert claim.status_code == 200 and claim.json()["isError"] is False, claim.text
    page = (memory / "entities" / "alpha-project.md").read_text()
    assert f"remote:{cid}" in page


def test_scopes_bound_the_operations(server):
    client, master, _ = server
    token = _agent(client, master, scopes=("search",))["token"]
    denied = client.post("/v1/save_note", json={"content": "x"}, headers=_auth(token))
    assert denied.status_code == 403 and denied.json()["code"] == "denied"
    me = client.get("/v1/me", headers=_auth(token)).json()
    assert me["operations"] == ["recall", "hub"] and me["scopes"] == ["search"] and me["kind"] == "agent"


def test_refusals_before_a_tool_runs(server):
    client, master, _ = server
    token = _agent(client, master)["token"]
    assert client.post("/v1/nope", json={}, headers=_auth(token)).json()["code"] == "unknown_operation"
    bad = client.post("/v1/recall", content=b"[1]", headers=_auth(token))
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_arguments"
    browser = client.post("/v1/recall", json={"query": "x"}, headers={**_auth(token), "Origin": "https://evil.example"})
    assert browser.status_code == 403 and browser.json()["code"] == "origin"


def test_a_write_while_sleep_holds_the_pages_is_409_with_retry_after(server, monkeypatch):
    client, master, _ = server
    from api.remote import runtime as remote_runtime

    token = _agent(client, master)["token"]
    monkeypatch.setattr(remote_runtime, "_sleep_running", lambda: True)
    monkeypatch.setattr(remote_runtime, "_SHARED", None)
    answer = client.post("/v1/save_note", json={"content": "x"}, headers=_auth(token))
    assert answer.status_code == 409 and answer.json()["code"] == "sleep_writing"
    assert answer.headers["Retry-After"] == str(agent_api.BUSY_RETRY_S)


def test_the_documents_are_open_and_describe_every_operation(server):
    client, _, _ = server
    text = client.get("/llms.txt").text
    assert client.get("/v1/llms.txt").text == text
    for op in agent_api.OPS:
        assert f"/v1/{op}" in text
    doc = client.get("/v1/openapi.json").json()
    assert doc["openapi"] == "3.1.0" and set(doc["paths"]) == {f"/v1/{op}" for op in agent_api.OPS} | {"/v1/me"}
    blob = json.dumps(doc)
    assert "conversation" not in json.dumps([p["post"]["requestBody"] for k, p in doc["paths"].items()
                                             if "post" in p and k != "/v1/capture_turns"])
    assert "cicada_save_episode" not in blob   # tool names are spelled as this door's operations


def test_every_operation_is_a_remote_tool_with_a_scope():
    from api.remote.tools import REMOTE_TOOLS

    for op, tool in agent_api.OPS.items():
        assert tool in REMOTE_TOOLS and catalog.TOOL_SCOPE[tool], op


def test_an_api_author_is_a_harness_contributor():
    from api.services import git_service

    assert git_service._classify_author_kind("api:texting-agent") == git_service.HARNESS_KIND


# --- the listener door (owner 2026-10-22) ------------------------------------------------------------------------------

def test_the_listener_serves_v1_with_the_same_envelope_and_never_mcp_to_an_agent_token(tmp_path, monkeypatch):
    from api import config
    from api.remote.app import build_app
    from api.remote.runtime import RemoteRuntime

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        db = remote_store.ConnectorStore()
        _, token = db.create(app="other", label="Agent", scopes=["search", "read"], expires_in_days=7, auth="api")
        app = build_app(db, runtime=RemoteRuntime(post=lambda p, d: {}, sleep_running=lambda: False))
        with TestClient(app, base_url="https://cicada.example.ts.net") as client:
            ok = client.post("/v1/recall", json={"query": "alpha"}, headers=_auth(token))
            assert ok.status_code == 200 and set(ok.json()) == {"text", "isError", "code", "data"}
            assert client.get("/v1/me", headers=_auth(token)).json()["operations"] == [
                "recall", "page", "timeline", "project", "inbox", "hub", "perspective", "video_queue", "read_queue",
                "backlog_list"]
            assert client.post("/v1/save_note", json={"content": "x"}, headers=_auth(token)).status_code == 403
            assert "/v1/recall" in client.get("/v1/llms.txt").text
            mcp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                              headers={**_auth(token), "Accept": "application/json, text/event-stream"})
            assert mcp.status_code == 401
            assert client.post("/v1/recall", json={}, headers=_auth("nope")).status_code == 401
            assert client.post("/v1/recall", json={"query": "x"},
                               headers={**_auth(token), "Origin": "https://evil.example"}).status_code == 403
    finally:
        config.get_settings.cache_clear()


# --- G212: pairing ---------------------------------------------------------------------------------------------------

def test_a_pairing_code_is_shown_once_spent_once_and_mints_a_device(server):
    client, master, _ = server
    made = client.post("/devices/pairing", json={"url": "https://cicada.example.ts.net", "kind": "full"},
                       headers=_auth(master))
    assert made.status_code == 201
    code, qr = made.json()["code"], made.json()["qr"]
    assert qr == {"v": 1, "url": "https://cicada.example.ts.net", "code": code} and len(code) == 9
    pairing_id = made.json()["pairing"]["id"]
    assert client.get(f"/devices/pairing/{pairing_id}", headers=_auth(master)).json()["pairing"]["state"] == "waiting"
    # A phone types it however it likes: lower case, no dash.
    paired = client.post("/pair", json={"code": code.lower().replace("-", ""), "name": "Example Phone"})
    assert paired.status_code == 201
    token, device = paired.json()["token"], paired.json()["device"]
    assert device_tokens.TOKEN_RE.match(token) and device["name"] == "Example Phone"
    assert client.get("/devices", headers=_auth(token)).status_code == 200
    seen = client.get(f"/devices/pairing/{pairing_id}", headers=_auth(master)).json()
    assert seen["pairing"]["state"] == "paired" and seen["device"]["id"] == device["id"]
    again = client.post("/pair", json={"code": code, "name": "Another"})
    assert again.status_code == 404


def test_a_code_is_hashed_at_rest_and_expires(tmp_path):
    from datetime import datetime, timedelta, timezone

    db = device_tokens.DeviceStore(tmp_path / "devices.db")
    then = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)
    pairing, code = db.create_pairing(now=then)
    raw = b"".join(p.read_bytes() for p in tmp_path.glob("devices.db*"))
    assert code.replace("-", "").encode() not in raw
    with pytest.raises(KeyError):
        db.redeem(code, "Phone", now=then + timedelta(seconds=device_tokens.PAIRING_TTL_S + 1))
    assert db.pairing(pairing.id, now=then + timedelta(hours=1)).state == "expired"


def test_a_cancelled_code_pairs_nothing_and_a_device_cannot_make_one(server):
    client, master, _ = server
    made = client.post("/devices/pairing", json={}, headers=_auth(master)).json()
    assert made["qr"]["url"] is None
    assert client.delete(f"/devices/pairing/{made['pairing']['id']}", headers=_auth(master)).status_code == 200
    assert client.post("/pair", json={"code": made["code"], "name": "Phone"}).status_code == 404
    device = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()["token"]
    assert client.post("/devices/pairing", json={}, headers=_auth(device)).status_code == 403
    assert client.post("/devices/pairing", json={"url": "http://cicada.example.ts.net"},
                       headers=_auth(master)).status_code == 400


def test_at_most_five_codes_wait(tmp_path):
    db = device_tokens.DeviceStore(tmp_path / "devices.db")
    for _ in range(device_tokens.MAX_OPEN_PAIRINGS):
        db.create_pairing()
    with pytest.raises(ValueError):
        db.create_pairing()


# --- ruling 38: `/v1` generated from the remote tool table ------------------------------------------------------------

#: The eleven operations #424 shipped, each with its tool — frozen byte for byte (Hyrum). Never edit this literal.
SHIPPED = {"recall": "cicada_recall", "ask": "cicada_ask", "page": "cicada_recall_detail",
           "timeline": "cicada_timeline", "project": "cicada_project", "save_note": "cicada_save_episode",
           "save_url": "cicada_save_url", "write_claim": "cicada_write_claim",
           "retract_claim": "cicada_retract_claim", "inbox": "cicada_check_nudges",
           "resolve_inbox": "cicada_resolve_inbox"}


def test_v1_is_the_remote_tool_table_minus_its_exclusions():
    """A tool added to `REMOTE_TOOLS` and not to `/v1` (or the reverse) fails here, unless `EXCLUDED` says why."""
    from api.remote.tools import REMOTE_TOOLS

    assert set(agent_api.OPS.values()) == set(REMOTE_TOOLS) - set(agent_api.EXCLUDED)
    assert len(agent_api.OPS) == len(set(agent_api.OPS.values())), "one operation per tool"
    assert set(agent_api.EXCLUDED) <= set(REMOTE_TOOLS) and all(agent_api.EXCLUDED.values())
    assert set(agent_api.EXCLUDED) == {"cicada_handshake"}
    # Local-only tools stay off `/v1` as they are off remote: the workspace continuation, page edits, the saved lists.
    assert not set(agent_api.OPS.values()) & catalog.NEVER_REMOTE
    assert "cicada_continue" not in agent_api.OPS.values()


def test_the_eleven_shipped_operations_are_frozen_and_listed_first():
    assert {op: agent_api.OPS[op] for op in SHIPPED} == SHIPPED
    assert list(agent_api.OPS)[:len(SHIPPED)] == list(SHIPPED) == list(agent_api.STABLE)


def test_new_operations_take_the_cli_command_spelled_with_underscores():
    from api.services import cli_map

    rows = cli_map.by_tool()
    new = {op: tool for op, tool in agent_api.OPS.items() if op not in SHIPPED}
    for op, tool in new.items():
        expected = agent_api.REMOTE_ONLY_OPS.get(tool) or "_".join(rows[tool].command).replace("-", "_")
        assert op == expected, (op, tool)
        assert rows.get(tool) is None or rows[tool].api_op is None, "only a frozen name overrides the command"
    # Every override in the table is one of the eleven, and spells exactly its shipped name.
    overrides = {r.api_op: r.tool for r in cli_map.rows() if r.api_op}
    assert overrides.items() <= SHIPPED.items()
    assert set(new) == {"hub", "perspective", "capture_turns", "source_add", "source_change", "video_record",
                        "video_queue", "video_claim", "read_queue", "read_record", "inbox_record_check",
                        "source_list", "progress_add", "backlog_list", "backlog_add", "backlog_note",
                        # Ruling 45 (2026-10-27): named by their `cli_map` rows.
                        "projects_create", "projects_link", "projects_influence",
                        # Decision 10 (2026-10-28): pages tied by hand.
                        "projects_tie_page",
                        # G227 follow-up (coordinator 2026-10-29): a remote merge or split is a proposal.
                        "page_merge", "page_split", "page_undo"}


def test_each_operation_needs_exactly_its_tool_s_scope():
    import itertools

    for op, tool in agent_api.OPS.items():
        assert agent_api.scope_of(op) == catalog.TOOL_SCOPE[tool] and catalog.TOOL_SCOPE[tool], op
    assert agent_api.scope_of("capture_turns") == "record" and agent_api.scope_of("source_list") == "sources"
    for n in range(len(catalog.SCOPES) + 1):
        for scopes in itertools.combinations(catalog.SCOPES, n):
            connector = catalog.Connector(id="abcdefgh", label="A", app="other", scopes=frozenset(scopes),
                                          created_at="2026-10-23T00:00:00+00:00", auth="api")
            allowed = catalog.tool_names_for(scopes)
            assert agent_api.me(connector)["operations"] == [o for o, t in agent_api.OPS.items() if t in allowed]


def test_the_openapi_document_is_generated_and_valid():
    import jsonschema

    doc = agent_api.openapi("https://cicada.example.ts.net")
    json.loads(json.dumps(doc))   # plain JSON
    assert doc["openapi"] == "3.1.0" and doc["info"]["title"] and doc["info"]["version"]
    assert doc["servers"] == [{"url": "https://cicada.example.ts.net"}]
    assert set(doc["paths"]) == {f"/v1/{op}" for op in agent_api.OPS} | {"/v1/me"}
    ids = [method["operationId"] for item in doc["paths"].values() for method in item.values()]
    assert len(ids) == len(set(ids)) == len(agent_api.OPS) + 1
    schemes = doc["components"]["securitySchemes"]
    assert all(name in schemes for req in doc["security"] for name in req)
    validator = jsonschema.Draft202012Validator   # OpenAPI 3.1's schema dialect
    for schema in doc["components"]["schemas"].values():
        validator.check_schema(schema)
    for path, item in doc["paths"].items():
        for verb, method in item.items():
            assert verb in ("get", "post") and method["responses"], path
            if verb == "post":
                body = method["requestBody"]["content"]["application/json"]["schema"]
                validator.check_schema(body)
                assert body["type"] == "object"
                # Only a relayed turn names its conversation, minted by this door ("new"), never a handshake's.
                assert ("conversation" in body.get("properties", {})) == (path == "/v1/capture_turns"), path
                assert set(body.get("required", ())) <= set(body.get("properties", {})), path
            for response in method["responses"].values():
                for content in response.get("content", {}).values():
                    ref = content["schema"]["$ref"]
                    assert ref.startswith("#/components/schemas/")
                    assert ref.rsplit("/", 1)[1] in doc["components"]["schemas"]
    # The door's own words: no MCP tool name and no handshake (this door has none).
    blob = json.dumps(doc)
    assert "cicada_" not in blob and "handshake" not in blob


def test_the_new_operations_run_the_same_bodies_over_http(server):
    client, master, _ = server
    token = _agent(client, master, scopes=("search", "read", "record"))["token"]
    hub = client.post("/v1/hub", json={"hub": "alpha"}, headers=_auth(token))
    assert hub.status_code == 200 and set(hub.json()) == {"text", "isError", "code", "data"}
    filed = client.post("/v1/backlog_add", json={"project": "alpha-project", "title": "Try the second index",
                                                 "description": "Recall misses prefixes; a second index may help."},
                        headers=_auth(token))
    assert filed.status_code == 200 and filed.json()["isError"] is False, filed.text
    listed = client.post("/v1/backlog_list", json={"project": "alpha-project"}, headers=_auth(token))
    assert listed.status_code == 200 and listed.json()["isError"] is False
    assert "second index" in listed.json()["text"] and "<<<cicada-reference" in listed.json()["text"]
    # The G199 check is the remote schema's, on every new operation too.
    bad = client.post("/v1/progress_add", json={"project": "alpha-project"}, headers=_auth(token))
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_arguments" and "kind" in bad.json()["text"]


def test_capture_turns_on_v1_is_relayed_never_the_person_s_own_words(server):
    from api.services import markdown_parser

    client, master, memory = server
    made = _agent(client, master)
    token, cid = made["token"], made["agent"]["id"]
    def relay(message, conversation=None, previous=None):
        body = {"message": message, **({"conversation": conversation} if conversation else {}),
                **({"previous_reply": previous} if previous else {})}
        answer = client.post("/v1/capture_turns", json=body, headers=_auth(token))
        assert answer.status_code == 200 and answer.json()["isError"] is False, answer.text
        return answer.json()["data"]

    # Two conversations, each started with "new" and continued with its own handle: TWO episodes (G104, ruling 32).
    a1 = relay("Remind me the canoe trip is in May.", "new")
    b1 = relay("Unrelated: what was the name of that sqlite extension?", "new")
    assert a1["conversation"] != b1["conversation"] and a1["episode_id"] != b1["episode_id"]
    a2 = relay("And pack the blue tent.", a1["conversation"], "Noted: the canoe trip is in May.")
    b2 = relay("Right, sqlite-vec.", b1["conversation"], "Was it sqlite-vec?")
    assert a2["episode_id"] == a1["episode_id"] and a2["conversation"] == a1["conversation"]
    assert b2["episode_id"] == b1["episode_id"] and a2["status"] == b2["status"] == "updated"
    episodes = {markdown_parser.parse(p).frontmatter.get("id"): markdown_parser.parse(p)
                for p in (memory / "episodes").glob("ep_*.md")}
    from api.services.turn_capture import relay_match_key

    for data, opener in ((a1, "Remind me the canoe trip is in May."),
                         (b1, "Unrelated: what was the name of that sqlite extension?")):
        page = episodes[data["episode_id"]]
        fm = page.frontmatter
        assert fm["evidence_kind"] == "assistant" and fm["harness"] == catalog.API_HARNESS
        assert fm["relay"]["connector"] == cid and fm["session_id"] == data["conversation"]
        assert fm["relay"]["first"] == relay_match_key(opener)   # an export of B upgrades B, not A
    assert "blue tent" in episodes[a1["episode_id"]].body and "blue tent" not in episodes[b1["episode_id"]].body
    # Without a conversation, the documented fallback: the token's day bucket.
    fallback = relay("A turn with no conversation.")
    assert fallback["conversation"] == f"rc_{cid}_{fallback['conversation'].rsplit('_', 1)[1]}"
    assert fallback["episode_id"] not in (a1["episode_id"], b1["episode_id"])
    reader = _agent(client, master, name="Reader", scopes=("search",))["token"]
    denied = client.post("/v1/capture_turns", json={"message": "x"}, headers=_auth(reader))
    assert denied.status_code == 403 and denied.json()["code"] == "denied"


def test_a_conversation_another_token_started_is_refused_never_merged(server):
    client, master, memory = server
    mine = _agent(client, master, name="Mine")["token"]
    theirs = _agent(client, master, name="Theirs")["token"]
    started = client.post("/v1/capture_turns", json={"message": "Their first turn.", "conversation": "new"},
                          headers=_auth(theirs)).json()["data"]
    before = sorted(p.name for p in (memory / "episodes").glob("ep_*.md"))
    for foreign in (started["conversation"], "rc_zzzzzzzz_2026-10-23_0123abcd", "not-a-handle", 7):
        answer = client.post("/v1/capture_turns", json={"message": "Into their record?", "conversation": foreign},
                             headers=_auth(mine))
        assert answer.status_code == 400 and answer.json()["code"] == "invalid_arguments", foreign
        assert "conversation" in answer.json()["text"]
    assert sorted(p.name for p in (memory / "episodes").glob("ep_*.md")) == before, "nothing written"
    # The owner of the handle continues it.
    again = client.post("/v1/capture_turns", json={"message": "Their second turn.",
                                                   "conversation": started["conversation"]}, headers=_auth(theirs))
    assert again.json()["data"]["episode_id"] == started["episode_id"]


def test_the_sources_scope_gates_the_sources_operation(server):
    client, master, _ = server
    plain = _agent(client, master, name="Plain")["token"]
    denied = client.post("/v1/source_list", json={"entity_id": "alpha-project"}, headers=_auth(plain))
    assert denied.status_code == 403 and denied.json()["code"] == "denied"
    trusted = _agent(client, master, name="Trusted", scopes=("search", "read", "record", "sources"))["token"]
    allowed = client.post("/v1/source_list", json={"entity_id": "alpha-project"}, headers=_auth(trusted))
    assert allowed.status_code == 200


def test_both_doors_refuse_with_the_same_sentence_and_code(tmp_path, monkeypatch):
    """One G199 contract and one scope check: the same token, the same refusal, on `/mcp` and on `/v1`."""
    from api import config
    from api.remote.app import build_app
    from api.remote.runtime import DENIED_TEXT, RemoteRuntime

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    mcp_headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                   "Mcp-Protocol-Version": "2025-11-25"}
    try:
        db = remote_store.ConnectorStore()
        _, token = db.create(app="other", label="Both", scopes=["search", "read"], expires_in_days=7)
        app = build_app(db, runtime=RemoteRuntime(post=lambda p, d: {}, sleep_running=lambda: False))
        with TestClient(app, base_url="https://cicada.example.ts.net") as client:
            def mcp(name, arguments):
                answer = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                   "params": {"name": name, "arguments": arguments}},
                                     headers={**mcp_headers, **_auth(token)})
                return answer.json()["result"]

            for op, tool, arguments in (("backlog_add", "cicada_add_backlog_item",
                                         {"project": "alpha-project", "title": "t", "description": "d"}),
                                        ("source_list", "cicada_sources", {"entity_id": "alpha-project"})):
                over_mcp = mcp(tool, arguments)
                over_v1 = client.post(f"/v1/{op}", json=arguments, headers=_auth(token))
                assert over_mcp["isError"] is True and over_v1.json()["isError"] is True
                assert over_mcp["content"][0]["text"] == over_v1.json()["text"] == DENIED_TEXT
                assert over_v1.status_code == 403 and over_v1.json()["code"] == "denied"
            over_mcp = mcp("cicada_backlog", {})
            over_v1 = client.post("/v1/backlog_list", json={}, headers=_auth(token))
            assert over_mcp["isError"] is True and over_v1.status_code == 400
            assert over_mcp["content"][0]["text"] == over_v1.json()["text"]
            assert over_mcp["structuredContent"]["code"] == over_v1.json()["code"] == "invalid_arguments"
    finally:
        config.get_settings.cache_clear()
