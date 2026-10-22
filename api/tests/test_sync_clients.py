"""G202 — the defects the 2026-10-22 two-device test found in one primary + its clients (D1, D3, D5, D6, D7).

D1 is reproduced end to end: two fake servers on loopback ports answer the client's real hook (its own extractor, its
own HTTP client, no redirect followed), the client is pointed from one to the other while a capture waits, and the
waiting capture must go to the server it was captured for — never the other. Synthetic data and placeholder names only.
"""
from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.services import transcript_capture as tc

SID = "aaaaaaaa-1111-4222-8333-444444444444"
SID2 = "bbbbbbbb-1111-4222-8333-444444444444"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})
    from api.services import tool_client

    monkeypatch.setattr(tool_client, "_LAST_WHERE", None)


def _line(typ, content, sid, ts="2026-10-22T01:50:00.000Z"):
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": sid, "cwd": "/home/example/alpha",
                       "message": {"role": typ, "content": content if typ == "user" else
                                   [{"type": "text", "text": content}]}})


class FakeServer:
    """A Cicada server as the hook sees it: `/capture/session` answers `created` and the bank it filed the post in;
    a resend naming another bank is refused like the real route (409 `bank_mismatch`). `down` drops the connection
    with no answer — the spool's signal."""

    def __init__(self, bank_id: str):
        self.bank_id = bank_id
        self.down = False
        self.posts: list[tuple[str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if outer.down:
                    self.close_connection = True
                    return
                if body.get("bank_id") and body["bank_id"] != outer.bank_id:
                    status, answer = 409, {"code": "bank_mismatch", "detail": "Memory switched"}
                else:
                    outer.posts.append((self.path, body))
                    status, answer = 200, {"status": "created", "bank": "default", "bankId": outer.bank_id}
                raw = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def sessions(self, sid: str) -> list[dict]:
        return [b for p, b in self.posts if p == "/capture/session" and b.get("session_id") == sid]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def two_servers():
    a, b = FakeServer("bank-a"), FakeServer("bank-b")
    yield a, b
    a.close()
    b.close()


@pytest.fixture
def client_home(tmp_path, monkeypatch):
    home = tmp_path / "client-home"
    projects = home / ".claude" / "projects" / "-home-example-alpha"
    projects.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: home / ".claude" / "projects")
    cicada_home = tmp_path / "client-cicada"
    cicada_home.mkdir()
    (cicada_home / "device_token").write_text("cic_dev_test")
    return home, projects, cicada_home


def _write(projects: Path, sid: str, turns) -> Path:
    path = projects / f"{sid}.jsonl"
    path.write_text("\n".join(_line(r, t, sid) for r, t in turns) + "\n")
    return path


def _fire(env, sid, transcript):
    from api.hooks import capture as hook

    payload = {"session_id": sid, "transcript_path": str(transcript), "cwd": "/home/example/alpha",
               "hook_event_name": "Stop"}
    return hook.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)), environ=env)


def _env(home, cicada_home, base):
    return {"CICADA_HOME": str(cicada_home), "CICADA_API_BASE": base, "HOME": str(home)}


# --- D1: a waiting capture follows the server it was captured for -----------------------------------------------------

def test_d1_a_waiting_capture_never_follows_the_client_to_another_server(two_servers, client_home):
    """The live repro (sync test, D1): with the client on A, a session lands; A goes away and the session's next turn
    is spooled; the client is pointed at B and fires another session. Before G202 the spool flushed the waiting turn
    into B, so the session ended up half on A and whole on B."""
    from api.hooks import hook_spool

    a, b = two_servers
    home, projects, cicada_home = client_home
    t1 = _write(projects, SID, [("user", "the hiring plan for alpha-project"), ("assistant", "noted")])
    _fire(_env(home, cicada_home, a.url), SID, t1)
    assert len(a.sessions(SID)) == 1

    a.down = True
    t1 = _write(projects, SID, [("user", "the hiring plan for alpha-project"), ("assistant", "noted"),
                                ("user", "hire one engineer first"), ("assistant", "ok")])
    _fire(_env(home, cicada_home, a.url), SID, t1)
    assert hook_spool.pending(cicada_home) == 1
    entry = json.loads(next((cicada_home / "spool" / "capture").glob("s-*.json")).read_text())
    assert entry["target"] == {"base": a.url, "bank_id": "bank-a"}

    t2 = _write(projects, SID2, [("user", "beta-project notes"), ("assistant", "saved")])
    _fire(_env(home, cicada_home, b.url), SID2, t2)          # the client now points at B
    assert len(b.sessions(SID2)) == 1
    assert b.sessions(SID) == []                              # the fix: A's capture never reached B
    assert hook_spool.pending(cicada_home) == 1               # kept, never dropped
    assert hook_spool.waiting(cicada_home, b.url) == {"here": 0, "elsewhere": {a.url.removeprefix("http://"): 1}}
    log = (cicada_home / "logs" / "capture.log").read_text()
    assert f"1 waits for another server ({a.url.removeprefix('http://')})" in log

    # Back on A (the person points the client back, or A was only away): a successful call flushes it there (D3).
    from api.hooks import hook_client

    a.down = False
    assert hook_client.flush_waiting(cicada_home, _env(home, cicada_home, a.url), surface="cli") == (1, 0)
    resent = a.sessions(SID)[-1]
    assert resent["bank_id"] == "bank-a" and len(resent["conversation"]["kept"]) == 4
    assert b.sessions(SID) == [] and hook_spool.pending(cicada_home) == 0


def test_d1_the_same_address_leading_to_another_server_keeps_the_capture(two_servers, client_home):
    """An SSH tunnel's local port can lead to another server under the same address: the bank id tells them apart.
    The server refuses the resend (409 `bank_mismatch`) and the entry keeps waiting, counted for this address."""
    from api.hooks import hook_client, hook_spool

    a, _b = two_servers
    home, projects, cicada_home = client_home
    t1 = _write(projects, SID, [("user", "alpha-project kickoff"), ("assistant", "noted")])
    _fire(_env(home, cicada_home, a.url), SID, t1)
    a.down = True
    t1 = _write(projects, SID, [("user", "alpha-project kickoff"), ("assistant", "noted"), ("user", "more"),
                                ("assistant", "ok")])
    _fire(_env(home, cicada_home, a.url), SID, t1)
    a.down, a.bank_id = False, "bank-other"                  # same address, another memory behind it
    before = len(a.posts)
    assert hook_client.flush_waiting(cicada_home, _env(home, cicada_home, a.url)) == (0, 1)
    assert len(a.posts) == before and hook_spool.pending(cicada_home) == 1


def test_d1_a_new_snapshot_for_one_server_never_replaces_the_one_waiting_for_another(tmp_path):
    from api.hooks import hook_spool

    home = tmp_path / "h"
    a = {"base": "https://a.example.ts.net", "bank_id": "bank-a"}
    b = {"base": "https://b.example.ts.net", "bank_id": "bank-b"}
    hook_spool.put(home, "/capture/session", {"session_id": "s", "n": 1}, key="claude-code:s", target=a)
    hook_spool.put(home, "/capture/session", {"session_id": "s", "n": 2}, key="claude-code:s", target=b)
    hook_spool.put(home, "/capture/session", {"session_id": "s", "n": 3}, key="claude-code:s", target=b)
    assert hook_spool.pending(home) == 2                       # one per server; B's newest replaced B's older
    hook_spool.drop(home, "claude-code:s", b["base"], ("bank-b",))
    assert hook_spool.waiting(home, a["base"]) == {"here": 1, "elsewhere": {}}
    sent = []
    hook_spool.flush(home, lambda r, body: sent.append(body) or 200, deadline=float("inf"),
                     keep=lambda s: True, size_of=lambda p, f: f, base=b["base"])
    assert sent == [] and hook_spool.pending(home) == 1        # nothing of A's goes to B


def test_d1_a_turn_waiting_for_another_server_never_holds_this_server_s_turns(tmp_path):
    from api.hooks import hook_client, hook_spool

    home = tmp_path / "ch"
    home.mkdir()
    (home / "device_token").write_text("cic_dev_test")
    hook_spool.put(home, "/capture/turn", {"session_id": "t"}, target={"base": "https://old.example.ts.net",
                                                                         "bank_id": None})
    env = {"CICADA_HOME": str(home), "CICADA_API_BASE": "https://new.example.ts.net", "HOME": str(tmp_path)}
    seen = []
    out = hook_client.deliver_turn(home, "/capture/turn", {"session_id": "u"}, environ=env, timeout=1,
                                   post=lambda url, body, token, t: seen.append(url) or (200, '{"bankId": "n1"}'))
    assert out == "http 200" and seen == ["https://new.example.ts.net/capture/turn"]
    assert hook_spool.bank_for(home, "https://new.example.ts.net/") == "n1"
    assert hook_spool.pending(home) == 1


def test_d1_the_route_refuses_a_resend_for_another_bank_and_names_the_bank_it_filed_in(tmp_path, monkeypatch):
    from api import config
    from api.main import app
    from api.services import bank_registry

    root = tmp_path / "server-memory"
    root.mkdir()
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "server-home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    from api.services.auth import get_token

    master = get_token()
    try:
        with TestClient(app) as client:
            auth = {"Authorization": f"Bearer {master}"}
            conv = {"kept": [{"role": "user", "text": "alpha-project kickoff"}], "gap": None, "summary": {}}
            body = {"harness": "claude-code", "session_id": SID, "transcript_bytes": 10, "transcript_size": 10,
                    "conversation": conv}
            first = client.post("/capture/session", json=body, headers=auth)
            assert first.status_code == 200, first.text
            filed = first.json()["bankId"]
            assert filed and filed == bank_registry.bank_id(root, bank_registry.active_bank_name(root))
            episodes = sorted((root / "episodes").glob("ep_*.md"))
            refused = client.post("/capture/session", json={**body, "bank_id": "0" * 32}, headers=auth)
            assert refused.status_code == 409 and refused.json()["code"] == "bank_mismatch"
            assert sorted((root / "episodes").glob("ep_*.md")) == episodes
            same = client.post("/capture/session", json={**body, "bank_id": filed}, headers=auth)
            assert same.status_code == 200 and same.json()["bankId"] == filed
            turn = {"harness": "cursor", "session_id": "conv-0001", "messages": [{"speaker": "user", "text": "hi"}]}
            assert client.post("/capture/turn", json={**turn, "bank_id": "f" * 32},
                               headers=auth).status_code == 409
            assert client.post("/capture/turn", json=turn, headers=auth).json()["bankId"] == filed
    finally:
        config.get_settings.cache_clear()


# --- D3: what waits is counted, and any successful call flushes it ----------------------------------------------------

def test_d3_status_counts_the_hooks_spool_and_the_app_outbox_by_server(tmp_path, monkeypatch):
    from api import cli
    from api.hooks import hook_spool

    home = tmp_path / "ch"
    monkeypatch.setenv("CICADA_HOME", str(home))
    here, there = "https://cicada.example.ts.net", "https://old.example.ts.net"
    hook_spool.put(home, "/capture/session", {"session_id": "a"}, key="k:a", target={"base": here, "bank_id": "x"})
    hook_spool.put(home, "/capture/session", {"session_id": "b"}, key="k:b", target={"base": there, "bank_id": "y"})
    app = home / "spool" / "app"
    app.mkdir(parents=True)
    (app / "p-1.json").write_text(json.dumps({"v": 2, "method": "POST", "path": "/sources/sync-notes", "base": there,
                                              "bankId": "y", "body": "", "queuedAt": 0}))
    (app / "p-2.json").write_text(json.dumps({"v": 1, "method": "POST", "path": "/sources/sync-notes", "body": "",
                                              "queuedAt": 0}))
    got = cli._waiting_captures(here)
    assert got == {"waiting": 2, "elsewhere": {"old.example.ts.net": 2}}
    lines = cli._waiting_lines(got, client=True)
    assert lines == ["Waiting to be sent to this server: 2 captures",
                     "Waiting for another server (old.example.ts.net): 2 captures — kept, sent only there"]
    # On a machine that holds its own memory, everything waiting is for a server it no longer uses.
    assert cli._waiting_captures(None)["waiting"] == 0
    assert not (tmp_path / "never" / "spool").exists()
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "never"))
    assert cli._waiting_captures(None) == {"waiting": 0, "elsewhere": {}}
    assert not (tmp_path / "never" / "spool").exists()        # counting never makes a spool


def test_d3_a_successful_tool_call_flushes_the_spool_in_the_background(tmp_path, monkeypatch):
    from api.hooks import hook_client, hook_spool
    from api.services import tool_client

    home = tmp_path / "ch"
    hook_spool.put(home, "/capture/session", {"session_id": "a"}, key="k:a")
    flushed = threading.Event()
    monkeypatch.setattr(hook_client, "flush_waiting", lambda h, env, surface="call": flushed.set())
    tool_client._flush_spool_soon({"CICADA_HOME": str(home)})
    assert flushed.wait(5)


def test_d3_a_successful_command_flushes_through_the_same_door(two_servers, client_home, monkeypatch):
    from api import cli_app
    from api.hooks import hook_spool

    a, _b = two_servers
    home, _projects, cicada_home = client_home
    hook_spool.put(cicada_home, "/capture/session", {"session_id": SID, "harness": "claude-code"}, key="k",
                   target={"base": a.url, "bank_id": "bank-a"})
    assert cli_app.flush_spool(_env(home, cicada_home, a.url)) == (1, 0)
    assert a.posts[-1][1]["bank_id"] == "bank-a"


# --- D5: platform-neutral copy ---------------------------------------------------------------------------------------

def test_d5_a_linux_server_never_says_this_mac():
    from api.services import embedding_health

    linux = embedding_health.sentence("model_missing", {"CICADA_RELEASE": "1"}, platform="linux")
    assert "this Mac" not in linux and "isn't on this server" in linux
    mac = embedding_health.sentence("model_missing", {"CICADA_RELEASE": "1"}, platform="darwin")
    assert "isn't on this Mac" in mac
    for kind in embedding_health.KINDS:
        assert "Mac" not in embedding_health.sentence(kind, platform="linux")


# --- D6: the handshake names the bank as the CLI does, and the server -------------------------------------------------

def _legacy_root(tmp_path) -> Path:
    import yaml

    root = tmp_path / "memory"
    root.mkdir()
    (root / "banks.yaml").write_text(yaml.safe_dump({"active": "default", "banks": {
        "default": {"legacy": True, "id": "a" * 32, "created_at": "2026-10-22"}}}))
    return root


def test_d6_the_now_line_says_the_roster_s_name_never_the_folder(tmp_path):
    from api.services import handshake

    root = _legacy_root(tmp_path)
    text, _meta = handshake.load_or_build(root, "claude-code", cache_dir=tmp_path / "cache")
    assert "Bank `default`" in text and "Bank `memory`" not in text and " on " not in text.split("Bank `")[1][:40]


def test_d6_a_client_s_primer_names_the_server_within_the_cap(tmp_path):
    from api.services import handshake

    root = _legacy_root(tmp_path)
    text, _meta = handshake.load_or_build(root, "claude-code", cache_dir=tmp_path / "cache",
                                          bank_name="default", server="cicada.example.ts.net")
    assert "Bank `default` on cicada.example.ts.net" in text
    assert len(text) // 4 <= handshake.MAX_TOKENS
    other, _ = handshake.load_or_build(root, "claude-code", cache_dir=tmp_path / "cache", bank_name="default",
                                       server="127.0.0.1:52101")
    assert "Bank `default` on 127.0.0.1:52101" in other and other != text   # two servers never read the same
    cli_text = handshake.build_cli(None, commands=frozenset({"recall"}), bank="default", server="srv.example")
    assert "Bank `default` on srv.example" in cli_text


def test_d6_the_door_takes_only_a_host_for_the_server():
    from api.services import tool_door

    assert tool_door._server({"server": "cicada.example.ts.net"}) == "cicada.example.ts.net"
    for bad in ("/Users/example/memory", "user@host", "", None, "x" * 300):
        assert tool_door._server({"server": bad}) is None


# --- D7: a running session is told when its memory moved -------------------------------------------------------------

class _Resp:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode()

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_d7_the_first_reply_after_a_switch_says_so_once(tmp_path, monkeypatch):
    from api.services import runtime_layout, tool_client

    answers = {"https://a.example.ts.net": {"text": "found alpha-project", "bank": "default", "bankId": "id-a"},
               "https://b.example.ts.net": {"text": "found beta-project", "bank": "default", "bankId": "id-b"}}

    class Opener:
        def open(self, req, timeout=None):
            return _Resp(answers[req.full_url.rsplit("/tools/call", 1)[0]])

    monkeypatch.setattr(runtime_layout, "opener", lambda: Opener())
    home = tmp_path / "ch"
    home.mkdir()
    (home / "device_token").write_text("cic_dev_test")

    def call(base):
        env = {"CICADA_HOME": str(home), "CICADA_API_BASE": base}
        return tool_client.call("cicada_recall", {"query": "x"}, caller={}, state={}, environ=env)["text"]

    assert call("https://a.example.ts.net") == "found alpha-project"
    assert call("https://a.example.ts.net") == "found alpha-project"
    switched = call("https://b.example.ts.net")
    first, rest = switched.split("\n\n", 1)
    assert first == ("Cicada: memory now comes from b.example.ts.net/default, not a.example.ts.net/default — "
                     "what you recalled earlier in this conversation came from the other one.")
    assert rest == "found beta-project"
    assert call("https://b.example.ts.net") == "found beta-project"          # once
    assert tool_client.where_changed((tool_client.THIS_MACHINE, "", "")).startswith(
        "Cicada: memory now comes from this machine, not b.example.ts.net/default")
