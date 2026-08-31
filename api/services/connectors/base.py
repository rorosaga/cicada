"""Injectable HTTP seam + network gate shared by every connector."""

from __future__ import annotations

import inspect
import os
from typing import Any, Callable

# Called as ``http_fn(method, url, *, headers=None, params=None, data=None,
# auth=None) -> dict``. May be sync or async: tests inject plain functions, the
# real default is async.
HttpFn = Callable[..., Any]

GATE_ENV = "CICADA_ALLOW_CONNECTOR_FETCH"
TIMEOUT_SECONDS = 15.0


class ConnectorError(RuntimeError):
    """A sync could not complete — recorded, never raised past ``sync()``."""


def network_allowed(allow_fetch: bool | None = None) -> bool:
    """Whether the DEFAULT transport may run. An injected ``http_fn`` bypasses
    this entirely — the caller has supplied the mechanism, so there is nothing
    left to gate."""
    if allow_fetch is not None:
        return bool(allow_fetch)
    return os.environ.get(GATE_ENV) == "1"


async def default_http(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    data: dict | None = None,
    auth: tuple[str, str] | None = None,
) -> dict:
    """The gated live-HTTP transport. Only ever invoked when the gate is open."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.request(
            method, url, headers=headers, params=params, data=data,
            auth=auth, timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()


async def call_http(http_fn: HttpFn, method: str, url: str, **kwargs) -> dict:
    """Call ``http_fn`` and await it if it returned a coroutine."""
    result = http_fn(method, url, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result
