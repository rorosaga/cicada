"""G74(a) §8 — which engine a Sleep cycle runs on, resolved once per cycle.

`resolve_llm_fn` is synchronous and called from deep inside every stage, so it
can never probe the connections registry (which shells out to vendor CLIs).
Resolution happens here, once, at the top of the cycle; the concrete mode
travels down as a ``Settings`` copy.

Precedence, and the reason for each rung:
  1. ``llm_mode`` of ``"agent"``, ``"codex"`` or ``"local"`` — deliberate
     configuration in ``api/.env``; it wins, and nothing is probed.
  2. G122 — a ``sleep-engine`` pref written by ``PUT /sleep/engine`` (the
     Settings → Intelligence engine picker), read only when the env var was never
     set at all (``settings.model_fields_set``, R2) and only for a real
     ``Settings`` object (never the duck-typed stand-ins several hermetic
     Sleep tests pass) — so a UI choice can promote the configured mode
     exactly as if it had been typed into ``api/.env``, without a second,
     independent registry read anywhere else in this module.
  3. ``"auto"`` — the shipped default since 2026-10-19 (owner: "OpenRouter, eliminate it as the default … the
     defaults now are either the Claude plan or the Codex/ChatGPT plan"): the Claude plan if it probes connected,
     else the ChatGPT plan if it is signed in (R-E20) — else NO engine (ruling 36 D1 removed the local rung)
     (``NO_ENGINE``), never a metered API key by itself. A resolved copy then carries ``no_engine_reason`` and every
     call built from it refuses before it is made (``providers.resolve_llm_fn``).
  4. ``"byok"`` — the person CHOSE an API key (``CICADA_LLM_MODE=byok`` or the picker): it defers to the
     ``use_for_sleep`` pref — once the Claude card's **Use for Sleep** toggle, now Settings → Intelligence' "Use my
     Claude plan when I start a cycle", shown only under the API key card because this is the only rung that reads
     it (G139 final review) — and otherwise reads with the key.

Trigger scope (spec §7, fix round 1 H1/H2; ruling 4): ``resolve_llm_mode``/``resolve_settings`` take a
``user_triggered`` flag — ``POST /sleep/trigger`` passes ``True`` (the default), the nightly cron
(``sleep_scheduler._run_if_idle``) passes ``False``. On a scheduled cycle a plan rung (a Settings-chosen ``agent`` or
``codex``, Auto's plan rungs, the Claude toggle) opens only through the person's switch (ruling 4b, below). With it off
the schedule never touches a plan's probe; it gets the local model, a key the person chose, or — 2026-10-19 — no engine
(``SCHEDULE_DEGRADED``), never a metered key by itself. An explicit ``CICADA_LLM_MODE=agent|codex|local`` still wins on
a scheduled cycle: deliberate dotfile configuration, unaffected by who pressed Run.

Ruling 4 covers BOTH plans (spec Decision 3, R-E20), through one tuple: ``SUBSCRIPTION_MODES``.

Ruling 4b (owner, 2026-10-16: "The server should be allowed to use plans too. Just have to set them up somehow"):
the machine's "Scheduled runs may use my plan" switch (``sleep_run_prefs``) opens the plans
(``SCHEDULE_PLAN_MODES``: Claude and, owner same day, "Yeah chat too", ChatGPT) on a schedule: a scheduled run
then resolves exactly as one the person starts would. It is the guard's only other door. Amended 2026-10-19 (owner:
"Make scheduled runs run on the plan by default"): the switch is ON unless the person turned it off.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from loguru import logger

from api.config import Settings

USE_FOR_SLEEP_PREF = "use_for_sleep"
CLAUDE_CONNECTION_ID = "claude-plan"
CODEX_CONNECTION_ID = "chatgpt-plan"
OLLAMA_CONNECTION_ID = "ollama-local"

# G122 — the pseudo-connection id `Registry.set_pref`/`.prefs()` read/write
# the Settings → Intelligence engine picker's choice under. Not a real adapter id
# (`Registry.get` would raise `KeyError` for it) — `set_pref`/`prefs()` never
# validate `connection_id` against `adapters()` (see registry.py), so an
# ordinary dict key here is all this needs.
SLEEP_ENGINE_PREF_KEY = "sleep-engine"

# "codex" was labelled first (Track E Task 3) so every engine-keyed site was
# generalised before the mode became selectable; it became selectable in the
# same change that put it under ruling 4's guard (Task 4, SUBSCRIPTION_MODES).
ENGINE_LABELS = {"agent": "claude-cli", "codex": "codex-cli", "local": "ollama", "byok": "litellm"}
#: The engine label of a resolved copy whose selection found nothing it may use (ruling 2026-10-19: Auto never falls
#: to a metered key by itself). Never stamped on a call: every call from such a copy refuses first.
NO_ENGINE_LABEL = "none"
#: Why a resolved Auto has no engine (a person-started run, or a scheduled one whose plan is open).
NO_ENGINE = ("no Sleep engine chosen — no plan is signed in, the local model isn't running, and an API key is used "
             "only when you choose it")
#: The engine label of an UNRESOLVED Auto (a ``Settings`` no one resolved): never "litellm" — it reads with no key
#: until resolved, and a call built from it refuses (``UNRESOLVED_AUTO``).
AUTO_LABEL = "auto"
UNRESOLVED_AUTO = ("Cicada had not chosen an engine for this call (Auto, unresolved) — it never falls to an API key by "
                   "itself. Connect your plan, or choose an engine in Settings → Intelligence (`cicada sleep engine --mode "
                   "…` on a server).")

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
    """The engine id for a resolved mode. An unresolved "auto" reads as ``auto`` — never the metered engine — and a
    resolved Auto that found nothing reads as ``none``; ``providers.resolve_llm_fn`` refuses a call from either.

    ``getattr`` rather than a direct attribute read: several hermetic Sleep
    tests pass a ``SimpleNamespace`` stand-in for ``Settings`` that predates
    ``llm_mode`` and never sets it — this must still resolve to "litellm"
    rather than raising ``AttributeError``, mirroring
    ``sleep_cycle._engine_label``'s own guard.
    """
    if no_engine(settings):
        return NO_ENGINE_LABEL
    mode = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
    if mode == "auto":
        return AUTO_LABEL   # unresolved: never reported as the metered engine (review of #360)
    return ENGINE_LABELS.get(mode, "litellm")


def no_engine(settings) -> bool:
    """A resolved copy whose engine selection found nothing it may use (``resolve_settings``): no plan, no local
    model, and no API key the person chose. Every engine call built from it refuses before it is made."""
    return bool(str(getattr(settings, "no_engine_reason", "") or "").strip())


def no_engine_sentence(why: str | None) -> str:
    """What a run with no engine says, in words, with the fix — naming the scheduled-plan switch when it is the
    reason (ruling 4b). Provider-neutral."""
    if why == SCHEDULE_DEGRADED:
        return ("Scheduled runs have no engine they may use: your plan is off for scheduled runs (“Scheduled runs may "
                "use my plan” in Settings → Sleep; on a server, `cicada sleep schedule --use-plan on`), no local model "
                "is running, and an API key is used only when you choose it as Sleep's engine. What was waiting is "
                "still waiting.")
    return ("No engine to read with: no plan is signed in, the local model isn't running, and an API key is used only "
            "when you choose it. Connect your plan, or choose an engine in Settings → Intelligence (on a server: `cicada "
            "engine connect claude-plan`, or `cicada sleep engine --mode byok` for a key you chose). What was waiting "
            "is still waiting.")


def shown_model(settings) -> str:
    """The model a resolved engine is shown running — the Sleep page's engine line and a run's pinned pair
    (``DrainState.engine_shown``), one rule so the two compare. Unlike :func:`author_model` (provenance), a
    local engine shows its own model and an unpicked ChatGPT-plan model reads as the plan's default."""
    engine = engine_label(settings)
    if engine == NO_ENGINE_LABEL:
        return ""
    if engine == "claude-cli":
        from api.services import agent_engine

        return agent_engine.model_for_stage(settings, None)
    if engine == "codex-cli":
        from api.services import codex_engine

        return codex_engine.model_for_stage(settings, None) or "default model"
    if engine == "ollama":
        return str(getattr(settings, "ollama_model", "") or "")
    return str(getattr(settings, "litellm_model", "") or "")


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

#: Ruling 4b (owner, 2026-10-16: "The server should be allowed to use plans too"; on the ChatGPT plan: "Yeah chat
#: too"): the plan modes the person's explicit switch — Settings → Sleep's "Scheduled runs may use my plan",
#: ``cicada sleep schedule --use-plan on|off``, stored as ``sleep_run_prefs.scheduled_use_plan``, on unless turned off
#: (2026-10-19) — may open on a schedule:
#: both plans, each only when it is the engine the person's own choice resolves to and it is signed in. The switch is
#: the guard's only door besides an explicit ``CICADA_LLM_MODE``.
SCHEDULE_PLAN_MODES = ("agent", "codex")

#: Why a scheduled run resolved to the metered engine: ruling 4 kept it off a plan because the person's switch is
#: off. ``sleep_cycle`` reads it to name the switch as a fix when that engine then refuses every call.
SCHEDULE_DEGRADED = "scheduled cycle — Sleep engine selection is user-triggered only"


def scheduled_plan_allowed(registry) -> bool:
    """The machine's "Scheduled runs may use my plan" switch (ruling 4b, amended 2026-10-19: on by default). On when
    unset — a new install, a machine that never chose — and off only on the person's explicit off (or a hand-edited
    value that is not a boolean, ``sleep_run_prefs.load``)."""
    from api.services import sleep_run_prefs

    try:
        return sleep_run_prefs.load(registry).scheduled_use_plan
    except Exception:  # noqa: BLE001 — ``load`` never raises; a stand-in that does reads as the default
        return sleep_run_prefs.RunOptions().scheduled_use_plan


def _schedule_may_use(mode: str, registry) -> bool:
    """Whether a scheduled run may resolve to ``mode``: every non-plan mode, and a plan mode only through the
    switch (``SCHEDULE_PLAN_MODES``). The one place ``SUBSCRIPTION_MODES`` meets a schedule."""
    if mode not in SUBSCRIPTION_MODES:
        return True
    return mode in SCHEDULE_PLAN_MODES and scheduled_plan_allowed(registry)

_VALID_PREF_MODES = ("auto", "agent", "codex", "byok", "local")


def _prefs_mode(registry) -> str | None:
    """The mode a Settings → Intelligence engine picker (G122) wrote, or ``None``
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
#: Ruling 36 D1 (2026-10-22): the local rung is gone — a model on this machine runs only when the person picks it.
_AUTO_LADDER = (CLAUDE_CONNECTION_ID, CODEX_CONNECTION_ID)


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
    press Consolidate", and the Settings → Intelligence card already shows the
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
        # Ruling 2026-10-19: Auto never reaches a metered key by itself — nothing on the ladder connected, nothing powers.
        for connection_id in _AUTO_LADDER:
            if connection_id in connected:
                return connection_id
        return None
    if registry is not None and use_for_sleep(registry) and CLAUDE_CONNECTION_ID in connected:
        return CLAUDE_CONNECTION_ID
    from api.services import telemetry

    # Round 4 final review: the OpenRouter card and the key-provider picker
    # write the byok pref's model, and a Sleep you start runs THAT model
    # (``resolve_settings`` applies ``_model_overrides``), so the card it
    # bills is read from the same slot before the env default. Reading only
    # ``settings.litellm_model`` named the env model's card (or none) once
    # OpenRouter was chosen. ``_model_overrides`` is ``{}`` unless the stored
    # pref was written for byok, so a stale plan model never leaks in here.
    model = _model_overrides(registry, "byok").get("litellm_model") if registry is not None else None
    model = model or getattr(settings, "litellm_model", "") or ""
    key_card, _billing = telemetry.connection_for_model(str(model))
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
    """R-E13: the Settings → Intelligence "Keep going on extra usage" choice.
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


def scheduled_plan_pin(settings) -> bool:
    """True when an explicit ``CICADA_LLM_MODE=agent|codex`` dotfile pin — the one case
    ``resolve_llm_mode`` hands a scheduled run a plan — decides the scheduled engine. The
    scheduler then reads one batch, never a whole queue, unattended on a plan (TODO ruling 16).
    No registry, no probe: only the env pin can do this."""
    fields = getattr(settings, "model_fields_set", None)
    if not fields or "llm_mode" not in fields:
        return False
    return (getattr(settings, "llm_mode", None) or "").strip().lower() in SUBSCRIPTION_MODES


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

    # G122, rung 2: a Settings → Intelligence engine picker choice, read only for a
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
            if not _schedule_may_use(configured, registry):
                # Ruling 2026-10-19: the person chose a plan, not a key — a schedule the plan is closed to has no
                # engine, never the metered key by itself.
                return "auto", SCHEDULE_DEGRADED
            return configured, "scheduled runs may use your plan (Settings → Sleep)"
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

    # Fix round 1, L3: an unrecognized ``llm_mode`` (a typo, or a future
    # value this module doesn't know yet) must never silently escalate into
    # the agent rung — and (2026-10-19) never into a metered key either: no
    # engine, said in words, before the registry is ever touched.
    if configured not in ("byok", "auto"):
        return "auto", f"unrecognized CICADA_LLM_MODE={configured!r} — choose an engine in Settings → Intelligence"

    if registry is None:
        from api.services.connections.registry import get_registry

        registry = get_registry(settings)

    if configured == "byok":
        # The person chose an API key (the env pin or the picker). Fix round 1, H1/H2 + ruling 4b: the Claude toggle
        # below is a plan, so a scheduled run reaches it only through the switch; without it, the chosen key.
        chose = "CICADA_LLM_MODE=byok" if env_explicit else "Sleep engine set to an API key in Settings"
        if not user_triggered and not _schedule_may_use("agent", registry):
            return "byok", SCHEDULE_DEGRADED
        prefer_claude = use_for_sleep(registry)
        if not prefer_claude:
            return "byok", chose
        claude = await _connected(registry, CLAUDE_CONNECTION_ID)
        if claude:
            if not user_triggered:
                return "agent", "scheduled runs may use your plan (Settings → Sleep)"
            return "agent", "Claude plan is set as the Sleep engine"
        # Only the use_for_sleep switch (Engines, under API key) reaches here, and that
        # toggle is Claude-only (R-E20) — never a reason to reach for ChatGPT.
        if claude is None:
            return "byok", "could not probe the Claude plan — using the API key you chose"
        return "byok", "Claude plan is not connected — using the API key you chose"

    # configured == "auto" from here — the default (2026-10-19). R-E20's ladder: the Claude plan, then the ChatGPT plan
    # (ruling 36 D1 removed the local rung: a model on this machine runs only when chosen); a plan is open to a scheduled
    # run only through the person's switch (ruling 4b). A rung whose probe fails (None) falls through to the next, as an
    # unconnected one does; the ladder never ends on a metered key or on a local model.
    claude_open = user_triggered or _schedule_may_use("agent", registry)
    codex_open = user_triggered or _schedule_may_use("codex", registry)
    if claude_open:
        claude = await _connected(registry, CLAUDE_CONNECTION_ID)
        if claude:
            if not user_triggered:
                return "agent", "scheduled runs may use your plan (Settings → Sleep)"
            return "agent", "Claude plan connected — running Sleep on your plan"
    if codex_open:
        codex = await _connected(registry, CODEX_CONNECTION_ID)
        if codex:
            return "codex", "ChatGPT plan signed in — running Sleep on your ChatGPT plan"
    if not (claude_open or codex_open):
        return "auto", SCHEDULE_DEGRADED
    return "auto", NO_ENGINE


#: The one-time record that Auto's local rung was retired for this install (ruling 36 D1): the date it was checked, and
#: whether a person reading through a local model under Auto was kept on it as an explicit choice.
AUTO_LOCAL_RECORD_KEY = "auto_local_retired"


async def retire_auto_local_rung(settings, registry) -> str | None:
    """Ruling 36 D1, once per install: Auto no longer reaches a local model. A person whose Auto read through one —
    nothing chosen, no plan connected, a local model running — keeps reading with it: their choice becomes an explicit
    ``local``, recorded (``AUTO_LOCAL_RECORD_KEY``, ``kept_local``) so Settings → Intelligence says so in one line,
    never silently. Everyone else only gets the record, so a local model installed later is never adopted. Returns
    ``"kept_local"``, ``"checked"``, or ``None`` when it had already run or the engine is pinned by the environment.
    Never raises: a failure leaves the record unwritten and the next start tries again."""
    try:
        entry = registry.prefs().get(SLEEP_ENGINE_PREF_KEY) or {}
        if entry.get(AUTO_LOCAL_RECORD_KEY):
            return None
        if hasattr(settings, "model_fields_set") and "llm_mode" in settings.model_fields_set:
            return None
        outcome = "checked"
        if configured_mode(settings, registry) == "auto":
            # The local model first: a short HTTP probe, so a machine without one never spawns a plan's CLI here.
            if await _connected(registry, OLLAMA_CONNECTION_ID) and not (
                    await _connected(registry, CLAUDE_CONNECTION_ID) or await _connected(registry, CODEX_CONNECTION_ID)):
                registry.set_pref(SLEEP_ENGINE_PREF_KEY, "mode", "local")
                outcome = "kept_local"
        registry.set_pref(SLEEP_ENGINE_PREF_KEY, AUTO_LOCAL_RECORD_KEY,
                          {"outcome": outcome, "on": datetime.now().date().isoformat()})
        return outcome
    except Exception as e:  # noqa: BLE001 — boot never fails for this
        logger.warning(f"retire_auto_local_rung: {e}")
        return None


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
        # returned {} — a model picked in Settings → Intelligence reached the
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
    if mode == "auto":
        # Nothing on the ladder may read (ruling 2026-10-19): the copy refuses every call, saying why.
        updates["no_engine_reason"] = no_engine_sentence(why)
    if not env_explicit:
        updates.update(_model_overrides(registry, mode))
        if _prefs_allow_overage(registry):
            updates["agent_allow_overage"] = True
    if not updates:
        return settings, why
    return settings.model_copy(update=updates), why
