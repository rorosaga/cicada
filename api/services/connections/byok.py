"""Usage-based (bring-your-own-key) connections — one adapter per provider.

One table, ``PROVIDERS`` (R-AG11), names every key Cicada can hold: the card
label, the env var ``secrets.env`` exports, the default model the API-key card
writes, and which key a LiteLLM model id bills (``provider_for_model``, shared
with ``telemetry.connection_for_model`` so the ledger and the engine card never
disagree about who is paid).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint, LoginSession
from api.services.connections import secrets


@dataclass(frozen=True)
class Provider:
    """One usage-billed key provider (R-AG11). ``default_model`` is what the
    API-key card writes when this provider is picked: the small tier, a
    ``-latest`` alias where the provider has one, and a model the installed
    LiteLLM's bundled price table lists with a price and structured output
    (``api.pin_litellm`` keeps that table the bundled one; ``test_byok_providers``
    pins it). A model the table does not list still runs, but its cost reads
    as unknown, so a default must be listed."""
    id: str
    brand: str
    env: str
    default_model: str
    key_url: str

    @property
    def label(self) -> str:
        return f"{self.brand} API key"

    @property
    def connection_id(self) -> str:
        return f"byok-{self.id}"


# Card order on Plans & keys: the four that shipped first keep their places.
PROVIDERS: tuple[Provider, ...] = (
    Provider("openai", "OpenAI", "OPENAI_API_KEY", "gpt-5.4-mini", "https://platform.openai.com/api-keys"),
    Provider("anthropic", "Anthropic", "ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5",
             "https://console.anthropic.com/settings/keys"),
    Provider("openrouter", "OpenRouter", "OPENROUTER_API_KEY", "openrouter/openai/gpt-oss-120b",
             "https://openrouter.ai/settings/keys"),
    Provider("gemini", "Gemini", "GEMINI_API_KEY", "gemini/gemini-flash-latest", "https://aistudio.google.com/apikey"),
    # G50/G215 (providers-2 §1.4, 2026-10-22): `grok-4-1-fast-*` is off xAI's models page and listed as retired; the
    # cheapest current id. LiteLLM 1.83.4 does not price it, so `price_supplement` carries its row with its basis.
    Provider("xai", "xAI", "XAI_API_KEY", "xai/grok-4.20-0309-non-reasoning", "https://console.x.ai"),
    Provider("groq", "Groq", "GROQ_API_KEY", "groq/openai/gpt-oss-120b", "https://console.groq.com/keys"),
    Provider("mistral", "Mistral", "MISTRAL_API_KEY", "mistral/mistral-small-latest",
             "https://console.mistral.ai/api-keys"),
    # G50/G215 (ruling 36 D1, providers-2 §5): open-model hosts. Each default is the host's gpt-oss-120b, the one
    # strong structured-output model all three serve that LiteLLM 1.83.4 prices (GLM 5.3 and DeepSeek V4 are not
    # in its table yet, so their cost would read unknown).
    Provider("fireworks", "Fireworks", "FIREWORKS_API_KEY", "fireworks_ai/accounts/fireworks/models/gpt-oss-120b",
             "https://fireworks.ai/account/api-keys"),
    Provider("deepinfra", "DeepInfra", "DEEPINFRA_API_KEY", "deepinfra/openai/gpt-oss-120b",
             "https://deepinfra.com/dash/api_keys"),
    Provider("together", "Together AI", "TOGETHERAI_API_KEY", "together_ai/openai/gpt-oss-120b",
             "https://api.together.ai/settings/api-keys"),
)
_BY_ID = {p.id: p for p in PROVIDERS}
# F-05's picker order; OpenRouter is its own card, not a row here.
PICKER: tuple[Provider, ...] = tuple(_BY_ID[i] for i in ("anthropic", "openai", "gemini", "xai", "groq", "mistral",
                                                         "fireworks", "deepinfra", "together"))
#: Providers whose LiteLLM rows lack the ``supports_response_schema`` flag although the host documents JSON mode
#: (``response_format: {"type": "json_object"}``) — the only structured output Cicada's engine sends. Named, with the
#: basis, so ``test_byok_providers`` keeps every other default to the flag.
JSON_MODE_ONLY = {"deepinfra": "DeepInfra's OpenAI-compatible endpoint documents JSON mode"}
#: What the key card says about a provider's own terms before a key is pasted (providers-2 §3, §5): the words a
#: personal-memory app owes the person, never a price (ruling 12).
TERMS_NOTE = {
    "gemini": "Turn on billing for this key's project. Google's free tier lets people at Google read what is sent.",
    "together": "Together keeps prompts and replies unless zero data retention is turned on for your account.",
}
BYOK_PROVIDERS: dict[str, tuple[str, str]] = {p.id: (p.env, p.label) for p in PROVIDERS}


def provider(provider_id: str) -> Provider:
    return _BY_ID[provider_id]


def provider_for_model(model: str | None) -> str:
    """Which key a LiteLLM model id bills — one rule for the engine card's
    ``provider`` and ``telemetry.connection_for_model``. An explicit prefix wins
    (so ``openrouter/anthropic/…`` is OpenRouter and ``groq/openai/…`` Groq: the
    router is who bills); bare ids fall back to the historical substrings."""
    m = (model or "").strip().lower()
    for p in PROVIDERS:
        if m.startswith(p.id + "/"):
            return p.id
    if "claude" in m:
        return "anthropic"
    if "gemini" in m:
        return "gemini"
    return "openai"


class ByokAdapter:
    kind = ConnectionKind.usage

    def __init__(self, provider: str):
        if provider not in BYOK_PROVIDERS:
            raise ValueError(f"unknown BYOK provider: {provider}")
        self.provider = provider
        self.env_var, self.label = BYOK_PROVIDERS[provider]
        self.id = f"byok-{provider}"

    def available(self) -> bool:
        return True

    async def status(self) -> ConnectionStatus:
        connected = secrets.has_secret(self.env_var)
        brand = provider(self.provider).brand
        store = secrets.where(self.env_var) if connected else None
        where = ("Key set in the backend's environment" if store == "environment"
                 else f"Key stored in {secrets.secrets_path()} (0600)")
        terms = TERMS_NOTE.get(self.provider)
        detail = None if connected else f"Paste a key; it is stored in {secrets.secrets_path()} (0600) and exported as {self.env_var}."
        if terms and not connected:
            detail = f"{detail} {terms}"
        return ConnectionStatus(
            id=self.id, label=self.label, kind=self.kind, available=True, connected=connected,
            billing="usage", engine_role="byok" if connected else None,
            plan_label="usage-based" if connected else None,
            how=(f"{where}; billed per token by {brand}." if connected else None),
            detail=detail,
            login=LoginHint(mode="key"),
            # G50/G215: the last four only — no route ever returns a key — where it lives, and when its provider
            # last accepted it (the save's check; None for a key saved unchecked or before checks existed).
            key_hint=secrets.hint(self.env_var) if connected else None,
            key_store=store,
            verified_at=secrets.verified_at(self.env_var) if connected else None,
            terms_note=terms,
        )

    def set_key(self, value: str, *, verified_at: str | None = None) -> None:
        """Save the key; ``verified_at`` is when its provider accepted it (``key_check``), ``None`` when saved
        unchecked — a replaced key never keeps the old key's check."""
        secrets.set_secret(self.env_var, value)
        secrets.mark_verified(self.env_var, verified_at)

    def remove_key(self) -> None:
        secrets.remove_secret(self.env_var)

    async def begin_login(self) -> LoginSession:
        return LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="key",
                            detail=f"PUT /connections/{self.id}/key with {{\"key\": ...}}")

    async def logout(self) -> None:
        self.remove_key()
