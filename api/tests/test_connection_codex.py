from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from api.services.connections import codex_cli
from api.services.connections.base import CliResult


def _jwt(claims: dict) -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'none'})}.{b64(claims)}.sig"


def _auth_json(tmp_path: Path, plan="plus", email="r@example.com") -> Path:
    claims = {"email": email, "https://api.openai.com/auth": {"chatgpt_plan_type": plan}}
    (tmp_path / "auth.json").write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": _jwt(claims), "access_token": "x", "refresh_token": "y"},
    }))
    return tmp_path


def _runner(rc=0, stdout="", stderr=""):
    calls: list[list[str]] = []

    async def run(argv):
        calls.append(argv)
        return CliResult(rc, stdout, stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_decode_jwt_claims_handles_missing_padding():
    claims = codex_cli.decode_jwt_claims(_jwt({"a": 1, "email": "e"}))
    assert claims == {"a": 1, "email": "e"}


def test_read_plan_from_auth_json(tmp_path):
    home = _auth_json(tmp_path, plan="pro")
    assert codex_cli.read_plan_from_auth_json(home / "auth.json") == ("pro", "r@example.com")


def test_read_plan_missing_file(tmp_path):
    assert codex_cli.read_plan_from_auth_json(tmp_path / "nope.json") == (None, None)


def test_status_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    home = _auth_json(tmp_path, plan="plus")
    run = _runner(stdout="Logged in using ChatGPT")
    s = asyncio.run(codex_cli.CodexPlanAdapter(runner=run, codex_home=home).status())
    assert run.calls == [["codex", "login", "status"]]
    assert s.connected and s.plan == "plus" and s.plan_label == "ChatGPT Plus"
    assert s.price_usd_month == 20.0 and s.account == "r@example.com"
    assert s.login.mode == "device-code"


def test_status_logged_out(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    s = asyncio.run(codex_cli.CodexPlanAdapter(runner=_runner(rc=1, stderr="Not logged in"), codex_home=tmp_path).status())
    assert s.available and not s.connected and s.plan is None


def test_status_api_key_mode_is_not_a_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    (tmp_path / "auth.json").write_text(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk"}))
    s = asyncio.run(codex_cli.CodexPlanAdapter(runner=_runner(stdout="Logged in using API key"), codex_home=tmp_path).status())
    assert not s.connected and "API key" in s.detail


def test_parse_device_output():
    text = "Enter this code at https://auth.openai.com/device\n\n    ABCD-EFGH\n"
    assert codex_cli.parse_device_output(text) == ("ABCD-EFGH", "https://auth.openai.com/device")
    assert codex_cli.parse_device_output("nothing here") == (None, None)


def test_begin_login_spawns_device_auth_and_tracks_session(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    spawned: list[list[str]] = []

    class _Proc:
        returncode = None

        def __init__(self):
            self.lines = [b"Visit https://auth.openai.com/device and enter WXYZ-1234\n"]
            self.stdout = self

        async def readline(self):
            return self.lines.pop(0) if self.lines else b""

        async def wait(self):
            self.returncode = 0
            return 0

    async def spawn(argv):
        spawned.append(argv)
        return _Proc()

    adapter = codex_cli.CodexPlanAdapter(runner=_runner(), codex_home=tmp_path, spawn=spawn)

    async def go():
        sess = await adapter.begin_login()
        await asyncio.sleep(0.05)  # let the watcher drain the fake process
        return sess

    sess = asyncio.run(go())
    assert spawned == [["codex", "login", "--device-auth"]]
    assert sess.mode == "device-code"
    tracked = codex_cli.login_sessions[sess.session_id]
    assert tracked.code == "WXYZ-1234" and tracked.url == "https://auth.openai.com/device"
    assert tracked.state == "done"


def test_logout_runs_cli(tmp_path):
    run = _runner()
    asyncio.run(codex_cli.CodexPlanAdapter(runner=run, codex_home=tmp_path).logout())
    assert run.calls == [["codex", "logout"]]
