"""G237, ruling 63: the seam a provider's own official SDK plugs into.

The owner, 2026-11-04: "have all official sdk's integrated where possible." A key whose provider is listed here is
served by that provider's own SDK; every other key stays on litellm (``providers.resolve_llm_fn``'s ``_call``). Adding a
provider is one row here and one module that keeps this contract; nothing in ``providers`` or the stages changes:

    complete(*, messages, model, stage, want_json, timeout, scope, effort, max_tokens, web_search) -> response

``response`` wears an OpenAI response's clothes both ways (``resp.choices[0]`` and ``resp["choices"][0]``), with
``usage`` gross (the cache counts a breakdown of it), the served ``model`` and ``_hidden_params.response_cost``.
``complete`` checks the scope's breaker first and raises only ``engine_errors`` (each in words, never the provider's own
text), so the semaphore, the breaker, the drain's retry and the ledger around it are the plan engines' own.

The engine label is what the ledger and the ``Cicada-Engine`` trailer name. ``engine_select.engine_label`` still reads
``litellm`` for every key on the wire: to the app that id means "the API-key engine".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


def _anthropic_matches(model: str) -> bool:
    from api.services import anthropic_models

    return anthropic_models.is_claude(model)


def _anthropic_complete(**kw: Any) -> Any:
    from api.services import anthropic_engine

    return anthropic_engine.complete(**kw)


@dataclass(frozen=True)
class DirectEngine:
    label: str                            # the ledger's and the trailer's engine id
    matches: Callable[[str], bool]        # does this model id bill this provider's own key, directly?
    complete: Callable[..., Any]


ANTHROPIC = DirectEngine("anthropic-api", _anthropic_matches, _anthropic_complete)
ENGINES: tuple[DirectEngine, ...] = (ANTHROPIC,)


def for_model(model: str | None) -> DirectEngine | None:
    """The provider SDK that serves this model id on a key, or ``None`` (litellm). A router's id is the router's."""
    m = (model or "").strip()
    return next((e for e in ENGINES if m and e.matches(m)), None)


def engine_label(model: str | None) -> str | None:
    engine = for_model(model)
    return engine.label if engine else None


def trailer_engine(engine: str | None, authors: list[str] | None) -> str | None:
    """The engine a commit names. ``litellm`` is the wire's word for any key; a commit's ``Cicada-Engine`` says what
    actually served it, so a key whose every model went through a provider's own SDK names that SDK. Mixed or unknown
    authors keep what they had: omitted or general rather than guessed."""
    if engine != "litellm":
        return engine
    labels = {engine_label(a) for a in (authors or []) if a}
    return labels.pop() if len(labels) == 1 and None not in labels else engine
