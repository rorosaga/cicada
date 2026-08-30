"""Local Ollama connection — free, on-device; 'connected' = model pulled."""
from __future__ import annotations

import uuid
from typing import Awaitable, Callable

from api.config import Settings
from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint, LoginSession


async def _http_tags(base_url: str) -> list[str]:
    import httpx

    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
        resp.raise_for_status()
        return [m.get("name", "") for m in resp.json().get("models", [])]


class OllamaAdapter:
    id = "ollama-local"
    label = "Ollama (local)"
    kind = ConnectionKind.local

    def __init__(self, settings: Settings, fetch_tags: Callable[[str], Awaitable[list[str]]] | None = None):
        self._settings = settings
        self._tags = fetch_tags or _http_tags

    def available(self) -> bool:
        return True  # decided live in status()

    async def status(self) -> ConnectionStatus:
        model = self._settings.ollama_model
        base = ConnectionStatus(id=self.id, label=self.label, kind=self.kind, billing="free",
                                login=LoginHint(mode="none"))
        try:
            names = await self._tags(self._settings.ollama_base_url)
        except Exception as exc:
            base.available, base.detail = False, f"Ollama not reachable at {self._settings.ollama_base_url} ({exc}). Install from ollama.com and start it."
            return base
        base.available = True
        if model in names or any(n.split(":")[0] == model for n in names):
            base.connected, base.engine_role, base.plan_label = True, "local", model
            base.how = f"Local models at `{self._settings.ollama_base_url}` — free."
        else:
            base.detail = f"Model not pulled — run `ollama pull {model}`"
        return base

    async def begin_login(self) -> LoginSession:
        return LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="none",
                            command=f"ollama pull {self._settings.ollama_model}")

    async def logout(self) -> None:
        return None
