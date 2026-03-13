"""Application configuration via pydantic-settings."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from context_agent.config.defaults import (
    COMPACTION_TRIGGER_RATIO,
    DEFAULT_TOP_K,
    HOT_TIER_TTL_S,
    HYBRID_SPARSE_WEIGHT,
    HYBRID_VECTOR_WEIGHT,
    JIT_LOCAL_CACHE_MAX_ENTRIES,
    JIT_RESULT_CACHE_TTL_S,
    MAX_NOTES_PER_SESSION,
    RERANK_TOP_K,
    TOOL_RAG_THRESHOLD,
    TOOL_TOP_K,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_CONFIG_DIR = PROJECT_ROOT / ".local" / "config"
DEFAULT_CONTEXT_AGENT_CONFIG_PATH = DEFAULT_RUNTIME_CONFIG_DIR / "context_agent.yaml"
REPOSITORY_CONTEXT_AGENT_TEMPLATE_PATH = PROJECT_ROOT / "config" / "context_agent.yaml"

_SECTION_FIELD_MAP: dict[tuple[str, ...], str] = {
    ("service", "name"): "service_name",
    ("service", "environment"): "environment",
    ("service", "log_level"): "log_level",
    ("service", "debug"): "debug",
    ("http", "host"): "http_host",
    ("http", "port"): "http_port",
    ("redis", "url"): "redis_url",
    ("redis", "pool_max_connections"): "redis_pool_max_connections",
    ("storage", "s3", "endpoint_url"): "s3_endpoint_url",
    ("storage", "s3", "bucket"): "s3_bucket",
    ("storage", "s3", "access_key"): "s3_access_key",
    ("storage", "s3", "secret_key"): "s3_secret_key",
    ("llm", "base_url"): "llm_base_url",
    ("llm", "model"): "llm_model",
    ("llm", "api_key"): "llm_api_key",
    ("llm", "timeout_s"): "llm_timeout_s",
    ("llm", "max_retries"): "llm_max_retries",
    ("compression", "llm", "base_url"): "llm_base_url",
    ("compression", "llm", "model"): "llm_model",
    ("compression", "llm", "api_key"): "llm_api_key",
    ("compression", "llm", "timeout_s"): "llm_timeout_s",
    ("compression", "llm", "max_retries"): "llm_max_retries",
    ("compression", "compaction_trigger_ratio"): "compaction_trigger_ratio",
    ("integrations", "openjiuwen", "config_path"): "openjiuwen_config_path",
    ("budgets", "latency", "hot_tier_timeout_ms"): "hot_tier_timeout_ms",
    ("budgets", "latency", "warm_tier_timeout_ms"): "warm_tier_timeout_ms",
    ("budgets", "latency", "cold_tier_timeout_ms"): "cold_tier_timeout_ms",
    ("budgets", "latency", "aggregation_timeout_ms"): "aggregation_timeout_ms",
    ("budgets", "tokens", "default_token_budget"): "default_token_budget",
    ("budgets", "tokens", "tool_result_token_limit"): "tool_result_token_limit",
    ("memory", "queue_maxsize"): "memory_queue_maxsize",
    ("memory", "worker_count"): "memory_worker_count",
    ("memory", "hot_tier_ttl_s"): "hot_tier_ttl_s",
    ("memory", "max_notes_per_session"): "max_notes_per_session",
    ("retrieval", "default_top_k"): "retrieval_default_top_k",
    ("retrieval", "timeout_ms"): "retrieval_timeout_ms",
    ("retrieval", "rerank_top_k"): "retrieval_rerank_top_k",
    ("retrieval", "hybrid", "vector_weight"): "retrieval_vector_weight",
    ("retrieval", "hybrid", "sparse_weight"): "retrieval_sparse_weight",
    ("retrieval", "hybrid", "rrf_k"): "retrieval_rrf_k",
    ("retrieval", "jit_cache", "ttl_s"): "jit_cache_ttl_s",
    ("retrieval", "jit_cache", "local_max_entries"): "jit_cache_local_max_entries",
    ("retrieval", "hotness", "alpha"): "retrieval_hotness_alpha",
    ("retrieval", "hotness", "half_life_days"): "retrieval_hotness_half_life_days",
    ("retrieval", "tool_selection", "rag_threshold"): "tool_rag_threshold",
    ("retrieval", "tool_selection", "top_k"): "tool_top_k",
    ("context_health", "thresholds", "poisoning"): "context_health_poisoning_threshold",
    ("context_health", "thresholds", "distraction"): "context_health_distraction_threshold",
    ("context_health", "thresholds", "confusion"): "context_health_confusion_threshold",
    ("context_health", "thresholds", "clash"): "context_health_clash_threshold",
    ("observability", "otlp_endpoint"): "otlp_endpoint",
    ("observability", "prometheus_enabled"): "prometheus_enabled",
    ("observability", "metrics_prefix"): "metrics_prefix",
    ("auth", "enabled"): "auth_enabled",
    ("auth", "secret_key"): "auth_secret_key",
    ("auth", "api_keys"): "api_keys",
}


def resolve_context_agent_config_path(explicit_path: str | None = None) -> Path | None:
    """Resolve the ContextAgent config file path.

    Priority:
    1. Explicit function argument
    2. `CA_CONTEXT_AGENT_CONFIG_PATH`
    3. `CA_SETTINGS_PATH` (compatibility alias)
    4. Runtime default `.local/config/context_agent.yaml`
    5. Repository template fallback `config/context_agent.yaml`
    """

    raw_path = (
        explicit_path
        or os.getenv("CA_CONTEXT_AGENT_CONFIG_PATH")
        or os.getenv("CA_SETTINGS_PATH")
    )
    if raw_path:
        candidate = Path(raw_path).expanduser()
        return candidate if candidate.is_absolute() else (Path.cwd() / candidate).resolve()

    for candidate in (
        DEFAULT_CONTEXT_AGENT_CONFIG_PATH,
        REPOSITORY_CONTEXT_AGENT_TEMPLATE_PATH,
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _flatten_context_agent_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten segmented context_agent.yaml content into Settings field names."""
    flattened: dict[str, Any] = {}
    for path, target_field in _SECTION_FIELD_MAP.items():
        current: Any = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if current is not None:
            flattened[target_field] = current

    for key, value in data.items():
        if key in Settings.model_fields:
            flattened.setdefault(key, value)

    return flattened


class ContextAgentYamlSettingsSource(PydanticBaseSettingsSource):
    """Load ContextAgent settings from a YAML or JSON file."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        self._data = self._load_data()

    def _load_data(self) -> dict[str, Any]:
        config_path = resolve_context_agent_config_path()
        if config_path is None:
            return {}
        if not config_path.is_file():
            raise FileNotFoundError(f"ContextAgent config file not found: {config_path}")

        suffix = config_path.suffix.lower()
        raw_text = config_path.read_text(encoding="utf-8")
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(raw_text) or {}
        elif suffix == ".json":
            data = json.loads(raw_text)
        else:
            raise ValueError(f"Unsupported ContextAgent config format: {config_path.name}")

        if not isinstance(data, dict):
            raise ValueError(f"ContextAgent config must be a mapping: {config_path}")

        flattened = _flatten_context_agent_mapping(data)

        openjiuwen_path = flattened.get("openjiuwen_config_path")
        if isinstance(openjiuwen_path, str) and openjiuwen_path.strip():
            candidate = Path(openjiuwen_path).expanduser()
            if not candidate.is_absolute():
                candidate = (config_path.parent / candidate).resolve()
            flattened["openjiuwen_config_path"] = str(candidate)

        flattened.setdefault("context_agent_config_path", str(config_path))
        return flattened

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        value = self._data.get(field_name)
        return value, field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._data)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Config source ─────────────────────────────────────────────────────────
    context_agent_config_path: str = ""

    # ── Service ───────────────────────────────────────────────────────────────
    service_name: str = "context-agent"
    environment: str = "development"  # development | staging | production
    log_level: str = "INFO"
    debug: bool = False

    # ── HTTP server ───────────────────────────────────────────────────────────
    http_host: str = "0.0.0.0"
    http_port: int = 8080

    # ── Redis (hot tier) ─────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_pool_max_connections: int = 50

    # ── Object storage (version snapshots) ───────────────────────────────────
    s3_endpoint_url: str = ""
    s3_bucket: str = "context-agent-versions"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # ── LLM service (compression / summarization) ────────────────────────────
    llm_base_url: str = "http://localhost:11434"  # Ollama default
    llm_model: str = "qwen2.5:7b"
    llm_api_key: str = ""
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 2
    compaction_trigger_ratio: float = Field(default=COMPACTION_TRIGGER_RATIO, gt=0.0, lt=1.0)

    # ── openJiuwen ────────────────────────────────────────────────────────────
    openjiuwen_config_path: str = ""

    # ── Latency budgets (ms) ──────────────────────────────────────────────────
    hot_tier_timeout_ms: float = Field(default=20.0, ge=1.0, le=200.0)
    warm_tier_timeout_ms: float = Field(default=100.0, ge=10.0, le=500.0)
    cold_tier_timeout_ms: float = Field(default=300.0, ge=50.0, le=2000.0)
    aggregation_timeout_ms: float = Field(default=200.0, ge=50.0, le=1000.0)

    # ── Token budgets ──────────────────────────────────────────────────────────
    default_token_budget: int = Field(default=4096, ge=512, le=131072)
    tool_result_token_limit: int = Field(default=1024, ge=128, le=8192)

    # ── Async memory processing ────────────────────────────────────────────────
    memory_queue_maxsize: int = 1000
    memory_worker_count: int = 2
    hot_tier_ttl_s: int = Field(default=HOT_TIER_TTL_S, ge=1, le=86400)
    max_notes_per_session: int = Field(default=MAX_NOTES_PER_SESSION, ge=1, le=10000)

    # ── Retrieval tuning ───────────────────────────────────────────────────────
    retrieval_default_top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=100)
    retrieval_timeout_ms: float = Field(default=250.0, ge=10.0, le=5000.0)
    retrieval_rerank_top_k: int = Field(default=RERANK_TOP_K, ge=1, le=200)
    retrieval_vector_weight: float = Field(default=HYBRID_VECTOR_WEIGHT, ge=0.0, le=1.0)
    retrieval_sparse_weight: float = Field(default=HYBRID_SPARSE_WEIGHT, ge=0.0, le=1.0)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    jit_cache_ttl_s: int = Field(default=JIT_RESULT_CACHE_TTL_S, ge=1, le=86400)
    jit_cache_local_max_entries: int = Field(
        default=JIT_LOCAL_CACHE_MAX_ENTRIES,
        ge=1,
        le=100000,
    )
    retrieval_hotness_alpha: float = Field(default=0.2, ge=0.0, le=1.0)
    retrieval_hotness_half_life_days: float = Field(default=7.0, gt=0.0, le=365.0)
    tool_rag_threshold: int = Field(default=TOOL_RAG_THRESHOLD, ge=1, le=1000)
    tool_top_k: int = Field(default=TOOL_TOP_K, ge=1, le=100)

    # ── Context health thresholds ──────────────────────────────────────────────
    context_health_poisoning_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    context_health_distraction_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    context_health_confusion_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    context_health_clash_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

    # ── Observability ──────────────────────────────────────────────────────────
    otlp_endpoint: str = ""
    prometheus_enabled: bool = True
    metrics_prefix: str = "context_agent"

    # ── Auth (minimal) ─────────────────────────────────────────────────────────
    auth_enabled: bool = False
    auth_secret_key: str = ""
    api_keys: list[str] = Field(default_factory=list)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            ContextAgentYamlSettingsSource(settings_cls),
            file_secret_settings,
        )

    @property
    def AUTH_ENABLED(self) -> bool:  # noqa: N802
        return self.auth_enabled

    @property
    def API_KEYS(self) -> list[str]:  # noqa: N802
        return self.api_keys

    @property
    def LOG_LEVEL(self) -> str:  # noqa: N802
        return self.log_level


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
