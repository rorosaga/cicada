"""G181 phase 2 — every client can talk to a backend on another machine (owner rulings 1–3, 2026-10-16).

In-process halves: the client base URL, per-device tokens and the auth gate, bank identities, the posted-session
writer and its checks, the hook's client path and spool, the tool door, and the CLI's identity check. The two-machine
proof (two real backends on two loopback ports) is `test_headless_two_machines.py`. Synthetic banks and placeholder
names only; nothing reaches the network.
"""
from __future__ import annotations

import io
import json
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.services import (
    bank_registry, device_tokens, markdown_parser, runtime_layout, session_post, tool_door,
    transcript_capture as tc,
)
from api.services.transcript_extract import FIRST_USER_CAP_CHARS, SESSION_CAP_CHARS, TURN_CAP_CHARS

SID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture(autouse=True)
def _fresh_episode_cache(monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})


def _line(typ, content, ts="2026-10-16T10:00:00.000Z"):
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": SID, "cwd": "/home/example/alpha",
                       "message": {"role": typ, "content": content}})


def _transcript(turns) -> str:
    return "\n".join(_line(r, t if r == "user" else [{"type": "text", "text": t}]) for r, t in turns) + "\n"


# --- the client base URL ---------------------------------------------------------------------------------------------

def test_unset_is_today_s_loopback_byte_for_byte():
    assert runtime_layout.is_client({}) is False
    assert runtime_layout.backend_url({}) == "http://127.0.0.1:8000"
    assert runtime_layout.backend_url({"CICADA_PORT": "8123"}) == "http://127.0.0.1:8123"
    assert runtime_layout.local_backend_url({"CICADA_API_BASE": "https://cicada.example.ts.net"}) == \
        "http://127.0.0.1:8000"


@pytest.mark.parametrize("raw, want", [
    ("https://cicada.example.ts.net", "https://cicada.example.ts.net"),
    ("https://cicada.example.ts.net/", "https://cicada.example.ts.net"),
    ("https://cicada.example.ts.net:8443/cicada/", "https://cicada.example.ts.net:8443/cicada"),
    ("http://127.0.0.1:18000", "http://127.0.0.1:18000"),
    ("http://localhost:18000", "http://localhost:18000"),
])
def test_a_base_is_https_or_a_loopback_tunnel(raw, want):
    env = {"CICADA_API_BASE": raw}
    assert runtime_layout.is_client(env) and runtime_layout.backend_url(env) == want


@pytest.mark.parametrize("raw", ["http://cicada.example.ts.net", "ftp://example.com", "cicada.example",
                                 "https://user:pw@example.com", "https://example.com/?a=1", "https://:99999"])
def test_a_bad_base_is_refused_and_never_falls_back_to_the_local_bank(raw):
    env = {"CICADA_API_BASE": raw}
    assert runtime_layout.is_client(env)          # still "not this machine's bank"
    with pytest.raises(ValueError) as err:
        runtime_layout.backend_url(env)
    assert raw not in str(err.value)               # the rule, never the value


def test_a_device_token_is_the_env_then_the_file_never_the_master_token(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "api_token").write_text("master\n")
    env = {"CICADA_HOME": str(home)}
    assert runtime_layout.client_token(env) == ""
    (home / "device_token").write_text("cic_dev_abc\n")
    assert runtime_layout.client_token(env) == "cic_dev_abc"
    assert runtime_layout.client_token({**env, "CICADA_API_TOKEN": "from-env"}) == "from-env"


def test_the_layout_module_stays_stdlib_only():
    """The hooks import it by path with no venv guarantee."""
    src = (Path(runtime_layout.__file__)).read_text()
    imports = [line.strip() for line in src.splitlines() if line.strip().startswith(("import ", "from "))]
    assert all(i.split()[1].split(".")[0] in {"__future__", "os", "pathlib", "urllib"} for i in imports), imports


# --- per-device tokens (owner ruling 1) ------------------------------------------------------------------------------

def test_a_device_token_is_hashed_named_and_revocable(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "server-home"))
    store = device_tokens.store()
    device, token = store.create("  laptop\x00 ")
    assert device.name == "laptop" and token.startswith("cic_dev_" + device.id + "_")
    raw = (tmp_path / "server-home" / "devices" / "devices.db").read_bytes()
    assert token.encode() not in raw and token.split("_")[-1].encode() not in raw
    assert stat.S_IMODE((tmp_path / "server-home" / "devices").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "server-home" / "devices" / "devices.db").stat().st_mode) == 0o600
    assert store.verify(token).id == device.id
    assert store.verify(token[:-1] + ("A" if token[-1] != "A" else "B")) is None
    assert store.verify("cic_rc_abcdefgh_" + "x" * 43) is None
    store.revoke(device.id)
    assert store.verify(token) is None
    with pytest.raises(ValueError):
        store.create("   ")


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A backend app with auth ON, a scaffolded synthetic root, and its own CICADA_HOME."""
    from api import config
    from api.main import app

    root = tmp_path / "server-memory"
    root.mkdir()
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "server-home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    from api.services.auth import get_token

    master = get_token()
    with TestClient(app) as client:
        yield client, master, root
    config.get_settings.cache_clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_only_the_master_token_issues_and_revokes_devices(server):
    client, master, _root = server
    made = client.post("/devices", json={"name": "laptop"}, headers=_auth(master))
    assert made.status_code == 201
    device, token = made.json()["device"], made.json()["token"]
    assert client.get("/banks", headers=_auth(token)).status_code == 200      # a device opens the API
    assert client.post("/devices", json={"name": "x"}, headers=_auth(token)).status_code == 403
    assert client.get("/devices", headers=_auth(token)).status_code == 403
    assert client.delete(f"/devices/{device['id']}", headers=_auth(token)).status_code == 403
    listed = client.get("/devices", headers=_auth(master)).json()["devices"]
    assert [d["id"] for d in listed] == [device["id"]] and "token" not in json.dumps(listed)
    assert client.delete(f"/devices/{device['id']}", headers=_auth(master)).status_code == 200
    assert client.get("/banks", headers=_auth(token)).status_code == 401      # revoked: at once
    assert client.get("/banks", headers=_auth("cic_dev_" + "a" * 8 + "_" + "b" * 43)).status_code == 401


# --- bank identity ---------------------------------------------------------------------------------------------------

def test_every_bank_gets_an_id_a_copy_gets_its_own_and_a_rename_keeps_it(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    assert bank_registry.bank_ids(root) == []
    assert bank_registry.ensure_bank_ids(root) is True                  # the legacy default, persisted with an id
    legacy = bank_registry.bank_id(root, "default")
    assert legacy and bank_registry.resolve_active_bank_path(root) == root   # resolution unchanged
    assert bank_registry.ensure_bank_ids(root) is False                 # reading again writes nothing
    slug = bank_registry.create_bank(root, "beta", seed_owner=False)
    beta = bank_registry.bank_id(root, slug)
    copy = bank_registry.duplicate_bank(root, slug, "gamma")
    assert len({legacy, beta, bank_registry.bank_id(root, copy)}) == 3
    renamed = bank_registry.rename_bank(root, slug, "delta")
    assert bank_registry.bank_id(root, renamed) == beta
    bank_registry.activate_bank(root, renamed)
    import contextvars

    # Pinned in a copy of the context: a pin set in the test's own context would follow every later test.
    assert contextvars.copy_context().run(bank_registry.pin_request_bank, root).id == beta
    assert bank_registry.pinned_bank() is None


def test_healthz_says_ids_never_names_and_a_wrong_id_is_refused(server):
    client, master, root = server
    health = client.get("/healthz").json()
    active = bank_registry.bank_id(root, bank_registry.active_bank_name(root))
    assert health["bankId"] == active and health["bankIds"] == [active]
    assert "default" not in json.dumps({k: health[k] for k in ("bankId", "bankIds")})
    ok = client.post("/tools/call", headers={**_auth(master), "X-Cicada-Bank-Id": active},
                     json={"tool": "cicada_timeline", "arguments": {}})
    assert ok.status_code == 200
    wrong = client.post("/tools/call", headers={**_auth(master), "X-Cicada-Bank-Id": "0" * 32},
                        json={"tool": "cicada_save_episode", "arguments": {"content": "never written"}})
    assert wrong.status_code == 409 and wrong.json()["code"] == "bank_mismatch"
    assert not any("never written" in p.read_text() for p in (root / "episodes").glob("*.md"))


def test_the_cli_compares_identities_and_falls_back_to_the_path(tmp_path, monkeypatch):
    from api import cli_app

    def fake(body):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(body).encode()

        class Opener:
            def open(self, *a, **k):
                return Resp()
        return Opener()

    root = tmp_path / "root"
    monkeypatch.setattr(cli_app, "_opener", lambda: fake({"memoryRoot": "/elsewhere", "bankIds": ["a" * 32]}))
    # The same memory seen through a different path (a container's mount, another machine): the id decides.
    assert cli_app.probe_backend("http://x", root, 1, bank_id="a" * 32)["state"] == "confirmed"
    assert cli_app.probe_backend("http://x", root, 1, bank_id="b" * 32)["state"] == "mismatch"
    # No id on one side (an older backend, a bank not yet given one): the path, as before.
    monkeypatch.setattr(cli_app, "_opener", lambda: fake({"memoryRoot": str(root)}))
    assert cli_app.probe_backend("http://x", root, 1, bank_id="a" * 32)["state"] == "confirmed"


# --- a session posted as turns (owner ruling 2) ----------------------------------------------------------------------

def _conv(turns, **extra):
    return {"kept": [{"role": r, "text": t} for r, t in turns], "gap": None, "summary": {}, **extra}


def test_what_arrives_is_checked_again_caps_scrub_and_the_session_cap():
    secret = "sk-ant-api03-" + "A" * 40
    conv = session_post.from_wire(_conv([("user", f"key {secret}"), ("assistant", "ok")]), harness="claude-code",
                                  session_id=SID, cwd=None)
    assert secret not in conv.turns[0].text and conv.summary["scrubbed"] >= 1
    with pytest.raises(session_post.PostRefused) as err:
        session_post.from_wire(_conv([("user", "a"), ("user", "x" * (TURN_CAP_CHARS + 1))]),
                               harness="claude-code", session_id=SID, cwd=None)
    assert err.value.reason == "turn_over_cap"
    words = ("plan " * FIRST_USER_CAP_CHARS)[:FIRST_USER_CAP_CHARS - 1] + "a"
    first = session_post.from_wire(_conv([("user", words)]), harness="claude-code", session_id=SID, cwd=None)
    assert len(first.turns[0].text) == FIRST_USER_CAP_CHARS
    many = [("user" if i % 2 == 0 else "assistant", f"{i} " + "word " * 380) for i in range(80)]
    big = session_post.from_wire(_conv(many), harness="claude-code", session_id=SID, cwd=None)
    assert big.gap is not None and sum(len(t.text) for t in big.turns) <= SESSION_CAP_CHARS
    for bad in ({"kept": "no"}, {"kept": [{"role": "system", "text": "x"}]}, {"kept": [], "gap": {"after": 5}}):
        with pytest.raises(session_post.PostRefused):
            session_post.from_wire(bad, harness="claude-code", session_id=SID, cwd=None)


def test_replies_turned_off_on_the_server_are_dropped_and_the_gap_follows():
    wire = {"kept": [{"role": "user", "text": "a"}, {"role": "assistant", "text": "b"},
                      {"role": "user", "text": "c"}, {"role": "assistant", "text": "d"}],
            "gap": {"after": 2, "dropped": 7, "first_at": None, "last_at": None}, "summary": {}}
    conv = session_post.from_wire(wire, harness="claude-code", session_id=SID, cwd=None, keep_assistant=False)
    assert [t.text for t in conv.turns] == ["a", "c"] and conv.gap.after == 1


def _posted(memory, wire, read, size, **kw):
    return tc.capture_posted(memory, harness="claude-code", session_id=SID, conversation=wire,
                             transcript_bytes=read, transcript_size=size, cwd="/home/example/alpha",
                             keep_assistant=True, **kw)


def test_one_session_is_one_episode_and_a_stale_resend_is_superseded(tmp_path):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    first = _conv([("user", "plan alpha"), ("assistant", "done")])
    grown = _conv([("user", "plan alpha"), ("assistant", "done"), ("user", "and beta")])
    r1 = _posted(memory, first, 100, 100, device="ab12cd34")
    assert r1.status == "created"
    assert _posted(memory, first, 100, 100, device="ab12cd34").status == "unchanged"
    assert _posted(memory, grown, 180, 180, device="ab12cd34").status == "updated"
    # A snapshot read before the newer one, resent after an outage: the file has grown past what is stored.
    assert _posted(memory, first, 100, 180, device="ab12cd34").status == "superseded"
    # A transcript that was replaced by a shorter file is never stuck.
    assert _posted(memory, first, 100, 100, device="ab12cd34").status == "updated"
    eps = list((memory / "episodes").glob("ep_*.md"))
    assert len(eps) == 1
    fm = markdown_parser.parse(eps[0]).frontmatter
    assert fm["session_id"] == SID and fm["capture_kind"] == "transcript" and fm["device"] == "ab12cd34"


def test_a_posted_session_never_lands_in_a_demo_bank(tmp_path):
    from api.services import demo_guard

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / demo_guard.MANIFEST).write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    assert demo_guard.is_demo(memory)
    result = _posted(memory, _conv([("user", "x")]), 1, 1)
    assert result.status == "refused" and result.reason == "demo_bank"


def test_the_route_records_the_device_from_the_token_never_the_body(server, tmp_path):
    client, master, root = server
    token = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()["token"]
    body = {"harness": "claude-code", "session_id": SID, "conversation": _conv([("user", "plan alpha")]),
            "transcript_bytes": 10, "transcript_size": 10, "cwd": "/home/example/alpha", "device": "forged"}
    answer = client.post("/capture/session", json=body, headers=_auth(token))
    assert answer.status_code == 200 and answer.json()["status"] == "created"
    ep = next((root / "episodes").glob("ep_*.md"))
    device_id = token.split("_")[2]
    assert markdown_parser.parse(ep).frontmatter["device"] == device_id
    bad = client.post("/capture/session", headers=_auth(token),
                      json={**body, "conversation": _conv([("user", "x" * (FIRST_USER_CAP_CHARS + 1))])})
    assert bad.status_code == 400 and bad.json()["detail"] == "turn_over_cap"


# --- the hook on a client machine ------------------------------------------------------------------------------------

@pytest.fixture
def client_machine(tmp_path, monkeypatch):
    """A client's HOME with one synthetic Claude Code transcript under its own harness root."""
    home = tmp_path / "client-home"
    projects = home / ".claude" / "projects" / "-home-example-alpha"
    projects.mkdir(parents=True)
    transcript = projects / f"{SID}.jsonl"
    transcript.write_text(_transcript([("user", "plan alpha with bob-example"), ("assistant", "planned")]))
    monkeypatch.setattr(tc, "harness_root", lambda h: home / ".claude" / "projects")
    cicada_home = tmp_path / "client-cicada"
    cicada_home.mkdir()
    (cicada_home / "device_token").write_text("cic_dev_test")
    env = {"CICADA_HOME": str(cicada_home), "CICADA_API_BASE": "https://cicada.example.ts.net",
           "HOME": str(home)}
    return env, transcript, cicada_home


def _fire(env, transcript, post, event="Stop"):
    from api.hooks import capture as hook

    payload = {"session_id": SID, "transcript_path": str(transcript), "cwd": "/home/example/alpha",
               "hook_event_name": event}
    return hook.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)), environ=env, post=post)


def test_the_client_hook_reads_here_posts_turns_and_never_a_path(client_machine):
    env, transcript, home = client_machine
    calls = []

    def post(url, body, token, timeout):
        calls.append((url, json.loads(body), token))
        return 200, json.dumps({"status": "created"})

    assert _fire(env, transcript, post) == 0
    (url, body, token), = calls
    assert url == "https://cicada.example.ts.net/capture/session" and token == "cic_dev_test"
    assert "transcript_path" not in body and str(transcript) not in json.dumps(body)
    assert [t["role"] for t in body["conversation"]["kept"]] == ["user", "assistant"]
    assert body["transcript_bytes"] == transcript.stat().st_size == body["transcript_size"]
    assert "http 200 created" in (home / "logs" / "capture.log").read_text()


def test_a_path_outside_the_harness_root_is_never_read_on_the_client_either(client_machine, tmp_path):
    env, _transcript_path, home = client_machine
    stray = tmp_path / "elsewhere" / f"{SID}.jsonl"
    stray.parent.mkdir()
    stray.write_text(_transcript([("user", "never read")]))
    calls = []
    _fire(env, stray, lambda *a: calls.append(a) or (200, "{}"))
    assert calls == [] and "refused: outside_root" in (home / "logs" / "capture.log").read_text()


def test_a_server_that_is_away_loses_nothing_and_a_later_firing_flushes(client_machine):
    from api.hooks import hook_spool

    env, transcript, home = client_machine
    assert _fire(env, transcript, lambda *a: (None, "")) == 0
    assert hook_spool.pending(home) == 1
    transcript.write_text(transcript.read_text() + _line("user", "and the second turn") + "\n")
    _fire(env, transcript, lambda *a: (None, ""))
    assert hook_spool.pending(home) == 1                               # one entry per session: the newest
    entry = json.loads(next((home / "spool" / "capture").glob("s-*.json")).read_text())
    assert len(entry["body"]["conversation"]["kept"]) == 3
    assert stat.S_IMODE(next((home / "spool" / "capture").glob("s-*.json")).stat().st_mode) == 0o600
    sent = []
    _fire(env, transcript, lambda url, body, token, timeout: sent.append(json.loads(body)) or (200, "{}"))
    assert hook_spool.pending(home) == 0 and len(sent) == 1           # the live post superseded the waiting one


def test_a_flush_sends_other_sessions_oldest_first_inside_the_budget(client_machine, tmp_path):
    from api.hooks import hook_spool

    env, transcript, home = client_machine
    hook_spool.put(home, "/capture/session", {"session_id": "other-session-1", "transcript_bytes": 5},
                   key="claude-code:other-session-1", transcript_path=str(tmp_path / "gone.jsonl"))
    hook_spool.put(home, "/capture/turn", {"session_id": "turns-1"})
    seen = []
    _fire(env, transcript, lambda url, body, token, timeout: seen.append((url, json.loads(body))) or (200, "{}"))
    routes = [u.rsplit("/", 2)[-2] + "/" + u.rsplit("/", 1)[-1] for u, _ in seen]
    assert routes == ["capture/session", "capture/session", "capture/turn"] and hook_spool.pending(home) == 0
    assert seen[1][1]["transcript_size"] == 5                          # gone: the size it had when read


def test_a_request_the_server_refuses_for_good_is_not_kept(client_machine):
    from api.hooks import hook_spool

    env, transcript, home = client_machine
    _fire(env, transcript, lambda *a: (422, '{"detail": "invalid request"}'))
    assert hook_spool.pending(home) == 0
    _fire(env, transcript, lambda *a: (401, '{"detail": "missing or invalid bearer token"}'))
    assert hook_spool.pending(home) == 1                               # a token being replaced: kept


def test_no_device_token_spools_and_says_so(client_machine):
    from api.hooks import hook_spool

    env, transcript, home = client_machine
    (home / "device_token").unlink()
    calls = []
    _fire(env, transcript, lambda *a: calls.append(a) or (200, "{}"))
    assert calls == [] and hook_spool.pending(home) == 1
    assert "spooled: no device token" in (home / "logs" / "capture.log").read_text()


def test_the_local_hook_is_unchanged_when_no_base_is_set(client_machine):
    env, transcript, home = client_machine
    env = {k: v for k, v in env.items() if k != "CICADA_API_BASE"}
    (home / "api_token").write_text("master")
    calls = []

    def post(url, body, token, timeout):
        calls.append((url, json.loads(body), token))
        return 200, json.dumps({"status": "created"})

    _fire(env, transcript, post)
    (url, body, token), = calls
    assert url == "http://127.0.0.1:8000/capture/transcript" and token == "master"
    assert body["transcript_path"] == str(transcript) and "conversation" not in body
    assert not (home / "spool").exists()


def test_a_cursor_turn_waits_in_order_behind_waiting_turns(tmp_path):
    from api.hooks import cursor as cursor_hook
    from api.hooks import hook_spool

    home = tmp_path / "ch"
    home.mkdir()
    (home / "device_token").write_text("cic_dev_test")
    env = {"CICADA_HOME": str(home), "CICADA_API_BASE": "https://cicada.example.ts.net", "HOME": str(tmp_path)}
    payload = {"hook_event_name": "beforeSubmitPrompt", "conversation_id": "conv-0001-abcd", "prompt": "first",
               "generation_id": "g1"}
    out = io.StringIO()
    cursor_hook.main(stdin=io.StringIO(json.dumps(payload)), stdout=out, environ=env, post=lambda *a: (None, ""))
    assert json.loads(out.getvalue()) == {"continue": True} and hook_spool.pending(home) == 1
    order = []
    reply = {**payload, "hook_event_name": "afterAgentResponse", "text": "second"}
    cursor_hook.main(stdin=io.StringIO(json.dumps(reply)), stdout=io.StringIO(), environ=env,
                     post=lambda url, body, token, timeout: order.append(json.loads(body)["messages"][0]["text"])
                     or (200, "{}"))
    assert order == ["first", "second"] and hook_spool.pending(home) == 0


# --- the tool door ---------------------------------------------------------------------------------------------------

def test_the_door_runs_every_stdio_tool_and_no_other():
    from _stdio_server import stdio_server
    import re

    server_src = Path(stdio_server().__file__).read_text()
    stdio = set(re.findall(r'elif name == "(cicada_[a-z_]+)"|if name == "(cicada_[a-z_]+)"', server_src))
    stdio = {a or b for a, b in stdio}
    assert stdio == set(tool_door.DISPATCH) | tool_door.SPECIAL
    assert tool_door.tools() == stdio                 # the CLI↔MCP table is the source of the names


def _door_ctx(memory, **kw):
    state = tool_door.SessionState()
    ctx = tool_door.context(memory_path=memory, bank_name="default", caller=tool_door.Caller(
        session_id="ses_2026-10-16_c0ffee00", harness=kw.pop("harness", "claude-code")), state=state,
        surface=kw.pop("surface", "mcp"), device_id="ab12cd34", backend_url="http://127.0.0.1:9",
        headers=lambda: {}, post=lambda p, d: {})
    return ctx, state


def test_a_door_call_never_opens_a_path_the_caller_names(tmp_path):
    from _synthetic_bank import _bank

    memory = _bank(tmp_path)
    picture = tmp_path / "shot.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    ctx, state = _door_ctx(memory)
    answer = tool_door.run("cicada_save_design", {"note": "a look", "image_path": str(picture)}, ctx=ctx,
                           state=state, surface="mcp", options={}, root=memory, bank_name="default")
    assert "cannot read a file on your machine" in answer.text


def test_a_door_save_carries_the_device_and_the_session(tmp_path, monkeypatch):
    from _synthetic_bank import _bank

    memory = _bank(tmp_path)
    ctx, state = _door_ctx(memory)
    answer = tool_door.run("cicada_save_episode", {"content": "decided to ship alpha", "title": "Ship"}, ctx=ctx,
                           state=state, surface="mcp", options={}, root=memory, bank_name="default")
    assert answer.error is None
    fm = markdown_parser.parse(memory / "episodes" / f"{answer.data['episode_id']}.md").frontmatter
    assert fm["device"] == "ab12cd34" and fm["session_id"] == "ses_2026-10-16_c0ffee00"


def test_the_door_s_session_state_round_trips(tmp_path):
    from _synthetic_bank import _bank

    memory = _bank(tmp_path)
    ctx, state = _door_ctx(memory)
    text = tool_door.run("cicada_pending", {}, ctx=ctx, state=state, surface="mcp", options={}, root=memory,
                         bank_name="default").text
    assert "ep_2026-09-01_001" in text and "ep_2026-09-01_001" in state.wire()["listed_revisions"]
    ctx2, state2 = _door_ctx(memory)
    state2.listed_revisions.update(state.listed_revisions)
    marked = tool_door.run("cicada_mark_processed", {"episode_ids": ["ep_2026-09-01_001"]}, ctx=ctx2, state=state2,
                           surface="mcp", options={}, root=memory, bank_name="default").text
    assert marked.startswith("Marked 1 episode(s)") and "processed_by: claude-code" in marked


def test_the_repo_context_s_git_probe_never_runs_in_the_backend(tmp_path, monkeypatch):
    from _synthetic_bank import _bank
    from api.services import repo_context

    memory = _bank(tmp_path)
    monkeypatch.setattr(repo_context, "resolve_repo_context", lambda d: pytest.fail("git ran in the backend"))
    ctx, state = _door_ctx(memory)
    answer = tool_door.run("cicada_repo_context", {"entity_id": "alpha-project"}, ctx=ctx, state=state,
                           surface="mcp", options={}, root=memory, bank_name="default")
    assert answer.data["entity"] == "alpha-project" and answer.data["repos"][0]["path"] == "~/src/alpha-project"


def test_the_cli_surface_keeps_the_command_line_s_doors(tmp_path):
    from _synthetic_bank import _bank

    memory = _bank(tmp_path)
    ctx, state = _door_ctx(memory, surface="cli")
    for tool in ("cicada_explore_start", "cicada_write_claim"):
        with pytest.raises(tool_door.DoorError) as err:
            tool_door.run(tool, {}, ctx=ctx, state=state, surface="cli", options={}, root=memory, bank_name="d")
        assert err.value.status == 403
    with pytest.raises(tool_door.DoorError) as err:
        tool_door.run("cicada_nope", {}, ctx=ctx, state=state, surface="mcp", options={}, root=memory, bank_name="d")
    assert err.value.status == 404


def test_a_device_counts_as_local_for_the_trust_list(server):
    """Owner ruling 3: a trusted harness through a device token edits at once; an untrusted one proposes."""
    client, master, root = server
    import subprocess

    from api.services import page_editors

    from _synthetic_bank import _entity

    bank = bank_registry.resolve_active_bank_path(root)
    _entity(bank, "alpha-project", type="project", body="## Summary\nAlpha ships in spring.\n")
    subprocess.run(["git", "add", "-A"], cwd=bank, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "seed"], cwd=bank,
                   check=True, capture_output=True)
    token = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()["token"]
    assert page_editors.is_trusted("claude-code")

    def edit(harness, old, text):
        return client.post("/tools/call", headers=_auth(token), json={
            "tool": "cicada_edit_page", "caller": {"session_id": "ses_2026-10-16_c0ffee00", "harness": harness},
            "arguments": {"subject": "alpha-project", "reason": "the season was wrong",
                          "edits": [{"old": old, "new": text}]}}).json()

    applied = edit("claude-code", "spring", "autumn")
    assert applied["error"] is None, applied
    assert "autumn" in (bank / "entities" / "alpha-project.md").read_text()
    log = subprocess.run(["git", "log", "-1", "--format=%B"], cwd=bank, capture_output=True, text=True).stdout
    assert "Cicada-Author: claude-code" in log
    proposed = edit("agent", "autumn", "winter")
    assert "winter" not in (bank / "entities" / "alpha-project.md").read_text()
    assert proposed["error"] is None and "propos" in proposed["text"].lower()


def test_a_very_long_session_is_read_by_a_detached_child_inside_the_hook_s_wait(client_machine, monkeypatch):
    from api.hooks import capture as hook

    env, transcript, home = client_machine
    monkeypatch.setattr(hook, "DETACH_BYTES", 10)
    handed = []
    monkeypatch.setattr(hook, "_detach", lambda payload, **kw: handed.append(payload) or True)
    calls = []
    _fire(env, transcript, lambda *a: calls.append(a) or (200, "{}"))
    assert calls == [] and handed and handed[0]["transcript_path"] == str(transcript)
    assert "reading a long session in the background" in (home / "logs" / "capture.log").read_text()
    # The child itself (marked detached) reads and posts, whatever the size.
    _fire({**env, hook.DETACHED_ENV: "1"}, transcript, lambda *a: calls.append(a) or (200, "{}"))
    assert len(calls) == 1
