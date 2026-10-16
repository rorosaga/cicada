"""G181 phase 2, end to end: two real backends on two loopback ports, in scratch directories.

One plays the SERVER (its own HOME, CICADA_HOME and memory root); the other plays the CLIENT machine's own backend,
whose bank must stay untouched. The client's hook, stdio MCP server and `cicada` command run as subprocesses with the
client's HOME and ``CICADA_API_BASE`` pointing at the server, signing with a device token the server issued
(`cicada device add`, run on the server). Shown: a captured session lands once on the server and never on the
client's disk; a server that is down loses nothing and a later firing flushes the spool; MCP recall, save and edit go
through HTTP (a trusted harness on a device edits at once); revocation ends the device at once; with no base set the
single-machine path still posts a path to its own backend. Synthetic data and placeholder names only.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
SID = "22222222-3333-4444-8555-666666666666"
SID2 = "33333333-4444-4555-8666-777777777777"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _base_env(home: Path, cicada_home: Path) -> dict:
    """A clean environment: nothing from the shell running the suite (no harness session, no capture switch)."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CICADA_HOME": str(cicada_home),
            "PYTHONPATH": str(REPO), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "CICADA_ALLOW_CONNECTOR_FETCH": "off", "CICADA_ALLOW_LOGO_FETCH": "off", "LANG": "C.UTF-8"}


class Backend:
    def __init__(self, root: Path, name: str):
        self.home = root / f"{name}-home"
        self.cicada_home = root / f"{name}-cicada"
        self.memory = root / f"{name}-memory"
        for d in (self.home, self.cicada_home, self.memory):
            d.mkdir(parents=True, exist_ok=True)
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.log = root / f"{name}-backend.log"
        self.proc = None

    @property
    def env(self) -> dict:
        return {**_base_env(self.home, self.cicada_home), "CICADA_MEMORY_PATH": str(self.memory),
                "CICADA_PORT": str(self.port)}

    def start(self):
        self.proc = subprocess.Popen(
            [PY, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=REPO, env=self.env, stdout=self.log.open("ab"), stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self.url}/healthz", timeout=1) as resp:
                    if resp.status == 200:
                        return self
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        self.stop()
        raise AssertionError("backend did not start:\n" + self.log.read_text()[-3000:])

    def stop(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc = None

    @property
    def bank(self) -> Path:
        from api.services import bank_registry

        return bank_registry.current_active(self.memory)[1]

    def episodes(self, session_id: str | None = None) -> list[Path]:
        eps = sorted((self.bank / "episodes").glob("ep_*.md"))
        return [p for p in eps if session_id is None or session_id in p.read_text()]


def _cli(env: dict, *argv: str, stdin: str | None = None) -> tuple[int, dict]:
    done = subprocess.run([PY, "-m", "api.cli", *argv, "--json"], cwd=REPO, env=env, input=stdin, capture_output=True,
                          text=True, timeout=120)
    try:
        return done.returncode, json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise AssertionError(f"cicada {argv}: {done.returncode}\n{done.stdout}\n{done.stderr}")


def _line(typ, content, sid=SID, ts="2026-10-16T10:00:00.000Z"):
    return json.dumps({"type": typ, "uuid": "u", "timestamp": ts, "sessionId": sid, "cwd": "/home/example/alpha",
                       "message": {"role": typ, "content": content}}) + "\n"


def _hook(env: dict, transcript: Path, sid: str = SID, event: str = "Stop") -> str:
    payload = {"session_id": sid, "transcript_path": str(transcript), "cwd": "/home/example/alpha",
               "hook_event_name": event}
    started = time.monotonic()
    done = subprocess.run([PY, str(REPO / "api" / "hooks" / "capture.py"), "--harness", "claude-code"],
                          input=json.dumps(payload), env=env, capture_output=True, text=True, timeout=30)
    elapsed = time.monotonic() - started
    assert done.returncode == 0 and done.stdout == ""
    assert elapsed < 5.0, f"the hook took {elapsed:.1f}s, past its registered 5 s"
    log = Path(env["CICADA_HOME"]) / "logs" / "capture.log"
    return log.read_text().splitlines()[-1]


class Mcp:
    def __init__(self, env: dict):
        self.proc = subprocess.Popen([PY, str(REPO / "mcp" / "server.py")], cwd=REPO, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.n = 0

    def ask(self, method: str, params: dict) -> dict:
        self.n += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        assert line, self.proc.stderr.read()
        return json.loads(line)

    def tool(self, name: str, **arguments) -> tuple[str, bool]:
        result = self.ask("tools/call", {"name": name, "arguments": arguments})["result"]
        return result["content"][0]["text"], bool(result.get("isError"))

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.proc.stderr.close()


@pytest.fixture(scope="module")
def machines(tmp_path_factory):
    root = tmp_path_factory.mktemp("two-machines")
    server = Backend(root, "server").start()
    laptop = Backend(root, "laptop").start()        # the client machine's own backend: its bank must stay untouched
    try:
        code, issued = _cli(server.env, "device", "add", "laptop")
        assert code == 0, issued
        token = issued["data"]["token"]
        (laptop.cicada_home / "device_token").write_text(token + "\n")
        os.chmod(laptop.cicada_home / "device_token", 0o600)
        projects = laptop.home / ".claude" / "projects" / "-home-example-alpha"
        projects.mkdir(parents=True)
        client_env = {**_base_env(laptop.home, laptop.cicada_home), "CICADA_API_BASE": server.url,
                      "CICADA_MEMORY_PATH": str(laptop.memory), "CICADA_PORT": str(laptop.port)}
        yield {"server": server, "laptop": laptop, "client_env": client_env, "projects": projects,
               "device_id": issued["data"]["device"]["id"], "root": root}
    finally:
        server.stop()
        laptop.stop()


def test_a_captured_session_lands_once_on_the_server_and_never_on_the_client(machines):
    server, laptop, env = machines["server"], machines["laptop"], machines["client_env"]
    transcript = machines["projects"] / f"{SID}.jsonl"
    transcript.write_text(_line("user", "plan alpha-project with bob-example")
                          + _line("assistant", [{"type": "text", "text": "planned"}]))
    before_laptop = laptop.episodes()
    assert "http 200 created" in _hook(env, transcript)
    assert "http 200 unchanged" in _hook(env, transcript)
    eps = server.episodes(SID)
    assert len(eps) == 1
    from api.services import markdown_parser

    fm = markdown_parser.parse(eps[0]).frontmatter
    assert fm["capture_kind"] == "transcript" and fm["device"] == machines["device_id"]
    assert laptop.episodes() == before_laptop                     # nothing on the client's own disk


def test_a_server_that_is_down_loses_nothing_and_the_spool_flushes_when_it_is_back(machines):
    server, env = machines["server"], machines["client_env"]
    transcript = machines["projects"] / f"{SID}.jsonl"
    server.stop()
    try:
        transcript.write_text(transcript.read_text() + _line("user", "also ship beta-project", ts="2026-10-16T11:00:00Z"))
        assert "spooled: no answer" in _hook(env, transcript)
        other = machines["projects"] / f"{SID2}.jsonl"
        other.write_text(_line("user", "a second session while the server was away", sid=SID2))
        assert "spooled: no answer" in _hook(env, other, sid=SID2)
        assert len(list((machines["laptop"].cicada_home / "spool" / "capture").glob("*.json"))) == 2
    finally:
        server.start()
    # The next firing (any session) posts its own and flushes what waited.
    line = _hook(env, other, sid=SID2)
    assert "http 200" in line and "spool: sent 1, 0 waiting" in line, line
    assert "also ship beta-project" in server.episodes(SID)[0].read_text()
    assert len(server.episodes(SID)) == 1 and len(server.episodes(SID2)) == 1
    assert list((machines["laptop"].cicada_home / "spool" / "capture").glob("*.json")) == []


def _seed_page(server: Backend):
    from _synthetic_bank import _entity

    bank = server.bank
    _entity(bank, "alpha-project", type="project", body="## Summary\nAlpha-project ships in spring.\n")
    subprocess.run(["git", "add", "-A"], cwd=bank, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "seed"],
                   cwd=bank, check=True, capture_output=True)


def test_the_mcp_server_on_a_client_goes_through_http(machines):
    server, laptop = machines["server"], machines["laptop"]
    _seed_page(server)
    env = {**machines["client_env"], "CICADA_SESSION_ID": "ses_2026-10-16_c0ffee00",
           "CICADA_SESSION_HARNESS": "claude-code"}
    before_laptop = laptop.episodes()
    mcp = Mcp(env)
    try:
        init = mcp.ask("initialize", {"clientInfo": {"name": "claude-code", "version": "1"}})["result"]
        assert "Cicada" in init.get("instructions", "")
        text, err = mcp.tool("cicada_save_episode", content="decided alpha-project ships with sqlite-vec",
                             title="Alpha decision")
        assert not err and "Episode saved as" in text, text
        saved = [p for p in server.episodes() if "ships with sqlite-vec" in p.read_text()]
        assert len(saved) == 1 and machines["device_id"] in saved[0].read_text()
        text, err = mcp.tool("cicada_recall_detail", entity_id="alpha-project")
        assert not err and "ships in spring" in text, text
        text, err = mcp.tool("cicada_recall", query="alpha-project")
        assert not err and "alpha" in text.lower(), text
        text, err = mcp.tool("cicada_edit_page", subject="alpha-project", reason="the season was wrong",
                             edits=[{"old": "spring", "new": "autumn"}])
        assert not err, text
        assert "autumn" in (server.bank / "entities" / "alpha-project.md").read_text()   # trusted: applied at once
        log = subprocess.run(["git", "log", "-1", "--format=%B"], cwd=server.bank, capture_output=True,
                             text=True).stdout
        assert "Cicada-Author: claude-code" in log
    finally:
        mcp.close()
    assert laptop.episodes() == before_laptop


def test_the_cli_on_a_client_uses_the_server_and_its_bank_identity(machines):
    env = machines["client_env"]
    code, status = _cli(env, "status")
    assert code == 0 and status["data"]["client"] is True and status["data"]["backend"]["state"] == "confirmed"
    code, out = _cli(env, "recall", "alpha-project")
    assert code == 0 and out["ok"], out
    code, out = _cli(env, "page", "list")
    assert code == 1 and out["code"] == "on_server"
    code, out = _cli(env, "save", "a note from the laptop's shell")
    assert code == 0 and out["ok"], out
    assert any("from the laptop's shell" in p.read_text() for p in machines["server"].episodes())


def test_revoking_the_device_ends_it_at_once(machines):
    server, env = machines["server"], machines["client_env"]
    code, out = _cli(server.env, "device", "revoke", machines["device_id"])
    assert code == 0, out
    mcp = Mcp(env)
    try:
        mcp.ask("initialize", {"clientInfo": {"name": "claude-code"}})
        text, err = mcp.tool("cicada_recall", query="alpha-project")
        assert err and "did not accept this device's token" in text
    finally:
        mcp.close()
    code, out = _cli(env, "recall", "alpha-project")
    assert code == 1 and out["code"] == "unauthorized"
    transcript = machines["projects"] / f"{SID}.jsonl"
    transcript.write_text(transcript.read_text() + _line("user", "after the revoke", ts="2026-10-16T12:00:00Z"))
    assert "spooled: http 401" in _hook(env, transcript)          # kept for a new token, never lost
    assert "after the revoke" not in server.episodes(SID)[0].read_text()


def test_the_single_machine_path_is_unchanged(machines):
    """No base: the hook posts a PATH to this machine's own backend, which reads its own transcript."""
    laptop = machines["laptop"]
    env = {**_base_env(laptop.home, laptop.cicada_home), "CICADA_PORT": str(laptop.port)}
    sid = "44444444-5555-4666-8777-888888888888"
    transcript = machines["projects"] / f"{sid}.jsonl"
    transcript.write_text(_line("user", "a session that stays on this machine", sid=sid))
    assert "http 200 created" in _hook(env, transcript, sid=sid)
    assert len(laptop.episodes(sid)) == 1
    assert machines["server"].episodes(sid) == []
