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
- `tests/unit/test_compression_router.py`：验证压缩路由与策略 fallback。
- `tests/unit/strategies/`：验证压缩策略注册和具体策略行为。
- `tests/integration/test_e2e_pipeline.py`：验证从聚合到压缩输出的主链路。

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
