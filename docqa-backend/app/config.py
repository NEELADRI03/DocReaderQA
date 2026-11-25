from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode


class Settings(BaseSettings):
    """Typed config. Each field reads the env var of the same name (case-insensitive)."""

    app_env: Literal["development", "production"] = "development"

    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    # Which implementation create_llm_client() and create_embedder() build
    llm_provider: Literal["ollama"] = "ollama"
    embedding_provider: Literal["ollama"] = "ollama"

    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen3:8b"
    # "none" turns qwen3's thinking off; thinking tokens are slow on a CPU and never shown
    llm_reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
    # Seconds to wait for the next streamed token; a 6k-token prompt on a CPU takes minutes
    llm_timeout_seconds: float = 300.0

    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768
    # nomic-embed-text expects these task prefixes; set both to "" for models without them
    embedding_document_prefix: str = "search_document: "
    embedding_query_prefix: str = "search_query: "

    # jwt_secret: SecretStr
    jwt_secret: Annotated[SecretStr, Field(min_length=32)]
    access_token_minutes: int = 30
    refresh_token_days: int = 7

    storage_dir: Path = Path("/data/storage")
    max_upload_mb: int = 50
    max_pages: int = 500

    # NoDecode: take the raw string instead of parsing it as JSON, then split it below
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_commas(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    # Cached, so the environment is read once per process
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
