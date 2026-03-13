# Copilot Instructions for ContextAgent

## Build, test, and lint commands

The repository is centered on the Python 3 virtualenv at `.venv` rather than `uv`.

```bash
make install
```

Installs the project with `.[dev,openjiuwen]` into `.venv`.

```bash
make run-dev
```

Starts the FastAPI app with `uvicorn context_agent.api.http_handler:app --reload --host 0.0.0.0 --port 8080`.

```bash
make lint
make type-check
make test
make test-int
make test-perf
make test-all
```

`make test` runs the unit suite only. `make test-int` and `make test-perf` are split out with pytest markers.

For targeted pytest runs, prefer the virtualenv interpreter directly:

```bash
.venv/bin/python3 -m pytest tests/unit/test_aggregator.py
.venv/bin/python3 -m pytest tests/integration/test_e2e_pipeline.py
.venv/bin/python3 -m pytest tests/unit/test_settings_config.py::test_build_default_api_router_without_openjiuwen_config
```

If the virtualenv is already activated, the docs also use:

```bash
python3 -m pytest
python3 -m pytest tests/unit
```

## High-level architecture

ContextAgent is a FastAPI service that exposes a single context-management pipeline. The module-level ASGI app in `context_agent/api/http_handler.py` calls `build_default_api_router()` from `context_agent/config/openjiuwen.py`, so startup wiring matters as much as the request handlers.

The default runtime always creates `WorkingMemoryManager` first. If `.local/config/context_agent.yaml` resolves an `integrations.openjiuwen.config_path` (or `CA_OPENJIUWEN_CONFIG_PATH`) and openJiuwen can be initialized, startup adds:

- `OpenJiuwenLTMAdapter` as the long-term memory port
- `AsyncMemoryProcessor` for queued long-term writes
- `MemoryOrchestrator` to write to working memory immediately and enqueue long-term persistence

If openJiuwen is unavailable, the service still starts in working-memory-only mode rather than failing the whole app.

The request path is:

1. `http_handler.py` accepts `/context` and delegates to `ContextAPIRouter`.
2. `ContextAPIRouter.handle()` builds an `AggregationRequest` and calls `ContextAggregator`.
3. `ContextAggregator` gathers long-term memory, working memory, and JIT refs concurrently, then deduplicates, sorts by score, and trims to the token budget.
4. `ContextAPIRouter` optionally applies `ExposureController` and `ContextHealthChecker`.
5. Non-raw outputs go through `CompressionStrategyRouter`, which uses `HybridStrategyScheduler` plus the strategy registry. If all compression strategies fail, it degrades to raw concatenation instead of raising.

Retrieval is split across two layers:

- `ContextAggregator` is the main assembly path for `/context`.
- `TieredMemoryRouter` and `UnifiedSearchCoordinator` implement tiered/hybrid retrieval primitives for hot/warm/cold search and RRF-based fusion.

## Key conventions

### Configuration is split across two YAML files

`context_agent/config/settings.py` flattens segmented runtime config sections from `.local/config/context_agent.yaml` into `Settings`, falling back to repository `config/context_agent.yaml` only as a template. That file then points to `.local/config/openjiuwen.yaml` (or an explicit override) for vector-store and openJiuwen memory configuration. Do not bypass this by wiring vector DB settings directly into business code.

### openJiuwen is the only long-term memory integration boundary

Long-term memory should go through `OpenJiuwenLTMAdapter` and `build_openjiuwen_ltm_adapter()`. The code intentionally adapts to multiple upstream openJiuwen constructor and method signatures, then bootstraps stores with `register_store()`, `set_config()`, and `set_scope_config()`. New long-term memory features should extend this adapter path instead of talking to pgvector, Milvus, or other stores directly.

### Working memory is session-scoped and survives openJiuwen failures

`WorkingMemoryManager` stores session notes and working-memory items in Redis hashes when Redis is available, with in-process dict fallback otherwise. The app relies on that fallback behavior in tests and local bootstrapping, so preserve it when changing storage code.

### Message ingestion classifies memory before persistence

`MemoryOrchestrator.ingest_messages()` always writes a `ContextItem` into working memory, then selectively enqueues long-term persistence based on lightweight heuristics or an explicit `requested_memory_type`. Procedural, semantic, episodic, and variable memories are handled differently; changes here affect both retrieval behavior and tests.

### Hot-tier caching is intentionally narrow

`TieredMemoryRouter` only caches `MemoryType.VARIABLE` items in the hot tier. Cache payloads are validated before use, and invalid entries are treated as misses rather than silently trusted.

### Compression strategies are registry-driven

`CompressionStrategyRouter` calls `ensure_default_strategies_registered()` on construction. Built-in strategies are registered through the singleton registry, and scheduler/router behavior assumes those IDs exist. If you add a new strategy, wire it through the registry and scheduler path rather than calling it directly from handlers.

### Tests are organized by use-case responsibilities

`tests/README.md` maps UC001-UC016 to concrete test files. When changing config loading, openJiuwen bootstrap, compression routing, or the end-to-end API flow, update the relevant focused tests instead of only adding a generic regression elsewhere.
