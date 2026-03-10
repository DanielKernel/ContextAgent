"""Application configuration via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Service ─────────────────────────────────────────────────────────────
    service_name: str = "context-agent"
    environment: str = "development"  # development | staging | production
    log_level: str = "INFO"
    debug: bool = False

    # ── HTTP server ──────────────────────────────────────────────────────────
    http_host: str = "0.0.0.0"
    http_port: int = 8080

    # ── Redis (hot tier) ────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_pool_max_connections: int = 50

    # ── Vector DB ────────────────────────────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_collection: str = "context_agent"
    # Milvus (production override)
    milvus_uri: str = ""

    # ── Object storage (version snapshots) ──────────────────────────────────
    s3_endpoint_url: str = ""
    s3_bucket: str = "context-agent-versions"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # ── LLM service (compression / summarization) ───────────────────────────
    llm_base_url: str = "http://localhost:11434"  # Ollama default
    llm_model: str = "qwen2.5:7b"
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 2

    # ── openJiuwen ───────────────────────────────────────────────────────────
    openjiuwen_config_path: str = ""  # path to openjiuwen config file

    # ── Latency budgets (ms) ─────────────────────────────────────────────────
    hot_tier_timeout_ms: float = Field(default=20.0, ge=1.0, le=200.0)
    warm_tier_timeout_ms: float = Field(default=100.0, ge=10.0, le=500.0)
    cold_tier_timeout_ms: float = Field(default=300.0, ge=50.0, le=2000.0)
    aggregation_timeout_ms: float = Field(default=200.0, ge=50.0, le=1000.0)

    # ── Token budgets ─────────────────────────────────────────────────────────
    default_token_budget: int = Field(default=4096, ge=512, le=131072)
    tool_result_token_limit: int = Field(default=1024, ge=128, le=8192)

    # ── Async memory processing ───────────────────────────────────────────────
    memory_queue_maxsize: int = 1000
    memory_worker_count: int = 2

    # ── Observability ─────────────────────────────────────────────────────────
    otlp_endpoint: str = ""  # empty = no OTLP export
    prometheus_enabled: bool = True
    metrics_prefix: str = "context_agent"

    # ── Auth (minimal) ────────────────────────────────────────────────────────
    auth_enabled: bool = False
    auth_secret_key: str = ""
    api_keys: list[str] = Field(default_factory=list)  # Bearer tokens allowed

    @property
    def AUTH_ENABLED(self) -> bool:
        return self.auth_enabled

    @property
    def API_KEYS(self) -> list[str]:
        return self.api_keys

    @property
    def LOG_LEVEL(self) -> str:
        return self.log_level


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
