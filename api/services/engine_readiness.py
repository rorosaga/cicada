"""Whether an engine Cicada may use is actually there (owner decision 2, 2026-10-16; G181, ruling 4b).

A fresh server's Sleep engine is the shipped default — an API model — with no key, and its schedule could be turned
on silently, `engine list` called seven key cards "available", and Ask made a keyless call and said only that it
"could not synthesize" (headless QA, finding 8). This module answers the one question each of those doors needs —
is there an engine here this run may use? — so each says so in words, and each offers connecting a plan first.

Nothing here spends, and nothing names a value: a key's PRESENCE (``secrets.has_secret``), the plans' cached
probe (``engine_select.probe_claude_cheaply``) and the local model's adapter status. The copy names no provider
(the provider-neutral copy rail): the API model is "the API model Sleep reads with".
"""
from __future__ import annotations

from dataclasses import dataclass

#: Why a scheduled run has no engine it may use (the wire's ``warningCode``); each client words its own fix.
NO_ENGINE = "no_engine"            # an API model with no key, and no plan open to scheduled runs
PLAN_SIGNED_OUT = "plan_signed_out"  # scheduled runs may use the chosen plan, but it is not signed in here
LOCAL_DOWN = "local_down"          # the local model Sleep is pinned to is not running
PLAN_NOT_CHOSEN = "plan_not_chosen"  # scheduled runs may use the signed-in plan, but Sleep reads with a keyless model

#: The command-line fix for each, offering a plan first (owner decision 2).
CLI_FIX = {
    NO_ENGINE: ("Connect your plan on this machine (`cicada engine connect claude-plan`, or `chatgpt-plan`), choose "
                "it as Sleep's engine and let scheduled runs use it (`cicada sleep schedule --use-plan on`), or add a "
                "key for an API model (Settings → Plans & keys, or ~/.cicada/secrets.env)."),
    PLAN_SIGNED_OUT: ("Sign in to your plan on this machine: `cicada engine connect claude-plan` (or "
                      "`chatgpt-plan`)."),
    LOCAL_DOWN: "Start the local model, or choose another engine (`cicada sleep engine --mode …`).",
    PLAN_NOT_CHOSEN: ("Choose your plan as Sleep's engine: `cicada sleep engine --mode agent` (Claude) or "
                      "`--mode codex` (ChatGPT)."),
}


@dataclass(frozen=True)
class Problem:
    code: str
    sentence: str

    def with_cli_fix(self) -> str:
        return f"{self.sentence} {CLI_FIX.get(self.code, '')}".strip()


def key_env(model: str | None) -> str:
    """The environment name of the key an API model bills (``byok.provider_for_model``)."""
    from api.services.connections import byok

    return byok.provider(byok.provider_for_model(model)).env


def key_missing(settings) -> bool:
    """A resolved ``Settings`` that would call an API model with no key for it. False for a plan or a local model."""
    from api.services.connections import secrets

    mode = str(getattr(settings, "llm_mode", "byok") or "byok").strip().lower()
    if mode != "byok":
        return False
    return not secrets.has_secret(key_env(getattr(settings, "litellm_model", "") or ""))


async def scheduled_problem(settings, registry=None) -> Problem | None:
    """Why a scheduled run here would have no engine it may use, or ``None`` when it has one."""
    from api.services import engine_select

    resolved, _why = await engine_select.resolve_settings(settings, registry, user_triggered=False)
    mode = str(getattr(resolved, "llm_mode", "byok") or "byok").strip().lower()
    if registry is None:
        from api.services.connections.registry import get_registry

        registry = get_registry(settings)
    if mode in ("agent", "codex"):
        probe = engine_select.probe_claude_cheaply if mode == "agent" else engine_select.probe_codex_cheaply
        ok, _detail = await probe(registry)
        return None if ok else Problem(PLAN_SIGNED_OUT, "Scheduled runs may use your plan, but it is not signed in "
                                                        "on this machine.")
    if mode == "local":
        try:
            status = await registry.status(engine_select.OLLAMA_CONNECTION_ID)
            running = bool(getattr(status, "connected", False))
        except Exception:  # noqa: BLE001 — an unprobeable local model reads as not running
            running = False
        return None if running else Problem(LOCAL_DOWN, "Scheduled runs read with the local model, and it is not "
                                                        "running.")
    if mode == "byok" and key_missing(resolved):
        if engine_select.scheduled_plan_allowed(registry):
            claude, _ = await engine_select.probe_claude_cheaply(registry)
            chatgpt = False if claude else (await engine_select.probe_codex_cheaply(registry))[0]
            if claude or chatgpt:
                return Problem(PLAN_NOT_CHOSEN, "Scheduled runs may use your plan, but Sleep reads with an API model "
                                                "that has no key here.")
        return Problem(NO_ENGINE, "Scheduled runs have no engine they may use here: no key is set for the API model "
                                  "Sleep reads with, and no plan is open to scheduled runs.")
    return None


ASK_NO_ENGINE = ("Cicada has no engine to answer with on this machine: no key is set for the API model it reads "
                 "with, and no plan is chosen. Connect your plan (`cicada engine connect claude-plan`, or "
                 "`chatgpt-plan`) or add a key for an API model (Settings → Plans & keys).")
