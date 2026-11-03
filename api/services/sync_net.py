"""Starting and stopping the home-network door and the relay link from the backend's lifespan (G132 phase 3b, ruling
51f). Nothing shared — nothing starts. No relay set — nothing relay-side is imported. The direct path needs nothing started: it is the
address the person already configured (``sync_direct_listen`` shows it; the backend still binds 127.0.0.1)."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def _shared(memory_path) -> bool:
    from api.services import demo_guard, runtime_layout, sync_publish

    try:
        if demo_guard.is_demo(Path(memory_path)):
            return False
        return runtime_layout.is_replica() or sync_publish.publishable(memory_path)
    except Exception:  # noqa: BLE001
        return False


async def on_start(app, settings) -> None:
    """After the backend knows its part (home or replica) and before a replica's follower starts: the home-network
    door while the memory is shared (ruling 51f D3), then the relay link when the person set a relay."""
    import asyncio

    from api.services import sync_transport

    shared = await asyncio.to_thread(_shared, settings.memory_path)
    if shared:
        await ensure_door(app, settings.memory_path, shared=True)
    if sync_transport.relay_url() is None or not shared:
        return
    await restart_link(app, settings.memory_path)


async def ensure_door(app, memory_path, *, shared: bool | None = None) -> None:
    """Open the door when this memory is shared and closed when it is not (the publish switch, a copy started or
    left). Off until a memory is shared; never for a demo; ``CICADA_SYNC_DOOR=off`` keeps it shut."""
    import asyncio

    from api.services import sync_door

    if shared is None:
        shared = await asyncio.to_thread(_shared, memory_path)
    if shared and sync_door.enabled():
        await sync_door.start(app, memory_path)
    else:
        await sync_door.stop()


async def on_stop() -> None:
    mod = sys.modules.get("api.services.sync_relay_link")
    if mod is not None:
        await mod.stop()
    door = sys.modules.get("api.services.sync_door")
    if door is not None:
        await door.stop()


async def restart_link(app, memory_path) -> None:
    """(Re)start the relay link for the setting now in force: stopped when cleared, started when set and shared."""
    from api.services import sync_transport

    mod = sys.modules.get("api.services.sync_relay_link")
    if mod is not None:
        await mod.stop()
    if sync_transport.relay_url() is None:
        return
    from api.services import sync_relay_link

    try:
        await sync_relay_link.start(app, memory_path)
    except Exception as exc:  # noqa: BLE001 — the direct path carries everything meanwhile
        logger.warning(f"relay: the link did not start ({type(exc).__name__})")


async def on_revoke(device) -> None:
    """A device the person removed leaves the relay group at once: a new epoch it holds no key to, and the relay
    closes its socket and drops what waited for it. Revoking cannot take back the copy it already holds."""
    from api.services import sync_transport

    link = sync_transport._link()   # noqa: SLF001
    if link is None or not link.is_home or not getattr(device, "relay_ed", None):
        return
    try:
        await link.revoke(device.relay_ed)
    except Exception as exc:  # noqa: BLE001 — the token is revoked either way; the group follows at the next connect
        logger.info(f"relay: the group was not rotated now ({type(exc).__name__})")
