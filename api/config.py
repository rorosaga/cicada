import os
from functools import lru_cache
from pathlib import Path

from loguru import logger
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from api.services.bank_registry import resolve_active_bank_path


class Settings(BaseSettings):
    # Memory storage.
    #
    # ``memory_root`` is the *container* for the whole memory system: the legacy
    # in-place files (``<root>/entities``, ``<root>/episodes``, ``<root>/.git``)
    # that are the synthetic ``default`` bank, the ``<root>/banks.yaml`` registry,
    # and ``<root>/banks/<name>/`` for every non-legacy bank.
    #
    # ``memory_path`` (below) is the *resolved active bank* — a computed property
    # so a bank switch (which mutates ``banks.yaml``, not this object) takes effect
    # without a restart even though ``get_settings()`` is ``@lru_cache``d.
    #
    # The raw field accepts both ``CICADA_MEMORY_ROOT`` and the legacy
    # ``CICADA_MEMORY_PATH`` env var (via ``validation_alias``) so existing
    # installs + the test suite (which set ``CICADA_MEMORY_PATH``) keep working
    # verbatim. With no ``banks.yaml`` on disk, ``memory_path`` returns the root
    # unchanged — identical to pre-banks behavior.
    memory_root: Path = Field(
        default=Path.home() / "cicada" / "memory",
        validation_alias=AliasChoices("CICADA_MEMORY_PATH", "CICADA_MEMORY_ROOT"),
    )

    @property
    def memory_path(self) -> Path:
        """The active memory bank's on-disk dir (resolved per-access)."""
        return resolve_active_bank_path(self.memory_root)

    # Embedding backend for the vector index.
    #   "local"  -> sentence-transformers on-device (no API key, offline). Default.
    #               EmbeddingGemma-300M (768-dim) — Google DeepMind, gated on HF
    #               (accept the license + set HF_TOKEN to download).
    #   "openai" -> text-embedding-3-small via OpenAI (needs OPENAI_API_KEY)
    # The mode requested here is the *configured* mode; the *resolved* mode
    # (see ``resolved_embedding_mode``) auto-degrades openai -> local when no
    # OPENAI_API_KEY is present so a key-less install still gets semantic search.
    # Default is "local" so Cicada runs fully on-device with no API/quota
    # dependency (the thesis's zero-infra goal); set CICADA_EMBEDDING_MODE=openai
    # to use OpenAI. Note: local and openai produce different-dimension vectors,
    # so switching modes requires a full index rebuild.
    embedding_mode: str = "local"             # CICADA_EMBEDDING_MODE
    embedding_model: str = "text-embedding-3-small"  # CICADA_EMBEDDING_MODEL (openai)
    # Local-mode model name (used when the resolved mode is "local").
    embedding_model_local: str = "google/embeddinggemma-300m"

    # LiteLLM model (format: provider/model-name)
    # Examples: gpt-5.4-mini, anthropic/claude-sonnet-4-20250514, gemini/gemini-2.0-flash
    # LiteLLM reads OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY from env automatically
    litellm_model: str = "gpt-5.4-mini"

    # Dedicated model for Stage 2 same/different/unsure disambiguation judge.
    # This call fires once per token-overlap candidate pair and does not need
    # the full reasoning depth of the main sleep-cycle model, so by default we
    # point it at a cheaper/faster model. Set CICADA_LITELLM_DISAMBIGUATION_MODEL
    # to override. An empty value falls back to ``litellm_model``.
    litellm_disambiguation_model: str = "gpt-5.4-nano"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Sleep cycle thresholds
    sleep_promotion_threshold: int = 2
    decay_nudge_threshold: float = 0.4
    archive_threshold: float = 0.2

    # Stage 5.57 link-enrichment (M5f) — bounded, offline-safe media-link
    # description enrichment into CPCG `describes`/`recommends` claims.
    link_enrich_enabled: bool = True          # CICADA_LINK_ENRICH_ENABLED kill switch
    link_enrich_max_per_cycle: int = 20       # hard cap on LLM summarize calls/cycle
    link_enrich_min_desc_len: int = 120       # chars; shorter OG desc => trigger summarize
    link_enrich_excerpt_chars: int = 2000     # chars of visible body text fed to the LLM

    # Hub tier (small-LLM traversal)
    hub_tag_min_members: int = 5     # min entities sharing a tag to spawn a topic hub
    hub_tag_max_hubs: int = 30       # cap on tag-cluster hubs
    hub_member_cap: int = 150        # max members listed per hub file

    model_config = {"env_prefix": "CICADA_", "env_file": ".env", "extra": "ignore"}

    @property
    def resolved_embedding_mode(self) -> str:
        """Effective embedding mode after auto-degrade.

        If ``embedding_mode == "openai"`` but no ``OPENAI_API_KEY`` is present
        in the environment, fall back to ``"local"`` so a key-less install
        still produces a usable (offline) index instead of silently going
        stale. Any explicit ``"local"`` is returned unchanged.
        """
        mode = (self.embedding_mode or "openai").strip().lower()
        if mode == "openai" and not (os.environ.get("OPENAI_API_KEY") or "").strip():
            return "local"
        return mode

    @property
    def resolved_embedding_model(self) -> str:
        """Embedding model name matching the resolved mode."""
        if self.resolved_embedding_mode == "openai":
            return self.embedding_model
        return self.embedding_model_local

    def warn_if_degraded(self) -> None:
        """Log a one-line warning when openai mode silently degraded to local."""
        configured = (self.embedding_mode or "openai").strip().lower()
        if configured == "openai" and self.resolved_embedding_mode == "local":
            logger.warning(
                "CICADA_EMBEDDING_MODE=openai but OPENAI_API_KEY is unset/empty — "
                "falling back to local sentence-transformers embeddings. Set "
                "OPENAI_API_KEY to use OpenAI, or set CICADA_EMBEDDING_MODE=local "
                "to silence this warning."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
