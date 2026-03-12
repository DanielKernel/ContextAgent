# ContextAgent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ContextAgent 是一个基于 openJiuwen 框架构建的上下文代理，目标是为业务 Agent 或大模型调用链提供统一、可扩展、可治理的上下文能力，帮助系统更准确地理解用户意图、任务背景与历史状态。

---

## ⚡ 快速开始

### 🚀 一键安装 + 对接 OpenClaw

```bash
# 第一步：安装 ContextAgent，默认初始化 pgvector 并启动服务
bash scripts/install.sh --start

# 如需切换后端，也可以显式选择 openJiuwen 向量库配置
bash scripts/install.sh --vector-backend qdrant --start

# 第二步：对接 OpenClaw
bash scripts/setup-openclaw.sh
```

就这两条命令。服务默认监听 `http://localhost:8000`，接入后 OpenClaw 会自动使用 ContextAgent 进行上下文管理。

> ContextAgent **只通过 openJiuwen 配置对接向量数据库**。安装脚本默认生成 `config/openjiuwen.yaml` 并写入 `CA_OPENJIUWEN_CONFIG_PATH`，不会在业务代码中直连向量库。

> **更多选项：**
> ```bash
> bash scripts/install.sh --help
> bash scripts/setup-openclaw.sh --help
> ```

---

### 安装

项目仅保留 **Python 3 自带虚拟环境** 路径，不再依赖 `uv`。

```bash
# 1) 创建 Python 3 虚拟环境
python3 -m venv .venv

# 2) 安装依赖
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e ".[dev,openjiuwen]"

# 3) 激活虚拟环境（可选，便于手动执行命令）
source .venv/bin/activate

# 4) 指定 openJiuwen 配置并启动服务
export CA_OPENJIUWEN_CONFIG_PATH=config/openjiuwen.yaml
.venv/bin/python3 -m uvicorn context_agent.api.http_handler:app --reload --host 0.0.0.0 --port 8080
```

也可以使用 `Makefile` 快捷命令（底层仍然是 Python 3 虚拟环境）：

```bash
make install        # 等价于：创建 .venv + pip install -e ".[dev,openjiuwen]"
export CA_OPENJIUWEN_CONFIG_PATH=config/openjiuwen.yaml
make run-dev        # 等价于：.venv/bin/python3 -m uvicorn ...
make venv-test      # 在 .venv 中运行测试
```

### 向量库后端选择

安装脚本会始终生成 **openJiuwen 配置文件**，由 openJiuwen 自己决定连接哪个向量库后端：

```bash
# 默认：本地安装并初始化 PostgreSQL + pgvector
bash scripts/install.sh --vector-backend pgvector --start

# 可选：生成 qdrant 配置（服务需按本地方式自行安装）
bash scripts/install.sh --vector-backend qdrant

# 可选：生成 milvus 配置（服务需按本地方式自行安装）
bash scripts/install.sh --vector-backend milvus
```

默认示例文件见：

- `examples/openjiuwen.pgvector.yaml.example`
- `examples/openjiuwen.qdrant.yaml.example`
- `examples/openjiuwen.milvus.yaml.example`

### 5 行接入

```python
import asyncio
from context_agent.orchestration.context_aggregator import ContextAggregator, AggregationRequest

async def main():
    aggregator = ContextAggregator(ltm=your_ltm_adapter)
    snapshot = await aggregator.aggregate(
        AggregationRequest(scope_id="user:123", session_id="sess-001", query="用户最近偏好")
    )
    print(f"获取到 {len(snapshot.items)} 条上下文，共 {snapshot.total_tokens} tokens")

asyncio.run(main())
```

> 📖 **详细接入文档**：[docs/agent-integration-guide.md](docs/agent-integration-guide.md)

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        接口层 (API Layer)                        │
│   ContextAPIRouter (Facade)   │   FastAPI HTTP Handler           │
└─────────────────┬───────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│                      编排层 (Orchestration)                       │
│  ContextAggregator  │  HybridStrategyScheduler  │  SubAgentMgr  │
│  CompressionRouter  │  (策略路由/子代理委托)                       │
└─────────────────┬───────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│                        核心层 (Core)                              │
│  TieredMemoryRouter │ JITResolver  │ ExposureController          │
│  HealthChecker      │ SearchCoordinator │ ToolGovernor            │
│  VersionManager     │ MultimodalProcessor │ MonitoringCollector   │
└─────────────────┬───────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│                       适配层 (Adapters)                           │
│  LTMAdapter  │  RetrieverAdapter  │  ContextEngineAdapter         │
│  LLMAdapter  │  ExternalMemoryAdapter  (ABC 接口隔离)             │
└─────────────────────────────────────────────────────────────────┘
                  │
         openJiuwen Framework / Redis / S3 / Vector DB
```

### 核心数据流

```
业务 Agent
    │ query + scope_id
    ▼
ContextAPIRouter.handle()
    │
    ├─► ContextAggregator ──► [LTM search ‖ WorkingMemory ‖ JIT refs]  (并发, 200ms 超时)
    │
    ├─► ExposureController  ──► 按策略过滤可见上下文
    │
    ├─► ContextHealthChecker ──► 检测 poisoning / distraction / clash
    │
    └─► CompressionStrategyRouter ──► 选择压缩策略 ──► ContextOutput
            │
            └─► 返回给 Agent（可直接拼入 system prompt）
```

---

## 📦 目录结构

```
context_agent/
├── adapters/          # openJiuwen 适配器（ABC + 实现）
├── api/               # FastAPI HTTP 接口层
│   ├── router.py      # ContextAPIRouter（Facade）
│   ├── http_handler.py# FastAPI app factory
│   ├── schemas.py     # Pydantic 请求/响应模型
│   └── auth.py        # Bearer token 认证
├── config/            # 配置与常量
├── core/
│   ├── context/       # JIT解析 / 暴露控制 / 健康检查 / 版本管理
│   ├── memory/        # 分层路由 / 异步处理 / 工作记忆
│   ├── monitoring/    # 指标采集 / 告警引擎
│   ├── multimodal/    # 多模态处理
│   └── retrieval/     # 统一检索 / 工具治理
├── models/            # 数据模型（Pydantic v2）
├── orchestration/     # 编排层（聚合/调度/压缩/子代理）
├── strategies/        # 压缩策略（注册表 + 5 种内置策略）
└── utils/             # 日志 / 追踪 / 错误
```

---

## 🚀 核心能力

| 能力 | 说明 | UC |
|------|------|-----|
| 多源上下文聚合 | 并发召回 LTM / 工作记忆 / JIT refs，200ms 超时 | UC001 |
| 分层记忆路由 | Hot(Redis <20ms) → Warm(LTM <100ms) → Cold(<300ms) | UC002 |
| JIT 按需检索 | ContextRef 延迟解析，60s 本地缓存 | UC004 |
| 混合策略调度 | 按 task_type / utilisation 自动选择压缩策略 | UC005 |
| 上下文暴露控制 | ExposurePolicy 精细控制可见内容 | UC006 |
| 压缩策略路由 | 5 种内置策略 + 自定义注册，失败自动降级 | UC009 |
| 子代理委托 | 创建受限子作用域，结果合并回主上下文 | UC014 |
| 版本管理 | S3 快照 + 恢复，支持调试和回滚 | UC013 |
| 上下文健康检查 | 检测 poisoning / distraction / confusion / clash | UC016 |
| 工具治理 | task_type 过滤 + RAG 工具选择（大工具集） | UC011 |

---

## 🔧 内置压缩策略

| 策略 ID | 场景 | 特点 |
|--------|------|------|
| `qa_compression` | 问答对话 | 保留高相关片段 |
| `task_compression` | 任务执行 | 保留状态，压缩过程 |
| `long_session_compression` | 长会话（>20轮） | 滚动摘要 |
| `realtime_compression` | 高实时 | < 5ms，无 LLM |
| `compaction` | 接近上限（>85%） | LLM 高保真压缩 |

---

## 🌐 HTTP API（服务模式）

```bash
# 方式一：Makefile（底层仍是 Python venv）
export CA_OPENJIUWEN_CONFIG_PATH=config/openjiuwen.yaml
make run-dev

# 方式二：直接使用虚拟环境
export CA_OPENJIUWEN_CONFIG_PATH=config/openjiuwen.yaml
make venv-run

# 手动启动（激活 .venv 后）
export CA_OPENJIUWEN_CONFIG_PATH=config/openjiuwen.yaml
python3 -m uvicorn context_agent.api.http_handler:app --host 0.0.0.0 --port 8080

# 检索上下文
curl -X POST http://localhost:8080/context \
  -H "Content-Type: application/json" \
  -d '{"scope_id":"user:123","session_id":"sess-001","query":"用户偏好","output_type":"compressed"}'

# 健康检查
curl http://localhost:8080/health
```

完整 API 文档：启动后访问 `http://localhost:8080/docs`

---

## 🧪 测试

```bash
# 使用 Python venv（推荐）
make test          # 单元测试
make test-int      # 集成测试
make test-all      # 全部测试 + 覆盖率报告

# 等价的 venv 命令
make venv-test     # 单元测试

# 直接运行（需已激活虚拟环境）
python3 -m pytest tests/unit/ -v
python3 -m pytest tests/integration/ -v
python3 -m pytest tests/ -v --tb=short
```

**测试覆盖范围：**
- 数据模型：`tests/unit/test_models.py`
- 策略注册表：`tests/unit/strategies/test_registry.py`
- 上下文聚合：`tests/unit/test_aggregator.py`
- 策略调度：`tests/unit/test_strategy_scheduler.py`
- 压缩路由：`tests/unit/test_compression_router.py`
- JIT 解析器：`tests/unit/core/context/test_jit_resolver.py`
- 暴露控制：`tests/unit/core/context/test_exposure_controller.py`
- 版本管理：`tests/unit/core/context/test_version_manager.py`
- 健康检查：`tests/unit/core/context/test_health_checker.py`
- 搜索协调：`tests/unit/core/retrieval/test_search_coordinator.py`
- 工具治理：`tests/unit/core/retrieval/test_tool_governor.py`
- 监控告警：`tests/unit/core/monitoring/test_monitoring.py`
- 多模态处理：`tests/unit/core/test_multimodal.py`
- E2E 流程：`tests/integration/test_e2e_pipeline.py`
- 子代理流程：`tests/integration/test_sub_agent_flow.py`

---

## 📚 示例

```bash
python3 examples/basic_recall.py        # 最简上下文召回
python3 examples/compression_demo.py   # 压缩策略演示
python3 examples/tool_governance.py    # 工具治理演示
python3 examples/sub_agent_delegation.py  # 子代理委托
python3 examples/business_agent.py     # 完整 CRM 客服 Agent 集成
```

---

## ⚙️ 配置参考

| 环境变量 | 默认值 | 说明 |
|---------|-------|------|
| `CA_REDIS_URL` | `redis://localhost:6379/0` | Redis 热层连接 |
| `CA_DEFAULT_TOKEN_BUDGET` | `4096` | 默认 token 预算 |
| `CA_AGGREGATION_TIMEOUT_MS` | `200` | 聚合超时（ms） |
| `CA_HOT_TIER_TIMEOUT_MS` | `20` | 热层超时（ms） |
| `CA_WARM_TIER_TIMEOUT_MS` | `100` | 温层超时（ms） |
| `CA_LLM_BASE_URL` | `http://localhost:11434` | LLM 服务地址（Ollama 默认） |
| `CA_LLM_MODEL` | `qwen2.5:7b` | 压缩策略使用的模型 |
| `CA_LOG_LEVEL` | `INFO` | 日志级别 |
| `CA_AUTH_ENABLED` | `false` | 开启 API Key 认证 |

---

## 📖 文档

- [docs/requirements-analysis.md](docs/requirements-analysis.md) — 需求分析说明书（16 UC）
- [docs/architecture-design.md](docs/architecture-design.md) — 架构设计文档（4+1 视图）
- [docs/agent-integration-guide.md](docs/agent-integration-guide.md) — **业务 Agent 接入指导**
