"""G74(a) §8 — which engine a Sleep cycle runs on, resolved once per cycle.

`resolve_llm_fn` is synchronous and called from deep inside every stage, so it
can never probe the connections registry (which shells out to vendor CLIs).
Resolution happens here, once, at the top of the cycle; the concrete mode
travels down as a ``Settings`` copy.

Precedence, and the reason for each rung:
  1. ``llm_mode`` of ``"agent"`` or ``"local"`` — deliberate configuration in
     ``api/.env``; it wins, and nothing is probed.
  2. ``"auto"`` — the Claude plan if it probes connected, else Ollama if it is
     running, else the configured API model.
  3. ``"byok"`` (the shipped default, i.e. nobody chose) — defers to the
     Claude card's **Use for Sleep** toggle, so flipping a switch in the app
     picks the engine without editing a dotfile. With no toggle set this is
     exactly today's behaviour, so every existing install is unchanged.
"""
from __future__ import annotations

from loguru import logger

from api.config import Settings

USE_FOR_SLEEP_PREF = "use_for_sleep"
CLAUDE_CONNECTION_ID = "claude-plan"
OLLAMA_CONNECTION_ID = "ollama-local"

ENGINE_LABELS = {"agent": "claude-cli", "local": "ollama", "byok": "litellm"}


def engine_label(settings: Settings) -> str:
    """The engine id for a resolved mode. An unresolved "auto" reads as byok,
    matching how ``providers.resolve_llm_fn`` degrades it.

    ``getattr`` rather than a direct attribute read: several hermetic Sleep
    tests pass a ``SimpleNamespace`` stand-in for ``Settings`` that predates
    ``llm_mode`` and never sets it — this must still resolve to "litellm"
    rather than raising ``AttributeError``, mirroring
    ``sleep_cycle._engine_label``'s own guard.
    """
    mode = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
    return ENGINE_LABELS.get(mode, "litellm")


def use_for_sleep(registry) -> bool:
    try:
        return bool((registry.prefs().get(CLAUDE_CONNECTION_ID) or {}).get(USE_FOR_SLEEP_PREF))
    except Exception:
        return False


async def _connected(registry, connection_id: str) -> bool | None:
    """``True``/``False``, or ``None`` when the probe itself failed."""
    try:
        status = await registry.status(connection_id)
    except Exception as exc:
        logger.warning(f"engine probe failed for {connection_id}: {type(exc).__name__}: {exc}")
        return None
    return bool(getattr(status, "connected", False))


async def resolve_llm_mode(settings: Settings, registry=None) -> tuple[str, str]:
    """Returns ``(concrete mode, one sentence saying why)``.

    ``getattr`` (not a direct attribute read) for the same reason as
    ``engine_label`` above: a duck-typed ``Settings`` stand-in without
    ``llm_mode`` must resolve to "byok" — today's behaviour — rather than
    raising before Stage 1 even starts.
    """
    configured = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
    if configured in ("agent", "local"):
        return configured, f"CICADA_LLM_MODE={configured}"

    if registry is None:
        from api.services.connections.registry import get_registry

        registry = get_registry(settings)

    prefer_claude = use_for_sleep(registry)
    if configured == "byok" and not prefer_claude:
        return "byok", "no Sleep engine chosen — using the configured API model"

    claude = await _connected(registry, CLAUDE_CONNECTION_ID)
    if claude is None:
        return "byok", "could not probe the Claude plan — using the configured API model"
    if claude:
        return "agent", (
            "Claude plan is set as the Sleep engine" if prefer_claude
            else "Claude plan connected — running Sleep on your plan"
        )

    if configured == "auto":
        ollama = await _connected(registry, OLLAMA_CONNECTION_ID)
        if ollama:
            return "local", "Ollama is running — using the local engine"

    return "byok", "Claude plan is not connected — using the configured API model"


async def resolve_settings(settings: Settings, registry=None) -> tuple[Settings, str]:
    """A ``Settings`` copy whose ``llm_mode`` is concrete, plus the reason.

    Never mutates the caller's object: ``get_settings()`` is ``@lru_cache``d
    and shared with every request handler.

    A duck-typed ``Settings`` stand-in (several hermetic Sleep tests pass a
    ``SimpleNamespace`` that predates ``llm_mode`` and has no ``model_copy``
    at all) is returned unchanged rather than crashing the pipeline entry
    point — in practice such a stand-in always resolves to the same "byok"
    ``engine_label`` degrades to regardless, so nothing downstream notices.
    """
    mode, why = await resolve_llm_mode(settings, registry)
    configured = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
    if mode == configured or not hasattr(settings, "model_copy"):
        return settings, why
    return settings.model_copy(update={"llm_mode": mode}), why
