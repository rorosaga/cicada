"""G180 parity — the app's commands from a shell (`api/cli_app.py`).

Commands that act on state the running backend owns go to its HTTP API with the token and name the CLI's pinned
bank on every write; reads of the bank run in process and work with the backend down; commands that act as the
person refuse from an agent's shell. Every backend here is a fake on an ephemeral loopback port — never 8000, never
a real bank."""
from __future__ import annotations

import json
import os
import shutil
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from _cli import free_port
from _intake_fixtures import CHAT_HTML, chatgpt_conversations, gemini_activity_html
from _synthetic_bank import _bank
from api.services import cli_map

TOKEN = "test-token-not-real"
SESSION_KEYS = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PROJECT_DIR", "CICADA_SESSION_ID", "CICADA_SESSION_HARNESS",
                "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_SANDBOX")
_SAME = object()


@contextmanager
def fake_backend(memory_root: str, routes: dict | None = None, *, health_delay: float = 0.0,
                 health_status: int = 200, health_root=_SAME):
    """A synthetic backend: `/healthz` names ``memory_root`` (or ``health_root``; None leaves it out), after
    ``health_delay`` seconds; ``routes`` maps (METHOD, path) → (status, body). Every other request is recorded
    (method, path with query, headers, body bytes)."""
    seen: list[dict] = []
    table = dict(routes or {})

    class Handler(BaseHTTPRequestHandler):
        def _answer(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                if health_delay:
                    import time

                    time.sleep(health_delay)
                root = memory_root if health_root is _SAME else health_root
                status, payload = health_status, {"status": "ok", "version": "9.9.9",
                                                  **({"memoryRoot": root} if root is not None else {})}
            else:
                seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers),
                             "body": body})
                status, payload = table.get((self.command, path), (200, {}))
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _answer  # noqa: N815 - http.server API

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # `shutdown()` waits for the loop's next poll: the default 0.5 s was most of every test here (suite cut 2).
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        server.seen = seen
        server.routes = table
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def _template(tmp_path_factory):
    """The synthetic bank, built (files + git) once for the module; `env` hands each test its own copy."""
    return _bank(tmp_path_factory.mktemp("cli-app-template"), git=True)


@pytest.fixture
def env(tmp_path, monkeypatch, _template):
    from api.config import Settings, get_settings

    before = Settings.model_config.get("env_file")
    memory = tmp_path / _template.name
    shutil.copytree(_template, memory, symlinks=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_MEMORY_ROOT", raising=False)
    monkeypatch.setenv("CICADA_PORT", str(free_port()))
    monkeypatch.setenv("CICADA_API_TOKEN", TOKEN)
    monkeypatch.setenv("LITELLM_MODE", "PRODUCTION")
    for key in SESSION_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield memory
    Settings.model_config["env_file"] = before
    get_settings.cache_clear()


def _run(argv, capsys):
    from api import cli

    code = cli.main([*argv, "--json"])
    out = capsys.readouterr()
    assert out.err == "", out.err
    return code, json.loads(out.out)


@contextmanager
def _backend(env, monkeypatch, routes=None, **health):
    with fake_backend(os.path.realpath(env), routes, **health) as server:
        monkeypatch.setenv("CICADA_PORT", str(server.server_address[1]))
        yield server


def _json(req) -> dict | None:
    return json.loads(req["body"]) if req["body"] else None


# --- each backend command sends the app's own request ----------------------------------------------------

BACKEND_CASES = [
    # argv, method, path, body sent, response
    (["sleep", "status"], "GET", "/sleep/status", None, {"status": "idle", "writing": False}),
    (["sleep", "start"], "POST", "/sleep/trigger", None, {"status": "started", "message": "Sleep cycle initiated"}),
    (["sleep", "start", "--continue"], "POST", "/sleep/trigger", {"continue": True},
     {"status": "started", "message": "Sleep run resumed"}),
    (["sleep", "stop"], "POST", "/sleep/cancel", None, {"status": "not_running", "message": "No sleep cycle"}),
    (["sleep", "end"], "POST", "/sleep/run/end", None, {"status": "none", "message": "There is no paused run."}),
    (["index", "rebuild"], "POST", "/maintenance/search-index/rebuild", None, {"state": "ready", "documents": 3}),
    (["index", "use", "default"], "POST", "/embeddings/choice", {"model": None}, {"model": "m", "reindex": {}}),
    (["index", "install", "--model", "gemma-x"], "POST", "/embeddings/install", {"model": "gemma-x"},
     {"model": "m", "install": {"state": "downloading"}}),
    (["feed", "add", "https://example.com/feed.xml", "--tag", "news"], "POST", "/sources/feeds",
     {"url": "https://example.com/feed.xml", "tags": ["news"]}, {"url": "https://example.com/feed.xml"}),
    (["feed", "remove", "https://example.com/feed.xml"], "DELETE", "/sources/feeds",
     {"url": "https://example.com/feed.xml"}, {"status": "ok"}),
    (["feed", "poll"], "POST", "/sources/poll-feeds", None, {"polled": 0}),
    # Ruling 45: the person's own project, from their own shell.
    (["projects", "new", "Alpha Garden", "--description", "Beds by the fence."], "POST", "/projects",
     {"name": "Alpha Garden", "description": "Beds by the fence.", "via": "cli"},
     {"id": "alpha-garden", "action": "created", "mine": True}),
    (["page", "decay", "alpha-project", "durable"], "PUT", "/entities/alpha-project/decay",
     {"decayClass": "durable"}, {"decayClass": "durable"}),
    (["inbox", "answer", "inbox-001", "--option", "keep"], "POST", "/inbox/inbox-001/resolve",
     {"action": "resolve", "optionKey": "keep"}, {"status": "resolved"}),
    (["inbox", "answer", "inbox-001", "--defer", "--days", "3"], "POST", "/inbox/inbox-001/resolve",
     {"action": "defer", "remindDays": 3}, {"status": "deferred", "remindAfter": "2026-10-12"}),
    (["inbox", "answer", "inbox-002", "--reject"], "POST", "/inbox/inbox-002/resolve", {"action": "reject"},
     {"status": "resolved"}),
    (["picture", "initials", "bob-example"], "POST", "/entities/bob-example/picture/initials", None,
     {"entityId": "bob-example", "pictureSource": "initials"}),
    (["picture", "clear", "bob-example"], "DELETE", "/entities/bob-example/picture", None,
     {"entityId": "bob-example", "pictureSource": None}),
    (["bank", "use", "beta"], "POST", "/banks/beta/activate", None, {"banks": [], "active": "beta"}),
    (["bank", "create", "beta", "--description", "a test"], "POST", "/banks",
     {"name": "beta", "description": "a test"}, {"banks": [], "active": "default"}),
    (["bank", "rename", "beta", "gamma"], "POST", "/banks/beta/rename", {"newName": "gamma"},
     {"banks": [], "active": "default"}),
    (["bank", "delete", "beta"], "DELETE", "/banks/beta", None, {"banks": [], "active": "default",
                                                               "trashedTo": ".trash/beta"}),
]

#: Bank CRUD names its own bank: the backend never checks it against the active one (`bank_binding.EXEMPT`).
NO_BANK_HEADER = {"/banks", "/banks/beta/activate", "/banks/beta/rename", "/banks/beta"}


@pytest.mark.parametrize("argv,method,path,body,response", BACKEND_CASES, ids=lambda v: str(v)[:40])
def test_each_backend_command_sends_the_apps_request(env, monkeypatch, capsys, argv, method, path, body, response):
    with _backend(env, monkeypatch, {(method, path): (200, response)}) as server:
        code, out = _run(argv, capsys)
    assert code == 0 and out["ok"] is True, out
    if argv[:2] == ["page", "decay"]:     # the page itself is not echoed: only what changed
        assert out["data"] == {"entity_id": "alpha-project", "decay_class": "durable"}
    else:
        assert out["data"] == response
    sent = [r for r in server.seen]
    assert len(sent) == 1, sent
    req = sent[0]
    assert (req["method"], req["path"].split("?")[0]) == (method, path)
    assert _json(req) == body
    assert req["headers"].get("Authorization") == f"Bearer {TOKEN}"
    bank_header = req["headers"].get("X-Cicada-Bank")
    if method == "GET" or path in NO_BANK_HEADER:
        assert bank_header is None
    else:
        assert bank_header == out["bank"]          # the bank this command pinned, as the app names it


def test_a_bank_name_is_percent_encoded_like_the_apps(env, monkeypatch):
    from types import SimpleNamespace

    from api import cli_app

    with _backend(env, monkeypatch, {("POST", "/sleep/cancel"): (200, {"status": "not_running"})}) as server:
        boot = SimpleNamespace(probe={"state": "confirmed"}, backend_url=f"http://127.0.0.1:{server.server_address[1]}",
                               pin=SimpleNamespace(name="my memory é"))
        cli_app.call(boot, "POST", "/sleep/cancel")
    assert server.seen[0]["headers"]["X-Cicada-Bank"] == "my%20memory%20%C3%A9"


# --- reads and writes that merge ----------------------------------------------------------------------------

def test_sleep_schedule_reads_then_merges_a_change(env, monkeypatch, capsys):
    current = {"mode": "manual", "enabled": False, "hour": 3, "minute": 0, "intervalHours": 6}
    with _backend(env, monkeypatch, {("GET", "/sleep/schedule"): (200, current),
                                     ("PUT", "/sleep/schedule"): (200, {**current, "mode": "daily", "hour": 4,
                                                                        "minute": 30, "enabled": True})}) as server:
        code, out = _run(["sleep", "schedule"], capsys)
        assert code == 0 and "only when started" in out["text"] and len(server.seen) == 1
        code, out = _run(["sleep", "schedule", "--at", "04:30"], capsys)
    assert code == 0 and "04:30" in out["text"]
    put = server.seen[-1]
    assert put["method"] == "PUT"
    assert _json(put) == {"mode": "daily", "hour": 4, "minute": 30, "intervalHours": 6}


@pytest.mark.parametrize("argv", [["sleep", "schedule", "--at", "25:00"], ["sleep", "schedule", "--every", "0"],
                                  ["sleep", "options", "--continue-after-reset", "maybe"]])
def test_bad_values_are_usage_errors_before_anything_is_sent(env, monkeypatch, capsys, argv):
    with _backend(env, monkeypatch) as server:
        code, out = _run(argv, capsys)
    assert code == 2 and out["code"] == "usage" and server.seen == []


def test_sleep_engine_and_options_change_through_the_backend(env, monkeypatch, capsys):
    engine = {"mode": "byok", "model": "m-1", "source": "prefs"}
    opts = {"batchSize": 25, "continueAfterReset": False, "reservePct": None}
    with _backend(env, monkeypatch, {("GET", "/sleep/engine"): (200, engine),
                                     ("PUT", "/sleep/engine"): (200, {**engine, "model": "m-2"}),
                                     ("PUT", "/sleep/run-options"): (200, {**opts, "batchSize": 10})}) as server:
        code, out = _run(["sleep", "engine", "--model", "m-2"], capsys)
        assert code == 0 and "m-2" in out["text"]
        assert _json(server.seen[-1]) == {"mode": "byok", "model": "m-2"}
        code, out = _run(["sleep", "options", "--batch-size", "10", "--reserve", "off"], capsys)
    assert code == 0 and "Batch size 10" in out["text"]
    assert _json(server.seen[-1]) == {"batchSize": 10, "reservePct": None}


def test_settings_owner_keeps_what_it_was_not_given(env, monkeypatch, capsys):
    owner = {"name": "Alex Example", "handle": "alex", "email": None}
    with _backend(env, monkeypatch, {("GET", "/settings/owner"): (200, owner),
                                     ("PUT", "/settings/owner"): (200, {**owner, "email": "a@example.com"})}) as server:
        code, out = _run(["settings", "owner"], capsys)
        assert code == 0 and len(server.seen) == 1
        code, out = _run(["settings", "owner", "--email", "a@example.com"], capsys)
    assert code == 0
    assert _json(server.seen[-1]) == {"name": "Alex Example", "handle": "alex", "email": "a@example.com"}


def test_index_status_reads_the_word_index_and_the_model(env, monkeypatch, capsys):
    with _backend(env, monkeypatch, {("GET", "/maintenance/search-index"): (200, {"state": "ready"}),
                                     ("GET", "/embeddings"): (200, {"model": "small", "models": [{"id": "small"}]})}):
        code, out = _run(["index", "status"], capsys)
    assert code == 0 and out["data"]["index"] == {"state": "ready"} and "small" in out["text"]


# --- the backend's refusals are typed ----------------------------------------------------------------------

def test_with_the_backend_down_a_backend_command_refuses_and_sends_nothing(env, capsys):
    code, out = _run(["sleep", "start"], capsys)
    assert code == 6 and out["ok"] is False and out["code"] == "backend_down"
    assert "Nothing was changed" in out["text"]


def test_a_backend_serving_another_folder_is_refused(env, monkeypatch, capsys, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    with fake_backend(str(other)) as server:
        monkeypatch.setenv("CICADA_PORT", str(server.server_address[1]))
        code, out = _run(["sleep", "stop"], capsys)
    assert code == 3 and out["code"] == "root_mismatch" and server.seen == []


@pytest.mark.parametrize("status,payload,code,exit_code", [
    (409, {"code": "sleep_writing", "detail": "Sleep is updating your memory."}, "sleep_writing", 1),
    (409, {"code": "bank_mismatch", "detail": "Memory switched"}, "bank_mismatch", 3),
    (409, {"detail": "A run is reading right now — pause it first."}, "refused", 1),
    (404, {"detail": "Entity x not found"}, "not_found", 1),
    (401, {"detail": "no"}, "unauthorized", 1),
    (500, {"detail": "boom"}, "backend_error", 70),
])
def test_backend_refusals_become_typed_codes(env, monkeypatch, capsys, status, payload, code, exit_code):
    with _backend(env, monkeypatch, {("POST", "/sleep/run/end"): (status, payload)}):
        got, out = _run(["sleep", "end"], capsys)
    assert got == exit_code and out["code"] == code and out["ok"] is False
    if code in ("sleep_writing", "refused"):
        assert payload["detail"].split(" —")[0] in out["text"]


def test_a_422_is_a_usage_error_with_the_backends_sentence(env, monkeypatch, capsys):
    with _backend(env, monkeypatch, {("PUT", "/entities/alpha-project/decay"): (422, {"detail": "bad class"})}):
        code, out = _run(["page", "decay", "alpha-project", "sometimes"], capsys)
    assert code == 2 and out["code"] == "usage" and out["text"] == "bad class"


# --- the person-only rule ---------------------------------------------------------------------------------

PERSON_ARGV = {
    "page decay": ["page", "decay", "alpha-project", "durable"],
    "inbox answer": ["inbox", "answer", "inbox-001", "--option", "keep"],
    "sleep start": ["sleep", "start"],
    "sleep schedule": ["sleep", "schedule", "--at", "04:00"],
    "index use": ["index", "use", "default"],
    "import": ["import", "PICTURE"],
    "sleep engine": ["sleep", "engine", "--model", "m-2"],
    "sleep options": ["sleep", "options", "--batch-size", "10"],
    "index install": ["index", "install", "--model", "x"],
    "feed poll": ["feed", "poll"],
    "projects new": ["projects", "new", "Alpha Garden"],
    "settings owner": ["settings", "owner", "--name", "Alex Example"],
    "picture set": ["picture", "set", "bob-example", "PICTURE"],
    "picture initials": ["picture", "initials", "bob-example"],
    "picture clear": ["picture", "clear", "bob-example"],
    "bank use": ["bank", "use", "beta"],
    "bank rename": ["bank", "rename", "beta", "gamma"],
    "bank delete": ["bank", "delete", "beta"],
    # The Skills page (2026-10-15): installing, updating and toggling skills are the person's.
    "skills check": ["skills", "check"],
    "skills add": ["skills", "add", "alice-example/handy-skills", "--yes"],
    "skills install": ["skills", "install", "macos-harness"],
    "skills update": ["skills", "update", "release-notes"],
    "skills update-all": ["skills", "update-all"],
    "skills on": ["skills", "on", "release-notes", "codex"],
    "skills off": ["skills", "off", "release-notes", "codex"],
    "skills refresh": ["skills", "refresh", "macos-harness"],
    "skills remove": ["skills", "remove", "release-notes"],
    "skills publish": ["skills", "publish", "release-notes", "--agent", "codex"],
    "device add": ["device", "add", "laptop"],
    "device revoke": ["device", "revoke", "ab12cd34"],
    "device pair": ["device", "pair"],
    "agent add": ["agent", "add", "Texting Agent"],
    "setup": ["setup"],
    "agent revoke": ["agent", "revoke", "ab12cd34"],
    "engine connect": ["engine", "connect", "claude-plan"],
    "connector connect": ["connector", "connect", "readwise"],
    "connector disconnect": ["connector", "disconnect", "readwise"],
    "connector sync": ["connector", "sync", "readwise"],
    "maintenance move-watched-rows": ["maintenance", "move-watched-rows", "--apply"],
}


def test_every_person_row_is_exercised_here():
    assert {r.name for r in cli_map.rows() if r.person} == set(PERSON_ARGV)


@pytest.mark.parametrize("name", sorted(PERSON_ARGV))
@pytest.mark.parametrize("identity", [{"CLAUDE_CODE_SESSION_ID": "11111111-2222-4333-8444-555555555555"},
                                      {"CICADA_SESSION_HARNESS": "codex"},
                                      {"CODEX_THREAD_ID": "0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"},
                                      {"CODEX_SANDBOX": "seatbelt"}])
def test_a_person_command_refuses_from_an_agents_shell(env, monkeypatch, capsys, tmp_path, name, identity):
    picture = tmp_path / "p.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    argv = [str(picture) if a == "PICTURE" else a for a in PERSON_ARGV[name]]
    for key, value in identity.items():
        monkeypatch.setenv(key, value)
    with _backend(env, monkeypatch, {("GET", "/sleep/engine"): (200, {"mode": "byok"}),
                                     ("GET", "/sleep/schedule"): (200, {"mode": "manual", "hour": 3, "minute": 0}),
                                     ("GET", "/settings/owner"): (200, {"name": ""}),
                                     ("GET", "/embeddings"): (200, {"model": "m"})}) as server:
        code, out = _run(argv, capsys)
    assert code == 1 and out["code"] == "person_only", out
    assert all(r["method"] == "GET" for r in server.seen), server.seen   # nothing was changed


def test_reading_a_person_row_without_changing_it_is_allowed_from_an_agents_shell(env, monkeypatch, capsys):
    monkeypatch.setenv("CICADA_SESSION_HARNESS", "codex")
    with _backend(env, monkeypatch, {("GET", "/sleep/engine"): (200, {"mode": "byok", "model": "m"})}):
        code, out = _run(["sleep", "engine"], capsys)
    assert code == 0 and out["ok"] is True


def test_the_watched_rows_dry_run_reads_and_names_only_ids_and_counts(env, monkeypatch, capsys):
    """Speed 2026-10-29: the move waits for the person's --apply; the dry run is a read, allowed from any shell."""
    monkeypatch.setenv("CICADA_SESSION_HARNESS", "codex")
    plan = {"days": 3, "rows": 40, "rows_files_kept": 1, "applied": False, "sample": ["ep_2026-10-14_002"]}
    with _backend(env, monkeypatch, {("GET", "/maintenance/watched-rows"): (200, plan)}) as server:
        code, out = _run(["maintenance", "move-watched-rows"], capsys)
    assert code == 0 and out["data"] == plan and [r["method"] for r in server.seen] == ["GET"]


# --- imports and pictures send the file's bytes -------------------------------------------------------------

def test_picture_set_uploads_the_file_as_the_apps_form_field(env, monkeypatch, capsys, tmp_path):
    picture = tmp_path / "face.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    with _backend(env, monkeypatch, {("POST", "/entities/bob-example/picture"): (200, {"pictureSource": "upload"})}) \
            as server:
        code, out = _run(["picture", "set", "bob-example", str(picture)], capsys)
    assert code == 0, out
    req = server.seen[0]
    assert req["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="face.png"' in req["body"] and b"\x89PNG\r\n\x1a\nfake" in req["body"]


def test_import_waits_for_a_background_job(env, monkeypatch, capsys, tmp_path):
    export = tmp_path / "conversations.json"
    export.write_text(json.dumps(chatgpt_conversations(2)))
    with _backend(env, monkeypatch, {("POST", "/intake/import"): (202, {"job": {"id": "job-1"}}),
                                     ("GET", "/intake/jobs/job-1"): (200, {"id": "job-1", "done": True, "created": 12,
                                                                           "updated": 1, "skipped": 2})}) as server:
        code, out = _run(["import", str(export)], capsys)
    assert code == 0 and "12 new" in out["text"]
    assert [r["path"] for r in server.seen] == ["/intake/import", "/intake/jobs/job-1"]
    assert server.seen[0]["headers"]["X-Cicada-Bank"] == out["bank"]


def test_import_preview_only_sniffs(env, monkeypatch, capsys, tmp_path):
    export = tmp_path / "conversations.json"
    export.write_text(json.dumps(chatgpt_conversations(2)))
    sniff = {"recognized": True, "kind": "chat", "vendor": "chatgpt", "delta": {"new": 3, "grown": 0, "unchanged": 1}}
    with _backend(env, monkeypatch, {("POST", "/intake/sniff"): (200, sniff)}) as server:
        code, out = _run(["import", str(export), "--preview"], capsys)
    assert code == 0 and "3 new" in out["text"] and [r["path"] for r in server.seen] == ["/intake/sniff"]


def test_import_never_reads_a_file_under_the_harness_transcript_folder(env, monkeypatch, capsys, tmp_path):
    home = tmp_path / "h"
    transcript = home / ".claude" / "projects" / "x" / "s.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    with _backend(env, monkeypatch) as server:
        code, out = _run(["import", str(transcript)], capsys)
    assert code == 1 and out["code"] == "refused" and server.seen == []


# --- reads of the bank run here, with the backend down ------------------------------------------------------

def test_page_list_and_graph_read_the_bank_with_the_backend_down(env, capsys):
    code, out = _run(["page", "list", "--type", "project"], capsys)
    assert code == 0
    assert {p["id"] for p in out["data"]["pages"]} >= {"alpha-project", "beta-project"}
    assert all(p["type"] == "project" for p in out["data"]["pages"])
    code, out = _run(["graph"], capsys)
    assert code == 0 and out["data"]["pages"] >= 5 and out["data"]["by_type"]["project"] >= 2


def test_coverage_reads_the_bank_and_names_no_page_unless_asked(env, capsys):
    code, out = _run(["coverage", "pictures"], capsys)
    assert code == 0 and out["data"]["pages"] >= 4 and "ids" not in out["data"]
    # Owner 2026-10-28 (E): a project with no trusted site or repository says so, like a brand.
    assert out["data"]["by_type"]["project"]["none"] == {"no_site": 2}
    assert out["data"]["by_type"]["person"]["none"] == {"no_identifier": 1}
    code, out = _run(["coverage", "sources", "--ids"], capsys)
    assert code == 0 and "bob-example" in out["data"]["ids"]["none/person"]


def test_inbox_all_lists_every_kind_and_hides_deferred(env, capsys):
    code, out = _run(["inbox", "all"], capsys)
    assert code == 0
    ids = {i["id"] for i in out["data"]["items"]}
    assert "inbox-001" in ids and "inbox-002" not in ids          # inbox-002 is deferred to 2099
    code, out = _run(["inbox", "all", "--kind", "conflict"], capsys)
    assert out["data"]["items"] == []


def test_page_history_and_sleep_history_read_git(env, capsys):
    code, out = _run(["page", "history", "alpha-project"], capsys)
    assert code == 0 and len(out["data"]["history"]) == 1
    code, out = _run(["page", "history", "no-such-page"], capsys)
    assert code == 1 and out["code"] == "not_found"
    code, out = _run(["sleep", "history"], capsys)
    assert code == 0 and isinstance(out["data"]["runs"], list)


def test_bank_and_feed_lists_read_the_bank(env, capsys):
    code, out = _run(["bank", "list"], capsys)
    assert code == 0 and out["data"]["active"] == out["bank"]
    code, out = _run(["feed", "list"], capsys)
    assert code == 0 and out["data"] == {"feeds": [], "total": 0}


def test_find_and_timeline_read_the_bank(env, capsys):
    code, out = _run(["find", "alpha"], capsys)
    assert code == 0 and "alpha-project" in out["text"]
    code, out = _run(["timeline", "--since", "30d"], capsys)
    assert code == 0 and out["command"] == "timeline"


def test_find_with_no_kind_never_asks_for_pictures(env, monkeypatch, capsys):
    """Hyrum (review of #506): `cicada find` with no `--kind` is every kind it was before pictures existed; pictures
    come only when named (`--kind image`), as `GET /search` serves them."""
    from api.services import image_index, search_service

    asked: list[list[str]] = []
    real = search_service.search

    def spy(memory_path, q, **kw):
        asked.append(list(kw.get("kinds") or []))
        return real(memory_path, q, **kw)

    monkeypatch.setattr(search_service, "search", spy)
    monkeypatch.setattr(image_index, "search", lambda *a, **k: [])
    code, _out = _run(["find", "alpha"], capsys)
    assert code == 0 and asked[-1] == list(search_service.KINDS) and "image" not in asked[-1]
    code, _out = _run(["find", "alpha", "--kind", "image"], capsys)
    assert code == 0 and asked[-1] == ["image"]


def test_bank_reads_never_call_the_backend(env, monkeypatch, capsys):
    with _backend(env, monkeypatch) as server:
        for argv in (["page", "list"], ["graph"], ["inbox", "all"], ["bank", "list"], ["feed", "list"],
                     ["sleep", "history"], ["page", "history", "alpha-project"], ["coverage", "pictures"],
                     ["coverage", "sources", "--ids"]):
            code, out = _run(argv, capsys)
            assert code == 0, (argv, out)
    assert server.seen == []


# --- the table -----------------------------------------------------------------------------------------------

def test_every_exposed_row_has_a_handler_and_a_place():
    from api import cli

    for row in cli_map.exposed():
        assert row.name in cli.COMMANDS, row.name
        assert row.via in ("bank", "backend", "both"), row.name
        if row.app:
            assert row.tool is None and row.exposed
        if row.person:
            assert row.mutates and row.via in ("backend", "both"), row.name


def test_the_agent_skill_keeps_the_app_commands_out_of_its_table():
    block = cli_map.skill_block()
    assert "`cicada sleep start`" not in block and "cicada commands" in block


def test_the_person_s_own_terminal_is_not_an_agent_shell(env):
    from api import cli_app

    assert cli_app.agent_shell({}) is None
    assert cli_app.agent_shell({"CODEX_THREAD_ID": "  "}) is None
    assert cli_app.agent_shell({"CODEX_THREAD_ID": "t-1"}) == "codex"


# --- a write goes only to a backend that confirmed this command's memory root (ruling 21's split-brain guard) ------

WRITES = [["feed", "add", "https://example.com/feed.xml"], ["sleep", "stop"], ["bank", "create", "beta"]]


# The two slow-backend guards wait out a real 1.5 s health answer twice, so each checks one write (suite cut 2): the
# guard is one function for every write, and `…never_confirms…` below still walks every write in `WRITES`.
def test_a_slow_backend_serving_another_root_receives_no_write(env, monkeypatch, capsys, tmp_path):
    argv = ["bank", "create", "beta"]
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    with _backend(env, monkeypatch, health_delay=1.5, health_root=str(elsewhere)) as server:
        code, out = _run(argv, capsys)
    assert code == 3 and out["ok"] is False and out["code"] == "root_mismatch", out
    assert server.seen == []                       # the POST never left this process


def test_a_slow_backend_that_confirms_the_root_on_the_second_ask_gets_the_write(env, monkeypatch, capsys):
    argv = ["feed", "add", "https://example.com/feed.xml"]
    with _backend(env, monkeypatch, health_delay=1.5) as server:
        code, out = _run(argv, capsys)
    assert code == 0 and out["ok"] is True, out
    assert "root_unverified" not in out["warnings"]
    assert len(server.seen) == 1 and server.seen[0]["method"] in ("POST", "DELETE")


@pytest.mark.parametrize("health", [{"health_root": None}, {"health_status": 500}], ids=["no-root", "http-500"])
@pytest.mark.parametrize("argv", WRITES, ids=lambda a: " ".join(a[:2]))
def test_a_backend_that_never_confirms_the_root_receives_no_write(env, monkeypatch, capsys, argv, health):
    with _backend(env, monkeypatch, **health) as server:
        code, out = _run(argv, capsys)
    assert code == 3 and out["code"] == "root_unverified" and out["ok"] is False, out
    assert out["warnings"] == ["root_unverified"]  # the refusal keeps why the root could not be checked
    assert server.seen == []


def test_a_read_from_an_unverified_backend_proceeds_with_its_warning(env, monkeypatch, capsys):
    with _backend(env, monkeypatch, {("GET", "/sleep/status"): (200, {"status": "idle"})}, health_root=None):
        code, out = _run(["sleep", "status"], capsys)
    assert code == 0 and out["warnings"] == ["root_unverified"]


# --- more typed refusals -----------------------------------------------------------------------------------------

def test_a_demo_bank_capture_refusal_is_the_demo_exit(env, monkeypatch, capsys):
    from api.services import demo_guard

    with _backend(env, monkeypatch, {("POST", "/sources/feeds"): (409, {"detail": demo_guard.REFUSAL})}):
        code, out = _run(["feed", "add", "https://example.com/feed.xml"], capsys)
    assert code == 4 and out["code"] == "demo_bank" and out["text"] == demo_guard.REFUSAL


def test_a_picture_over_the_servers_bound_is_refused_with_its_sentence(env, monkeypatch, capsys, tmp_path):
    picture = tmp_path / "big.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    sentence = "That picture is too large — Cicada keeps pictures under 512 KB."
    with _backend(env, monkeypatch, {("POST", "/entities/bob-example/picture"): (413, {"detail": sentence})}):
        code, out = _run(["picture", "set", "bob-example", str(picture)], capsys)
    assert code == 1 and out["code"] == "refused" and out["text"] == sentence


def test_index_install_without_a_recommendation_sends_nothing(env, monkeypatch, capsys):
    with _backend(env, monkeypatch, {("GET", "/embeddings"): (200, {"model": "m", "recommended": None,
                                                                     "nextModel": None})}) as server:
        code, out = _run(["index", "install"], capsys)
    assert code == 1 and out["code"] == "refused"
    assert [r["method"] for r in server.seen] == ["GET"]


def test_an_import_that_outlasts_the_wait_never_says_imported(env, monkeypatch, capsys, tmp_path):
    from api import cli_app

    monkeypatch.setattr(cli_app, "JOB_WAIT_MAX_S", 0.3)
    monkeypatch.setattr(cli_app, "JOB_POLL_S", 0.05)
    export = tmp_path / "conversations.json"
    export.write_text(json.dumps(chatgpt_conversations(2)))
    with _backend(env, monkeypatch, {("POST", "/intake/import"): (202, {"job": {"id": "job-1"}}),
                                     ("GET", "/intake/jobs/job-1"): (200, {"id": "job-1", "done": False, "staged": 4,
                                                                           "total": 40})}):
        code, out = _run(["import", str(export)], capsys)
    assert code == 6 and out["code"] == "backend_timeout" and "Imported" not in out["text"]
    assert "still running" in out["text"]


# --- one `import`: a chat export goes to the backend's intake, a platform export is read here (#262) -------------

def _x_archive(path):
    import io
    import zipfile

    likes = "window.YTD.like.part0 = " + json.dumps([
        {"like": {"tweetId": "1000000000000000011", "fullText": "alpha-project ships"}}])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data/like.js", likes)
    path.write_bytes(buf.getvalue())
    return path


def test_a_platform_export_is_read_here_and_never_sent_to_the_backend(env, monkeypatch, capsys, tmp_path):
    archive = _x_archive(tmp_path / "twitter-archive.zip")
    with _backend(env, monkeypatch) as server:
        code, out = _run(["import", str(archive)], capsys)
    assert code == 0 and out["data"]["created"] == 1, out
    assert server.seen == []


def test_a_chat_export_goes_to_the_backends_intake(env, monkeypatch, capsys, tmp_path):
    export = tmp_path / "conversations.json"
    export.write_text(json.dumps(chatgpt_conversations(2)))
    with _backend(env, monkeypatch, {("POST", "/intake/import"): (200, {"episodesStaged": 2})}) as server:
        code, out = _run(["import", str(export)], capsys)
    assert code == 0 and "2 new" in out["text"]
    assert [r["path"] for r in server.seen] == ["/intake/import"]


@pytest.mark.parametrize("kind", ["chat", "platform"])
def test_both_import_branches_are_person_only(env, monkeypatch, capsys, tmp_path, kind):
    if kind == "chat":
        path = tmp_path / "conversations.json"
        path.write_text(json.dumps(chatgpt_conversations(2)))
    else:
        path = _x_archive(tmp_path / "twitter-archive.zip")
    monkeypatch.setenv("CODEX_THREAD_ID", "t-1")
    with _backend(env, monkeypatch) as server:
        code, out = _run(["import", str(path)], capsys)
    assert code == 1 and out["code"] == "person_only" and server.seen == []
    assert not list((env / "entities").glob("media-*.md"))


def test_a_preview_of_either_branch_is_allowed_from_an_agents_shell(env, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CODEX_THREAD_ID", "t-1")
    code, out = _run(["import", str(_x_archive(tmp_path / "twitter-archive.zip")), "--preview"], capsys)
    assert code == 0 and out["data"]["total"] == 1


@pytest.mark.parametrize("name,page", [
    ("chat.html", CHAT_HTML),
    ("MyActivity.html", gemini_activity_html((("example.com opening hours", None, "Jan 5, 2026, 9:00:00 AM PST"),),
                                             product="Search", verb="Searched for")),
], ids=["chatgpt-viewer", "takeout-search-activity"])
def test_a_page_the_intake_refuses_for_good_is_never_read_as_saved_items(env, monkeypatch, capsys, tmp_path, name,
                                                                          page):
    from api.routers import intake

    path = tmp_path / name
    path.write_text(page)
    with _backend(env, monkeypatch) as server:
        code, out = _run(["import", str(path)], capsys)
    assert code == 1 and out["code"] == "refused" and out["text"] in intake.FINAL_REFUSALS, out
    assert server.seen == [] and not list((env / "entities").glob("media-*.md"))


# --- skills (the Skills page, 2026-10-15) -------------------------------------------------------------------

def test_skills_add_shows_first_and_installs_only_with_yes(env, monkeypatch, capsys):
    preview = {"planId": "p1", "name": "release-notes", "description": "Writes release notes.", "agents": ["codex"],
               "files": [{"path": "SKILL.md", "size": 10, "script": False}], "scripts": [],
               "repo": {"repo": "alice-example/handy-skills", "commit": "a" * 40, "licence": "MIT"}}
    routes = {("POST", "/skills/preview"): (200, preview),
              ("POST", "/skills/install"): (200, {"name": "release-notes", "agents": ["codex"]})}
    with _backend(env, monkeypatch, routes) as server:
        code, out = _run(["skills", "add", "alice-example/handy-skills"], capsys)
        assert code == 0 and "Nothing installed" in out["text"] and "aaaaaaa" in out["text"]
        assert [r["path"] for r in server.seen] == ["/skills/preview"]
        code, out = _run(["skills", "add", "alice-example/handy-skills", "--yes"], capsys)
    assert code == 0 and "Installed for codex" in out["text"]
    install = server.seen[-1]
    assert install["path"] == "/skills/install" and _json(install) == {"planId": "p1", "agents": ["codex"]}


def test_an_agent_drafts_a_skill_from_its_shell_and_nothing_installs(env, monkeypatch, capsys):
    from api.services import skill_store

    monkeypatch.setenv("CICADA_SESSION_HARNESS", "codex")
    code, out = _run(["skills", "create", "release-notes", "Writes release notes.", "Read the log."], capsys)
    assert code == 0 and "held" in out["text"]
    assert [d["name"] for d in skill_store.drafts()] == ["release-notes"]
    code, out = _run(["skills", "propose", "install", "You asked for it.", "--source", "alice-example/handy-skills"],
                     capsys)
    assert code == 0 and out["text"].startswith("Filed for the person")
