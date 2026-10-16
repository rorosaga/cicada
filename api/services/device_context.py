"""Which of the person's devices this request came from (G181 phase 3: "where memory came from").

``auth.require_token`` looks the bearer up and, for a per-device token (``device_tokens``), binds the device's id here
for the rest of the request — the same evidence ``request.state.device`` holds, never anything the client says about
itself. The one writer that reads it is ``episode_ids.create_episode``: a NEW episode written while serving a request
a device signed records ``device: <id>`` in its frontmatter (unless its writer already set one), so every door a
device posts through — the app's readers, an upload, a save, a tool call, a session — says where it came from without
each route threading the id by hand. The master token, an open path and auth turned off bind nothing, so everything
the server's own machine writes carries no ``device`` (the app reads that as "this server").

A ``ContextVar`` follows the request into ``run_in_threadpool`` / ``asyncio.to_thread`` and into the tasks it starts.
Work that is not the device's even when a device started it — Sleep, whose run a client's click may start — calls
:func:`clear` first, so nothing Sleep writes is credited to the device that pressed the button. Ids only: the token
never reaches this module.
"""
from __future__ import annotations

from contextvars import ContextVar

_DEVICE: ContextVar[str | None] = ContextVar("cicada_request_device", default=None)


def bind(device_id: str | None) -> None:
    """Record the device (or none) for the rest of this request's context."""
    _DEVICE.set(device_id or None)


def clear() -> None:
    """Work that is the server's own from here on (Sleep): nothing it writes is credited to a device."""
    _DEVICE.set(None)


def current() -> str | None:
    return _DEVICE.get()


def stamp(frontmatter: dict) -> dict:
    """Add ``device`` to a new episode's frontmatter when a device signed this request and the writer set none."""
    device = _DEVICE.get()
    if device and not frontmatter.get("device"):
        frontmatter["device"] = device
    return frontmatter
