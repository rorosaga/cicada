"""G74(a) §8 — which engine a Sleep cycle runs on, resolved once per cycle.

`resolve_llm_fn` is synchronous and called from deep inside every stage, so it
can never probe the connections registry (which shells out to vendor CLIs).
Resolution happens here, once, at the top of the cycle; the concrete mode
travels down as a ``Settings`` copy.

Precedence, and the reason for each rung:
  1. ``llm_mode`` of ``"agent"`` or ``"local"`` — deliberate configuration in
     ``api/.env``; it wins, and nothing is probed.
  2. G122 — a ``sleep-engine`` pref written by ``PUT /sleep/engine`` (the
     Settings → Sleep engine picker), read only when the env var was never
     set at all (``settings.model_fields_set``, R2) and only for a real
     ``Settings`` object (never the duck-typed stand-ins several hermetic
     Sleep tests pass) — so a UI choice can promote the configured mode
     exactly as if it had been typed into ``api/.env``, without a second,
     independent registry read anywhere else in this module.
  3. ``"auto"`` — the Claude plan if it probes connected, else Ollama if it is
     running, else the configured API model.
  4. ``"byok"`` (the shipped default, i.e. nobody chose) — defers to the
     Claude card's **Use for Sleep** toggle, so flipping a switch in the app
     picks the engine without editing a dotfile. With no toggle set this is
     exactly today's behaviour, so every existing install is unchanged.

Trigger scope (spec §7, fix round 1 H1/H2): the toggle/auto resolution paths
(anything that can pick "agent" without an explicit ``CICADA_LLM_MODE=agent``)
are **user-triggered only**. ``resolve_llm_mode``/``resolve_settings`` take a
``user_triggered`` flag — ``POST /sleep/trigger`` passes ``True`` (the
default), the nightly cron (``sleep_scheduler._run_if_idle``) passes
``False``. A scheduled cycle degrades straight to byok, before ever touching
the registry, regardless of the toggle — "the scheduler stays on the existing
engine selection" per spec §7, and `Copy.sleepEngineExplainer` promises
exactly that ("never on the nightly schedule"). An explicit
``CICADA_LLM_MODE=agent``/``local`` still wins on a scheduled cycle: that is
deliberate dotfile configuration, unaffected by who pressed Run — spec §7's
"existing engine selection" the scheduler keeps.
"""
from __future__ import annotations

import asyncio

from loguru import logger

from api.config import Settings

USE_FOR_SLEEP_PREF = "use_for_sleep"
CLAUDE_CONNECTION_ID = "claude-plan"
OLLAMA_CONNECTION_ID = "ollama-local"

# G122 — the pseudo-connection id `Registry.set_pref`/`.prefs()` read/write
# the Settings → Sleep engine picker's choice under. Not a real adapter id
# (`Registry.get` would raise `KeyError` for it) — `set_pref`/`prefs()` never
# validate `connection_id` against `adapters()` (see registry.py), so an
# ordinary dict key here is all this needs.
SLEEP_ENGINE_PREF_KEY = "sleep-engine"

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


_VALID_PREF_MODES = ("auto", "agent", "byok", "local")


def _prefs_mode(registry) -> str | None:
    """The mode a Settings → Sleep engine picker (G122) wrote, or ``None``
    when there is no pref, the file is unreadable, or the stored value isn't
    one of the four modes this module knows how to resolve. Defensive like
    ``use_for_sleep`` above — a corrupt or hand-edited prefs file must never
    raise mid-resolution; it just reads as "nothing chosen"."""
    try:
        mode = (registry.prefs().get(SLEEP_ENGINE_PREF_KEY) or {}).get("mode")
    except Exception:
        return None
    return mode if mode in _VALID_PREF_MODES else None


def _model_overrides(registry, mode: str) -> dict:
    """The ``{field: value}`` overrides a G122 model/disambiguation-model
    pref applies for ``mode``, keyed off whichever field that mode actually
    reads (``resolve_settings``'s ``settings.model_copy`` target names).

    Returns ``{}`` for ``"auto"`` (no concrete mode to attach a model to yet),
    a ``None`` registry, or an unreadable prefs file — the caller then simply
    applies no override, identical to today's behaviour. The stored
    ``model``/``disambiguation_model`` strings are untyped and shared by
    whichever mode is CURRENTLY selected (see `sleep_engine_prefs`'s own
    cross-mode staleness guard, which clears them on a mode switch) — this
    function only ever reads them, never decides whether they're stale.
    """
    if registry is None or mode == "auto":
        return {}
    try:
        entry = registry.prefs().get(SLEEP_ENGINE_PREF_KEY) or {}
    except Exception:
        return {}
    model = entry.get("model")
    disambiguation = entry.get("disambiguation_model")
    if mode == "agent":
        updates = {}
        if model:
            updates["agent_model"] = model
        if disambiguation:
            updates["agent_disambiguation_model"] = disambiguation
        return updates
    if mode == "local":
        return {"ollama_model": model} if model else {}
    if mode == "byok":
        updates = {}
        if model:
            updates["litellm_model"] = model
        if disambiguation:
            updates["litellm_disambiguation_model"] = disambiguation
        return updates
    return {}


async def probe_claude_cheaply(registry, *, timeout: float = 5.0) -> tuple[bool, str]:
    """Is the Claude plan usable — resolved cache-first, with a bounded
    fallback probe. Shared by ``_connected`` below and
    ``sleep_cycle._probe_engine_cheaply`` (the pre-flight abort check) so
    the fix round 1, M1 pattern (Task 5's ruling-2 fix) lives in exactly one
    place instead of two copies that can drift.

    ``Registry.cached_statuses()`` (when the registry exposes it) NEVER
    probes — a pure in-memory read of whatever ``GET /connections`` /
    ``GET /status`` last warmed, 30 s TTL. Only a genuinely cold cache falls
    through to ``agent_engine.probe()``, bounded at ``timeout`` seconds —
    never ``Registry.status()`` directly, whose own spawn is a fixed,
    unshortenable 15 s default with no way to shorten it from here. A
    registry test double with no ``cached_statuses`` concept at all reads
    straight from ``registry.status()``.
    """
    cached_statuses = getattr(registry, "cached_statuses", None)
    if cached_statuses is not None:
        for status in cached_statuses():
            if status.id != CLAUDE_CONNECTION_ID:
                continue
            if status.connected:
                return True, status.how or "Claude Code signed in on this Mac."
            return False, status.detail or "Claude Code is not connected."
        from api.services import agent_engine

        return await asyncio.to_thread(agent_engine.probe, timeout=timeout)
    status = await registry.status(CLAUDE_CONNECTION_ID)
    if status.connected:
        return True, status.how or "Claude Code signed in on this Mac."
    return False, status.detail or "Claude Code is not connected."


async def _connected(registry, connection_id: str) -> bool | None:
    """``True``/``False``, or ``None`` when the probe itself failed.

    The Claude plan goes through ``probe_claude_cheaply`` above (cache-first,
    bounded fallback). Anything else this module probes (Ollama today) has
    no CLI-spawn risk in the first place — its adapter's own ``status()`` is
    already a short (3 s) HTTP call — so it reads straight from
    ``registry.status()``.
    """
    try:
        if connection_id == CLAUDE_CONNECTION_ID:
            ok, _detail = await probe_claude_cheaply(registry)
            return ok
        status = await registry.status(connection_id)
    except Exception as exc:
        logger.warning(f"engine probe failed for {connection_id}: {type(exc).__name__}: {exc}")
        return None
    return bool(getattr(status, "connected", False))


async def resolve_llm_mode(
    settings: Settings, registry=None, *, user_triggered: bool = True,
) -> tuple[str, str]:
    """Returns ``(concrete mode, one sentence saying why)``.

    ``getattr`` (not a direct attribute read) for the same reason as
    ``engine_label`` above: a duck-typed ``Settings`` stand-in without
    ``llm_mode`` must resolve to "byok" — today's behaviour — rather than
    raising before Stage 1 even starts.
    """
    configured = (getattr(settings, "llm_mode", None) or "byok").strip().lower()

    # G122, rung 2: a Settings → Sleep engine picker choice, read only for a
    # real ``Settings`` (never the duck-typed stand-ins several hermetic
    # Sleep tests pass — `model_fields_set` doesn't exist on those, so this
    # whole block, registry touch included, is skipped for them, R2) and
    # only when the env var was never set at all — an explicit
    # `CICADA_LLM_MODE` is a deliberate dotfile pin and stays fully
    # authoritative (R4; `resolve_settings` mirrors this same gate for the
    # model/disambiguation-model overrides).
    has_fields_set = hasattr(settings, "model_fields_set")
    env_explicit = has_fields_set and "llm_mode" in settings.model_fields_set
    if has_fields_set and not env_explicit:
        if registry is None:
            from api.services.connections.registry import get_registry

            registry = get_registry(settings)
        pref_mode = _prefs_mode(registry)
        if pref_mode is not None:
            configured = pref_mode

    if configured in ("agent", "local"):
        # R3: a prefs-chosen "agent" is not a dotfile edit — ruling 4 still
        # applies to it exactly as it does to the auto/byok rungs below. An
        # *explicit* `CICADA_LLM_MODE=agent` is deliberate configuration and
        # is untouched by trigger source (unchanged from before G122).
        if configured == "agent" and not env_explicit and not user_triggered:
            return "byok", "scheduled cycle — Sleep engine selection is user-triggered only"
        return configured, (
            f"CICADA_LLM_MODE={configured}" if env_explicit
            else f"Sleep engine set to {configured!r} in Settings"
        )

    # Fix round 1, M2: a duck-typed ``Settings`` stand-in (several hermetic
    # Sleep tests pass a ``SimpleNamespace`` that predates ``llm_mode`` and
    # has no ``model_copy`` at all) can never actually BECOME a resolved
    # copy — ``resolve_settings`` below has nothing to hand back if this
    # function found "agent". Bailing here, before the registry is ever
    # touched, is the fix: the earlier ``getattr``/``hasattr`` guard let
    # `resolve_settings` reach this point, probe the REAL registry (a real
    # `claude auth status --json` spawn was reproduced live against this
    # machine's actual `~/.cicada/connections.json`), resolve "agent", and
    # then silently discard that result — `last_engine` said "litellm" while
    # `engine_detail` claimed the plan. A crash would have been safer than
    # that divergence; returning byok before ever probing is safer still.
    if not hasattr(settings, "model_copy"):
        return "byok", "no Sleep engine chosen — using the configured API model"

    # Fix round 1, H1/H2: the toggle/auto rungs are user-triggered only
    # (spec §7) — a scheduled cycle must never spend plan quota unattended,
    # matching what `Copy.sleepEngineExplainer` promises. Explicit
    # agent/local (above) is deliberate dotfile config and is untouched by
    # trigger source — that's "the existing engine selection" spec §7 says
    # the scheduler keeps.
    if not user_triggered:
        return "byok", "scheduled cycle — Sleep engine selection is user-triggered only"

    # Fix round 1, L3: an unrecognized ``llm_mode`` (a typo, or a future
    # value this module doesn't know yet) must degrade to byok WITHOUT ever
    # touching the registry — never silently escalate an unrecognized
    # string into the agent rung just because it isn't literally "byok".
    if configured not in ("byok", "auto"):
        return "byok", f"unrecognized CICADA_LLM_MODE={configured!r} — using the configured API model"

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


async def resolve_settings(
    settings: Settings, registry=None, *, user_triggered: bool = True,
) -> tuple[Settings, str]:
    """A ``Settings`` copy whose ``llm_mode`` is concrete, plus the reason.

    Never mutates the caller's object: ``get_settings()`` is ``@lru_cache``d
    and shared with every request handler.

    The ``hasattr(settings, "model_copy")`` check below is now a pure
    backstop (fix round 1, M2): ``resolve_llm_mode`` bails to "byok" before
    ever probing for a duck-typed stand-in, so ``mode`` can only differ from
    ``configured`` for a real ``Settings`` object — this branch should be
    unreachable in practice, but a future call site that resolves the mode
    itself and only calls this function for the copy must not crash either.

    G122/R4: a G122 model/disambiguation-model override is applied ONLY when
    the env var was never explicit — the same gate ``resolve_llm_mode``
    itself uses for the mode rung — so a UI-only model tweak can never ride
    along behind an operator's deliberate ``CICADA_LLM_MODE`` pin. This is
    the only place ``_model_overrides`` is called, and it reuses the same
    ``registry`` this call was already given rather than reading prefs a
    second, independent time.
    """
    mode, why = await resolve_llm_mode(settings, registry, user_triggered=user_triggered)
    configured = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
    if not hasattr(settings, "model_copy"):
        return settings, why           # M2 guard, unchanged in spirit
    env_explicit = hasattr(settings, "model_fields_set") and "llm_mode" in settings.model_fields_set
    updates: dict = {}
    if mode != configured:
        updates["llm_mode"] = mode
    if not env_explicit:
        updates.update(_model_overrides(registry, mode))
    if not updates:
        return settings, why
    return settings.model_copy(update=updates), why
