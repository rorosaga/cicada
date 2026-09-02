"""Usage-based (bring-your-own-key) connections — one adapter per provider."""
from __future__ import annotations

import uuid

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint, LoginSession
from api.services.connections import secrets

BYOK_PROVIDERS: dict[str, tuple[str, str]] = {
    "openai": ("OPENAI_API_KEY", "OpenAI API key"),
    "anthropic": ("ANTHROPIC_API_KEY", "Anthropic API key"),
    "openrouter": ("OPENROUTER_API_KEY", "OpenRouter API key"),
    "gemini": ("GEMINI_API_KEY", "Gemini API key"),
}


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
        brand = {"openai": "OpenAI", "anthropic": "Anthropic",
                 "openrouter": "OpenRouter", "gemini": "Gemini"}[self.provider]
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
