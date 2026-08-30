"""Adapter list + machine-global preferences + a short status cache.

Prefs (``$CICADA_HOME/connections.json``, 0600) hold *user choices only*
(tier override, enabled flag). Live status is re-probed with a 30 s TTL —
never persisted — so no plan/email snapshot ever touches disk.
"""
from __future__ import annotations

import asyncio
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
# G63: what the *selected* engine actually does, and what every other connected
# connection is doing instead. Only one adapter is the engine at a time (see
# api/routers/status.py, which picks the first connected `engine_role`), so this
# assignment belongs to the registry — an adapter probing itself cannot know.
ENGINE_POWERS = ["Sleep extraction", "Ask", "clarification wording"]
STANDBY_POWERS = ["Standby"]

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
    @staticmethod
    def assign_powers(statuses: list[ConnectionStatus]) -> list[ConnectionStatus]:
        """Stamp `powers` across a probed set, in place.

        The first connected adapter in adapter order is the engine — the same
        rule `GET /status` uses to report `engine` — so it gets the real list
        and every other connected one reads "Standby". Disconnected adapters
        keep an empty list: they aren't powering anything.
        """
        engine_assigned = False
        for status in statuses:
            if not status.connected:
                status.powers = []
                continue
            if not engine_assigned:
                status.powers = list(ENGINE_POWERS)
                engine_assigned = True
            else:
                status.powers = list(STANDBY_POWERS)
        return statuses

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

    async def status_with_powers(self, connection_id: str, fresh: bool = False) -> ConnectionStatus:
        """One connection's status, carrying the same ``powers`` the full set
        would give it.

        ``powers`` is a property of the *set*, not of an adapter — only the
        first connected adapter is the engine — so a single probe can't derive
        it and ``status()`` leaves it ``[]``. Single-connection responses go
        straight into the app's store (``ConnectionsViewModel.pollUntilConnected``
        writes the row it polls), so returning ``[]`` visibly drops a card's
        "Powers" line. Probe the whole ordered set (warm-cached per adapter,
        so this is usually free) and return the requested row from it.
        """
        for status in await self.statuses(fresh=fresh):
            if status.id == connection_id:
                return status
        return await self.status(connection_id, fresh=fresh)

    async def statuses(self, fresh: bool = False) -> list[ConnectionStatus]:
        """Probe every adapter concurrently, preserving adapter order.

        Adapters never raise (each ``status()`` implementation catches its
        own errors), but ``asyncio.gather`` is still used without
        ``return_exceptions`` short-circuiting the others — a failing
        coroutine must not take the rest down.
        """
        adapters = self.adapters()
        results = await asyncio.gather(
            *(self.status(a.id, fresh=fresh) for a in adapters),
            return_exceptions=True,
        )
        statuses: list[ConnectionStatus] = []
        for adapter, result in zip(adapters, results):
            if isinstance(result, BaseException):
                # Defensive fallback only — adapters are documented to never
                # raise. Re-probe the cache (may still be empty) rather than
                # let one bad adapter drop an entry from the response.
                cached = self._cache.get(adapter.id)
                if cached:
                    statuses.append(cached[1])
                continue
            statuses.append(result)
        return self.assign_powers(statuses)

    def cached_statuses(self) -> list[ConnectionStatus]:
        """Cache-only snapshot, in adapter order — never probes.

        Used by ``GET /status`` (the menu-bar poll) so a cold or expired
        cache never triggers a fresh ``claude``/``codex``/Ollama shell-out;
        it just contributes nothing to the connections block until the next
        ``GET /connections`` warms the cache.
        """
        now = time.monotonic()
        out: list[ConnectionStatus] = []
        for adapter in self.adapters():
            hit = self._cache.get(adapter.id)
            if hit and now - hit[0] < STATUS_TTL_SECONDS:
                out.append(hit[1])
        return out


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
