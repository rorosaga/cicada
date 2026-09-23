"""G122 — the business logic behind ``GET/PUT /sleep/engine``.

This is the Settings → Sleep page's engine-and-model picker: a read/write
surface over the ``sleep-engine`` pref ``engine_select.py`` already knows how
to resolve (see that module's rung 2). Kept as its own service, not folded
into ``engine_select.py`` itself, because that module is a hot, synchronous-
looking resolution path called from deep inside every Sleep stage (its own
docstring: "``resolve_llm_fn`` is synchronous ... can never probe the
connections registry") — this file is the opposite shape: an on-demand,
fully-probing read for one settings page, never called from a Sleep cycle.

G124 rail: nothing here ever reports a price or a token count — a candidate
only carries enough to render a segmented control and, once selected, a
model list.
"""
from __future__ import annotations

from fastapi import HTTPException

from api.config import Settings
from api.models.schemas import (
    SleepEngineCandidate,
    SleepEngineChoice,
    SleepEnginePreview,
    SleepEnginePreviews,
    SleepEngineResponse,
)
from api.services import agent_engine, codex_app_server, codex_engine, engine_select
from api.services.connections import registry as registry_module

PREF_KEY = engine_select.SLEEP_ENGINE_PREF_KEY
# One list with the resolver (Track E Task 4): a mode the picker may write is
# exactly a mode `engine_select._prefs_mode` will read back — two copies let
# `codex` be writable here yet silently ignored there, or the reverse.
VALID_MODES = engine_select._VALID_PREF_MODES

# The agent rung's model picker offers these plus whatever `agent_model` is
# already configured (so an existing non-default choice never disappears
# from the list just because this page hasn't seen it before).
_AGENT_MODEL_CHOICES = ("sonnet", "haiku", "opus")


def _configured_choice(settings: Settings, reg) -> tuple[str, str]:
    """The ``(mode, source)`` this GET reports, mirroring the env/prefs
    precedence ``engine_select.resolve_llm_mode`` applies (rungs 1-2) but
    WITHOUT its connectivity probe — a probe answers "what would actually
    run", which belongs to ``preview`` below; this answers "what is
    configured", a synchronous, side-effect-free read."""
    has_fields_set = hasattr(settings, "model_fields_set")
    env_explicit = has_fields_set and "llm_mode" in settings.model_fields_set
    configured = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
    if env_explicit:
        return configured, "env"
    pref_mode = engine_select._prefs_mode(reg)
    if pref_mode is not None:
        return pref_mode, "prefs"
    return configured, "default"


def _resolved_model_pair(settings: Settings, reg, mode: str, source: str) -> tuple[str, str]:
    """The ``(model, disambiguation_model)`` this GET reports for the
    CONFIGURED mode — not necessarily what a probe would pick it to run on
    (that's ``preview``). An explicit env pin (source == "env") never
    consults a G122 override, mirroring ``resolve_settings``'s own R4 gate.
    """
    overrides = {} if source == "env" else engine_select._model_overrides(reg, mode)
    if mode == "agent":
        model = overrides.get("agent_model") or agent_engine.model_for_stage(settings, None)
        disambiguation = overrides.get("agent_disambiguation_model") or agent_engine.model_for_stage(
            settings, "disambiguation"
        )
        return model, disambiguation
    if mode == "codex":
        # R-E17: an empty `codex_model` means "the plan's current default" —
        # reported as "" here (no model id lives in code); a real cycle's
        # pre-flight resolves it from `model/list`.
        model = overrides.get("codex_model") or codex_engine.model_for_stage(settings, None)
        disambiguation = (overrides.get("codex_disambiguation_model")
                          or codex_engine.model_for_stage(settings, "disambiguation") or model)
        return model, disambiguation
    if mode == "local":
        # Ollama binds one model for every stage (providers.resolve_llm_fn
        # forces `ollama/<ollama_model>` regardless of the caller's
        # requested model once `mode == "local"`) — there is no separate
        # disambiguation model to report.
        model = overrides.get("ollama_model") or settings.ollama_model
        return model, model
    model = overrides.get("litellm_model") or settings.litellm_model
    disambiguation = (
        overrides.get("litellm_disambiguation_model")
        or (getattr(settings, "litellm_disambiguation_model", "") or "").strip()
        or settings.litellm_model
    )
    return model, disambiguation


async def _candidates(settings: Settings, reg) -> list[SleepEngineCandidate]:
    """The picker's five cards (R-E4). Probes the whole registry once
    (``statuses`` is 30 s cached, so this is usually free) rather than
    one-off probing each connection — the same shared-cache pattern every
    other read of the registry already uses. The ChatGPT roster comes from
    the app-server snapshot (30 s cached, no quota, R-E18) and only once that
    plan is signed in: a signed-out home has no roster worth offering."""
    statuses = {status.id: status for status in await reg.statuses(fresh=False)}
    claude = statuses.get(engine_select.CLAUDE_CONNECTION_ID)
    chatgpt = statuses.get(engine_select.CODEX_CONNECTION_ID)
    ollama = statuses.get(engine_select.OLLAMA_CONNECTION_ID)

    agent_models = list(_AGENT_MODEL_CHOICES)
    if settings.agent_model and settings.agent_model not in agent_models:
        agent_models.append(settings.agent_model)

    # R-E17: never a model id in code — the roster is whatever the plan's
    # own `model/list` says today (default first), plus a configured choice
    # so an existing pick never disappears from the list.
    codex_models: list[str] = []
    if chatgpt and chatgpt.connected:
        snap = await codex_app_server.snapshot()
        codex_models = list(snap.models) if snap else []
    configured_codex = (settings.codex_model or "").strip()
    if configured_codex and configured_codex not in codex_models:
        codex_models.append(configured_codex)

    try:
        ollama_models = list(await registry_module._ollama_fetch_tags(settings.ollama_base_url))
    except Exception:
        ollama_models = []

    return [
        SleepEngineCandidate(
            id="auto", label="Auto", available=True,
            detail=("Your Claude plan if it's signed in, else your ChatGPT plan, else Ollama if "
                    "it's running, else your API key."),
        ),
        SleepEngineCandidate(
            id="agent", label="Claude plan",
            available=bool(claude and claude.available), connected=bool(claude and claude.connected),
            models=agent_models, detail=claude.detail if claude else None,
        ),
        SleepEngineCandidate(
            id="codex", label="ChatGPT plan",
            available=bool(chatgpt and chatgpt.available), connected=bool(chatgpt and chatgpt.connected),
            models=codex_models,
            detail=((chatgpt.plan_label or "Signed in to ChatGPT.") if chatgpt and chatgpt.connected
                    else (chatgpt.detail if chatgpt else None)),
        ),
        SleepEngineCandidate(
            id="local", label="Ollama",
            available=bool(ollama and ollama.available), connected=bool(ollama and ollama.connected),
            models=ollama_models, detail=ollama.detail if ollama else None,
        ),
        SleepEngineCandidate(
            id="byok", label="API key", available=True, connected=True,
            detail="Uses the model configured on the Plans & keys page.",
        ),
    ]


def _preview(resolved: Settings, why: str) -> SleepEnginePreview:
    """One preview line for an already-resolved ``Settings`` copy (from
    ``engine_select.resolve_settings``) — the model each engine label reads
    off of is exactly what ``sleep_cycle``/``providers`` would use, so this
    can never drift from what actually runs."""
    engine = engine_select.engine_label(resolved)
    if engine == "claude-cli":
        model = agent_engine.model_for_stage(resolved, None)
    elif engine == "codex-cli":
        # R-E17: an unpicked model reads as the plan's own default, named in
        # words — the id is only known once a cycle's pre-flight asks.
        model = codex_engine.model_for_stage(resolved, None) or "default model"
    elif engine == "ollama":
        model = resolved.ollama_model
    else:
        model = resolved.litellm_model
    return SleepEnginePreview(engine=engine, model=model, why=why)


async def build_response(settings: Settings, reg) -> SleepEngineResponse:
    """Assembles the full GET/PUT /sleep/engine body. Called by both routes:
    PUT writes the pref first, then re-reads through this same function so
    the response it hands back is exactly what a subsequent GET would say —
    never a hand-built echo of the request body that could drift from what
    was actually persisted."""
    mode, source = _configured_choice(settings, reg)
    model, disambiguation_model = _resolved_model_pair(settings, reg, mode, source)
    candidates = await _candidates(settings, reg)

    manual_settings, manual_why = await engine_select.resolve_settings(settings, reg, user_triggered=True)
    scheduled_settings, scheduled_why = await engine_select.resolve_settings(
        settings, reg, user_triggered=False
    )
    preview = SleepEnginePreviews(
        manual=_preview(manual_settings, manual_why),
        scheduled=_preview(scheduled_settings, scheduled_why),
    )

    # R-E13: the stored opt-in, or an env-pinned CICADA_AGENT_ALLOW_OVERAGE —
    # either one is what a cycle would honour, so the card shows it on.
    allow_overage = (bool((reg.prefs().get(PREF_KEY) or {}).get("allow_overage"))
                     or bool(settings.agent_allow_overage))
    return SleepEngineResponse(
        mode=mode, model=model, disambiguation_model=disambiguation_model,
        source=source, candidates=candidates, preview=preview, allow_overage=allow_overage,
    )


def validate_and_write(body: SleepEngineChoice, reg) -> None:
    """Validates a PUT body and, only if it passes, persists it. Raises
    ``HTTPException(422)`` — never writes a half-valid choice."""
    if body.mode not in VALID_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {VALID_MODES}")

    if body.mode in ("agent", "codex"):
        # Both plan engines pass the id to a CLI as `--model`/`-m`: the same
        # charset `build_argv` enforces before any spawn (a leading `-` must
        # never become a flag) is checked here, before it is ever stored.
        if body.model is not None and not agent_engine.is_valid_model_id(body.model):
            raise HTTPException(status_code=422, detail="invalid model id for this engine")
        if body.disambiguation_model is not None and not agent_engine.is_valid_model_id(
            body.disambiguation_model
        ):
            raise HTTPException(
                status_code=422, detail="invalid disambiguation model id for this engine"
            )
    elif body.mode == "local":
        if body.model is not None and not body.model.strip():
            raise HTTPException(status_code=422, detail="model must not be blank")
        if body.disambiguation_model is not None and not body.disambiguation_model.strip():
            raise HTTPException(status_code=422, detail="disambiguation model must not be blank")

    # Cross-mode staleness guard: `model`/`disambiguation_model` share ONE
    # untyped string slot per `sleep-engine` pref entry, with no mode tag of
    # its own — `engine_select._model_overrides` reinterprets whatever sits
    # there as belonging to whichever mode is CURRENTLY selected. Clear a
    # field on a mode switch unless this same PUT also supplies a fresh
    # value for it, so a Local-mode Ollama tag can never survive a switch to
    # Agent mode and get misread as a Claude alias (or vice versa).
    previous_mode = (reg.prefs().get(PREF_KEY) or {}).get("mode")
    mode_changed = previous_mode is not None and previous_mode != body.mode
    if mode_changed and "model" not in body.model_fields_set:
        reg.set_pref(PREF_KEY, "model", None)
    if mode_changed and "disambiguation_model" not in body.model_fields_set:
        reg.set_pref(PREF_KEY, "disambiguation_model", None)

    # `mode` is always written — the one required field. `model`/
    # `disambiguation_model` use the same "omitted vs explicitly null"
    # idiom `routers/connections.py::PrefsBody` already uses for `tier`.
    reg.set_pref(PREF_KEY, "mode", body.mode)
    if "model" in body.model_fields_set:
        reg.set_pref(PREF_KEY, "model", body.model)
    if "disambiguation_model" in body.model_fields_set:
        reg.set_pref(PREF_KEY, "disambiguation_model", body.disambiguation_model)
    # R-E13: the opt-in is stored only while it is on; `None` removes the key
    # so an opted-out bank's prefs file reads exactly as one that never chose.
    if "allow_overage" in body.model_fields_set:
        reg.set_pref(PREF_KEY, "allow_overage", True if body.allow_overage else None)
