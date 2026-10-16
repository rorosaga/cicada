"""A headless Chrome for tests of the site-explore capture script — just enough of browser-harness's helpers (``cdp``,
``js``, ``wait_for_load``, ``wait_for_network_idle``, ``switch_tab``) over the DevTools protocol of one page.

Its own scratch profile (``--user-data-dir`` under the test's tmp dir), ``--use-mock-keychain`` so it never asks the
login keychain for anything, a port the OS picks, and the process is always killed on exit. Never the person's own
Chrome or profile. Tests skip when no Chrome is found (``CICADA_CHROME`` names one explicitly)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

CANDIDATES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium")


def chrome_binary() -> str | None:
    given = os.environ.get("CICADA_CHROME")
    if given:
        return given if Path(given).is_file() else None
    return next((c for c in CANDIDATES if Path(c).is_file()), None)


class Page:
    """One page target, driven synchronously."""

    def __init__(self, ws_url: str):
        from websockets.sync.client import connect

        self.ws = connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=10)
        self.next_id = 0

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass

    def cdp(self, method, _response_timeout=30, **params):
        if method.startswith("Target."):
            return {"targetId": "page", "browserContextId": "ctx"}   # the test drives one page it opened
        self.next_id += 1
        mid = self.next_id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        deadline = time.monotonic() + _response_timeout
        while True:
            raw = self.ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result", {})

    def js(self, expression):
        got = self.cdp("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if got.get("exceptionDetails"):
            raise RuntimeError(str(got["exceptionDetails"])[:300])
        return (got.get("result") or {}).get("value")

    def wait_for_load(self, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js("document.readyState") == "complete":
                return True
            time.sleep(0.05)
        return False

    def helpers(self) -> dict:
        return {"cdp": self.cdp, "js": self.js, "wait_for_load": self.wait_for_load,
                "wait_for_network_idle": lambda timeout=10.0, idle_ms=500: False,
                "switch_tab": lambda *a, **k: None}


@contextmanager
def headless_page(profile: Path):
    binary = chrome_binary()
    if binary is None:
        raise RuntimeError("no Chrome")
    profile.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [binary, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}", "--use-mock-keychain",
         "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
         "--disable-background-networking", "--disable-component-update", "--hide-scrollbars", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    page = None
    try:
        port_file = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 20
        while not port_file.is_file() or not port_file.read_text().strip():
            if time.monotonic() > deadline or proc.poll() is not None:
                raise RuntimeError("Chrome did not start")
            time.sleep(0.05)
        port = int(port_file.read_text().split()[0])
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5).read())
        ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page")
        page = Page(ws_url)
        page.cdp("Page.enable")
        yield page
    finally:
        if page is not None:
            page.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)
