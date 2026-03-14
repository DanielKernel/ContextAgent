"""Helpers for loading openJiuwen configuration and wiring default startup."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import re
import ssl
import threading
from pathlib import Path
from typing import Any, Coroutine
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from context_agent.adapters.llm_adapter import HttpLLMAdapter
from context_agent.adapters.openjiuwen_db_kv_store import OpenJiuwenDbBasedKVStoreCompat
from context_agent.adapters.ltm_adapter import OpenJiuwenLTMAdapter
from context_agent.api.router import ContextAPIRouter
from context_agent.config.settings import (
    DEFAULT_RUNTIME_CONFIG_DIR,
    Settings,
    get_settings,
)
from context_agent.core.monitoring.runtime_health import RuntimeDependencyHealthChecker
from context_agent.core.memory.async_processor import AsyncMemoryProcessor
from context_agent.core.memory.orchestrator import MemoryOrchestrator
from context_agent.core.memory.working_memory import WorkingMemoryManager
from context_agent.orchestration.context_aggregator import ContextAggregator
from context_agent.utils.errors import ContextAgentError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPENJIUWEN_CONFIG_PATH = DEFAULT_RUNTIME_CONFIG_DIR / "openjiuwen.yaml"
REPOSITORY_OPENJIUWEN_TEMPLATE_PATH = PROJECT_ROOT / "config" / "openjiuwen.yaml"
_PLACEHOLDER_PATTERN = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def _expand_env_placeholders(value: Any) -> Any:
    """Recursively expand ${VAR} placeholders from the environment."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_env_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env_placeholders(item) for key, item in value.items()}
    return value


def _run_async_in_sync(awaitable: Any) -> Any:
    """Run an awaitable from synchronous startup code."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover - defensive thread bridge
            error["value"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "value" in error:
        raise error["value"]
    return result.get("value")


def _instantiate_long_term_memory(long_term_memory_cls: type, config: dict[str, Any]) -> Any:
    """Instantiate openJiuwen LongTermMemory across constructor variants."""
    init_fn = long_term_memory_cls.__init__
    try:
        init_signature = inspect.signature(init_fn)
    except (TypeError, ValueError):
        init_signature = None

    parameter_names = (
        [name for name in init_signature.parameters if name != "self"]
        if init_signature is not None
        else []
    )

    attempts: list[tuple[str, Any]] = []
    supported_kwargs = {
        key: value for key, value in config.items() if key in parameter_names
    }

    if "config" in parameter_names:
        attempts.append(("LongTermMemory(config=config)", lambda: long_term_memory_cls(config=config)))

    if "cfg" in parameter_names:
        attempts.append(("LongTermMemory(cfg=config)", lambda: long_term_memory_cls(cfg=config)))

    if supported_kwargs:
        attempts.append(("LongTermMemory(**config)", lambda: long_term_memory_cls(**supported_kwargs)))

    attempts.append(("LongTermMemory(config)", lambda: long_term_memory_cls(config)))

    for factory_name in ("from_config", "create", "build"):
        factory = getattr(long_term_memory_cls, factory_name, None)
        if callable(factory):
            attempts.append((f"LongTermMemory.{factory_name}(config)", lambda factory=factory: factory(config)))
            if supported_kwargs:
                attempts.append(
                    (f"LongTermMemory.{factory_name}(**config)", lambda factory=factory: factory(**supported_kwargs))
                )

    if not parameter_names:
        attempts.append(("LongTermMemory()", lambda: long_term_memory_cls()))

    errors: list[str] = []
    for label, attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            errors.append(f"{label}: {exc}")
            continue

    raise ContextAgentError(
        "Unsupported openJiuwen LongTermMemory constructor signature. "
        "Please align ContextAgent with the installed openJiuwen version.",
        code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
        details={
            "constructor_parameters": parameter_names,
            "attempts": errors,
        },
    )


def load_openjiuwen_config(config_path: str | Path) -> dict[str, Any]:
    """Load openJiuwen config from a YAML or JSON file."""
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise ContextAgentError(
            f"openJiuwen config file not found: {path}",
            code=ErrorCode.CONFIGURATION_ERROR,
        )

    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        elif suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            raise ContextAgentError(
                f"Unsupported openJiuwen config format: {path.name}",
                code=ErrorCode.CONFIGURATION_ERROR,
            )
    except json.JSONDecodeError as exc:
        raise ContextAgentError(
            f"Invalid JSON in openJiuwen config: {path}",
            code=ErrorCode.CONFIGURATION_ERROR,
            details={"path": str(path)},
        ) from exc
    except yaml.YAMLError as exc:
        raise ContextAgentError(
            f"Invalid YAML in openJiuwen config: {path}",
            code=ErrorCode.CONFIGURATION_ERROR,
            details={"path": str(path)},
        ) from exc

    if not isinstance(data, dict):
        raise ContextAgentError(
            f"openJiuwen config must be a mapping: {path}",
            code=ErrorCode.CONFIGURATION_ERROR,
        )
    return data


def _import_openjiuwen_symbol(module_name: str, symbol_name: str) -> Any:
    module = importlib.import_module(module_name)
    return getattr(module, symbol_name)


def _normalize_provider_name(provider: str) -> str:
    normalized = provider.strip()
    provider_map = {
        "openai": "OpenAI",
        "openrouter": "OpenRouter",
        "siliconflow": "SiliconFlow",
        "dashscope": "DashScope",
    }
    return provider_map.get(normalized.lower(), normalized)


def _is_unresolved_placeholder(value: object) -> bool:
    return isinstance(value, str) and bool(_PLACEHOLDER_PATTERN.search(value))


def _settings_llm_uses_builtin_defaults(settings: Settings) -> bool:
    return (
        settings.llm_base_url == Settings.model_fields["llm_base_url"].default
        and settings.llm_model == Settings.model_fields["llm_model"].default
        and settings.llm_api_key == Settings.model_fields["llm_api_key"].default
    )


def _settings_llm_defers_to_openjiuwen(settings: Settings) -> bool:
    if _settings_llm_uses_builtin_defaults(settings):
        return True
    if not settings.llm_base_url.strip() or not settings.llm_model.strip():
        return True
    if _is_unresolved_placeholder(settings.llm_base_url) or _is_unresolved_placeholder(
        settings.llm_model
    ):
        return True
    return False


def _resolve_effective_llm_config(
    settings: Settings,
    openjiuwen_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if openjiuwen_config is not None and _settings_llm_defers_to_openjiuwen(settings):
        llm_config = openjiuwen_config.get("llm_config", {})
        if isinstance(llm_config, dict) and llm_config:
            base_url = str(llm_config.get("base_url", "")).strip()
            model = str(llm_config.get("model", "")).strip()
            if base_url and model and not _is_unresolved_placeholder(base_url) and not _is_unresolved_placeholder(model):
                return {
                    "base_url": base_url,
                    "model": model,
                    "api_key": llm_config.get("api_key", ""),
                    "timeout": llm_config.get("timeout", settings.llm_timeout_s),
                    "max_retries": llm_config.get("max_retries", settings.llm_max_retries),
                }
        return None

    if not settings.llm_base_url.strip() or not settings.llm_model.strip():
        return None
    if _is_unresolved_placeholder(settings.llm_base_url) or _is_unresolved_placeholder(settings.llm_model):
        return None
    return {
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "api_key": settings.llm_api_key,
        "timeout": settings.llm_timeout_s,
        "max_retries": settings.llm_max_retries,
    }


def _resolve_ssl_cert_path(config: dict[str, Any]) -> tuple[bool, str | None]:
    verify_ssl = bool(config.get("verify_ssl", True))
    ssl_cert = config.get("ssl_cert")
    if not verify_ssl or ssl_cert:
        return verify_ssl, ssl_cert

    try:
        import certifi

        certifi_path = certifi.where()
    except Exception:  # pragma: no cover - depends on runtime environment
        certifi_path = None

    if certifi_path and Path(certifi_path).is_file():
        return True, certifi_path

    default_verify_paths = ssl.get_default_verify_paths()
    default_cafile = default_verify_paths.cafile
    if default_cafile and Path(default_cafile).is_file():
        return True, default_cafile

    logger.warning(
        "No CA bundle found for openJiuwen model client; disabling SSL verification",
    )
    return False, None


def _export_safe_cert_dir(ssl_cert: str | None) -> None:
    if not ssl_cert:
        return
    cert_path = Path(ssl_cert).expanduser().resolve()
    os.environ["SAFE_CERT_DIR"] = str(cert_path.parent)
    os.environ.setdefault("EMBEDDING_SSL_CERT", str(cert_path))
    os.environ.setdefault("EMBEDDING_SSL_VERIFY", "true")


def _build_model_configs(config: dict[str, Any]) -> tuple[Any | None, Any | None]:
    llm_config = config.get("llm_config", {})
    if not isinstance(llm_config, dict) or not llm_config:
        return None, None

    ModelRequestConfig = _import_openjiuwen_symbol(
        "openjiuwen.core.foundation.llm.schema.config",
        "ModelRequestConfig",
    )
    ModelClientConfig = _import_openjiuwen_symbol(
        "openjiuwen.core.foundation.llm.schema.config",
        "ModelClientConfig",
    )

    request_config = ModelRequestConfig(
        model=llm_config.get("model", ""),
        temperature=llm_config.get("temperature", 0.2),
        top_p=llm_config.get("top_p", 0.7),
        max_tokens=llm_config.get("max_tokens"),
    )
    verify_ssl, ssl_cert = _resolve_ssl_cert_path(llm_config)
    _export_safe_cert_dir(ssl_cert)
    client_config = ModelClientConfig(
        client_provider=_normalize_provider_name(llm_config.get("provider", "openai")),
        api_key=llm_config.get("api_key", ""),
        api_base=llm_config.get("base_url", ""),
        timeout=llm_config.get("timeout", 30),
        max_retries=llm_config.get("max_retries", 2),
        verify_ssl=verify_ssl,
        ssl_cert=ssl_cert,
    )
    return request_config, client_config


def _build_embedding_model(config: dict[str, Any]) -> Any | None:
    embedding_config = config.get("embedding_config", {})
    if not isinstance(embedding_config, dict) or not embedding_config:
        return None

    EmbeddingConfig = _import_openjiuwen_symbol(
        "openjiuwen.core.foundation.store.base_embedding",
        "EmbeddingConfig",
    )
    embed_config = EmbeddingConfig(
        model_name=embedding_config.get("model", ""),
        base_url=embedding_config.get("base_url", ""),
        api_key=embedding_config.get("api_key"),
    )
    provider = str(embedding_config.get("provider", "openai")).strip().lower()
    embedding_timeout = embedding_config.get("timeout", 60)
    embedding_retries = embedding_config.get("max_retries", 3)
    embedding_batch_size = embedding_config.get("batch_size", 8)
    verify_ssl, ssl_cert = _resolve_ssl_cert_path(embedding_config)
    _export_safe_cert_dir(ssl_cert)
    if verify_ssl:
        os.environ["EMBEDDING_SSL_VERIFY"] = "true"
    else:
        os.environ["EMBEDDING_SSL_VERIFY"] = "false"
    if provider in {"openai", "openrouter", "dashscope", "siliconflow"}:
        OpenAIEmbedding = _import_openjiuwen_symbol(
            "openjiuwen.core.retrieval.embedding.openai_embedding",
            "OpenAIEmbedding",
        )
        return OpenAIEmbedding(
            config=embed_config,
            timeout=embedding_timeout,
            max_retries=embedding_retries,
            max_batch_size=embedding_batch_size,
            dimension=embedding_config.get("dimension"),
            verify=ssl_cert if ssl_cert else verify_ssl,
        )

    APIEmbedding = _import_openjiuwen_symbol(
        "openjiuwen.core.retrieval.embedding.api_embedding",
        "APIEmbedding",
    )
    return APIEmbedding(
        config=embed_config,
        timeout=embedding_timeout,
        max_retries=embedding_retries,
        max_batch_size=embedding_batch_size,
    )


def _build_memory_engine_config(config: dict[str, Any]) -> Any:
    MemoryEngineConfig = _import_openjiuwen_symbol(
        "openjiuwen.core.memory.config.config",
        "MemoryEngineConfig",
    )
    request_config, client_config = _build_model_configs(config)
    return MemoryEngineConfig(
        default_model_cfg=request_config,
        default_model_client_cfg=client_config,
    )


def _build_memory_scope_config(config: dict[str, Any]) -> Any:
    MemoryScopeConfig = _import_openjiuwen_symbol(
        "openjiuwen.core.memory.config.config",
        "MemoryScopeConfig",
    )
    EmbeddingConfig = _import_openjiuwen_symbol(
        "openjiuwen.core.retrieval.common.config",
        "EmbeddingConfig",
    )
    request_config, client_config = _build_model_configs(config)
    embedding_config = config.get("embedding_config", {})
    scope_embedding_config = None
    if isinstance(embedding_config, dict) and embedding_config:
        scope_embedding_config = EmbeddingConfig(
            model_name=embedding_config.get("model", ""),
            base_url=embedding_config.get("base_url", ""),
            api_key=embedding_config.get("api_key", ""),
        )
    return MemoryScopeConfig(
        model_cfg=request_config,
        model_client_cfg=client_config,
        embedding_cfg=scope_embedding_config,
    )


def _normalize_async_dsn(dsn: str) -> str:
    def _rewrite_postgres_url(raw_dsn: str) -> str:
        parts = urlsplit(raw_dsn)
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        rewritten_query: list[tuple[str, str]] = []
        for key, value in query_pairs:
            if key != "sslmode":
                rewritten_query.append((key, value))
                continue

            normalized_value = value.strip().lower()
            if normalized_value == "disable":
                rewritten_query.append(("ssl", "false"))
            elif normalized_value in {"require", "verify-ca", "verify-full"}:
                rewritten_query.append(("ssl", "true"))
            # `allow` / `prefer` are libpq-specific best-effort modes. asyncpg
            # has no equivalent, so we drop them and let the driver defaults apply.

        return urlunsplit(
            (
                "postgresql+asyncpg",
                parts.netloc,
                parts.path,
                urlencode(rewritten_query),
                parts.fragment,
            )
        )

    if dsn.startswith("postgresql+asyncpg://"):
        return _rewrite_postgres_url(dsn)
    if dsn.startswith("postgresql+"):
        return dsn
    if dsn.startswith("postgresql://"):
        return _rewrite_postgres_url(dsn)
    if dsn.startswith("postgres://"):
        return _rewrite_postgres_url(dsn.replace("postgres://", "postgresql://", 1))
    if dsn.startswith("sqlite:///"):
        return dsn.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return dsn


def _build_db_store(vector_store_config: dict[str, Any]) -> tuple[Any, Any]:
    from sqlalchemy.ext.asyncio import create_async_engine

    DefaultDbStore = _import_openjiuwen_symbol(
        "openjiuwen.core.foundation.store.db.default_db_store",
        "DefaultDbStore",
    )

    dsn = vector_store_config.get("dsn")
    if not dsn:
        raise ContextAgentError(
            "openJiuwen vector_store.dsn is required.",
            code=ErrorCode.CONFIGURATION_ERROR,
        )
    normalized_dsn = _normalize_async_dsn(dsn)
    try:
        engine = create_async_engine(normalized_dsn, pool_pre_ping=True, echo=False)
    except ModuleNotFoundError as exc:
        if exc.name == "asyncpg" and normalized_dsn.startswith("postgresql+asyncpg://"):
            raise ContextAgentError(
                "PostgreSQL async driver 'asyncpg' is required for openJiuwen pgvector startup. "
                "Reinstall ContextAgent with the openjiuwen extra.",
                code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
                details={"dsn": normalized_dsn, "missing_dependency": "asyncpg"},
            ) from exc
        raise
    return engine, DefaultDbStore(engine)


def _build_kv_store(db_engine: Any) -> Any:
    return OpenJiuwenDbBasedKVStoreCompat(db_engine)


def _build_in_memory_kv_store() -> Any:
    InMemoryKVStore = _import_openjiuwen_symbol(
        "openjiuwen.core.foundation.store.kv.in_memory_kv_store",
        "InMemoryKVStore",
    )
    return InMemoryKVStore()


def _instantiate_vector_store(backend: str, vector_store_config: dict[str, Any]) -> Any:
    store_module = importlib.import_module("openjiuwen.core.foundation.store")
    create_vector_store = getattr(store_module, "create_vector_store", None)

    kwargs = {
        "collection_name": vector_store_config.get("table_name", "ltm_memory"),
        "distance_metric": vector_store_config.get("distance", "cosine"),
        "database_url": vector_store_config.get("dsn"),
        "dsn": vector_store_config.get("dsn"),
        "embedding_dimension": vector_store_config.get("embedding_dimension"),
        "dimension": vector_store_config.get("embedding_dimension"),
        "schema_name": vector_store_config.get("schema", "public"),
        "schema": vector_store_config.get("schema", "public"),
        "index_type": vector_store_config.get("index_type"),
        "lists": vector_store_config.get("lists"),
    }
    kwargs = {key: value for key, value in kwargs.items() if value is not None}

    def _instantiate_with_supported_kwargs(store_cls: Any) -> Any:
        if backend == "pgvector":
            from context_agent.adapters.openjiuwen_pgvector_store import OpenJiuwenPGVectorStoreBridge

            return OpenJiuwenPGVectorStoreBridge(
                {
                    **vector_store_config,
                    "dsn": _normalize_async_dsn(vector_store_config.get("dsn", "")),
                }
            )
        try:
            signature = inspect.signature(store_cls)
        except (TypeError, ValueError):
            return store_cls(**kwargs)
        if any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ):
            return store_cls(**kwargs)
        filtered_kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
        return store_cls(**filtered_kwargs)

    if callable(create_vector_store):
        try:
            vector_store = create_vector_store(backend, **kwargs)
        except TypeError:
            vector_store = None
        if vector_store is not None:
            return vector_store

    class_candidates = {
        "pgvector": [
            ("openjiuwen.core.retrieval.vector_store.pg_store", "PGVectorStore"),
            ("openjiuwen.core.foundation.store.vector.pgvector_vector_store", "PGVectorStore"),
            ("openjiuwen.core.foundation.store.vector.pgvector_store", "PGVectorStore"),
            ("openjiuwen.core.foundation.store.vector.pg_vector_store", "PGVectorStore"),
            ("openjiuwen.core.foundation.store.vector.pgvector_vector_store", "PgVectorStore"),
        ],
        "chroma": [
            ("openjiuwen.core.foundation.store.vector.chroma_vector_store", "ChromaVectorStore"),
        ],
        "milvus": [
            ("openjiuwen.core.foundation.store.vector.milvus_vector_store", "MilvusVectorStore"),
        ],
    }

    errors: list[str] = []
    for module_name, class_name in class_candidates.get(backend, []):
        try:
            store_cls = _import_openjiuwen_symbol(module_name, class_name)
        except ModuleNotFoundError as exc:
            if backend == "pgvector" and exc.name == "pgvector":
                raise ContextAgentError(
                    "Python package 'pgvector' is required for openJiuwen pgvector startup. "
                    "Reinstall ContextAgent with the openjiuwen extra.",
                    code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
                    details={
                        "backend": backend,
                        "missing_dependency": "pgvector",
                        "module": module_name,
                    },
                ) from exc
            errors.append(f"{module_name}.{class_name}: {exc}")
            continue
        except (ImportError, AttributeError) as exc:
            errors.append(f"{module_name}.{class_name}: {exc}")
            continue
        try:
            return _instantiate_with_supported_kwargs(store_cls)
        except TypeError as exc:
            errors.append(f"{module_name}.{class_name}: {exc}")

    raise ContextAgentError(
        f"Unsupported openJiuwen vector store backend: {backend}",
        code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
        details={"backend": backend, "attempts": errors},
    )


def _has_cleanup_method(resource: Any) -> bool:
    return any(callable(getattr(resource, name, None)) for name in ("close", "aclose", "dispose"))


async def _bootstrap_long_term_memory(
    ltm: Any, config: dict[str, Any]
) -> tuple[Any, tuple[Any, ...]]:
    vector_store_config = config.get("vector_store", {})
    if not isinstance(vector_store_config, dict):
        raise ContextAgentError(
            "openJiuwen vector_store config must be a mapping.",
            code=ErrorCode.CONFIGURATION_ERROR,
        )

    backend = str(vector_store_config.get("backend", "pgvector")).strip().lower()
    db_store = None
    cleanup_resources: list[Any] = []
    if backend == "pgvector":
        db_engine, db_store = _build_db_store(vector_store_config)
        kv_store = _build_kv_store(db_engine)
        if _has_cleanup_method(db_engine):
            cleanup_resources.append(db_engine)
    else:
        kv_store = _build_in_memory_kv_store()
    vector_store = _instantiate_vector_store(backend, vector_store_config)
    if _has_cleanup_method(vector_store):
        cleanup_resources.append(vector_store)
    embedding_model = _build_embedding_model(config)
    await ltm.register_store(
        kv_store=kv_store,
        vector_store=vector_store,
        db_store=db_store,
        embedding_model=embedding_model,
    )
    ltm.set_config(_build_memory_engine_config(config))
    await ltm.set_scope_config(
        config.get("user_id", "context-agent"),
        _build_memory_scope_config(config),
    )
    return ltm, tuple(cleanup_resources)


def resolve_openjiuwen_config_path(explicit_path: str | Path | None = None) -> Path | None:
    """Resolve the openJiuwen config path from explicit value, env, runtime default, or repo fallback."""
    candidate_path = explicit_path or os.getenv("CA_OPENJIUWEN_CONFIG_PATH")
    if candidate_path:
        candidate = Path(candidate_path).expanduser()
        return candidate if candidate.is_absolute() else (Path.cwd() / candidate).resolve()

    for candidate in (
        DEFAULT_OPENJIUWEN_CONFIG_PATH,
        REPOSITORY_OPENJIUWEN_TEMPLATE_PATH,
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


async def build_openjiuwen_ltm_adapter_async(config_path: str | Path) -> OpenJiuwenLTMAdapter:
    """Build an OpenJiuwenLTMAdapter from an openJiuwen config file."""
    config = _expand_env_placeholders(load_openjiuwen_config(config_path))
    try:
        from openjiuwen.core.memory.long_term_memory import LongTermMemory
    except ImportError as exc:
        raise ContextAgentError(
            "openJiuwen is required when CA_OPENJIUWEN_CONFIG_PATH is set. "
            "Install the project with the openjiuwen extra or add openjiuwen to the environment.",
            code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
        ) from exc

    vector_store = config.get("vector_store", {})
    vector_backend = (
        vector_store.get("backend", "unknown")
        if isinstance(vector_store, dict)
        else "unknown"
    )
    logger.info(
        "loading openJiuwen long-term memory",
        config_path=str(Path(config_path).expanduser().resolve()),
        vector_backend=vector_backend,
    )
    try:
        ltm = _instantiate_long_term_memory(LongTermMemory, config)
        cleanup_resources: tuple[Any, ...] = ()
        if hasattr(ltm, "register_store") and hasattr(ltm, "set_scope_config"):
            ltm, cleanup_resources = await _bootstrap_long_term_memory(ltm, config)
    except TypeError as exc:
        raise ContextAgentError(
            "Failed to initialize openJiuwen LongTermMemory with the installed "
            "constructor signature.",
            code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
            details={"reason": str(exc)},
        ) from exc
    except ContextAgentError:
        raise
    except Exception as exc:
        raise ContextAgentError(
            "Failed to bootstrap openJiuwen LongTermMemory stores.",
            code=ErrorCode.OPENJIUWEN_UNAVAILABLE,
            details={
                "reason": str(exc),
                "vector_backend": vector_backend,
            },
        ) from exc
    return OpenJiuwenLTMAdapter(
        ltm=ltm,
        memory_config=config.get("memory_config"),
        cleanup_resources=cleanup_resources,
    )


def build_openjiuwen_ltm_adapter(config_path: str | Path) -> OpenJiuwenLTMAdapter:
    """Build an OpenJiuwenLTMAdapter from an openJiuwen config file."""
    from typing import cast
    return cast(OpenJiuwenLTMAdapter, _run_async_in_sync(build_openjiuwen_ltm_adapter_async(config_path)))


async def build_default_api_router_async(settings: Settings | None = None) -> ContextAPIRouter:
    """Build the default API router, wiring openJiuwen LTM when configured."""
    runtime_settings = settings or get_settings()
    aggregator_kwargs: dict[str, Any] = {}
    router_kwargs: dict[str, Any] = {}
    llm_adapter: HttpLLMAdapter | None = None
    openjiuwen_config: dict[str, Any] | None = None
    working_memory = WorkingMemoryManager()
    aggregator_kwargs["working_memory"] = working_memory
    router_kwargs["working_memory"] = working_memory

    resolved_openjiuwen_config = resolve_openjiuwen_config_path(
        runtime_settings.openjiuwen_config_path
    )

    if resolved_openjiuwen_config is not None:
        openjiuwen_config = _expand_env_placeholders(
            load_openjiuwen_config(resolved_openjiuwen_config)
        )
        try:
            ltm_adapter = await build_openjiuwen_ltm_adapter_async(
                resolved_openjiuwen_config
            )
        except ContextAgentError as exc:
            if exc.code != ErrorCode.OPENJIUWEN_UNAVAILABLE:
                raise
            logger.warning(
                "openJiuwen long-term memory unavailable, starting with working memory only",
                config_path=str(resolved_openjiuwen_config),
                error=str(exc),
                details=exc.details,
            )
        else:
            memory_processor = AsyncMemoryProcessor(ltm=ltm_adapter)
            router_kwargs["memory_processor"] = memory_processor
            router_kwargs["memory_orchestrator"] = MemoryOrchestrator(
                working_memory=working_memory,
                async_processor=memory_processor,
            )
            aggregator_kwargs["ltm"] = ltm_adapter
            logger.info(
                "openJiuwen long-term memory enabled",
                config_path=str(resolved_openjiuwen_config),
            )
    else:
        logger.info(
            "starting without openJiuwen long-term memory",
            reason="No openJiuwen config file was found",
        )

    llm_adapter = build_default_llm_adapter(runtime_settings, openjiuwen_config)
    if llm_adapter is not None:
        router_kwargs["llm_adapter"] = llm_adapter
    router_kwargs["runtime_health_checker"] = RuntimeDependencyHealthChecker(
        settings=runtime_settings,
        openjiuwen_config_path=resolved_openjiuwen_config,
        openjiuwen_config=openjiuwen_config,
        llm_adapter=llm_adapter,
    )

    return ContextAPIRouter(
        aggregator=ContextAggregator(**aggregator_kwargs),
        **router_kwargs,
    )


def build_default_api_router(settings: Settings | None = None) -> ContextAPIRouter:
    """Build the default API router, wiring openJiuwen LTM when configured."""
    from typing import cast
    return cast(ContextAPIRouter, _run_async_in_sync(build_default_api_router_async(settings)))


def build_default_llm_adapter(
    settings: Settings | None = None,
    openjiuwen_config: dict[str, Any] | None = None,
) -> HttpLLMAdapter | None:
    """Build the default HTTP LLM adapter for compression/summarization."""
    runtime_settings = settings or get_settings()
    effective_llm_config = _resolve_effective_llm_config(runtime_settings, openjiuwen_config)
    if effective_llm_config is None:
        logger.info(
            "starting without default llm adapter",
            reason="LLM config is empty, unresolved, or intentionally deferred to openJiuwen",
        )
        return None

    return HttpLLMAdapter(
        base_url=effective_llm_config["base_url"],
        model=effective_llm_config["model"],
        timeout_s=effective_llm_config["timeout"],
        max_retries=effective_llm_config["max_retries"],
        api_key=effective_llm_config["api_key"],
    )
