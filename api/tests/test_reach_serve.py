"""One click serves this Mac to the person's tailnet (owner 2026-10-29, "Yes, one click"; the dated amendment to
G132 (c), G212). The click runs EXACTLY ``tailscale serve --bg --https=8443 <port>`` — the argv the guide showed — or
that one mapping's off, then re-reads the state. Never ``funnel``, never ``up``, never a shell, never an argv from the
request; 10 s cap; stdin closed; errors as sentences. A fake ``tailscale`` binary on disk stands in for the real one:
it answers the two reads from a state file and logs every argv it was given."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from api.remote import reach

FAKE = r'''#!{python}
import json, sys
from pathlib import Path
here = Path(__file__).parent
(here / "argv.log").open("a").write(json.dumps(sys.argv[1:]) + "\n")
state = json.loads((here / "state.json").read_text())
args = sys.argv[1:]
if args == ["status", "--json"]:
    print(json.dumps({{"BackendState": "Running", "Self": {{"DNSName": "mac.example.ts.net."}}}}))
elif args == ["funnel", "status", "--json"]:
    print(json.dumps(state.get("serve") or {{}}))
elif args[:1] == ["serve"]:
    if state.get("fail"):
        print(state["fail"], file=sys.stderr)
        sys.exit(1)
    if args[-1] == "off":
        state["serve"] = {{}}
    else:
        https = args[2].split("=", 1)[1]
        state["serve"] = {{"Web": {{f"mac.example.ts.net:{{https}}": {{"Handlers": {{"/": {{"Proxy": f"http://127.0.0.1:{{args[-1]}}"}}}}}}}}}}
    (here / "state.json").write_text(json.dumps(state))
else:
    sys.exit(64)
'''


@pytest.fixture
def fake(tmp_path):
    folder = tmp_path / "bin"
    folder.mkdir()
    binary = folder / "tailscale"
    binary.write_text(FAKE.format(python=sys.executable))
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    (folder / "state.json").write_text(json.dumps({}))

    def set_state(**state):
        (folder / "state.json").write_text(json.dumps(state))

    def argv_log():
        log = folder / "argv.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    kw = dict(which=lambda name: str(binary) if name == "tailscale" else None, exists=lambda path: False)
    return kw, set_state, argv_log


def _changes(log):
    """Every argv that is not one of the two reads: what the click changed."""
    return [a for a in log if a not in (["status", "--json"], ["funnel", "status", "--json"])]


def test_the_click_runs_exactly_the_serve_the_guide_showed_then_reads_ready(fake):
    kw, _set, log = fake
    shown = reach.guide(8000, **kw)
    assert shown["step"] == "serve" and shown["command"] == "tailscale serve --bg --https=8443 8000"
    out = reach.run_serve("serve", 8000, **kw)
    assert out["ok"] is True and out["message"] is None and out["ran"] == shown["command"]
    assert _changes(log()) == [["serve", "--bg", "--https=8443", "8000"]]
    assert out["guide"]["step"] == "ready" and out["guide"]["url"] == "https://mac.example.ts.net:8443"
    assert out["guide"]["stopCommand"] == "tailscale serve --https=8443 off"


def test_the_stop_turns_off_that_one_mapping_and_nothing_else(fake):
    kw, set_state, log = fake
    set_state(serve={"Web": {"mac.example.ts.net:9443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}}})
    shown = reach.guide(8000, **kw)
    assert shown["step"] == "ready" and shown["stopCommand"] == "tailscale serve --https=9443 off"
    out = reach.run_serve("stop", 8000, **kw)
    assert out["ok"] and out["ran"] == shown["stopCommand"]
    assert _changes(log()) == [["serve", "--https=9443", "off"]]
    assert out["guide"]["step"] == "serve"


@pytest.mark.parametrize("serve, action, why", [
    ({"Web": {"mac.example.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}}}, "serve",
     "already reachable"),
    ({}, "stop", "nothing to stop"),
    ({"Web": {"mac.example.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}},
      "AllowFunnel": {"mac.example.ts.net:443": True}}, "serve", "close the public funnel first"),
    ({"Web": {"mac.example.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}},
      "AllowFunnel": {"mac.example.ts.net:443": True}}, "stop", "nothing to stop"),
])
def test_a_step_with_nothing_to_run_runs_nothing_and_says_why(fake, serve, action, why):
    kw, set_state, log = fake
    set_state(serve=serve)
    out = reach.run_serve(action, 8000, **kw)
    assert out["ok"] is False and out["ran"] is None and why in out["message"]
    assert _changes(log()) == []


def test_without_tailscale_nothing_runs():
    out = reach.run_serve("serve", 8000, which=lambda name: None, exists=lambda path: False,
                          run=lambda *a, **k: pytest.fail("ran something"))
    assert out["ok"] is False and out["guide"]["step"] == "install"


@pytest.mark.parametrize("fail, words", [
    ("Serve is not enabled on your tailnet. To enable, visit: https://login.tailscale.com/f/serve?node=abc",
     "Serve isn't on for your tailnet yet: turn it on at https://login.tailscale.com/f/serve?node=abc"),
    ("Access denied: serve config denied", "this user may not change Tailscale's settings"),
    ("something odd", "Run the command yourself in a terminal"),
])
def test_a_failure_is_a_sentence(fake, fail, words):
    kw, set_state, _log = fake
    set_state(fail=fail)
    out = reach.run_serve("serve", 8000, **kw)
    assert out["ok"] is False and words in out["message"] and out["guide"]["step"] == "serve"


def test_the_command_is_argv_only_capped_and_never_waits_on_input(monkeypatch):
    seen = []

    class Done:
        stdout, stderr, returncode = "", "", 0

    def run(argv, **kw):
        seen.append((argv, kw))
        if argv[1:] == ["status", "--json"]:
            return type("S", (), {"stdout": json.dumps({"BackendState": "Running"}), "returncode": 0})()
        if argv[1:] == ["funnel", "status", "--json"]:
            return type("S", (), {"stdout": "{}", "returncode": 0})()
        return Done()

    reach.run_serve("serve", 8000, which=lambda n: "/opt/fake/tailscale", exists=lambda p: False, run=run)
    (argv, kw), = [(a, k) for a, k in seen if a[1] == "serve"]
    assert isinstance(argv, list) and argv == ["/opt/fake/tailscale", "serve", "--bg", "--https=8443", "8000"]
    assert kw["timeout"] == reach.SERVE_TIMEOUT == 10.0 and kw["stdin"] is subprocess.DEVNULL
    assert "shell" not in kw and "funnel" not in argv and "up" not in argv


def test_a_timeout_is_a_sentence():
    def run(argv, **kw):
        if argv[1:] == ["status", "--json"]:
            return type("S", (), {"stdout": json.dumps({"BackendState": "Running"}), "returncode": 0})()
        if argv[1:] == ["funnel", "status", "--json"]:
            return type("S", (), {"stdout": "{}", "returncode": 0})()
        raise subprocess.TimeoutExpired(argv, 10.0, output=b"", stderr=b"")

    out = reach.run_serve("serve", 8000, which=lambda n: "/opt/fake/tailscale", exists=lambda p: False, run=run)
    assert out["ok"] is False and "within 10 seconds" in out["message"]


def test_an_unknown_action_is_refused():
    with pytest.raises(ValueError):
        reach.run_serve("funnel", 8000, which=lambda n: None, exists=lambda p: False)


# ---------- the route ----------


@pytest.fixture
def server(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config
    from api.main import app
    from api.services.auth import get_token
    from api.tests.test_sleep_cycle_hold import _bank

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    master = get_token()
    with TestClient(app) as client:
        yield client, master
    config.get_settings.cache_clear()


def test_the_route_takes_an_action_never_an_argv_and_checks_after(server, monkeypatch):
    client, master = server
    ran = []
    monkeypatch.setattr(reach, "run_serve", lambda action, port, **kw: ran.append((action, port)) or {
        "ok": True, "message": None, "ran": f"tailscale serve --bg --https=8443 {port}",
        "guide": {"tailscale": "running", "dnsName": "mac.example.ts.net", "url": "https://mac.example.ts.net:8443",
                  "command": None, "step": "ready", "stopCommand": "tailscale serve --https=8443 off"}})
    monkeypatch.setattr(reach, "self_check", lambda url, **kw: {"ok": True, "failed": None, "ms": 9})
    headers = {"Authorization": f"Bearer {master}"}
    got = client.post("/devices/reach/serve", json={"action": "serve", "argv": ["up"]}, headers=headers)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["ok"] and body["reach"]["step"] == "ready" and body["reach"]["check"]["ok"] is True
    assert ran and ran[0][0] == "serve"
    assert client.post("/devices/reach/serve", json={"action": "up"}, headers=headers).status_code == 422
    assert client.post("/devices/reach/serve", json={"action": "serve"}).status_code == 401


def test_no_shell_in_the_module():
    source = Path(reach.__file__).read_text()
    assert "shell=True" not in source and "os.system" not in source and "Popen" not in source
    assert os.path.basename(reach.__file__) == "reach.py"
