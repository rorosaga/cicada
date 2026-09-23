"""The remote connector's own listener (G135 R-R1, R-R19..R-R21): a second,
embedded uvicorn server on 127.0.0.1 — never 0.0.0.0; a tunnel the person
provisions is the only way in from outside.

Three uvicorn behaviours are wrong for a server that lives INSIDE another
(each verified on 0.44). `Server.serve` swaps the process's SIGINT/SIGTERM
handlers → `capture_signals` is a no-op here, and the host server keeps its
own. Its own bind failure calls `sys.exit(1)` → the socket is pre-bound and a
busy port becomes `error`. `Config(access_log=False)` empties the
process-global `uvicorn.access` logger, silencing the MAIN server too → this
server's protocol simply never logs, per connection (`_QuietH11`). The stock
protocol writes the request path to the access log, and a secret link's path
IS the token (negative control run while planning).
"""
from __future__ import annotations

import asyncio
import contextlib
import socket

import uvicorn
from loguru import logger
from uvicorn.protocols.http.h11_impl import H11Protocol

from api.remote import store


class _QuietH11(H11Protocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.access_log = False


class _EmbeddedServer(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):
        yield


class RemoteListener:
    def __init__(self) -> None:
        self._server: _EmbeddedServer | None = None
        self._task: asyncio.Task | None = None
        self.port: int | None = None
        self.error: str | None = None

    @property
    def up(self) -> bool:
        return bool(self._server is not None and self._server.started
                    and self._task is not None and not self._task.done())

    async def start(self, *, port: int | None = None, app=None) -> bool:
        if self.up:
            return True
        self.error = None
        port = store.remote_port() if port is None else port
        if app is None:
            try:
                from api.remote.app import build_app  # R-R21: the SDK is imported here and only here
            except ImportError:
                self.error = "the remote connector needs the mcp package — run ./install.sh"
                logger.warning(f"Remote connector not started: {self.error}")
                return False
            app = build_app()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            sock.close()
            self.error = f"port {port} is already in use"
            logger.warning(f"Remote connector not started: {self.error}")
            return False
        config = uvicorn.Config(app, http=_QuietH11, ws="none", lifespan="on", log_config=None)
        server = _EmbeddedServer(config)
        self._server, self.port = server, sock.getsockname()[1]
        self._task = asyncio.create_task(server.serve(sockets=[sock]), name="cicada-remote")
        for _ in range(250):
            if server.started or self._task.done():
                break
            await asyncio.sleep(0.02)
        if not server.started:
            self.error = "the listener did not start"
            await self.stop()
            return False
        logger.info(f"Remote connector listening on 127.0.0.1:{self.port}")
        return True

    async def stop(self) -> None:
        server, task = self._server, self._task
        self._server = self._task = None
        if server is None or task is None:
            return
        server.should_exit = True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except Exception:  # noqa: BLE001 — a stuck shutdown is forced, never raised into the host
            server.force_exit = True
            task.cancel()
        logger.info("Remote connector listener stopped")


LISTENER = RemoteListener()


async def start_if_enabled() -> bool:
    """Called by the backend lifespan. Never raises into boot."""
    try:
        if not store.load_settings().enabled:
            return False
        return await LISTENER.start()
    except Exception as exc:  # noqa: BLE001
        LISTENER.error = type(exc).__name__
        logger.warning(f"Remote connector not started: {type(exc).__name__}")
        return False
