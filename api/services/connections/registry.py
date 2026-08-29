"""Adapter list + machine-global preferences + a short status cache.

Prefs (``$CICADA_HOME/connections.json``, 0600) hold *user choices only*
(tier override, enabled flag). Live status is re-probed with a 30 s TTL —
never persisted — so no plan/email snapshot ever touches disk.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from api.config import Settings
from api.models.schemas import ConnectionStatus
from api.services.auth import cicada_home
from api.services.connections import base, byok, claude_cli, codex_cli, ollama

PREFS_FILE_NAME = "connections.json"
STATUS_TTL_SECONDS = 30
VALID_TIERS = ("5x", "20x")

_ollama_fetch_tags = ollama._http_tags  # patched in tests


class Registry:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache: dict[str, tuple[float, ConnectionStatus]] = {}

    # --- prefs -------------------------------------------------------------
    def _prefs_path(self) -> Path:
        return cicada_home() / PREFS_FILE_NAME

    def prefs(self) -> dict:
        try:
            return json.loads(self._prefs_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def set_pref(self, connection_id: str, key: str, value) -> None:
        prefs = self.prefs()
        entry = prefs.setdefault(connection_id, {})
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
        path = self._prefs_path()
        path.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.invalidate()

    # --- adapters ----------------------------------------------------------
    def adapters(self) -> list:
        prefs = self.prefs()
        runner = base.run_cli
        return [
            claude_cli.ClaudePlanAdapter(runner=runner, tier=prefs.get("claude-plan", {}).get("tier")),
            codex_cli.CodexPlanAdapter(runner=runner, tier=prefs.get("chatgpt-plan", {}).get("tier")),
            *[byok.ByokAdapter(p) for p in byok.BYOK_PROVIDERS],
            ollama.OllamaAdapter(self._settings, fetch_tags=_ollama_fetch_tags),
        ]

    def get(self, connection_id: str):
        for adapter in self.adapters():
            if adapter.id == connection_id:
                return adapter
        raise KeyError(connection_id)

    # --- status (cached) ---------------------------------------------------
    def invalidate(self) -> None:
        self._cache.clear()

    async def status(self, connection_id: str, fresh: bool = False) -> ConnectionStatus:
        now = time.monotonic()
        hit = self._cache.get(connection_id)
        if hit and not fresh and now - hit[0] < STATUS_TTL_SECONDS:
            return hit[1]
        status = await self.get(connection_id).status()
        self._cache[connection_id] = (now, status)
        return status

    async def statuses(self, fresh: bool = False) -> list[ConnectionStatus]:
        return [await self.status(a.id, fresh=fresh) for a in self.adapters()]


_registry: Registry | None = None
_registry_home: str | None = None


def get_registry(settings: Settings) -> Registry:
    global _registry, _registry_home
    home = str(cicada_home())
    if _registry is None or _registry_home != home:
        _registry, _registry_home = Registry(settings), home
    return _registry


def reset_registry() -> None:
    global _registry, _registry_home
    _registry, _registry_home = None, None
