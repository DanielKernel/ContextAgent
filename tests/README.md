# Tests 目录说明

`tests/` 用来验证 ContextAgent 的配置加载、上下文聚合、压缩策略、openJiuwen 集成以及端到端行为。

## 目录结构

| 目录 | 说明 |
| --- | --- |
| `tests/unit/` | 纯单元测试，覆盖配置、模型、路由、策略、适配器等局部逻辑 |
| `tests/integration/` | 集成测试，验证多模块协作链路，例如 API → 聚合 → 压缩 |
| `tests/performance/` | 性能与负载相关测试或基准入口 |

## 当前重点测试主题

- `tests/unit/test_settings_config.py`：验证 `config/context_agent.yaml` 的分段配置加载与环境变量覆盖。
- `tests/unit/test_openjiuwen_config.py`：验证 openJiuwen 配置发现、装配与降级行为。
- `tests/unit/test_http_handler_health.py`：验证 `/health` 运行态依赖检查输出。
- `tests/unit/test_compression_router.py`：验证压缩路由与策略 fallback。
- `tests/unit/strategies/`：验证压缩策略注册和具体策略行为。
- `tests/integration/test_e2e_pipeline.py`：验证从聚合到压缩输出的主链路。

## 用例覆盖矩阵

下表对应 `docs/requirements-analysis.md` 中的 UC001–UC016：

| 用例 | 当前测试覆盖 |
| --- | --- |
| `UC001` 多源上下文聚合 | `tests/unit/test_aggregator.py`、`tests/integration/test_e2e_pipeline.py` |
| `UC002` 分层分级记忆管理 | `tests/unit/core/memory/test_tiered_router.py` |
| `UC003` 动态上下文更新与管理 | `tests/unit/core/context/test_health_checker.py`、`tests/unit/test_compression_router.py` |
| `UC004` 即时上下文检索 | `tests/unit/core/context/test_jit_resolver.py` |
| `UC005` 混合式召回策略 | `tests/unit/test_strategy_scheduler.py`、`tests/unit/core/retrieval/test_search_coordinator.py` |
| `UC006` 上下文暴露控制 | `tests/unit/core/context/test_exposure_controller.py`、`tests/integration/test_sub_agent_flow.py` |
| `UC007` Agent 上下文接口调用 | `tests/unit/test_api_router_outputs.py`、`tests/integration/test_e2e_pipeline.py` |
| `UC008` 记忆异步处理与更新 | `tests/unit/core/memory/test_async_processor.py`、`tests/unit/test_memory_orchestrator.py` |
| `UC009` 上下文压缩与摘要 | `tests/unit/test_compression_router.py`、`tests/unit/strategies/test_registry.py` |
| `UC010` 结构化笔记与工作记忆管理 | `tests/unit/test_memory_orchestrator.py`、`tests/unit/test_openviking_capabilities.py` |
| `UC011` 工具上下文治理 | `tests/unit/core/retrieval/test_tool_governor.py` |
| `UC012` 结构化存储与混合检索 | `tests/unit/core/retrieval/test_search_coordinator.py` |
| `UC013` 上下文版本管理与回滚 | `tests/unit/core/context/test_version_manager.py` |
| `UC014` 子代理上下文隔离与摘要回传 | `tests/integration/test_sub_agent_flow.py` |
| `UC015` 多语言与多模态上下文扩展 | `tests/unit/core/test_multimodal.py` |
| `UC016` 召回质量与时延监控 | `tests/unit/core/monitoring/test_monitoring.py` |

## 性能回归覆盖

`tests/performance/test_usecase_latency.py` 提供了针对关键路径的轻量性能 smoke tests：

- `UC001` 聚合
- `UC002` 热层召回
- `UC004` scratchpad JIT 检索
- `UC009` 实时压缩
- `UC012` 混合检索

这些测试使用 stub / in-memory 路径，目标是让 CI 中能够稳定地对 P95 目标做回归守护。

## 运行方式

常用命令：

```bash
python3 -m pytest
python3 -m pytest tests/unit
python3 -m pytest tests/integration/test_e2e_pipeline.py
```

如果你修改了配置系统，优先回归这些测试：

```bash
python3 -m pytest \
  tests/unit/test_settings_config.py \
  tests/unit/test_config_migration.py \
  tests/unit/test_openjiuwen_config.py
```

如果你修改了压缩或 OpenClaw 接入，再补跑：

```bash
python3 -m pytest \
  tests/unit/test_compression_router.py \
  tests/unit/strategies/test_registry.py \
  tests/unit/test_openclaw_bridge.py \
  tests/integration/test_e2e_pipeline.py
```

如果你修改了需求用例主链路，建议至少补跑：

```bash
python3 -m pytest \
  tests/unit/core/memory/test_tiered_router.py \
  tests/unit/core/memory/test_async_processor.py \
  tests/unit/test_api_router_outputs.py \
  tests/unit/core/monitoring/test_monitoring.py \
  tests/performance/test_usecase_latency.py
```
