"""G135 R-R19..R-R21 — the embedded listener: loopback only, no access log, the
host server's signals untouched, a busy port is an error not an exit, and a
missing SDK is reported, never raised. Every socket here is 127.0.0.1:0."""
from __future__ import annotations

import asyncio
import logging
import signal
import socket
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.remote import listener as remote_listener
from api.remote import store
from api.remote.app import build_app


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def access_log():
    """A handler on the process-global `uvicorn.access` logger, at INFO — it
    stands in for the MAIN server's access log. Without the level, INFO
    records would be filtered before any handler and every assertion below
    would pass vacuously."""
    access = logging.getLogger("uvicorn.access")
    grab, level = _Grab(), access.level
    access.addHandler(grab)
    access.setLevel(logging.INFO)
    yield access, grab
    access.removeHandler(grab)
    access.setLevel(level)


def _tools_list(port: int, token: str):
    async def go():
        async with httpx.AsyncClient(trust_env=False) as client:
            return await client.post(
                f"http://127.0.0.1:{port}/c/{token}/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={"Accept": "application/json, text/event-stream", "Mcp-Protocol-Version": "2025-11-25"})
    return go()


def test_the_listener_serves_on_loopback_logs_no_path_and_stops(tmp_path, access_log):
    access, grab = access_log
    db = store.ConnectorStore(tmp_path / "remote" / "connectors.db")
    _, token = db.create(app="claude", label="", scopes=["search"], expires_in_days=30)
    before = signal.getsignal(signal.SIGTERM)
    lst = remote_listener.RemoteListener()

    async def scenario():
        assert await lst.start(port=0, app=build_app(db)) is True
        assert lst.up and signal.getsignal(signal.SIGTERM) is before
        async with httpx.AsyncClient(trust_env=False) as client:
            prm = await client.get(f"http://127.0.0.1:{lst.port}/.well-known/oauth-protected-resource/mcp")
            assert prm.status_code == 200
        assert (await _tools_list(lst.port, token)).status_code == 200
        await lst.stop()
        assert not lst.up

    asyncio.run(scenario())
    assert grab in access.handlers, "the listener must never strip the main server's access log"
    assert not any(token in line for line in grab.lines)


def test_the_stock_protocol_would_have_logged_the_token(tmp_path, access_log):
    """Negative control for the test above: the same request through uvicorn's
    stock H11 protocol DOES write the secret path to the access log — so the
    quiet protocol, not an absent handler, is what keeps the token out."""
    import uvicorn
    from uvicorn.protocols.http.h11_impl import H11Protocol

    _, grab = access_log
    db = store.ConnectorStore(tmp_path / "remote" / "connectors.db")
    _, token = db.create(app="claude", label="", scopes=["search"], expires_in_days=30)

    async def scenario():
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        server = remote_listener._EmbeddedServer(
            uvicorn.Config(build_app(db), http=H11Protocol, ws="none", lifespan="on", log_config=None))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        for _ in range(250):
            if server.started:
                break
            await asyncio.sleep(0.02)
        await _tools_list(sock.getsockname()[1], token)
        server.should_exit = True
        await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    assert any(token in line for line in grab.lines)


def test_a_busy_port_is_an_error_not_an_exit(tmp_path):
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    lst = remote_listener.RemoteListener()
    try:
        started = asyncio.run(lst.start(port=busy.getsockname()[1],
                                        app=build_app(store.ConnectorStore(tmp_path / "c.db"))))
    finally:
        busy.close()
    assert started is False and "already in use" in (lst.error or "") and not lst.up


def test_a_missing_sdk_is_reported_not_raised(monkeypatch):
    monkeypatch.setitem(sys.modules, "api.remote.app", None)
    lst = remote_listener.RemoteListener()
    assert asyncio.run(lst.start(port=0)) is False
    assert "mcp package" in (lst.error or "")


def test_the_backend_lifespan_starts_it_only_when_enabled(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_REMOTE_PORT", "0")
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app):
            assert not remote_listener.LISTENER.up, "off by default"
        store.save_settings(store.RemoteSettings(enabled=True))
        with TestClient(main.app):
            assert remote_listener.LISTENER.up
        assert not remote_listener.LISTENER.up, "stopped with the backend"
    finally:
        asyncio.run(remote_listener.LISTENER.stop())
        config.get_settings.cache_clear()
