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
    LiteLLM knows with structured output (``test_byok_providers`` pins it)."""
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
    Provider("openrouter", "OpenRouter", "OPENROUTER_API_KEY", "openrouter/~openai/gpt-mini-latest",
             "https://openrouter.ai/settings/keys"),
    Provider("gemini", "Gemini", "GEMINI_API_KEY", "gemini/gemini-flash-latest", "https://aistudio.google.com/apikey"),
    Provider("xai", "xAI", "XAI_API_KEY", "xai/grok-4.5-latest", "https://console.x.ai"),
    Provider("groq", "Groq", "GROQ_API_KEY", "groq/openai/gpt-oss-120b", "https://console.groq.com/keys"),
    Provider("mistral", "Mistral", "MISTRAL_API_KEY", "mistral/mistral-small-latest",
             "https://console.mistral.ai/api-keys"),
)
_BY_ID = {p.id: p for p in PROVIDERS}
# F-05's picker order; OpenRouter is its own card, not a row here.
PICKER: tuple[Provider, ...] = tuple(_BY_ID[i] for i in ("anthropic", "openai", "gemini", "xai", "groq", "mistral"))
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
        return ConnectionStatus(
            id=self.id, label=self.label, kind=self.kind, available=True, connected=connected,
            billing="usage", engine_role="byok" if connected else None,
            plan_label="usage-based" if connected else None,
            how=(f"Key stored in {secrets.secrets_path()} (0600); billed per token by {brand}."
                 if connected else None),
            detail=None if connected else f"Paste a key; it is stored in {secrets.secrets_path()} (0600) and exported as {self.env_var}.",
            login=LoginHint(mode="key"),
        )

    def set_key(self, value: str) -> None:
        secrets.set_secret(self.env_var, value)

    def remove_key(self) -> None:
        secrets.remove_secret(self.env_var)

    async def begin_login(self) -> LoginSession:
        return LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="key",
                            detail=f"PUT /connections/{self.id}/key with {{\"key\": ...}}")

    async def logout(self) -> None:
        self.remove_key()
