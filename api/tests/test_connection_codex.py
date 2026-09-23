from __future__ import annotations

import asyncio

from api.services import codex_app_server
from api.services.codex_app_server import CodexSnapshot
from api.services.connections import base, codex_cli
from api.services.connections.base import CliResult


def _runner(rc=0, stdout="", stderr=""):
    calls: list[list[str]] = []

    async def run(argv):
        calls.append(argv)
        return CliResult(rc, stdout, stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


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

    adapter = codex_cli.CodexPlanAdapter(runner=_runner(), spawn=spawn)

    async def go():
        sess = await adapter.begin_login()
        # The watcher task must be strongly referenced (not just held by the
        # event loop, which only holds weak refs) so it survives to completion.
        assert codex_cli._watchers, "watcher task was not retained"
        await asyncio.sleep(0.05)  # let the watcher drain the fake process
        return sess

    sess = asyncio.run(go())
    assert spawned == [["codex", "login", "--device-auth"]]
    assert sess.mode == "device-code"
    tracked = codex_cli.login_sessions[sess.session_id]
    assert tracked.code == "WXYZ-1234" and tracked.url == "https://auth.openai.com/device"
    assert tracked.state == "done"


def test_begin_login_supersedes_prior_pending_session(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")

    class _Proc:
        returncode = None

        def __init__(self):
            self.stdout = self
            self.killed = False

        async def readline(self):
            # Never produces a line / EOF — the fake never actually dies, so
            # the watcher stays parked in "pending" (real ``kill()`` would
            # close the pipe and unblock this; ``begin_login`` itself is what
            # marks the session "failed", independent of the watcher).
            await asyncio.sleep(3600)
            return b""

        def kill(self):
            self.killed = True

        async def wait(self):
            self.returncode = -9
            return -9

    procs: list[_Proc] = []

    async def spawn(argv):
        proc = _Proc()
        procs.append(proc)
        return proc

    adapter = codex_cli.CodexPlanAdapter(runner=_runner(), spawn=spawn)

    async def go():
        first = await adapter.begin_login()
        await asyncio.sleep(0.01)
        second = await adapter.begin_login()
        await asyncio.sleep(0.05)
        return first, second

    first, second = asyncio.run(go())
    assert procs[0].killed is True
    assert codex_cli.login_sessions[first.session_id].state == "failed"
    assert codex_cli.login_sessions[first.session_id].detail == "superseded"
    assert first.session_id != second.session_id
    assert second.session_id in codex_cli.login_sessions


def test_raw_output_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")

    class _Proc:
        returncode = None

        def __init__(self):
            # > 4096 chars of lines.
            self.lines = [f"line {i} filler filler filler filler\n".encode() for i in range(300)]
            self.stdout = self

        async def readline(self):
            return self.lines.pop(0) if self.lines else b""

        async def wait(self):
            self.returncode = 0
            return 0

    async def spawn(argv):
        return _Proc()

    adapter = codex_cli.CodexPlanAdapter(runner=_runner(), spawn=spawn)

    async def go():
        sess = await adapter.begin_login()
        await asyncio.sleep(0.05)
        return sess

    sess = asyncio.run(go())
    tracked = codex_cli.login_sessions[sess.session_id]
    assert tracked.state == "done"
    assert len(tracked.raw_output) <= codex_cli.RAW_OUTPUT_CAP


def test_status_binary_vanishes_between_which_and_exec(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    s = asyncio.run(codex_cli.CodexPlanAdapter(
        runner=_runner(rc=127, stderr="codex: not found"),
    ).status())
    assert not s.available and not s.connected
    assert "install" in s.detail.lower()


def test_a_failed_spawn_orphans_no_pending_session(tmp_path, monkeypatch):
    """The binary can vanish between `available()` and the spawn. Registering
    the session first left a "pending" entry in `login_sessions` that nothing
    ever prunes (pruning only touches terminal sessions) and that the app polls
    forever, behind a bare 500."""
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    codex_cli._live.pop("chatgpt-plan", None)  # other tests in this module leave one
    before = dict(codex_cli.login_sessions)

    async def spawn(argv):
        raise FileNotFoundError("codex")

    adapter = codex_cli.CodexPlanAdapter(runner=_runner(), spawn=spawn)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(adapter.begin_login())

    assert exc.value.status_code == 502
    assert "codex login" in exc.value.detail
    assert codex_cli.login_sessions == before, "a failed spawn registered a session anyway"
    assert codex_cli._live.get(adapter.id) is None


def _snap(**kw):
    base_kw = dict(signed_in=True, account_type="chatgpt", plan="plus", email="bob@example.com")
    base_kw.update(kw)
    return CodexSnapshot(**base_kw)


def _adapter(run, snap):
    async def snapshot(**_kw):
        return snap
    return codex_cli.CodexPlanAdapter(runner=run, snapshot=snapshot)


def test_cicada_never_reads_auth_json_any_more():
    """R-E8: an id_token is a vendor token; the app-server answers instead."""
    assert not hasattr(codex_cli, "read_plan_from_auth_json")
    assert not hasattr(codex_cli, "decode_jwt_claims")


def test_status_reads_plan_and_email_from_the_app_server(monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    run = _runner(stdout="Logged in using ChatGPT")
    s = asyncio.run(_adapter(run, _snap()).status())
    assert run.calls == [["codex", "login", "status"]]
    assert s.connected and s.plan == "plus" and s.plan_label == "ChatGPT Plus" and s.account == "bob@example.com"
    assert s.engine_role == "subscription-cli" and s.login.mode == "device-code"
    assert s.how.startswith("Signed in to ChatGPT with Cicada's own Codex sign-in on this Mac")


def test_a_prolite_plan_reads_as_words(monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    s = asyncio.run(_adapter(_runner(stdout="Logged in using ChatGPT"), _snap(plan="prolite")).status())
    assert s.plan_label == "ChatGPT Pro Lite"


def test_status_stays_connected_when_the_app_server_is_unavailable(monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    s = asyncio.run(_adapter(_runner(stdout="Logged in using ChatGPT"), None).status())
    assert s.connected and s.plan is None and s.plan_label is None


def test_status_logged_out_names_the_in_app_sign_in(monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    s = asyncio.run(_adapter(_runner(rc=1, stderr="Not logged in"), None).status())
    assert s.available and not s.connected and "Sign in with ChatGPT" in s.detail


def test_an_api_key_account_is_not_a_plan(monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    s = asyncio.run(_adapter(_runner(stdout="Logged in using an API key"),
                             _snap(account_type="apiKey", plan=None, email=None)).status())
    assert not s.connected and "API key" in s.detail


def test_logout_runs_in_cicadas_home_and_forgets_the_snapshot(monkeypatch):
    invalidated = []
    monkeypatch.setattr(codex_app_server, "invalidate", lambda: invalidated.append(True))
    run = _runner()
    asyncio.run(codex_cli.CodexPlanAdapter(runner=run).logout())
    assert run.calls == [["codex", "logout"]] and invalidated == [True]


def test_the_default_spawn_resolves_the_binary_and_runs_in_cicadas_home(monkeypatch):
    seen = {}

    async def fake_exec(*argv, **kw):
        seen["argv"], seen["env"] = argv, kw["env"]
        return object()

    monkeypatch.setattr(codex_cli, "resolve_binary", lambda name: f"/opt/tools/{name}")
    monkeypatch.setattr(codex_cli.asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(codex_cli.CodexPlanAdapter._default_spawn(["codex", "login", "--device-auth"]))
    assert seen["argv"] == ("/opt/tools/codex", "login", "--device-auth")
    assert seen["env"]["CODEX_HOME"] == str(base.codex_home())


def test_a_failed_sign_in_says_so_in_plain_words(monkeypatch):
    """R-E28: "codex login exited 1" was a process fact, not a sentence the
    Plans & keys card can show a person."""
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    codex_cli._live.pop("chatgpt-plan", None)  # other tests in this module leave one

    class _Proc:
        returncode = None

        def __init__(self):
            self.lines = [b"Error: device code sign-in is not enabled for this account\n"]
            self.stdout = self

        async def readline(self):
            return self.lines.pop(0) if self.lines else b""

        async def wait(self):
            self.returncode = 1
            return 1

    async def spawn(argv):
        return _Proc()

    adapter = codex_cli.CodexPlanAdapter(runner=_runner(), spawn=spawn)

    async def go():
        sess = await adapter.begin_login()
        await asyncio.sleep(0.05)  # let the watcher drain the fake process
        return sess

    sess = asyncio.run(go())
    tracked = codex_cli.login_sessions[sess.session_id]
    assert tracked.state == "failed"
    assert tracked.detail == "Sign-in didn't finish (codex exited 1)."
