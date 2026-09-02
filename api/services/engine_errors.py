"""G74(a) — the failure taxonomy for the `claude -p` Sleep engine.

The rung's failures are subprocess-shaped, so nothing above it can branch on
litellm exception types (``entity_extractor._EXTRACT_RETRYABLE`` matched
*nothing* and gave a CLI failure zero retries). These seven types are the
contract every layer above branches on: the extractor's retry tuple, its
per-episode classifier, the resolver's failure-vs-uncertainty split, and the
Sleep page's honest engine copy.

No logic and no imports beyond stdlib on purpose — this module is safe to
import from anywhere, including ``providers`` at seam-resolution time.
"""
from __future__ import annotations


class EngineError(Exception):
    """Base: the Sleep engine could not answer. Never a model's opinion."""


class EngineUnavailable(EngineError):
    """The engine cannot be reached at all: binary missing, signed out, or
    stdout that isn't the JSON envelope. Not retryable — retrying a signed-out
    CLI 200 times is just 200 spawns."""


class EngineTimeout(EngineError):
    """The subprocess exceeded its wall-clock budget (rc 124)."""


class EngineThrottled(EngineError):
    """The plan is rate-limited right now. Trips the circuit breaker: after
    the first one the cycle stops cleanly rather than re-hitting it once per
    remaining episode."""


class EngineExhausted(EngineError):
    """``terminal_reason: budget_exhausted`` — the plan window is spent."""


class EngineModelNotFound(EngineError):
    """The model id/alias is unusable. A configuration bug, not a transient.

    Raised either after the fact (the CLI rejected the model id — an
    ``api_error_status == 404``/"model not found" envelope) or pre-flight, in
    ``agent_engine.build_argv``, when a caller-supplied value fails the
    conservative id/alias charset check before any subprocess spawns (review
    fix round 1, M1: a value beginning with ``-`` would otherwise be appended
    as a raw argv token right after ``--model`` with no validation)."""


class EngineProtocolError(EngineError):
    """A well-formed JSON envelope of an unexpected shape (no ``result`` and
    no ``structured_output``). Worth one retry — a truncated stream produces
    this."""


class EngineFailed(EngineError):
    """``is_error: true`` with a ``terminal_reason`` we cannot yet classify.

    The spec (§9, "still unverified") could not produce a real 429/quota
    envelope on demand, so an unrecognised failure is logged in full and given
    one retry rather than being silently mapped onto a class it may not be.
    """


#: Engine failures worth exactly one retry inside a single call. Deliberately
#: excludes ``EngineThrottled`` (the breaker handles it — a retry would spawn
#: again), ``EngineUnavailable``, ``EngineExhausted`` and
#: ``EngineModelNotFound`` (all of which need a human, not a second attempt).
RETRYABLE: tuple[type[Exception], ...] = (EngineTimeout, EngineProtocolError, EngineFailed)
