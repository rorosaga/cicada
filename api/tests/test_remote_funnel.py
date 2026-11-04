"""One click opens the connector's own port to the internet (ruling 59, owner 2026-11-04, amends G132 (c) and the headless
rail). The click runs EXACTLY the command shown; only the connector's port; never over a mapping the person set up; the
off removes that one mapping; every answer is read back from Tailscale.

The stand-in binary models the real CLI's three traps (cmd/tailscale/cli/serve_v2.go, v1.104): a funnel on a held port
replaces ``/`` and opens the whole port; an off with no ``--set-path`` deletes every handler on the port; and, with Funnel
not allowed, it prints a URL and waits or exits 0 having changed nothing. Nothing here touches a real Tailscale."""
from __future__ import annotations

import json
import re
import shlex
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.remote import app as remote_app
from api.remote import reach, store
from api.remote.runtime import RemoteRuntime
from api.routers import remote as remote_router

HOST = "mac.example.ts.net"
FAKE = r'''#!{python}
import json, sys, time
from pathlib import Path
here = Path(__file__).parent
(here / "argv.log").open("a").write(json.dumps(sys.argv[1:]) + "\n")
state = json.loads((here / "state.json").read_text())
args = sys.argv[1:]
host = "mac.example.ts.net"
serve = state.get("serve") or {{}}

def save():
    state["serve"] = serve
    (here / "state.json").write_text(json.dumps(state))

def flag(name):
    return next((a.split("=", 1)[1] for a in args if a.startswith(name + "=")), None)

if args == ["status", "--json"]:
    backend = state.get("backend", "Running")
    print(json.dumps({{"BackendState": backend, "Version": state.get("version", "1.104.4-tabc"),
                      "Self": {{"DNSName": host + "."}}}}))
    sys.exit(0 if backend == "Running" else 1)
if args == ["funnel", "status", "--json"]:
    if state.get("read_hang"):
        time.sleep(30)
    print(json.dumps(serve))
    sys.exit(0)
if args[:1] not in (["funnel"], ["serve"]):
    sys.exit(64)
if args[-1] == "off" and state.get("off_fail"):
    print(state["off_fail"], file=sys.stderr)
    sys.exit(1)
if args[-1] != "off" and args[0] == "funnel":
    mode = state.get("mode")
    if mode == "wait":
        print("Funnel is not enabled on your tailnet. To enable, visit:", flush=True)
        print("         https://login.tailscale.com/f/funnel?node=abc", flush=True)
        time.sleep(30)
    if mode == "hang":
        time.sleep(30)
    if mode == "exit0":
        print("Funnel is not enabled on your tailnet. To enable, visit: https://login.tailscale.com/f/funnel?node=abc")
        sys.exit(0)
    if mode:
        print(mode, file=sys.stderr)
        sys.exit(1)
https = flag("--https") or "443"  # the CLI's own default
hp = host + ":" + https
if args[-1] == "off":
    handlers = serve.get("Web", {{}}).get(hp, {{}}).get("Handlers", {{}})
    mount = flag("--set-path")
    for m in ([mount] if mount else list(handlers)):
        handlers.pop(m, None)
    if not handlers:
        serve.get("Web", {{}}).pop(hp, None)
        serve.get("TCP", {{}}).pop(https, None)
        serve.get("AllowFunnel", {{}}).pop(hp, None)
else:
    serve.setdefault("TCP", {{}})[https] = {{"HTTPS": True}}
    serve.setdefault("Web", {{}}).setdefault(hp, {{"Handlers": {{}}}})["Handlers"]["/"] = {{"Proxy": "http://127.0.0.1:" + args[-1]}}
    if args[0] == "funnel":
        serve.setdefault("AllowFunnel", {{}})[hp] = True
save()
'''


def web(https, target, *, funnel=False, extra=None):
    hp = f"{HOST}:{https}"
    handlers = {"/": {"Proxy": f"http://127.0.0.1:{target}"}, **(extra or {})}
    out = {"TCP": {str(https): {"HTTPS": True}}, "Web": {hp: {"Handlers": handlers}}}
    if funnel:
        out["AllowFunnel"] = {hp: True}
    return out


def merged(*configs):
    out: dict = {}
    for c in configs:
        for key, value in c.items():
            out.setdefault(key, {}).update(value)
    return out


class Stub:
    def __init__(self, folder: Path):
        self.folder = folder
        self.binary = folder / "tailscale"
        self.binary.write_text(FAKE.format(python=sys.executable))
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)
        self.set()
        self.kw = dict(which=lambda name: str(self.binary) if name == "tailscale" else None,
                       exists=lambda path: False)

    def set(self, **state):
        (self.folder / "state.json").write_text(json.dumps(state))

    @property
    def serve(self) -> dict:
        return json.loads((self.folder / "state.json").read_text()).get("serve") or {}

    def log(self) -> list[list[str]]:
        path = self.folder / "argv.log"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def changes(self) -> list[list[str]]:
        reads = (["status", "--json"], ["funnel", "status", "--json"])
        return [a for a in self.log() if a not in reads]


@pytest.fixture
def stub(tmp_path):
    folder = tmp_path / "bin"
    folder.mkdir()
    return Stub(folder)


def click_on(stub, port=8765, **kw):
    shown = reach.funnel_state(port, **stub.kw, **{k: v for k, v in kw.items() if k in ("closed_ports", "saved_url")})
    return shown, reach.run_funnel("on", port, shown=shown.command, listener_up=True, **stub.kw, **kw)


# ---------- the command ----------


def test_the_click_runs_exactly_the_command_shown_then_reads_it_back(stub):
    shown, out = click_on(stub)
    assert shown.step == "off" and shown.command == "tailscale funnel --bg --https=443 8765"
    assert out["ok"] is True and out["ran"] == shown.command and out["message"] is None
    assert stub.changes() == [["funnel", "--bg", "--https=443", "8765"]]
    assert out["state"].step == "on" and out["state"].mapped_url == f"https://{HOST}"
    assert out["state"].stop_command == "tailscale funnel --https=443 --set-path=/ off"


def test_the_off_removes_that_one_mapping_and_nothing_else(stub):
    backend = web(8443, 8000)
    # The person added a path of their own under the same port later: the off names `/`, so it stays.
    stub.set(serve=merged(backend, web(443, 8765, funnel=True, extra={"/mine": {"Proxy": "http://127.0.0.1:3000"}})))
    out = reach.run_funnel("off", 8765, **stub.kw)
    assert out["ok"] is True and out["ran"] == "tailscale funnel --https=443 --set-path=/ off"
    assert stub.changes() == [["funnel", "--https=443", "--set-path=/", "off"]]
    assert list(stub.serve["Web"][f"{HOST}:443"]["Handlers"]) == ["/mine"]
    assert stub.serve["Web"][f"{HOST}:8443"] == backend["Web"][f"{HOST}:8443"]


def test_the_tailnet_mapping_stays_private_through_on_and_off(stub):
    stub.set(serve=web(8443, 8000))
    guide_before = reach.guide(8000, **stub.kw)
    assert guide_before["step"] == "ready" and guide_before["url"] == f"https://{HOST}:8443"
    _, out = click_on(stub)
    assert out["ok"] and stub.changes() == [["funnel", "--bg", "--https=443", "8765"]]
    assert stub.serve["AllowFunnel"] == {f"{HOST}:443": True}, "8443 must never become public"
    assert reach.guide(8000, **stub.kw)["step"] == "ready"
    assert reach.tailnet_backend(8000, **stub.kw).public is False
    assert reach.run_funnel("off", 8765, **stub.kw)["ok"]
    assert stub.serve["Web"] == web(8443, 8000)["Web"] and not stub.serve.get("AllowFunnel")
    assert reach.guide(8000, **stub.kw) == guide_before


def test_a_held_443_is_never_replaced_and_10000_is_used(stub):
    # `headless.md`'s own suggestion: the backend served to the tailnet on 443. A funnel there would take that serve away.
    held = web(443, 8000)
    stub.set(serve=held)
    shown, out = click_on(stub)
    assert shown.command == "tailscale funnel --bg --https=10000 8765"
    assert out["ok"] and out["state"].mapped_url == f"https://{HOST}:10000"
    assert stub.serve["Web"][f"{HOST}:443"] == held["Web"][f"{HOST}:443"]
    assert stub.serve["AllowFunnel"] == {f"{HOST}:10000": True}
    assert reach.tailnet_backend(8000, **stub.kw).public is False
    assert reach.run_funnel("off", 8765, **stub.kw)["ran"] == "tailscale funnel --https=10000 --set-path=/ off"
    assert stub.serve["Web"] == held["Web"]


@pytest.mark.parametrize("held", [
    merged(web(443, 3000), web(10000, 3001)),
    merged(web(443, 8765), web(10000, 8000)),  # a tailnet-only serve of the connector is the person's too
    {"TCP": {"443": {"TCPForward": "127.0.0.1:22"}, "10000": {"TCPForward": "127.0.0.1:23"}}},
    {"Foreground": {"s1": merged(web(443, 3000), web(10000, 3001))}},
    {"Web": {f"{HOST}:443": {"Handlers": {"/only-a-path": {"Proxy": "http://127.0.0.1:3000"}}},
             f"{HOST}:10000": {"Handlers": {"/too": {"Text": "x"}}}}},
    {"AllowFunnel": {f"{HOST}:443": True, f"{HOST}:10000": True}},
])
def test_when_both_ports_are_held_it_says_so_and_runs_nothing(stub, held):
    stub.set(serve=held)
    state = reach.funnel_state(8765, **stub.kw)
    assert state.step == "taken" and state.command is None and "won't replace" in state.message
    out = reach.run_funnel("on", 8765, shown="tailscale funnel --bg --https=443 8765", listener_up=True, **stub.kw)
    assert out["ok"] is False and out["ran"] is None and stub.changes() == []
    assert stub.serve == held


def test_8443_is_never_a_candidate_even_when_free():
    assert 8443 not in reach.FUNNEL_HTTPS_PORTS
    with pytest.raises(ValueError):
        reach.funnel_argv("/x/tailscale", 8443, 8765)


# ---------- every off removes one mapping, every command to copy is safe to paste ----------


def paste(stub, command):
    """Run a command as the person would, with the stand-in as `tailscale`."""
    words = shlex.split(command)
    assert words[0] == "tailscale", command
    return subprocess.run([str(stub.binary), *words[1:]], capture_output=True, text=True, timeout=10, check=False)


def test_stop_serving_keeps_the_other_handlers_on_its_port(stub):
    stub.set(serve=web(8443, 8000, extra={"/mine": {"Proxy": "http://127.0.0.1:3000"}}))
    shown = reach.guide(8000, **stub.kw)
    assert shown["stopCommand"] == "tailscale serve --https=8443 --set-path=/ off"
    out = reach.run_serve("stop", 8000, **stub.kw)
    assert out["ok"] and out["ran"] == shown["stopCommand"], "exactly the command shown"
    assert stub.changes() == [["serve", "--https=8443", "--set-path=/", "off"]]
    assert list(stub.serve["Web"][f"{HOST}:8443"]["Handlers"]) == ["/mine"]


def test_closing_a_funnelled_backend_keeps_the_other_handlers_on_its_port(stub):
    stub.set(serve=web(443, 8000, funnel=True, extra={"/mine": {"Proxy": "http://127.0.0.1:3000"}}))
    shown = reach.guide(8000, **stub.kw)
    assert shown["step"] == "unfunnel" and shown["command"] == "tailscale funnel --https=443 --set-path=/ off"
    assert paste(stub, shown["command"]).returncode == 0
    assert list(stub.serve["Web"][f"{HOST}:443"]["Handlers"]) == ["/mine"]
    assert reach.tailnet_backend(8000, **stub.kw).public is False, "the backend is no longer behind it"


def test_without_the_path_the_cli_would_have_deleted_them(stub):
    """The negative control: what the stand-in does with the old commands, which is what `removeWebServe` does."""
    stub.set(serve=web(8443, 8000, extra={"/mine": {"Proxy": "http://127.0.0.1:3000"}}))
    assert paste(stub, "tailscale serve --https=8443 off").returncode == 0
    assert not stub.serve.get("Web")


def test_the_command_to_copy_never_replaces_a_held_443(stub):
    held = web(443, 8000)  # `headless.md`'s example: the API served to the tailnet on 443
    stub.set(serve=held)
    command = reach.detect(8765, **stub.kw).funnel_copy
    assert command == "tailscale funnel --bg --https=10000 8765"
    assert paste(stub, command).returncode == 0
    assert stub.serve["Web"][f"{HOST}:443"] == held["Web"][f"{HOST}:443"]
    assert stub.serve["AllowFunnel"] == {f"{HOST}:10000": True}
    assert reach.guide(8000, **stub.kw)["url"] == f"https://{HOST}", "the person's serve of the API still works"


def test_the_old_bare_command_took_the_serve_at_root_away(stub):
    """The negative control: with the API at `/` on 443 the bare command replaces that handler. The API is not public, the
    connector is, and the person's devices have lost the API."""
    stub.set(serve=web(443, 8000))
    assert paste(stub, "tailscale funnel --bg 8765").returncode == 0
    assert stub.serve["Web"][f"{HOST}:443"]["Handlers"] == {"/": {"Proxy": "http://127.0.0.1:8765"}}
    assert reach.guide(8000, **stub.kw)["step"] == "serve", "nothing serves the API any more"


def test_the_old_bare_command_made_another_path_on_that_port_public(stub):
    """The negative control: Funnel is per host and port, so whatever else is mounted there, an API included, goes public."""
    api = {"Proxy": "http://127.0.0.1:8000"}
    stub.set(serve={"TCP": {"443": {"HTTPS": True}}, "Web": {f"{HOST}:443": {"Handlers": {"/api": api}}}})
    assert paste(stub, "tailscale funnel --bg 8765").returncode == 0
    assert stub.serve["AllowFunnel"] == {f"{HOST}:443": True}
    assert stub.serve["Web"][f"{HOST}:443"]["Handlers"]["/api"] == api


@pytest.mark.parametrize("serve, expected", [
    ({}, "tailscale funnel --bg --https=443 8765"),
    (web(443, 8765, funnel=True), "tailscale funnel --bg --https=443 8765"),  # already its own: harmless, the same
    (web(10000, 8765, funnel=True), "tailscale funnel --bg --https=10000 8765"),
    (web(8443, 8000), "tailscale funnel --bg --https=443 8765"),
    (merged(web(443, 3000), web(10000, 3001)), reach.FUNNEL_COPY_TAKEN),
])
def test_the_command_to_copy_follows_the_same_rule_as_the_click(stub, serve, expected):
    stub.set(serve=serve)
    assert reach.detect(8765, **stub.kw).funnel_copy == expected


@pytest.mark.parametrize("words", [reach.FUNNEL_COPY_UNKNOWN, reach.FUNNEL_COPY_TAKEN, reach.FUNNEL_COPY_PORT])
def test_words_in_the_command_field_are_harmless_if_pasted(words):
    """An older app shows the field in a box to copy. A shell comment, or in an interactive zsh `command not found: #`;
    nothing in it a shell would act on."""
    assert re.fullmatch(r"# [A-Za-z0-9_ .,]+", words), words


def test_a_tailscale_that_will_not_answer_offers_no_command(stub):
    def run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 2.0)

    assert reach.detect(8765, run=run, **stub.kw).funnel_copy == reach.FUNNEL_COPY_UNKNOWN


def test_status_offers_no_command_when_the_port_is_the_apis(route, stub, monkeypatch):
    client, _listener, _ = route
    monkeypatch.setenv("CICADA_REMOTE_PORT", str(config.get_settings().port))
    assert client.get("/remote/status").json()["funnelCommand"] == reach.FUNNEL_COPY_PORT


def test_setup_points_at_the_safe_door_and_no_bare_command():
    from api import cli_setup

    source = Path(cli_setup.__file__).read_text()
    assert "funnelCommand" not in source and "cicada funnel on" in source


def test_what_https_publishes_is_said_before_the_click(stub):
    state = reach.funnel_state(8765, **stub.kw)
    assert state.step == "off" and "public certificate log" in state.message and "tailnet's name" in state.message
    assert "can't be undone" in reach.funnel_wire(state)["message"]
    stub.set(mode="Funnel not available; HTTPS must be enabled. See https://tailscale.com/s/https.")
    _, out = click_on(stub)
    assert "can't be undone" in reach.funnel_wire(out["state"], fix_url=out["fixUrl"])["message"], "still in sight"


# ---------- only the connector's port ----------


@pytest.mark.parametrize("port, closed", [(8000, (8000,)), (50000, (8000, 50000)), (0, ())])
def test_the_api_port_and_the_door_can_never_be_opened(stub, port, closed):
    state = reach.funnel_state(port, closed_ports=closed, **stub.kw)
    assert state.step == "port" and state.command is None
    out = reach.run_funnel("on", port, shown=f"tailscale funnel --bg --https=443 {port}", listener_up=True,
                           closed_ports=closed, **stub.kw)
    assert out["ok"] is False and out["ran"] is None and stub.log() == [], "it must not even ask Tailscale"


def test_a_stale_or_forged_command_runs_nothing(stub):
    out = reach.run_funnel("on", 8765, shown="tailscale funnel --bg --https=443 8000", listener_up=True, **stub.kw)
    assert out["ok"] is False and out["ran"] is None and stub.changes() == [] and "out of date" in out["message"]


def test_nothing_opens_while_the_connector_is_not_listening(stub):
    shown = reach.funnel_state(8765, **stub.kw)
    out = reach.run_funnel("on", 8765, shown=shown.command, listener_up=False, **stub.kw)
    assert out["ok"] is False and stub.changes() == []


def test_the_command_is_argv_only_capped_and_never_waits_on_input():
    seen = []

    def run(argv, **kw):
        seen.append((argv, kw))
        if argv[1:] == ["status", "--json"]:
            return type("S", (), {"stdout": json.dumps({"BackendState": "Running"}), "returncode": 0})()
        return type("S", (), {"stdout": "{}", "stderr": "", "returncode": 0})()

    reach.run_funnel("on", 8765, shown="tailscale funnel --bg --https=443 8765", listener_up=True,
                     which=lambda n: "/opt/fake/tailscale", exists=lambda p: False, run=run)
    (argv, kw), = [(a, k) for a, k in seen if a[1:3] != ["status", "--json"] and "--bg" in a]
    assert argv == ["/opt/fake/tailscale", "funnel", "--bg", "--https=443", "8765"]
    assert kw["timeout"] == reach.FUNNEL_TIMEOUT == 10.0 and kw["stdin"] is subprocess.DEVNULL and "shell" not in kw


def test_only_one_place_builds_it_and_only_the_route_runs_it():
    api = Path(reach.__file__).parents[1]
    sources = {p: p.read_text() for p in api.rglob("*.py") if "tests" not in p.parts and "vendor" not in p.parts}
    assert [p.name for p, s in sources.items() if '"funnel", "--bg"' in s] == ["reach.py"]
    assert sorted(p.name for p, s in sources.items() if "run_funnel(" in s) == ["reach.py", "remote.py"]
    assert not any('"up"' in s.split("def run_funnel")[1] for p, s in sources.items() if p.name == "reach.py")
    for p, s in sources.items():
        if p.name == "reach.py" or p.parent.name == "remote":
            assert "shell=True" not in s and "os.system" not in s


def test_no_argv_in_any_flow_is_up_login_reset_or_clear(stub):
    click_on(stub)
    reach.run_funnel("off", 8765, **stub.kw)
    assert stub.changes()
    assert not {"up", "login", "logout", "reset", "clear", "set"} & {w for a in stub.changes() for w in a}


# ---------- read back, never assumed ----------


@pytest.mark.parametrize("state, step, words", [
    ({"backend": "NeedsLogin"}, "sign-in", "Sign in"),
    ({"backend": "NeedsMachineAuth"}, "sign-in", "Sign in"),
    ({"backend": "Stopped"}, "turn-on", "Turn it on"),
    ({"backend": "NoState"}, "open", "Open Tailscale"),
    ({"version": "1.50.1-tabc"}, "update", "too old"),
])
def test_a_machine_not_ready_says_what_to_do_and_runs_nothing(stub, state, step, words):
    stub.set(**state)
    got = reach.funnel_state(8765, **stub.kw)
    assert got.step == step and words in got.message and got.command is None
    out = reach.run_funnel("on", 8765, shown="tailscale funnel --bg --https=443 8765", listener_up=True, **stub.kw)
    assert out["ok"] is False and out["ran"] is None and stub.changes() == []


def test_not_installed_says_so():
    state = reach.funnel_state(8765, which=lambda n: None, exists=lambda p: False,
                               run=lambda *a, **k: pytest.fail("ran something"))
    assert state.step == "install" and "Install Tailscale" in state.message


def test_a_serve_config_that_will_not_answer_offers_nothing(stub, monkeypatch):
    def run(argv, **kw):
        if argv[1:] == ["funnel", "status", "--json"]:
            raise subprocess.TimeoutExpired(argv, 2.0)
        return subprocess.run(argv, **kw)

    state = reach.funnel_state(8765, run=run, **stub.kw)
    assert state.step == "unknown" and state.command is None


@pytest.mark.parametrize("mode, words, fix", [
    ("Funnel not available; HTTPS must be enabled. See https://tailscale.com/s/https.", "HTTPS certificates are off",
     "https://console.tailscale.com/admin/dns"),
    ('Funnel not available; "funnel" node attribute not set. See https://tailscale.com/s/no-funnel.',
     "policy doesn't allow Funnel", "https://console.tailscale.com/admin/acls"),
    ("port 443 is not allowed for funnel; allowed ports are: 8443", "doesn't allow Funnel on this port",
     "https://console.tailscale.com/admin/acls"),
    ("Access denied: serve config denied\nUse 'sudo tailscale set --operator=$USER'", "--operator=$USER", None),
    ("Another client is changing the serve config; please try again.", "Try again", None),
    ("flag provided but not defined: -bg", "too old", None),
    ("something odd", "Run this in a terminal to see why: tailscale funnel --bg --https=443 8765", None),
])
def test_a_refusal_is_a_sentence_with_the_exact_fix(stub, mode, words, fix):
    stub.set(mode=mode)
    _, out = click_on(stub)
    assert out["ok"] is False and words in out["message"] and out["fixUrl"] == fix
    assert out["state"].step == "off" and stub.serve == {}


def test_first_run_waiting_on_the_tailnet_is_bounded_and_gives_the_link(stub, monkeypatch):
    monkeypatch.setattr(reach, "FUNNEL_TIMEOUT", 0.5)
    stub.set(mode="wait")
    _, out = click_on(stub)
    assert out["ok"] is False and "isn't on for your tailnet yet" in out["message"]
    assert out["fixUrl"] == "https://login.tailscale.com/f/funnel?node=abc" and stub.serve == {}


@pytest.mark.parametrize("host", ["console.tailscale.com", "login.tailscale.com"])
def test_a_first_run_link_on_either_admin_host_is_offered(stub, host):
    stub.set(mode=f"Funnel is not enabled on your tailnet. To enable, visit: https://{host}/f/funnel?node=abc")
    _, out = click_on(stub)
    assert out["ok"] is False and "isn't on for your tailnet yet" in out["message"]
    assert out["fixUrl"] == f"https://{host}/f/funnel?node=abc"


def test_exit_0_having_changed_nothing_is_a_failure(stub):
    stub.set(mode="exit0")
    _, out = click_on(stub)
    assert out["ok"] is False and out["fixUrl"] == "https://login.tailscale.com/f/funnel?node=abc"


def test_a_hung_cli_is_a_sentence(stub, monkeypatch):
    monkeypatch.setattr(reach, "FUNNEL_TIMEOUT", 0.5)
    stub.set(mode="hang")
    _, out = click_on(stub)
    assert out["ok"] is False and "within 10 seconds" in out["message"] and out["ran"]


def test_only_a_tailscale_address_is_ever_offered_as_a_link(stub):
    stub.set(mode="To enable, visit: https://evil.example/f/funnel or https://login.tailscale.com.evil.example/x")
    _, out = click_on(stub)
    assert out["ok"] is False and out["fixUrl"] is None


def test_one_opened_from_a_terminal_is_closed_there(stub):
    stub.set(serve={"Foreground": {"s1": web(443, 8765, funnel=True)}})
    state = reach.funnel_state(8765, **stub.kw)
    assert state.step == "terminal" and state.stop_command is None and "Ctrl+C" in state.message
    assert reach.run_funnel("off", 8765, **stub.kw)["ran"] is None and stub.changes() == []


def test_one_the_person_opened_by_hand_is_seen_and_can_be_closed(stub):
    stub.set(serve=web(443, 8765, funnel=True))  # what the docs told them to run: `tailscale funnel --bg 8765`
    state = reach.funnel_state(8765, **stub.kw)
    assert state.step == "on" and reach.run_funnel("off", 8765, **stub.kw)["ok"] and stub.serve.get("Web") in (None, {})


def test_a_funnel_of_another_port_is_reported_and_never_closed(stub):
    """A mapping left on the connector's old port and the person's own site look alike from here: shown with its off to
    copy, whatever the step, and never run."""
    stub.set(serve=web(443, 8765, funnel=True))
    state = reach.funnel_state(9001, **stub.kw)  # CICADA_REMOTE_PORT moved after the click
    assert state.step == "off" and state.command == "tailscale funnel --bg --https=10000 9001"
    (other,) = state.others
    assert other.url == f"https://{HOST}" and other.local_port == 8765 and other.kind == "other"
    assert other.command == "tailscale funnel --https=443 --set-path=/ off"
    assert "reaches local port 8765" in other.message
    out = reach.run_funnel("off", 9001, **stub.kw)
    assert out["ran"] is None and stub.changes() == [] and "listed" in out["message"]
    assert stub.serve == web(443, 8765, funnel=True)
    assert paste(stub, other.command).returncode == 0, "its off is right, when the person runs it"
    assert not stub.serve.get("Web")


@pytest.mark.parametrize("serve, count", [
    (web(443, 8765, funnel=True), 0),  # the connector's own door
    (web(443, 8765), 0),               # tailnet-only: not public
    (web(443, 3000), 0),
    ({"Web": {f"{HOST}:443": {"Handlers": {"/": {"Proxy": "https://example.com"}}}},
      "AllowFunnel": {f"{HOST}:443": True}}, 0),  # not this machine's
    (merged(web(443, 3000, funnel=True), web(10000, 3001, funnel=True)), 2),
    (web(443, 8765, funnel=True, extra={"/api": {"Proxy": "http://127.0.0.1:8000"}}), 1),
])
def test_what_counts_as_another_public_mapping(serve, count):
    assert len(reach.funnel_others(serve, 8765)) == count


def test_the_apis_port_funnelled_is_named_as_such(stub):
    stub.set(serve=web(443, 8000, funnel=True, extra={"/odd path": {"Proxy": "http://127.0.0.1:8000"}}))
    state = reach.funnel_state(8765, closed_ports=(8000,), **stub.kw)
    assert {o.kind for o in state.others} == {"api"} and "Cicada's own API" in state.others[0].message
    assert "--set-path='/odd path' off" in state.others[1].command, "safe to paste"


def test_one_in_a_terminal_has_no_command_to_copy(stub):
    stub.set(serve={"Foreground": {"s1": web(443, 3000, funnel=True)}})
    (other,) = reach.funnel_state(8765, **stub.kw).others
    assert other.command is None and "Ctrl+C" in other.message


def test_closing_nothing_never_says_the_certificate_words(stub):
    out = reach.run_funnel("off", 8765, **stub.kw)
    assert out["ok"] is False and out["message"] == "The connector isn't open to the internet, so there is nothing to close."


def test_the_wire_shows_an_address_only_when_it_answered():
    on = reach.FunnelState("on", stop_command="x", mapped_url=f"https://{HOST}")
    assert reach.funnel_wire(on)["url"] is None
    assert reach.funnel_wire(on, answers=True)["url"] == f"https://{HOST}"
    waiting = reach.funnel_wire(on, answers=False)
    assert waiting["url"] is None and "10 minutes" in waiting["message"]
    dead = reach.funnel_wire(on, answers=False, listener_up=False)
    assert dead["url"] is None and "nothing answers" in dead["message"]


# ---------- the route ----------


class _FakeListener:
    def __init__(self, *, can_start=True):
        self.up, self.error, self.can_start = False, None, can_start

    async def start(self, **kwargs):
        self.up = self.can_start
        self.error = None if self.can_start else "port 8765 is already in use"
        return self.up

    async def stop(self):
        self.up = False


@pytest.fixture
def route(tmp_path, monkeypatch, stub):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(_bank(tmp_path)))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CICADA_REMOTE_PORT", raising=False)
    monkeypatch.setenv("PATH", f"{stub.folder}:{__import__('os').environ['PATH']}")
    config.get_settings.cache_clear()
    listener = _FakeListener()
    monkeypatch.setattr(remote_router, "LISTENER", listener)
    probes = []
    monkeypatch.setattr(reach, "probe", lambda url, **k: probes.append(url) or True)
    yield TestClient(main.app), listener, probes
    config.get_settings.cache_clear()


def test_starting_the_backend_and_every_read_change_nothing(tmp_path, monkeypatch, stub):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(_bank(tmp_path)))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", f"{stub.folder}:{__import__('os').environ['PATH']}")
    config.get_settings.cache_clear()
    with TestClient(main.app) as client:
        assert client.get("/remote/status").json()["enabled"] is False
        assert client.get("/remote/funnel?check=true").json()["step"] == "off"
        assert client.get("/devices/reach").status_code == 200
    assert stub.changes() == []
    config.get_settings.cache_clear()


def test_status_fields_are_exactly_what_they_were(route, stub):
    """Hyrum: `/remote/status` is read by the app and `cicada setup`; the funnel's answer is a route of its own."""
    client, _listener, _ = route
    body = client.get("/remote/status").json()
    assert set(body) == {"enabled", "port", "listenerUp", "listenerError", "publicBaseUrl", "detectedUrl", "effectiveUrl",
                         "tailscale", "ngrokInstalled", "reachable", "funnelCommand", "ngrokCommand", "funnelNote"}
    assert body["funnelNote"] is None
    assert body["funnelCommand"] == "tailscale funnel --bg --https=443 8765" and body["tailscale"] == "no-funnel"


def test_one_click_turns_the_connector_on_and_opens_only_its_port(route, stub):
    client, listener, probes = route
    shown = client.get("/remote/funnel").json()
    assert shown["step"] == "off" and shown["url"] is None
    # Whatever the request adds, the body has no port and no argv to use.
    got = client.post("/remote/funnel", json={"action": "on", "shown": shown["command"], "port": 8000,
                                              "argv": ["up"], "command": "tailscale up"}).json()
    assert got["ok"] is True and got["ran"] == "tailscale funnel --bg --https=443 8765"
    assert stub.changes() == [["funnel", "--bg", "--https=443", "8765"]]
    assert listener.up and store.load_settings().enabled is True
    assert got["funnel"]["step"] == "on" and got["funnel"]["url"] == f"https://{HOST}" and got["funnel"]["answers"] is True
    assert probes == [f"https://{HOST}"]
    status = client.get("/remote/status").json()
    assert status["tailscale"] == "funnel-on" and status["detectedUrl"] == f"https://{HOST}"


def test_a_failed_click_changes_nothing(route, stub):
    client, listener, _ = route
    stub.set(mode='Funnel not available; "funnel" node attribute not set. See https://tailscale.com/s/no-funnel.')
    shown = client.get("/remote/funnel").json()
    got = client.post("/remote/funnel", json={"action": "on", "shown": shown["command"]}).json()
    assert got["ok"] is False and got["fixUrl"] == "https://console.tailscale.com/admin/acls"
    assert got["funnel"]["fixUrl"] == got["fixUrl"] and got["funnel"]["step"] == "off"
    assert listener.up is False and store.load_settings().enabled is False


def test_a_connector_that_cannot_start_is_never_opened(route, stub, monkeypatch):
    client, _listener, _ = route
    monkeypatch.setattr(remote_router, "LISTENER", _FakeListener(can_start=False))
    shown = client.get("/remote/funnel").json()
    got = client.post("/remote/funnel", json={"action": "on", "shown": shown["command"]}).json()
    assert got["ok"] is False and got["ran"] is None and "already in use" in got["message"]
    assert stub.changes() == [] and store.load_settings().enabled is False


def test_a_port_configured_onto_the_api_is_refused_by_the_route(route, stub, monkeypatch):
    client, _listener, _ = route
    monkeypatch.setenv("CICADA_REMOTE_PORT", str(config.get_settings().port))
    assert client.get("/remote/funnel").json()["step"] == "port"
    got = client.post("/remote/funnel", json={"action": "on", "shown": "tailscale funnel --bg --https=443 8000"}).json()
    assert got["ok"] is False and stub.log() == []


def test_the_off_leaves_the_connector_on(route, stub):
    client, listener, _ = route
    assert client.put("/remote/settings", json={"enabled": True}).status_code == 200
    stub.set(serve=web(443, 8765, funnel=True))
    got = client.post("/remote/funnel", json={"action": "off"}).json()
    assert got["ok"] is True and got["funnel"]["step"] == "off"
    assert listener.up and store.load_settings().enabled is True


def test_the_truth_after_a_restart_comes_from_tailscale_and_nothing_is_stored(route, stub, monkeypatch):
    client, listener, _ = route
    shown = client.get("/remote/funnel").json()
    client.post("/remote/funnel", json={"action": "on", "shown": shown["command"]})
    assert set(json.loads(store.settings_path().read_text())) == {"enabled", "public_base_url"}
    # The backend came back and the listener has not (or the person switched the connector off): the mapping persists
    # in Tailscale, and the page says so rather than offering the address.
    listener.up = False
    got = client.get("/remote/funnel?check=true").json()
    assert got["step"] == "on" and got["answers"] is False and got["url"] is None and "nothing answers" in got["message"]
    assert got["stopCommand"]
    # Someone closed it behind Cicada's back: the next read says so.
    stub.set()
    assert client.get("/remote/funnel").json()["step"] == "off"


@pytest.fixture
def held_port():
    """A real program on a real port: what a public mapping serves once the listener is gone."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    yield sock.getsockname()[1]
    sock.close()


def test_with_the_listener_down_another_program_on_the_port_is_said(route, stub, held_port, monkeypatch):
    """The review of #607: `answers: false`, "nothing answers", while the port served that program's private body."""
    client, listener, probes = route
    monkeypatch.setenv("CICADA_REMOTE_PORT", str(held_port))
    stub.set(serve=web(443, held_port, funnel=True))
    assert listener.up is False
    for path in ("/remote/funnel", "/remote/funnel?check=true"):
        got = client.get(path).json()
        assert got["step"] == "on" and got["otherProgram"] is True and got["url"] is None
        assert "Another program" in got["message"] and "nothing answers" not in got["message"]
        assert got["stopCommand"] == "tailscale funnel --https=443 --set-path=/ off", "with the off offered"
    assert probes == [], "the identity probe would only say no"
    assert client.post("/remote/funnel", json={"action": "off"}).json()["ok"] is True
    assert not stub.serve.get("Web")


def test_with_the_listener_down_and_nothing_on_the_port_it_says_what_could_happen(route, stub, monkeypatch):
    client, _listener, _ = route
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("CICADA_REMOTE_PORT", str(free))
    stub.set(serve=web(443, free, funnel=True))
    got = client.get("/remote/funnel").json()
    assert got["otherProgram"] is False and got["answers"] is False
    assert "any program that takes the connector's port will be public" in got["message"]


def test_a_saved_address_does_not_hide_another_program(route, stub, held_port, monkeypatch):
    client, _listener, _ = route
    assert client.put("/remote/settings", json={"publicBaseUrl": "https://own.example"}).status_code == 200
    monkeypatch.setenv("CICADA_REMOTE_PORT", str(held_port))
    stub.set(serve=web(443, held_port, funnel=True))
    assert client.get("/remote/funnel").json()["otherProgram"] is True


def test_turning_the_connector_off_closes_its_address_in_the_same_act(route, stub):
    client, listener, _ = route
    assert client.put("/remote/settings", json={"enabled": True}).status_code == 200
    stub.set(serve=merged(web(8443, 8000), web(443, 8765, funnel=True), web(10000, 3000, funnel=True)))
    got = client.put("/remote/settings", json={"enabled": False}).json()
    assert got["enabled"] is False and listener.up is False and "closed too" in got["funnelNote"]
    assert stub.changes() == [["funnel", "--https=443", "--set-path=/", "off"]], "its own door and no other"
    assert f"{HOST}:8443" in stub.serve["Web"] and f"{HOST}:10000" in stub.serve["Web"]
    # Turning it back on never reopens it: that stays the person's click.
    after = client.put("/remote/settings", json={"enabled": True}).json()
    assert after["funnelNote"] is None and len(stub.changes()) == 1
    assert client.get("/remote/funnel").json()["step"] == "off"


def test_the_switch_closes_every_mapping_of_the_connector(route, stub):
    client, _listener, _ = route
    assert client.put("/remote/settings", json={"enabled": True}).status_code == 200
    stub.set(serve=merged(web(443, 8765, funnel=True), web(10000, 8765, funnel=True)))
    assert "closed too" in client.put("/remote/settings", json={"enabled": False}).json()["funnelNote"]
    assert not stub.serve.get("Web")


def test_the_connector_turns_off_even_if_the_address_will_not_close(route, stub):
    client, listener, _ = route
    assert client.put("/remote/settings", json={"enabled": True}).status_code == 200
    stub.set(serve=web(443, 8765, funnel=True), off_fail="something odd")
    got = client.put("/remote/settings", json={"enabled": False}).json()
    assert got["enabled"] is False and listener.up is False
    assert got["funnelNote"].startswith("The connector is off, but its public address is still open.")
    again = client.get("/remote/funnel").json()
    assert again["step"] == "on" and again["stopCommand"], "still in sight, with its off"


def test_one_from_a_terminal_is_said_when_the_switch_goes_off(route, stub):
    client, _listener, _ = route
    assert client.put("/remote/settings", json={"enabled": True}).status_code == 200
    stub.set(serve={"Foreground": {"s1": web(443, 8765, funnel=True)}})
    assert "Ctrl+C" in client.put("/remote/settings", json={"enabled": False}).json()["funnelNote"]
    assert stub.changes() == []


def test_nothing_to_close_says_nothing_and_saving_an_address_closes_nothing(route, stub):
    client, _listener, _ = route
    assert client.put("/remote/settings", json={"enabled": True}).status_code == 200
    assert client.put("/remote/settings", json={"enabled": False}).json()["funnelNote"] is None
    stub.set(serve=web(443, 8765, funnel=True))
    assert client.put("/remote/settings", json={"publicBaseUrl": "https://own.example"}).json()["funnelNote"] is None
    assert stub.changes() == []


def test_the_api_port_this_request_arrived_on_is_closed_whatever_the_settings_say(stub, tmp_path, monkeypatch):
    """`uvicorn --port` leaves `get_settings().port` at 8000. The request's own socket knows better."""
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(_bank(tmp_path)))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", f"{stub.folder}:{__import__('os').environ['PATH']}")
    monkeypatch.setenv("CICADA_REMOTE_PORT", "8123")
    config.get_settings.cache_clear()
    assert config.get_settings().port != 8123
    client = TestClient(main.app, base_url="http://127.0.0.1:8123")
    assert client.get("/remote/funnel").json()["step"] == "port"
    assert client.get("/remote/status").json()["funnelCommand"] == reach.FUNNEL_COPY_PORT
    got = client.post("/remote/funnel", json={"action": "on", "shown": "tailscale funnel --bg --https=443 8123"}).json()
    assert got["ok"] is False and stub.changes() == []
    config.get_settings.cache_clear()


def test_a_start_warns_only_about_a_real_exposure_and_changes_nothing(stub, held_port, monkeypatch):
    import asyncio

    from loguru import logger

    from api.remote import listener as remote_listener

    seen = []
    sink = logger.add(lambda m: seen.append(str(m)), level="WARNING")
    monkeypatch.setenv("PATH", f"{stub.folder}:{__import__('os').environ['PATH']}")
    monkeypatch.setenv("CICADA_REMOTE_PORT", str(held_port))
    try:
        asyncio.run(remote_listener.warn_if_exposed())
        assert seen == [] and stub.changes() == [], "a program on that port and no mapping: nothing to say"
        stub.set(serve=web(443, held_port, funnel=True))
        asyncio.run(remote_listener.warn_if_exposed())
        assert len(seen) == 1 and f"port {held_port}" in seen[0] and "ts.net" not in seen[0]
        assert stub.changes() == [], "a start never touches Tailscale"
    finally:
        logger.remove(sink)


def test_a_normal_start_never_runs_tailscale(stub, monkeypatch):
    import asyncio

    from api.remote import listener as remote_listener

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    free = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("PATH", f"{stub.folder}:{__import__('os').environ['PATH']}")
    monkeypatch.setenv("CICADA_REMOTE_PORT", str(free))
    asyncio.run(remote_listener.warn_if_exposed())
    assert stub.log() == []


def test_a_saved_address_of_their_own_comes_first(route, stub):
    client, _listener, _ = route
    assert client.put("/remote/settings", json={"publicBaseUrl": "https://own.example"}).status_code == 200
    got = client.get("/remote/funnel").json()
    assert got["step"] == "address" and got["command"] is None and "Clear it" in got["message"]


def test_an_unknown_action_is_refused(route, stub):
    client, _listener, _ = route
    assert client.post("/remote/funnel", json={"action": "reset"}).status_code == 422
    assert stub.changes() == []


def test_the_click_takes_the_master_token(tmp_path, monkeypatch, stub):
    from api.services import auth, device_tokens

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(_bank(tmp_path)))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setenv("PATH", f"{stub.folder}:{__import__('os').environ['PATH']}")
    config.get_settings.cache_clear()
    _device, token = device_tokens.store().create("Other computer")
    with TestClient(main.app) as client:
        body = {"action": "on", "shown": "tailscale funnel --bg --https=443 8765"}
        assert client.post("/remote/funnel", json=body).status_code == 401
        assert client.post("/remote/funnel", json=body,
                           headers={"Authorization": f"Bearer {token}"}).status_code == 403
        assert stub.changes() == []
        master = {"Authorization": f"Bearer {auth.get_token()}"}
        assert client.get("/remote/funnel", headers=master).json()["step"] == "off"
    config.get_settings.cache_clear()


# ---------- what a stranger sees at the public address ----------


@pytest.fixture
def stranger(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    (memory / "entities" / "sentinel-person.md").write_text("---\nname: ZEBRA-SENTINEL\ntype: person\n---\nZEBRA-SENTINEL\n")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    db = store.ConnectorStore(tmp_path / "remote" / "connectors.db")
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    with TestClient(remote_app.build_app(db, runtime=runtime), base_url=f"https://{HOST}") as client:
        yield client
    config.get_settings.cache_clear()


@pytest.mark.parametrize("path", [
    "/", "/healthz", "/graph", "/entities", "/inbox", "/docs", "/redoc", "/openapi.json", "/remote/status",
    "/remote/funnel", "/remote/connectors", "/remote/oauth/requests", "/devices", "/devices/reach", "/sync/status",
    "/tools/call", "/capture/mine",
])
def test_no_backend_route_is_there(stranger, path):
    assert stranger.get(path).status_code == 404
    assert stranger.post(path, json={}).status_code == 404


def test_no_way_to_approve_a_sign_in_from_outside(stranger):
    for path in ("/remote/oauth/approve", "/remote/oauth/match", "/authorize/approve", "/approve", "/consent"):
        assert stranger.post(path, json={"userCode": "AAAA-BBBB"}).status_code == 404


def test_the_memory_needs_a_token(stranger):
    no_token = stranger.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                             headers={"Accept": "application/json, text/event-stream"})
    assert no_token.status_code == 401 and "resource_metadata" in no_token.headers["www-authenticate"]
    assert "result" not in no_token.text
    assert stranger.get("/v1/me").status_code == 401
    assert stranger.post("/v1/recall", json={"query": "x"}).status_code == 401
    assert stranger.post("/c/cic_rc_aaaaaaaa_bad/mcp", json={}).status_code == 401


def test_the_open_documents_say_nothing_about_the_person(stranger, tmp_path):
    prm = stranger.get("/.well-known/oauth-protected-resource/mcp")
    assert prm.status_code == 200 and prm.json()["resource"] == f"https://{HOST}/mcp"
    assert prm.json()["resource_name"] == "Cicada"
    assert stranger.get("/.well-known/oauth-authorization-server").status_code == 200
    for path in ("/v1/openapi.json", "/v1/llms.txt", "/llms.txt"):
        got = stranger.get(path)
        assert got.status_code == 200
        assert "ZEBRA-SENTINEL" not in got.text and str(tmp_path) not in got.text
    bad = stranger.get("/authorize?client_id=nobody&redirect_uri=https://evil.example/cb&response_type=code",
                       follow_redirects=False)
    assert bad.status_code == 400 and "location" not in bad.headers, "a mismatch is a page, never a redirect"
