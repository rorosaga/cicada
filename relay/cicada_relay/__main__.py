"""``python -m cicada_relay``: run the relay until SIGTERM or SIGINT. Every setting is a ``RELAY_*`` variable
(``config.Config``)."""
from __future__ import annotations

import asyncio
import logging
import signal

from .config import Config
from .server import Relay


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # The websocket library's own lines can name a peer's address; the relay logs ids, sizes and timings only.
    logging.getLogger("websockets").setLevel(logging.CRITICAL)
    relay = await Relay(Config.from_env()).start()
    logging.getLogger("cicada_relay").info("listening port=%d tls=%s", relay.port, bool(relay.config.tls_cert))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await relay.stop()


if __name__ == "__main__":
    asyncio.run(main())
