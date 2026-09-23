"""G74(a) §8 — which engine a Sleep cycle runs on, resolved once per cycle.

`resolve_llm_fn` is synchronous and called from deep inside every stage, so it
can never probe the connections registry (which shells out to vendor CLIs).
Resolution happens here, once, at the top of the cycle; the concrete mode
travels down as a ``Settings`` copy.

Precedence, and the reason for each rung:
  1. ``llm_mode`` of ``"agent"``, ``"codex"`` or ``"local"`` — deliberate
     configuration in ``api/.env``; it wins, and nothing is probed.
  2. G122 — a ``sleep-engine`` pref written by ``PUT /sleep/engine`` (the
     Settings → Engines engine picker), read only when the env var was never
     set at all (``settings.model_fields_set``, R2) and only for a real
     ``Settings`` object (never the duck-typed stand-ins several hermetic
     Sleep tests pass) — so a UI choice can promote the configured mode
     exactly as if it had been typed into ``api/.env``, without a second,
     independent registry read anywhere else in this module.
  3. ``"auto"`` — the Claude plan if it probes connected, else the ChatGPT
     plan if it is signed in (R-E20), else Ollama if it is running, else the
     configured API model.
  4. ``"byok"`` (the shipped default, i.e. nobody chose) — defers to the
     ``use_for_sleep`` pref — once the Claude card's **Use for Sleep** toggle,
     now Settings → Engines' "Use my Claude plan when I start a cycle", shown
     only under the API key card because this is the only rung that reads it
     (G139 final review) — so flipping a switch in the app picks the engine
     without editing a dotfile. With no toggle set this is
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

Ruling 4 covers BOTH plans (spec Decision 3, R-E20): a Settings-chosen mode in
``SUBSCRIPTION_MODES`` (``agent``, ``codex``) degrades to byok on a schedule,
and so does every auto/toggle rung. ``CICADA_LLM_MODE=codex`` is dotfile
configuration exactly as ``=agent`` is, and runs on a schedule.
"""
from __future__ import annotations

import asyncio

from loguru import logger

from api.config import Settings

USE_FOR_SLEEP_PREF = "use_for_sleep"
CLAUDE_CONNECTION_ID = "claude-plan"
CODEX_CONNECTION_ID = "chatgpt-plan"
OLLAMA_CONNECTION_ID = "ollama-local"

# G122 — the pseudo-connection id `Registry.set_pref`/`.prefs()` read/write
# the Settings → Engines engine picker's choice under. Not a real adapter id
# (`Registry.get` would raise `KeyError` for it) — `set_pref`/`prefs()` never
# validate `connection_id` against `adapters()` (see registry.py), so an
# ordinary dict key here is all this needs.
SLEEP_ENGINE_PREF_KEY = "sleep-engine"

# "codex" was labelled first (Track E Task 3) so every engine-keyed site was
# generalised before the mode became selectable; it became selectable in the
# same change that put it under ruling 4's guard (Task 4, SUBSCRIPTION_MODES).
ENGINE_LABELS = {"agent": "claude-cli", "codex": "codex-cli", "local": "ollama", "byok": "litellm"}

#: Engine label → (connection id, billing) for the two plan engines — the one
#: map every site that used to test the literal "claude-cli" reads now
#: (sleep_cycle._finalize, link_enrichment, link_recon), so a third plan
#: engine is a row here, not a grep. `connection` must EQUAL the adapter id:
#: consumption_stats joins strictly on it.
PLAN_ENGINES: dict[str, tuple[str, str]] = {
    "claude-cli": (CLAUDE_CONNECTION_ID, "subscription"),
    "codex-cli": (CODEX_CONNECTION_ID, "subscription"),
}
PLAN_NAMES: dict[str, str] = {"claude-cli": "Claude plan", "codex-cli": "ChatGPT plan"}


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


def author_model(settings) -> str:
    """R-E22: the model to stamp on work this engine did when nothing better
    was recorded (a claim's ``authored_by``, a link-backfill fallback). The
    plan engines read their own model; ``litellm_model`` never ran on them —
    the L2 rule ``_finalize`` already applies to commit trailers. Every other
    engine keeps ``litellm_model``, byte-identical to before."""
    engine = engine_label(settings)
    if engine == "claude-cli":
        from api.services import agent_engine

        return agent_engine.model_for_stage(settings, None)
    if engine == "codex-cli":
        from api.services import codex_engine

        return codex_engine.model_for_stage(settings, None) or "unknown"
    return str(getattr(settings, "litellm_model", "") or "unknown")


def use_for_sleep(registry) -> bool:
    try:
        return bool((registry.prefs().get(CLAUDE_CONNECTION_ID) or {}).get(USE_FOR_SLEEP_PREF))
    except Exception:
        return False


#: Ruling 4, generalised in code (spec Decision 3, R-E20): the modes that
#: spend a subscription. A Settings-chosen one never runs on a schedule; one
#: tuple, so a third plan engine cannot forget the guard.
SUBSCRIPTION_MODES = ("agent", "codex")

_VALID_PREF_MODES = ("auto", "agent", "codex", "byok", "local")


def _prefs_mode(registry) -> str | None:
    """The mode a Settings → Engines engine picker (G122) wrote, or ``None``
    when there is no pref, the file is unreadable, or the stored value isn't
    one of the modes this module knows how to resolve. Defensive like
    ``use_for_sleep`` above — a corrupt or hand-edited prefs file must never
    raise mid-resolution; it just reads as "nothing chosen"."""
    try:
        mode = (registry.prefs().get(SLEEP_ENGINE_PREF_KEY) or {}).get("mode")
    except Exception:
        return None
    return mode if mode in _VALID_PREF_MODES else None


#: R-E20's auto ladder, in the order ``resolve_llm_mode`` walks it — the
#: POWERS line reads the same order so a card never claims an engine the
#: ladder would not reach first.
_AUTO_LADDER = (CLAUDE_CONNECTION_ID, CODEX_CONNECTION_ID, OLLAMA_CONNECTION_ID)


def configured_mode(settings, registry) -> str:
    """What a Sleep you start yourself is CONFIGURED to use — env pin, else
    the G122 pref, else the env default. No probe (R-E24).

    The same env-explicit gate ``resolve_llm_mode`` applies (R4): an explicit
    ``CICADA_LLM_MODE`` is a dotfile pin and a Settings choice never
    overrides it. A duck-typed stand-in without ``model_fields_set`` reads
    as "not explicit", but only a registry is ever consulted for the pref.
    """
    configured = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
    env_explicit = hasattr(settings, "model_fields_set") and "llm_mode" in settings.model_fields_set
    if not env_explicit and registry is not None:
        pref = _prefs_mode(registry)
        if pref is not None:
            configured = pref
    return configured


def powered_connection_id(settings, registry, connected_ids) -> str | None:
    """R-E24: which connection a Sleep you start would run on, from the
    configured mode and an ALREADY-probed connected set — the answer the
    POWERS line and ``/status``'s engine report, never a probe of its own.
    ``None`` when the configured engine is not connected.

    A person present is assumed (user-triggered), so ruling 4's scheduled
    degradation is not applied here: the card answers "what runs when I
    press Consolidate", and the Settings → Engines card already shows the
    scheduled line separately (G122). The ``byok`` fallthrough names the key
    card the configured API model bills (``telemetry.connection_for_model``,
    the join ``consumption_stats`` already uses), so a default install's
    POWERS sit on its API key rather than on whichever plan is listed first.
    """
    connected = set(connected_ids)
    mode = configured_mode(settings, registry)
    direct = {"agent": CLAUDE_CONNECTION_ID, "codex": CODEX_CONNECTION_ID, "local": OLLAMA_CONNECTION_ID}
    if mode in direct:
        return direct[mode] if direct[mode] in connected else None
    if mode == "auto":
        for connection_id in _AUTO_LADDER:
            if connection_id in connected:
                return connection_id
    elif registry is not None and use_for_sleep(registry) and CLAUDE_CONNECTION_ID in connected:
        return CLAUDE_CONNECTION_ID
    from api.services import telemetry

    key_card, _billing = telemetry.connection_for_model(str(getattr(settings, "litellm_model", "") or ""))
    return key_card if key_card in connected else None


def _model_overrides(registry, mode: str) -> dict:
    """The ``{field: value}`` overrides a G122 model/disambiguation-model
    pref applies for ``mode``, keyed off whichever field that mode actually
    reads (``resolve_settings``'s ``settings.model_copy`` target names).

    Returns ``{}`` for ``"auto"`` (no concrete mode to attach a model to yet),
    a ``None`` registry, an unreadable prefs file, or a ``mode`` other than
    the one the pref entry was written for — the caller then simply applies
    no override, identical to today's behaviour.

    The stored ``model``/``disambiguation_model`` slot belongs to the mode
    that WROTE it (the entry's own ``mode``; `sleep_engine_prefs`'s
    cross-mode staleness guard clears it on a switch), never to whatever the
    ladder resolved this time. Task 4 review round 1: once R-E21 handed the
    real registry here, a scheduled cycle that ruling 4 degraded from a
    Settings-chosen plan (agent/codex) to byok read the plan's model — a
    Claude CLI alias or a ChatGPT-plan model id — into ``litellm_model``,
    so every nightly cycle either failed or billed the person's API key for
    a model they never chose for it. ``sleep_engine_prefs.
    _resolved_model_pair`` always passes the stored pref mode, so the GET's
    own report is unaffected.
    """
    if registry is None or mode == "auto":
        return {}
    try:
        entry = registry.prefs().get(SLEEP_ENGINE_PREF_KEY) or {}
    except Exception:
        return {}
    if entry.get("mode") != mode:
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
    if mode == "codex":
        updates = {}
        if model:
            updates["codex_model"] = model
        if disambiguation:
            updates["codex_disambiguation_model"] = disambiguation
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


def _prefs_allow_overage(registry) -> bool:
    """R-E13: the Settings → Engines "Keep going on extra usage" choice.
    Defensive like ``_prefs_mode`` — an unreadable prefs file reads as "not
    opted in", never as a reason to spend extra usage."""
    if registry is None:
        return False
    try:
        return bool((registry.prefs().get(SLEEP_ENGINE_PREF_KEY) or {}).get("allow_overage"))
    except Exception:
        return False


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


async def probe_codex_cheaply(registry, *, timeout: float = 5.0) -> tuple[bool, str]:
    """Is the ChatGPT plan signed in — cache-first, the twin of
    ``probe_claude_cheaply``. A cold cache falls back to a bounded ``codex
    login status`` (≈0.01 s) through ``codex_engine.probe`` — never the
    app-server (the cycle pre-flight's job, once, R-E18) and never
    ``Registry.status`` (which would run it)."""
    cached_statuses = getattr(registry, "cached_statuses", None)
    if cached_statuses is not None:
        for status in cached_statuses():
            if status.id != CODEX_CONNECTION_ID:
                continue
            if status.connected:
                return True, status.how or "Signed in to ChatGPT."
            return False, status.detail or "ChatGPT isn't signed in for Cicada."
        from api.services import codex_engine

        return await asyncio.to_thread(codex_engine.probe, timeout=timeout)
    status = await registry.status(CODEX_CONNECTION_ID)
    if status.connected:
        return True, status.how or "Signed in to ChatGPT."
    return False, status.detail or "ChatGPT isn't signed in for Cicada."


async def _connected(registry, connection_id: str) -> bool | None:
    """``True``/``False``, or ``None`` when the probe itself failed.

    The Claude plan goes through ``probe_claude_cheaply`` and the ChatGPT
    plan through ``probe_codex_cheaply`` above (both cache-first, bounded
    fallback — a CLI spawn is never unbounded here). Anything else this module probes (Ollama today) has
    no CLI-spawn risk in the first place — its adapter's own ``status()`` is
    already a short (3 s) HTTP call — so it reads straight from
    ``registry.status()``.
    """
    try:
        if connection_id == CLAUDE_CONNECTION_ID:
            ok, _detail = await probe_claude_cheaply(registry)
            return ok
        if connection_id == CODEX_CONNECTION_ID:
            ok, _detail = await probe_codex_cheaply(registry)
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

    # G122, rung 2: a Settings → Engines engine picker choice, read only for a
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

    if configured in ("agent", "codex", "local"):
        # R3 / R-E20: a prefs-chosen PLAN is not a dotfile edit — ruling 4
        # applies to it exactly as to the auto/byok rungs below. An explicit
        # CICADA_LLM_MODE=agent|codex is deliberate configuration and is
        # untouched by trigger source (unchanged from before G122).
        if configured in SUBSCRIPTION_MODES and not env_explicit and not user_triggered:
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
    if configured == "byok":
        # Only the use_for_sleep switch (Engines, under API key) reaches here, and that
        # toggle is Claude-only (R-E20) — never a reason to reach for ChatGPT.
        return "byok", "Claude plan is not connected — using the configured API model"

    # configured == "auto" from here. R-E20: the ChatGPT plan is the second
    # rung; a probe that fails (None) falls through to Ollama — the second
    # rung must not abort the ladder the way an unprobeable FIRST rung does.
    codex = await _connected(registry, CODEX_CONNECTION_ID)
    if codex:
        return "codex", "ChatGPT plan signed in — running Sleep on your ChatGPT plan"
    ollama = await _connected(registry, OLLAMA_CONNECTION_ID)
    if ollama:
        return "local", "Ollama is running — using the local engine"
    return "byok", "No plan is signed in and Ollama isn't running — using the configured API model"


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
    the only place ``_model_overrides`` is called, and it hands the mode rung
    and the overrides the SAME registry (R-E21) rather than reading prefs a
    second, independent time. The R-E13 overage opt-in rides the same gate.
    """
    has_fields_set = hasattr(settings, "model_fields_set")
    env_explicit = has_fields_set and "llm_mode" in settings.model_fields_set
    if registry is None and has_fields_set and not env_explicit:
        # R-E21: resolve the registry ONCE, here, so the mode rung and the
        # model/overage overrides read the same prefs. With `registry=None`
        # (every Sleep cycle, the link backfill, the maintenance endpoint)
        # `resolve_llm_mode` fetched its own and `_model_overrides(None, …)`
        # returned {} — a model picked in Settings → Engines reached the
        # preview and never the cycle.
        from api.services.connections.registry import get_registry

        registry = get_registry(settings)
    mode, why = await resolve_llm_mode(settings, registry, user_triggered=user_triggered)
    configured = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
    if not hasattr(settings, "model_copy"):
        return settings, why           # M2 guard, unchanged in spirit
    updates: dict = {}
    if mode != configured:
        updates["llm_mode"] = mode
    if not env_explicit:
        updates.update(_model_overrides(registry, mode))
        if _prefs_allow_overage(registry):
            updates["agent_allow_overage"] = True
    if not updates:
        return settings, why
    return settings.model_copy(update=updates), why
