from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Memory storage
    memory_path: Path = Path.home() / "cicada" / "memory"

    # LiteLLM model (format: provider/model-name)
    # Examples: openai/gpt-4o-mini, anthropic/claude-sonnet-4-20250514, gemini/gemini-2.0-flash
    # LiteLLM reads OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY from env automatically
    litellm_model: str = "openai/gpt-4o-mini"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Sleep cycle thresholds
    sleep_promotion_threshold: int = 2
    decay_nudge_threshold: float = 0.4
    archive_threshold: float = 0.2

    model_config = {"env_prefix": "CICADA_", "env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
