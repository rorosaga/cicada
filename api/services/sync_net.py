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


def _door_wanted(memory_path) -> bool:
    """The door is open while this memory is shared with another device: it publishes its log, it is a copy, or a
    device is paired with it (a capture-only phone sends its captures through it). Never for a demo."""
    from api.services import demo_guard, device_tokens

    try:
        if demo_guard.is_demo(Path(memory_path)):
            return False
        if _shared(memory_path):
            return True
        return any(not r.get("revoked_at") and not r.get("is_self") for r in device_tokens.store().export())
    except Exception:  # noqa: BLE001
        return False


async def on_start(app, settings) -> None:
    """After the backend knows its part (home or replica) and before a replica's follower starts: the home-network
    door while the memory is shared (ruling 51f D3), then the relay link when the person set a relay."""
    import asyncio

    from api.services import sync_transport

    shared = await asyncio.to_thread(_shared, settings.memory_path)
    if shared or await asyncio.to_thread(_door_wanted, settings.memory_path):
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
        shared = await asyncio.to_thread(_door_wanted, memory_path)
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
    closes its socket and drops what waited for it. Revoking cannot take back the copy it already holds. The door
    forgets it at once too (every request it carries is checked against the store again anyway)."""
    from api.services import sync_transport

    door = sys.modules.get("api.services.sync_door")
    if door is not None and door.SERVER is not None:
        door.SERVER.lookup.forget()
        door.SERVER.close_device(device.id)          # its open sessions and its watch end now, not at their timeout

    link = sync_transport._link()   # noqa: SLF001
    if link is None or not link.is_home or not getattr(device, "relay_ed", None):
        return
    try:
        await link.revoke(device.relay_ed)
    except Exception as exc:  # noqa: BLE001 — the token is revoked either way; the group follows at the next connect
        logger.info(f"relay: the group was not rotated now ({type(exc).__name__})")


def may_open_door(memory_path) -> bool:
    """A pairing may open the door on any bank but a demo."""
    from api.services import demo_guard

    try:
        return not demo_guard.is_demo(Path(memory_path))
    except Exception:  # noqa: BLE001
        return False


def pairing_door(pairing_id: str | None = None) -> dict | None:
    """What a new device needs to reach this computer's door with no address of its own (ruling 51f; the phone app's
    later QR v2 carries it): this computer's device id and public signing key, the door's public key, its port and
    its addresses now. None while no door is open here. Public halves only."""
    door = sys.modules.get("api.services.sync_door")
    if door is None or door.SERVER is None or not door.SERVER.running():
        return None
    from api.services import device_key, home_move

    me = home_move.ensure_own_identity()
    routes = door.own_routes()
    if not me or not routes:
        return None
    out = {"v": 1, "home": me, "sign": device_key.public_jwk(create=True), **routes}
    if pairing_id:
        out["pair"] = door.SERVER.open_pairing(pairing_id)      # the one-time secret: only ever in this answer
    return out
