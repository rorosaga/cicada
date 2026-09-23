"""G139 — which environment switches steer this backend, by NAME only.

Settings → Advanced lists them because several silently outrank what the app
chooses — `CICADA_LLM_MODE` pins the engine even on the schedule (TODO ruling
4's one exception) — and Privacy & data shows the three outbound gates.
Names only, never values (R-O22): a value can be a secret (`CICADA_API_TOKEN`)
or a path that names the owner, and "this is set" is all the app needs.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

#: The switches the app explains, in the order it lists them. A name outside
#: this list is never reported — the app has no plain words for it.
KNOWN: tuple[str, ...] = (
    "CICADA_LLM_MODE", "CICADA_AGENT_MODEL", "CICADA_CODEX_MODEL", "CICADA_OLLAMA_MODEL",
    "CICADA_CONSOLIDATION_MODEL", "CICADA_EMBEDDING_MODE", "CICADA_MEMORY_PATH", "CICADA_MEMORY_ROOT",
    "CICADA_HOME", "CICADA_API_TOKEN", "CICADA_API_AUTH", "CICADA_TELEMETRY",
    "CICADA_ALLOW_CONNECTOR_FETCH", "CICADA_ALLOW_FEED_FETCH", "CICADA_ALLOW_LOGO_FETCH",
    "CICADA_OBSERVER_OWNER", "CICADA_REMOTE_PORT", "CICADA_AGENT_ALLOW_OVERAGE",
)

#: A settings field whose env name is not `CICADA_<FIELD>` (config.py's alias).
_FIELD_ENV = {"memory_root": "CICADA_MEMORY_PATH"}


def present(fields_set: frozenset[str] | set[str] = frozenset(),
            environ: Mapping[str, str] | None = None) -> list[str]:
    """`KNOWN` names set in the process env, or loaded by pydantic from
    `api/.env` (`Settings.model_fields_set`, which never reaches os.environ)."""
    env = os.environ if environ is None else environ
    loaded = {_FIELD_ENV.get(f, f"CICADA_{f.upper()}") for f in fields_set}
    # `memory_root` answers to two aliases; when the env already names the
    # one that was used, the field being set is that name, not a second one.
    if "CICADA_MEMORY_ROOT" in env and "CICADA_MEMORY_PATH" not in env:
        loaded.discard("CICADA_MEMORY_PATH")
    return [name for name in KNOWN if name in env or name in loaded]


def gates() -> dict[str, bool]:
    """The three outbound gates, each read by the function that enforces it —
    never a second parse of the env (CLAUDE.md, "Reaching the outside world")."""
    from api.services import feed_registry, logo_service
    from api.services.connectors import base as connector_base

    return {
        "connector_fetch": connector_base.network_allowed(),
        "feed_fetch": feed_registry.fetch_allowed(),
        "logo_fetch": logo_service.fetch_allowed(),
    }
