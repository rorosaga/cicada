"""Verify a key before it is saved (G50/G215, ruling 36 D1; research providers-2 §4.5 step 3).

One authenticated read per provider that costs no tokens — its models list (OpenRouter: its key endpoint, because its
models list answers without a key). It runs only when the person pastes a key and presses Save, sends the key only to
that provider's own fixed host below (never a host a request names), through ``net_guard``'s request hook, with no
cookies and a 6 s budget, and logs nothing: not the key, not the URL, not the body. The answer is three words:

* ``ok`` — the provider accepted the key (HTTP 200); ``models`` is the ids it lists, when it lists them, so the
  caller can say whether the default model is one of them.
* ``refused`` — HTTP 401 or 403 (and 400 where that provider answers a bad key with it, ``Probe.refuses``): the key
  is wrong, revoked or lacks access. Never saved.
* ``unreachable`` — anything else (a timeout, DNS, a 5xx, a 429): Cicada could not tell. The caller offers "Save
  without checking"; it never guesses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

TIMEOUT_S = 6.0
MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Probe:
    url: str
    #: ``bearer`` (Authorization: Bearer), ``x-api-key`` (Anthropic), ``x-goog-api-key`` (Gemini).
    auth: str = "bearer"
    #: The statuses that mean "this key is not valid". xAI and Gemini answer a bad key with 400 (measured
    #: 2026-10-22 with a made-up key: xAI "Incorrect API key provided", Gemini "API_KEY_INVALID"); a GET with no
    #: body on these fixed endpoints has nothing else a 400 could be about.
    refuses: tuple[int, ...] = (401, 403)


#: The one host each provider's key is ever sent to. Every probe is a GET that bills nothing.
PROBES: dict[str, Probe] = {
    "openai": Probe("https://api.openai.com/v1/models"),
    "anthropic": Probe("https://api.anthropic.com/v1/models", "x-api-key"),
    "openrouter": Probe("https://openrouter.ai/api/v1/key"),
    "gemini": Probe("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key", (400, 401, 403)),
    "xai": Probe("https://api.x.ai/v1/models", refuses=(400, 401, 403)),
    "groq": Probe("https://api.groq.com/openai/v1/models"),
    "mistral": Probe("https://api.mistral.ai/v1/models"),
    "fireworks": Probe("https://api.fireworks.ai/inference/v1/models"),
    "deepinfra": Probe("https://api.deepinfra.com/v1/openai/models"),
    "together": Probe("https://api.together.xyz/v1/models"),
}


@dataclass(frozen=True)
class KeyCheck:
    result: str                     # ok | refused | unreachable
    models: frozenset[str] | None = None


def _headers(probe: Probe, key: str) -> dict[str, str]:
    if probe.auth == "x-api-key":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if probe.auth == "x-goog-api-key":
        return {"x-goog-api-key": key}
    return {"Authorization": f"Bearer {key}"}


def _model_ids(payload) -> frozenset[str] | None:
    """``data[].id`` (OpenAI-shaped) or ``models[].name`` (Gemini, ``models/<id>``); ``None`` when neither."""
    if not isinstance(payload, dict):
        return None
    rows = payload.get("data") if isinstance(payload.get("data"), list) else payload.get("models")
    if not isinstance(rows, list):
        return None
    ids = set()
    for row in rows:
        if isinstance(row, dict):
            value = row.get("id") or row.get("name")
            if isinstance(value, str):
                ids.add(value.split("/", 1)[1] if value.startswith("models/") else value)
    return frozenset(ids)


async def _http_check(provider_id: str, key: str) -> KeyCheck:
    import httpx

    from api.services import net_guard

    probe = PROBES[provider_id]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False,
                                     event_hooks={"request": [net_guard.httpx_request_guard]}) as client:
            response = await client.get(probe.url, headers=_headers(probe, key))
    except Exception:  # noqa: BLE001 — the class never matters to the person: Cicada could not tell
        return KeyCheck("unreachable")
    if response.status_code in probe.refuses:
        return KeyCheck("refused")
    if response.status_code != 200:
        return KeyCheck("unreachable")
    models = None
    if len(response.content) <= MAX_BYTES:
        try:
            models = _model_ids(response.json())
        except ValueError:
            models = None
    return KeyCheck("ok", models)


Checker = Callable[[str, str], Awaitable[KeyCheck]]
#: Patched in tests (no network in the suite).
check: Checker = _http_check


def default_listed(models: frozenset[str] | None, default_model: str) -> bool | None:
    """Whether the provider's list names Cicada's default model for it (its id after the LiteLLM prefix); ``None``
    when the provider did not list models."""
    if not models:
        return None
    bare = default_model.split("/", 1)[1] if "/" in default_model else default_model
    return bare in models or default_model in models
