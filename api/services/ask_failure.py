"""Why Ask's model call failed, in the person's words (G148, tester blocker 2026-11-06).

A plan limit, a sign-out, a timeout and a dropped connection all answered "I retrieved related memory but could not
synthesize a reliable answer" — the cause went to the log, so the person could neither fix it nor tell it from a bad
reply. Sleep already says these failures well, so this module only sorts an exception into a code with the classifiers
Sleep uses and words it for a question: ``engine_errors`` (the engine's own classes), ``agent_engine.limit_kind_of``
(which window), ``engine_cause`` (what a key's provider said) and ``sleep_drain.offline_cause`` (the network's doing).
It holds no keywords of its own.

An exception's message never leaves (G199): the sentence comes from the code, a reset time from the exception's own
``resets_at`` (the vendor's, never estimated), and the class name stays in the log. No figures (ruling 12).
Copy is provider-neutral: "your plan", "the engine you chose".
"""
from __future__ import annotations

from dataclasses import dataclass

from api.services import agent_engine, engine_cause, engine_errors

#: How long a caller waits for one answer. The engine's own clock is 300 s a call and an unreadable reply is asked
#: once more, so a shorter wait gives up on a backend that is still working (the app's 60 s idle default did, and the
#: MCP fallback then ran the whole job a second time).
ASK_WAIT_S = 600.0

#: The closed set of codes on the wire (``failure``). ``unreadable`` is the one that is not an engine failure: the
#: engine answered and the reply could not be read, twice; ``no_engine`` is told before a call is made.
CODES = ("plan_window", "plan_weekly", "overage", "plan_limit", "key_limit", "rate_limited", "key_refused",
         "model_unknown", "engine_unavailable", "timeout", "offline", "no_engine", "unreadable")

UNREADABLE = "unreadable"
NO_ENGINE = "no_engine"   # there is no engine to call at all (`engine_readiness`), told before any call


@dataclass(frozen=True)
class AskFailure:
    code: str
    sentence: str
    resets_at: int | None = None


def classify(exc: BaseException) -> str | None:
    """The code for an exception out of the model call, or ``None`` when it names none of ``CODES`` (an unnamed
    failure: the caller asks once more, as it does for an unreadable reply)."""
    if isinstance(exc, engine_errors.EngineOverage):
        return "overage"
    if isinstance(exc, (engine_errors.EngineThrottled, engine_errors.EngineExhausted)):
        kind = agent_engine.limit_kind_of(exc)
        return {"five_hour": "plan_window", "seven_day": "plan_weekly", "overage": "overage",
                "key_limit": "key_limit"}.get(kind, "plan_limit")
    if isinstance(exc, engine_errors.EngineModelNotFound):
        return "model_unknown"
    cause = engine_cause.classify(exc)
    if isinstance(exc, engine_errors.EngineUnavailable):
        return "key_refused" if cause == "auth" else "engine_unavailable"
    if isinstance(exc, (engine_errors.EngineTimeout, TimeoutError)):
        return "timeout"
    if cause:
        return {"spending_limit": "key_limit", "auth": "key_refused", "model_not_found": "model_unknown",
                "rate_limited": "rate_limited"}[cause]
    from api.services import sleep_drain

    # No sleep to blame and a route assumed: only a failure of the connection itself reads as the network's.
    if sleep_drain.offline_cause(exc, slept_s=0.0, route=True):
        return "offline"
    try:
        import litellm

        if isinstance(exc, litellm.exceptions.Timeout):
            return "timeout"
    except Exception:  # noqa: BLE001 — litellm missing or renamed
        pass
    return None


def _resets_at(exc: BaseException) -> int | None:
    value = getattr(exc, "resets_at", None)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def sentence(code: str, resets_at: int | None = None) -> str:
    """What happened and what to do, in one line; when it resets only when the vendor said."""
    from api.services import plan_limits

    when = plan_limits.reset_phrase(resets_at)
    again = f"Ask again {when}." if when else "Ask again once it resets."
    if code == "plan_window":
        return f"Your plan's usage window is full. {again}"
    if code == "plan_weekly":
        return f"Your plan's week is used up. {again}"
    if code == "overage":
        return f"Your plan's included usage is used up. {again}"
    if code == "plan_limit":
        return f"Your plan's usage limit is reached. {again}"
    if code == "key_limit":
        return engine_cause.sentence("spending_limit")
    if code == "rate_limited":
        return "The provider is rate-limiting the API key. Ask again in a minute, or raise the key's rate limit."
    if code == "key_refused":
        return engine_cause.sentence("auth")
    if code == "model_unknown":
        return ("The provider does not know the model you chose. Choose another engine in Settings → Intelligence, "
                "or change the model where it was set.")
    if code == "engine_unavailable":
        return ("The engine you chose isn't signed in or can't be started here. Sign in to it again, or choose "
                "another engine in Settings → Intelligence.")
    if code == "timeout":
        return "The engine took too long to answer. Ask again, or choose a faster engine in Settings → Intelligence."
    if code == "offline":
        return "The connection to the engine dropped. Ask again once this computer is online."
    raise ValueError(f"unknown ask failure code {code!r}")


def failure_for(exc: BaseException) -> AskFailure | None:
    """The failure an exception out of the model call is, or ``None`` when it is not one ``CODES`` names."""
    code = classify(exc)
    if code is None:
        return None
    resets = _resets_at(exc)
    return AskFailure(code, sentence(code, resets), resets)
