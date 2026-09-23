"""G141 capture-side track (R-CS10..R-CS14): a demo bank knows it is one, and
capture never writes a real conversation into it — the Stop hook saves into the
real bank left most recently (or answers 409); the MCP write tools and Telegram
refuse in plain words. The generator still writes its own made-up episodes.
Synthetic banks and transcripts only."""
from __future__ import annotations

import asyncio
import io
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _stdio_server import stdio_server
from api import config, main
from api.hooks import capture as hook
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import (bank_registry, demo_bank, demo_guard, mcp_tools, telegram_capture, telemetry,
                          transcript_capture as tc)

SID = "44444444-2222-4333-8444-555555555555"


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True).stdout


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    return root


def _demo(root: Path) -> Path:
    """A registered demo bank, marked the way the generator marks it — without
    populate's few seconds of git, which one test below covers."""
    slug = bank_registry.create_bank(root, "demo")
    path = bank_registry.bank_dir(root, slug)
    demo_guard.write_manifest(path)
    return path


def _open_demo_without_stamps(root: Path) -> None:
    """A registry from before `last_active_at` existed: the demo is active and
    no bank carries a stamp."""
    reg = bank_registry.load_registry(root)
    reg["active"] = "demo"
    bank_registry.save_registry(root, reg)


def _loose_demo(tmp_path: Path) -> Path:
    bank = tmp_path / "loose-demo"
    bank_registry.scaffold_bank(bank, git_init=False)
    demo_guard.write_manifest(bank)
    return bank


def _files(bank: Path) -> set[str]:
    return {p.relative_to(bank).as_posix() for p in bank.rglob("*") if p.is_file() and ".git" not in p.parts}


def _episodes(bank: Path) -> list[str]:
    return sorted(p.name for p in (bank / "episodes").glob("ep_*.md"))


@pytest.fixture(autouse=True)
def _fresh_settings():
    yield
    config.get_settings.cache_clear()


def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    return TestClient(main.app)


# --- the marker (R-CS10) -----------------------------------------------------------


def test_the_generator_marks_its_bank_first_and_versions_the_mark(tmp_path):
    bank = tmp_path / "demo"
    bank_registry.scaffold_bank(bank)
    demo_bank.populate(bank)
    assert demo_guard.is_demo(bank)
    assert len(_episodes(bank)) >= 40  # the guard never stops the generator (R-CS17)
    assert _git(bank, "ls-files", demo_guard.MANIFEST).strip() == demo_guard.MANIFEST
    message = _git(bank, "log", "--format=%B", "--", demo_guard.MANIFEST)
    assert message.startswith("Demo bank") and "Cicada-Author: cicada" in message


def test_a_demo_generated_before_the_manifest_is_still_recognised(tmp_path):
    bank = tmp_path / "old-demo"
    bank_registry.scaffold_bank(bank)
    _git(bank, "config", "user.email", demo_guard.GENERATOR_EMAIL)
    assert demo_guard.is_demo(bank)


def test_a_real_bank_is_never_a_demo_even_when_named_demo(tmp_path):
    root = _root(tmp_path)
    path = bank_registry.bank_dir(root, bank_registry.create_bank(root, "demo"))
    assert not demo_guard.is_demo(path)
    (path / demo_guard.MANIFEST).write_text("kind: [unclosed", encoding="utf-8")
    assert not demo_guard.is_demo(path)  # a malformed manifest never blocks a real bank
    assert not demo_guard.is_demo(None) and not demo_guard.is_demo(tmp_path / "missing")


# --- which real bank was open last (R-CS11) ----------------------------------------


def test_activating_a_bank_stamps_the_one_it_leaves(tmp_path):
    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    bank_registry.activate_bank(root, "work")  # leaves default
    banks = bank_registry.load_registry(root)["banks"]
    stamp = banks["default"]["last_active_at"]
    assert stamp and "last_active_at" not in banks["work"]
    bank_registry.activate_bank(root, "work")  # re-activating stamps nothing
    banks = bank_registry.load_registry(root)["banks"]
    assert banks["default"]["last_active_at"] == stamp and "last_active_at" not in banks["work"]


def test_the_fallback_is_the_real_bank_left_most_recently(tmp_path):
    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    _demo(root)
    bank_registry.activate_bank(root, "work")  # leaves default
    bank_registry.activate_bank(root, "demo")  # leaves work — the most recent real bank
    assert bank_registry.most_recent_real_bank(root) == "work"
    target = bank_registry.capture_bank(root)
    assert (target.name, target.path, target.redirected_from) == (
        "work", bank_registry.bank_dir(root, "work"), "demo")


def test_without_stamps_one_real_bank_is_the_answer_and_two_are_never_guessed(tmp_path):
    root = _root(tmp_path)
    _demo(root)
    _open_demo_without_stamps(root)
    assert bank_registry.most_recent_real_bank(root) == "default"
    bank_registry.create_bank(root, "work")
    assert bank_registry.most_recent_real_bank(root) is None
    assert bank_registry.capture_bank(root) is None


def test_a_real_active_bank_is_its_own_capture_target(tmp_path):
    root = _root(tmp_path)
    target = bank_registry.capture_bank(root)
    assert (target.name, target.path, target.redirected_from) == ("default", root, None)


# --- the Stop hook (R-CS12) ---------------------------------------------------------


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    folder = tmp_path / "claude-projects" / "-home-example-alpha-project"
    folder.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: folder.parent)
    monkeypatch.setattr(tc, "_episode_cache", {})
    path = folder / f"{SID}.jsonl"
    path.write_text(json.dumps({"type": "user", "uuid": "u", "timestamp": "2026-09-23T09:00:00.000Z",
                                "sessionId": SID,
                                "message": {"role": "user", "content": "Should alpha-project ship Friday?"}})
                    + "\n", encoding="utf-8")
    return path


def _post(client: TestClient, transcript: Path):
    return client.post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                    "transcript_path": str(transcript)})


def test_the_stop_hook_saves_into_the_real_bank_left_last_while_the_demo_is_open(tmp_path, monkeypatch,
                                                                                    transcript):
    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    demo = _demo(root)
    bank_registry.activate_bank(root, "work")
    bank_registry.activate_bank(root, "demo")
    r = _post(_client(root, monkeypatch), transcript)
    assert r.status_code == 200, r.text
    assert (r.json()["bank"], r.json()["redirectedFrom"]) == ("work", "demo")
    assert len(_episodes(bank_registry.bank_dir(root, "work"))) == 1
    assert _episodes(demo) == [] and _episodes(root) == []


def test_with_no_real_bank_to_choose_the_hook_gets_409_and_nothing_is_written(tmp_path, monkeypatch,
                                                                               transcript):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    demo = _demo(root)
    _open_demo_without_stamps(root)  # two real banks and no stamp: never guess
    r = _post(_client(root, monkeypatch), transcript)
    assert r.status_code == 409 and r.json()["detail"] == demo_guard.HOOK_REFUSAL
    for bank in (root, bank_registry.bank_dir(root, "work"), demo):
        assert _episodes(bank) == []
    (ev,) = [e for e in telemetry.read_events() if e.kind == "capture"]
    assert ev.refs["status"] == "refused" and ev.refs["reason"] == "demo_bank"


def test_a_real_active_bank_is_named_and_nothing_is_redirected(tmp_path, monkeypatch, transcript):
    root = _root(tmp_path)
    r = _post(_client(root, monkeypatch), transcript)
    assert r.status_code == 200, r.text
    assert (r.json()["bank"], r.json()["redirectedFrom"]) == ("default", None)
    assert len(_episodes(root)) == 1


def test_the_service_refuses_a_demo_path_before_it_validates_anything(tmp_path):
    r = tc.capture_transcript(_loose_demo(tmp_path), harness="claude-code", session_id=SID,
                              transcript_path=str(tmp_path / "never-read.jsonl"), cwd=None,
                              keep_assistant=True)
    assert (r.status, r.reason) == ("refused", "demo_bank")  # not "not_a_file": nothing was checked


def test_the_hook_log_names_the_bank_a_redirected_session_went_to(tmp_path):
    token = tmp_path / "api_token"
    token.write_text("tok-123")
    log = tmp_path / "logs" / "capture.log"

    def post(url, body, tok, timeout):
        return 200, json.dumps({"status": "created", "bank": "work", "redirectedFrom": "demo"})

    payload = {"session_id": SID, "transcript_path": f"/home/example/.claude/projects/x/{SID}.jsonl",
               "cwd": "/home/example/alpha-project", "hook_event_name": "Stop"}
    rc = hook.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)), environ={},
                   post=post, log_path=log, token_path=token)
    assert rc == 0
    assert "http 200 created into work (the demo memory is open)" in log.read_text(encoding="utf-8")


# --- MCP, stdio and remote (R-CS13) --------------------------------------------------


def _ctx(bank: Path) -> mcp_tools.ToolContext:
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code")


WRITES = {
    "cicada_save_episode": lambda ctx: mcp_tools.save_episode(ctx, "Decided alpha-project ships Friday.", "T"),
    "cicada_save_url": lambda ctx: mcp_tools.save_url(ctx, "https://example.com/a", None),
    "cicada_record_watch": lambda ctx: mcp_tools.record_watch(ctx, "https://example.com/v", "A summary."),
    "cicada_write_claim": lambda ctx: mcp_tools.write_claim(ctx, "alpha-project", "uses", "tool-example-a",
                                                            None, None, None, None),
    "cicada_retract_claim": lambda ctx: mcp_tools.retract_claim(ctx, "alpha-project", "clm_x", "wrong"),
    "cicada_add_source": lambda ctx: mcp_tools.add_source(ctx, "alpha-project", "https://example.com/team"),
    "cicada_note_progress": lambda ctx: mcp_tools.note_progress(ctx, "alpha-project", "happening",
                                                                "Shipped the first build.", "done"),
}


def test_the_write_table_is_the_remote_catalogs():
    assert set(WRITES) == set(catalog.WRITE_TOOLS)


@pytest.mark.parametrize("tool", sorted(WRITES))
def test_every_mcp_write_tool_refuses_a_demo_bank_and_writes_nothing(tmp_path, tool):
    bank = _loose_demo(tmp_path)
    before = _files(bank)
    assert WRITES[tool](_ctx(bank)) == demo_guard.AGENT_REFUSAL
    assert _files(bank) == before


def test_the_stdio_server_refuses_too(tmp_path, monkeypatch):
    server = stdio_server()
    bank = _loose_demo(tmp_path)
    monkeypatch.setattr(server, "get_memory_path", lambda: bank)
    assert server.handle_save_episode("Decided alpha-project ships Friday.", "T") == demo_guard.AGENT_REFUSAL
    assert _episodes(bank) == []


def test_a_remote_write_into_a_demo_bank_is_refused_with_its_own_status(tmp_path):
    bank = _loose_demo(tmp_path)
    runtime = RemoteRuntime(memory_path=lambda: bank, post=lambda p, d: {}, sleep_running=lambda: False)
    connector = catalog.Connector(id="ab12cd34", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES,
                                  created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")
    text, status = runtime.call(connector, "cicada_save_episode", {"content": "x", "title": "t"})
    assert (text, status) == (demo_guard.AGENT_REFUSAL, "demo")


def test_a_real_bank_still_saves(tmp_path):
    bank = tmp_path / "real"
    (bank / "episodes").mkdir(parents=True)
    assert "Episode saved" in mcp_tools.save_episode(_ctx(bank), "Decided alpha-project ships Friday.", "T")


# --- Telegram (R-CS14) ------------------------------------------------------------


def test_a_telegram_message_is_not_saved_into_a_demo_bank_and_the_chat_is_told(tmp_path):
    bank = _loose_demo(tmp_path)
    calls: list = []

    def spy(*a, **k):
        calls.append(a)
        return {"status": "created"}

    update = {"update_id": 1, "message": {"message_id": 1, "from": {"id": 111, "is_bot": False,
                                                                    "first_name": "Bob"},
                                          "chat": {"id": 111, "type": "private"}, "date": 1_750_000_000,
                                          "text": "remember alpha-project https://example.com/a"}}
    result = asyncio.run(telegram_capture.ingest_telegram_update(bank, update, save_url_fn=spy,
                                                                 save_episode_fn=spy))
    assert result == {"kind": "skipped", "reason": "demo_bank", "ack": demo_guard.TELEGRAM_ACK, "chat_id": 111}
    assert calls == []
