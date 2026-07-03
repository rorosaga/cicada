import os
from functools import lru_cache
from pathlib import Path

from loguru import logger
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from api.services.bank_registry import resolve_active_bank_path

# Key-backed embedding modes -> the env var whose presence keeps them from
# degrading to local. Module-level so pydantic doesn't treat it as a field.
_EMBEDDING_MODE_KEYS = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


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
    #   "openrouter" -> OpenRouter /embeddings (needs OPENROUTER_API_KEY).
    #                   Default model google/gemini-embedding-2 (~3072-dim, the
    #                   real dim is recorded live from the first response). Like
    #                   openai it auto-degrades to local when the key is missing.
    embedding_mode: str = "local"             # CICADA_EMBEDDING_MODE
    embedding_model: str = "text-embedding-3-small"  # CICADA_EMBEDDING_MODEL (openai)
    # Local-mode model name (used when the resolved mode is "local").
    embedding_model_local: str = "google/embeddinggemma-300m"
    # OpenRouter-mode embedding model (used when the resolved mode is "openrouter").
    # CICADA_EMBEDDING_MODEL maps to this when mode=openrouter; we keep a separate
    # field so swapping mode doesn't clobber the openai model name and vice-versa.
    embedding_model_openrouter: str = "google/gemini-embedding-2"

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

    # Dedicated model for the sleep/consolidation path. Empty (the default)
    # means "use litellm_model", so an unconfigured install behaves identically
    # to today. Set CICADA_CONSOLIDATION_MODEL to point consolidation at any
    # provider litellm can route (e.g. openrouter/z-ai/glm-5.2) without changing
    # the default litellm_model used everywhere else. Read via
    # ``effective_consolidation_model``.
    consolidation_model: str = ""             # CICADA_CONSOLIDATION_MODEL

    # Optional OpenRouter attribution headers, attached by the provider factory
    # ONLY when the resolved model id starts with "openrouter/". Both empty (the
    # default) => no headers attached, so the default path is untouched.
    openrouter_referer: str = ""              # CICADA_OPENROUTER_REFERER (HTTP-Referer)
    openrouter_title: str = "Cicada"          # CICADA_OPENROUTER_TITLE (X-OpenRouter-Title)

    # LLM consolidation mode — how ``resolve_llm_fn`` routes the sleep-cycle
    # model. "byok" (default) is today's behavior: whatever ``litellm_model``
    # (or ``effective_consolidation_model``) resolves to, routed through
    # litellm's normal provider prefixes (openai/anthropic/openrouter/...) using
    # the matching *_API_KEY env var. "local" routes to an on-device Ollama
    # server instead — no API key required, fully offline — by binding the
    # model to ``ollama/<ollama_model>`` and pointing litellm's api_base at
    # ``ollama_base_url``. "agent" is reserved for a future MCP-agent-driven
    # mode; not yet implemented here. Setting llm_mode != "local" leaves
    # resolve_llm_fn's byok/openrouter behavior byte-identical to before this
    # field existed.
    llm_mode: str = "byok"                    # CICADA_LLM_MODE (agent|byok|local)
    # Model name passed to Ollama when llm_mode="local" (litellm bind:
    # "ollama/<ollama_model>"). Does NOT include the "ollama/" prefix itself.
    ollama_model: str = "llama3.1"             # CICADA_OLLAMA_MODEL
    # Base URL of the local Ollama server, forwarded to litellm as api_base.
    ollama_base_url: str = "http://localhost:11434"  # CICADA_OLLAMA_BASE_URL

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # G15 — the user's GitHub handle, used to render their profile picture
    # (https://github.com/<handle>.png) as the avatar for `user`-authored
    # commits on the Contributors page. Optional: set CICADA_GITHUB_USER to
    # override; otherwise it's derived from the repo's `origin` remote.
    github_user: str = ""  # CICADA_GITHUB_USER

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

    # Telegram capture connector (Wave B ingestion) — a message forwarded/sent
    # to the user's own bot, POSTed by Telegram to `POST /capture/telegram`,
    # becomes a staged episode or media item (see
    # `api/services/telegram_capture.py`). Empty (the default) keeps the
    # connector fully inert: the endpoint 503s and no webhook traffic is
    # accepted, so an unconfigured install gets zero added surface area. Set
    # CICADA_TELEGRAM_BOT_TOKEN to the token from @BotFather to activate.
    telegram_bot_token: str = ""  # CICADA_TELEGRAM_BOT_TOKEN

    model_config = {"env_prefix": "CICADA_", "env_file": ".env", "extra": "ignore"}

    @property
    def telegram_enabled(self) -> bool:
        """Whether the Telegram capture connector is configured (token present)."""
        return bool((self.telegram_bot_token or "").strip())

    @property
    def effective_consolidation_model(self) -> str:
        """The model id the sleep/consolidation path should use.

        Returns ``consolidation_model`` when set, else ``litellm_model``. Empty
        default => identical to today's behavior (everything on litellm_model).
        """
        return (self.consolidation_model or "").strip() or self.litellm_model

    @property
    def resolved_embedding_mode(self) -> str:
        """Effective embedding mode after auto-degrade.

        If a key-backed mode (``openai`` / ``openrouter``) is requested but its
        API key is unset/empty in the environment, fall back to ``"local"`` so a
        key-less install still produces a usable (offline) index instead of
        silently going stale. Any explicit ``"local"`` is returned unchanged.
        """
        mode = (self.embedding_mode or "openai").strip().lower()
        key_env = _EMBEDDING_MODE_KEYS.get(mode)
        if key_env and not (os.environ.get(key_env) or "").strip():
            return "local"
        return mode

    @property
    def resolved_embedding_model(self) -> str:
        """Embedding model name matching the resolved mode."""
        mode = self.resolved_embedding_mode
        if mode == "openai":
            return self.embedding_model
        if mode == "openrouter":
            return self.embedding_model_openrouter
        return self.embedding_model_local

    def warn_if_degraded(self) -> None:
        """Log a one-line warning when a key-backed mode silently degraded to local."""
        configured = (self.embedding_mode or "openai").strip().lower()
        if (
            configured in _EMBEDDING_MODE_KEYS
            and self.resolved_embedding_mode == "local"
        ):
            key_env = _EMBEDDING_MODE_KEYS[configured]
            logger.warning(
                f"CICADA_EMBEDDING_MODE={configured} but {key_env} is unset/empty — "
                "falling back to local sentence-transformers embeddings. Set "
                f"{key_env} to use {configured}, or set CICADA_EMBEDDING_MODE=local "
                "to silence this warning."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
