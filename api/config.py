from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Memory storage
    memory_path: Path = Path.home() / "cicada" / "memory"

    # LiteLLM configuration
    litellm_model: str = "gpt-4o-mini"
    litellm_api_key: str = ""
    litellm_api_base: str | None = None

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Sleep cycle thresholds
    sleep_promotion_threshold: int = 2
    decay_nudge_threshold: float = 0.4
    archive_threshold: float = 0.2

    model_config = {"env_prefix": "CICADA_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
