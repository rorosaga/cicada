"""G213 — `cicada setup`: detect, report, then each step on the person's yes. A scripted UI and a fake backend; no
process is run, nothing reaches the network."""
from __future__ import annotations

import shlex

from api import cli_setup
from api.cli_types import Refusal


class Scripted(cli_setup.Ui):
    def __init__(self, answers=None, interactive=True):
        self.interactive, self.console, self.said, self.answers = interactive, None, [], list(answers or [])

    def say(self, text=""):
        self.said.append(cli_setup._plain(text))

    def confirm(self, question, default=True):
        return self.answers.pop(0) if self.interactive else default

    def text(self, question, default=""):
        # questionary pre-fills the default: Enter on it keeps it.
        return (self.answers.pop(0) or default) if self.interactive else default

    def choose_many(self, question, choices):
        return [c for c, on in choices if on]


ARGV = ["example-agent", "mcp", "add", "cicada", "--", "python", "-m", "mcp.server"]


def _backend(calls, *, down=False, paired=True):
    def call(method, path, body=None):
        calls.append((method, path, body))
        if down:
            raise Refusal("backend_down", "no backend")
        if path == "/healthz":
            return {"status": "ok", "version": "0.6.0", "entityCount": 12}
        if path == "/agents/wiring":
            return {"agents": [
                {"id": "example-agent", "installed": True, "recall": "off",
                 "connect": [{"step": "mcp", "display": shlex.join(ARGV), "argv": ARGV}]},
                {"id": "other-agent", "installed": True, "recall": "on", "connect": []},
                {"id": "absent-agent", "installed": False, "recall": "off", "connect": []}]}
        if path == "/remote/status":
            return {"tailscale": "funnel-on", "effectiveUrl": "https://cicada.example.ts.net"}
        if path == "/devices/pairing":
            # The server fills the QR with its tailnet serve when the person gave no url (G212).
            return {"pairing": {"id": "ab12cd34", "state": "waiting"}, "code": "ABCD-EFGH",
                    "kind": (body or {}).get("kind"),
                    "qr": {"v": 1, "url": (body or {}).get("url") or "https://mac.example.ts.net:8443",
                           "code": "ABCD-EFGH"}}
        if path.startswith("/devices/pairing/"):
            return {"pairing": {"state": "paired" if paired else "waiting"},
                    "device": {"id": "zz99yy88", "name": "Example Phone"} if paired else None}
        if path == "/agent-api/tokens":
            return {"token": "cic_api_x", "prompt": f"Use Cicada at {(body or {}).get('baseUrl')} …",
                    "agent": {"id": "q1w2e3r4"}}
        raise AssertionError(path)
    return call


def test_without_a_terminal_it_reports_and_writes_nothing():
    calls, ran = [], []
    result = cli_setup.run_setup(call=_backend(calls), ui=Scripted(interactive=False), run=ran.append)
    assert [c[0] for c in calls] == ["GET", "GET", "GET"] and ran == []
    assert "example-agent: not connected yet" in result.text and "other-agent: reaches Cicada" in result.text
    assert "absent-agent" not in result.text and "cicada device pair" in result.text


def test_each_step_runs_only_on_a_yes_and_runs_what_it_showed():
    calls, ran = [], []
    ui = Scripted([True, True, True, True, "Texting Agent"])
    result = cli_setup.run_setup(call=_backend(calls), ui=ui, run=lambda argv: ran.append(argv) or 0)
    assert ran == [ARGV]
    assert result.data["connected"] == ["example-agent"]
    assert result.data["pairing"]["qr"]["url"] == "https://mac.example.ts.net:8443"
    pairing_call = next(c for c in calls if c[1] == "/devices/pairing")
    assert pairing_call[2] == {"kind": "capture"}   # never the listener's public address
    assert result.data["pairing"]["paired"]["name"] == "Example Phone"
    token_call = next(c for c in calls if c[1] == "/agent-api/tokens")
    assert token_call[2]["name"] == "Texting Agent" and token_call[2]["baseUrl"] == "https://cicada.example.ts.net"
    assert "Use Cicada at https://cicada.example.ts.net" in result.text


def test_a_no_skips_the_step():
    calls, ran = [], []
    cli_setup.run_setup(call=_backend(calls), ui=Scripted([False, False, False]), run=ran.append)
    assert ran == [] and not any(c[0] == "POST" for c in calls)


def test_a_failed_command_stops_that_agent_s_steps():
    calls = []
    ui = Scripted([True, False, False])
    result = cli_setup.run_setup(call=_backend(calls), ui=ui, run=lambda argv: 3)
    assert result.data["connected"] == [] and any("exited 3" in s for s in ui.said)


def test_a_command_whose_display_differs_from_its_argv_never_runs():
    found = cli_setup.Found(server={}, agents=[{"id": "x", "installed": True, "recall": "off",
                                                "connect": [{"display": "echo safe", "argv": ["rm", "-rf", "/"]}]}])
    ran = []
    assert cli_setup.connect_agents(found, Scripted([True]), ran.append) == [] and ran == []


def test_flags_run_their_step_without_a_terminal():
    calls = []
    result = cli_setup.run_setup(call=_backend(calls), ui=Scripted(interactive=False), pair_now=True,
                                 agent_name="Texting Agent", url="https://other.example.ts.net")
    posted = [c for c in calls if c[0] == "POST"]
    assert [c[1] for c in posted] == ["/devices/pairing", "/agent-api/tokens"]
    assert posted[0][2] == {"kind": "capture"}   # --url is the agent's (public) address, never the QR's
    assert posted[1][2]["baseUrl"] == "https://other.example.ts.net"
    assert result.data["pairing"]["paired"] is None   # no wait without a terminal


def test_no_server_says_how_to_start_one():
    result = cli_setup.run_setup(call=_backend([], down=True), ui=Scripted(interactive=False))
    assert result.code == "backend_down" and "No Cicada server answered" in result.text


def test_the_wait_ends_at_its_deadline():
    calls, clock = [], iter(range(0, 10_000, 100))
    out = cli_setup.pair(_backend(calls, paired=False), Scripted(), None, wait=True, sleep=lambda s: None,
                         clock=lambda: next(clock))
    assert out["paired"] is None and len([c for c in calls if c[1].startswith("/devices/pairing/")]) >= 1
