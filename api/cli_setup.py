"""`cicada setup` (G213, owner 2026-10-22): look at this machine, say what was found, and confirm each step.

What it does, in order — every write is the backend's own route (ruling 21a), every command it runs is shown first,
word for word, and runs only on the person's yes:

1. **Detect** (no writes): the Cicada server and its memory (`/healthz`), the agents on this machine and whether each
   reaches Cicada (`GET /agents/wiring`, the probe Settings → Agents shows), and a way in from outside — Tailscale,
   a Funnel address, ngrok (`GET /remote/status`, which detects and never changes a tunnel).
2. **Connect agents**: for each installed agent that does not reach Cicada yet, the exact commands the app would run
   after a click (`connect`, `display == shlex.join(argv)`), run here on a yes.
3. **Pair a device** (G212): a one-time code and its QR payload (`POST /devices/pairing`), then a wait for the new
   device to pair, Ctrl-C to stop waiting.
4. **Hand an agent the HTTP API** (G213): an agent token (`POST /agent-api/tokens`) and the paragraph to give it.

The person's act only (`require_person`): it makes credentials. Without a terminal (a pipe, CI) it asks nothing:
it reports what it found and the commands that would do the rest — unless the flags name a step (`--pair`,
`--agent NAME`), which then runs with its defaults. `rich` and `questionary` are imported here only; without them
the same steps print as plain lines and prompts.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from api.cli_types import Refusal, Result

PAIR_WAIT_S = 600
PAIR_POLL_S = 2.0
STEP_TIMEOUT_S = 120


@dataclass
class Found:
    server: dict | None = None
    server_error: str | None = None
    agents: list[dict] = field(default_factory=list)
    remote: dict | None = None


class Ui:
    """Prompts and output. ``rich``/``questionary`` when present and on a terminal; plain otherwise. Tests pass a
    scripted one."""

    def __init__(self, interactive: bool) -> None:
        self.interactive = interactive
        try:
            from rich.console import Console

            self.console = Console(stderr=True, highlight=False)
        except ImportError:   # an install from before the dependency: the same steps, plain
            self.console = None

    def say(self, text: str = "") -> None:
        if self.console is not None:
            self.console.print(text)
        else:
            print(_plain(text), file=sys.stderr)

    def status(self, text: str):
        if self.console is not None and self.interactive:
            return self.console.status(text, spinner="dots")
        return _NoStatus()

    def confirm(self, question: str, default: bool = True) -> bool:
        if not self.interactive:
            return default
        try:
            import questionary

            answer = questionary.confirm(question, default=default).ask()
        except ImportError:
            raw = input(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
            answer = default if not raw else raw.startswith("y")
        if answer is None:   # Ctrl-C at a prompt
            raise KeyboardInterrupt
        return bool(answer)

    def text(self, question: str, default: str = "") -> str:
        if not self.interactive:
            return default
        try:
            import questionary

            answer = questionary.text(question, default=default).ask()
        except ImportError:
            answer = input(f"{question} ") or default
        if answer is None:
            raise KeyboardInterrupt
        return answer.strip()

    def choose_many(self, question: str, choices: list[tuple[str, bool]]) -> list[str]:
        if not self.interactive:
            return [c for c, on in choices if on]
        try:
            import questionary

            answer = questionary.checkbox(question, choices=[questionary.Choice(c, checked=on)
                                                             for c, on in choices]).ask()
        except ImportError:
            raw = input(f"{question} ({', '.join(c for c, _ in choices)}; blank for the default) ").strip()
            answer = [c.strip() for c in raw.split(",") if c.strip()] if raw else [c for c, on in choices if on]
        if answer is None:
            raise KeyboardInterrupt
        return list(answer)


class _NoStatus:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _plain(text: str) -> str:
    import re

    return re.sub(r"\[/?[a-z ]+\]", "", text)


def detect(call: Callable, ui: Ui) -> Found:
    found = Found()
    with ui.status("Looking for the Cicada server…"):
        try:
            found.server = call("GET", "/healthz")
        except Refusal as exc:
            found.server_error = exc.code
    if found.server is None:
        return found
    with ui.status("Looking for agents on this machine…"):
        try:
            found.agents = list((call("GET", "/agents/wiring") or {}).get("agents") or [])
        except Refusal:
            found.agents = []
    with ui.status("Looking for a way in from outside…"):
        try:
            found.remote = call("GET", "/remote/status")
        except Refusal:
            found.remote = None
    return found


def _check(ok: bool | None) -> str:
    return {True: "[green]✓[/green]", False: "[yellow]•[/yellow]", None: "[dim]–[/dim]"}[ok]


def report(found: Found, ui: Ui) -> list[str]:
    lines: list[str] = []
    if found.server is None:
        lines.append(f"{_check(False)} No Cicada server answered ({found.server_error or 'backend_down'}). Start it "
                     "with the app, or `./install.sh` on this machine, then run `cicada setup` again.")
    else:
        pages = found.server.get("entityCount")
        held = f", {pages} page{'' if pages == 1 else 's'} in memory" if isinstance(pages, int) else ""
        lines.append(f"{_check(True)} Cicada server is running (version {found.server.get('version', '?')}{held}).")
        installed = [a for a in found.agents if a.get("installed")]
        if not installed:
            lines.append(f"{_check(None)} No agents found on this machine.")
        for agent in installed:
            on = agent.get("recall") == "on"
            lines.append(f"{_check(on)} {agent.get('id')}: {'reaches Cicada' if on else 'not connected yet'}")
        remote = found.remote or {}
        if remote.get("effectiveUrl") or remote.get("detectedUrl"):
            url = remote.get("effectiveUrl") or remote.get("detectedUrl")
            lines.append(f"{_check(True)} A public address for phone and cloud agents: {url}")
        elif remote.get("tailscale") not in (None, "", "missing"):
            lines.append(f"{_check(False)} Tailscale is here, with no public address yet. Phones on your tailnet "
                         f"can pair; cloud agents need `{remote.get('funnelCommand', 'tailscale funnel')}`.")
        else:
            lines.append(f"{_check(None)} No Tailscale or ngrok: this machine is reachable from itself only.")
    for line in lines:
        ui.say(line)
    return lines


def connect_agents(found: Found, ui: Ui, run: Callable) -> list[str]:
    done: list[str] = []
    for agent in found.agents:
        steps = agent.get("connect") or []
        if not agent.get("installed") or agent.get("recall") == "on" or not steps:
            continue
        ui.say(f"\n[bold]{agent.get('id')}[/bold] — these commands connect it to Cicada:")
        for step in steps:
            ui.say(f"  $ {step.get('display') or shlex.join(step.get('argv') or [])}")
        if not ui.interactive or not ui.confirm(f"Run them for {agent.get('id')}?"):
            continue
        ok = True
        for step in steps:
            argv = list(step.get("argv") or [])
            if not argv or shlex.join(argv) != (step.get("display") or shlex.join(argv)):
                ok = False   # what would run is not what was shown: never run it
                break
            with ui.status(f"{step.get('display')}"):
                code = run(argv)
            if code != 0:
                ok = False
                ui.say(f"  [red]✗[/red] exited {code}; nothing else was run for {agent.get('id')}.")
                break
        if ok:
            done.append(str(agent.get("id")))
            ui.say(f"  {_check(True)} {agent.get('id')} connected.")
    return done


def pair(call: Callable, ui: Ui, url: str | None, *, wait: bool, sleep=time.sleep, clock=time.monotonic) -> dict:
    import json

    body = {"url": url} if url else {}
    answer = call("POST", "/devices/pairing", body=body)
    code, qr = answer.get("code"), answer.get("qr") or {}
    ui.say(f"\nPairing code: [bold]{code}[/bold]   (ten minutes, once)")
    ui.say(f"QR payload: {json.dumps(qr, separators=(',', ':'))}")
    ui.say("Scan it in the Cicada app on the new device, or post {\"code\", \"name\"} to <this server>/pair.")
    if not wait:
        return {"pairing": answer.get("pairing"), "code": code, "qr": qr, "paired": None}
    pairing_id = (answer.get("pairing") or {}).get("id")
    deadline = clock() + PAIR_WAIT_S
    state, device = "waiting", None
    try:
        with ui.status("Waiting for the new device (Ctrl-C to stop waiting)…"):
            while clock() < deadline:
                seen = call("GET", f"/devices/pairing/{pairing_id}")
                state, device = (seen.get("pairing") or {}).get("state"), seen.get("device")
                if state != "waiting":
                    break
                sleep(PAIR_POLL_S)
    except KeyboardInterrupt:
        ui.say("Stopped waiting; the code still works until it expires.")
    if state == "paired" and device:
        ui.say(f"{_check(True)} Paired '{device.get('name')}' ({device.get('id')}).")
    return {"pairing": answer.get("pairing"), "code": code, "qr": qr, "paired": device}


def agent_token(call: Callable, ui: Ui, name: str, url: str | None, scopes: list[str] | None = None,
                days: int | None = None) -> dict:
    body: dict = {"name": name}
    if scopes:
        body["scopes"] = scopes
    if days:
        body["expiresInDays"] = days
    if url:
        body["baseUrl"] = url
    answer = call("POST", "/agent-api/tokens", body=body)
    prompt = answer.get("prompt") or ""
    ui.say(f"\nGive {name} this paragraph (shown once; Cicada keeps only the token's hash):\n")
    if ui.console is not None:
        from rich.panel import Panel

        ui.console.print(Panel(prompt, expand=False))
    else:
        ui.say(prompt)
    return answer


def run_setup(*, call: Callable, ui: Ui, url: str | None = None, pair_now: bool | None = None,
              agent_name: str | None = None, run: Callable | None = None) -> Result:
    run = run or _run_argv
    ui.say("[bold]Cicada setup[/bold]\n")
    found = detect(call, ui)
    lines = report(found, ui)
    data: dict = {"found": {"server": found.server is not None, "agents": [a.get("id") for a in found.agents
                                                                            if a.get("installed")],
                            "remote": bool((found.remote or {}).get("effectiveUrl"))}}
    if found.server is None:
        return Result(text="\n".join(_plain(line) for line in lines), data=data, code="backend_down")
    data["connected"] = connect_agents(found, ui, run)
    remote = found.remote or {}
    base = url or remote.get("effectiveUrl") or remote.get("detectedUrl")

    if pair_now is None:
        pair_now = ui.interactive and ui.confirm("\nPair a phone or another machine now?", default=False)
    if pair_now:
        if ui.interactive and not url:
            base = ui.text("The address it will reach this server at (blank: fill it in on the device):",
                           default=base or "") or None
        data["pairing"] = pair(call, ui, base, wait=ui.interactive)

    if agent_name is None and ui.interactive and ui.confirm(
            "\nGive a personal agent (one that can't use MCP) access over HTTP?", default=False):
        agent_name = ui.text("The agent's name:")
    if agent_name:
        scopes = ui.choose_many("What may it do?", [("search", True), ("read", True), ("record", True),
                                                    ("answer", False), ("ask", False), ("sources", False)])
        data["agent"] = agent_token(call, ui, agent_name, base, scopes=scopes)

    ui.say("\n[bold]Done.[/bold] `cicada device list` and `cicada agent list` show what can reach this server.")
    summary = [_plain(line) for line in lines]
    if not ui.interactive and not pair_now and not agent_name:
        summary += ["", "Next, in your own terminal: `cicada setup` (asks before each step), "
                        "`cicada device pair --url <address>`, `cicada agent add <name> --url <address>`."]
    if data.get("agent"):
        summary += ["", data["agent"].get("prompt") or ""]
    if data.get("pairing"):
        summary += ["", f"Pairing code: {data['pairing']['code']}"]
    return Result(text="\n".join(summary), data=data)


def _run_argv(argv: list[str]) -> int:
    try:
        return subprocess.run(argv, timeout=STEP_TIMEOUT_S, check=False).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 127
