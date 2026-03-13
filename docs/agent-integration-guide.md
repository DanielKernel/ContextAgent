# ContextAgent 业务 Agent 接入与配置指南

> 本文档聚焦当前仓库已经落地的接入方式、正式配置文件结构以及与 openJiuwen 的职责边界。所有配置示例均以仓库内正式配置文件为准，不再使用环境变量片段作为主要示例。

---

## 1. 推荐的部署形态

ContextAgent 现在推荐始终维护两份正式配置：

- 运行态配置：`.local/config/context_agent.yaml`
- 运行态配置：`.local/config/openjiuwen.yaml`

职责边界如下：

| 配置文件 | 负责内容 |
| --- | --- |
| `.local/config/context_agent.yaml` | ContextAgent 运行态配置；安装/升级时默认写入这里，避免被 `git pull` 覆盖 |
| `.local/config/openjiuwen.yaml` | openJiuwen 运行态配置；由 ContextAgent 配置中的相对路径自动解析 |
| `config/context_agent.yaml` / `config/openjiuwen.yaml` | 仓库静态模板与发布基线，不建议直接承载线上动态配置 |

ContextAgent **只通过 openJiuwen 配置接入向量数据库**。不要把 pgvector、qdrant、milvus 的连接逻辑直接写入业务代码。

---

## 2. 配置加载规则

默认启动链路：

1. 优先读取 `.local/config/context_agent.yaml`
2. 再读取其中 `integrations.openjiuwen.config_path` 指向的 `.local/config/openjiuwen.yaml`
3. 若运行态配置不存在，才回退到仓库内 `config/` 模板
4. 装配 `OpenJiuwenLTMAdapter`
5. 在 openJiuwen 可用时启用长期记忆；不可用时降级为 working-memory-only

建议把运行态配置放在同一个 `.local/config/` 目录下，这样 `git pull`、重新安装或切换分支时都不会覆盖线上动态配置。

---

## 3. `.local/config/context_agent.yaml` 分段配置

当前正式结构如下：

```yaml
service:
  name: context-agent
  environment: development
  log_level: INFO
  debug: false

http:
  host: 0.0.0.0
  port: 8080

redis:
  url: redis://localhost:6379/0
  pool_max_connections: 50

storage:
  s3:
    endpoint_url: ""
    bucket: context-agent-versions
    access_key: ""
    secret_key: ""

llm:
  base_url: http://localhost:11434
  model: qwen2.5:7b
  timeout_s: 30.0
  max_retries: 2

integrations:
  openjiuwen:
    config_path: openjiuwen.yaml

budgets:
  latency:
    hot_tier_timeout_ms: 20.0
    warm_tier_timeout_ms: 100.0
    cold_tier_timeout_ms: 300.0
    aggregation_timeout_ms: 200.0
  tokens:
    default_token_budget: 4096
    tool_result_token_limit: 1024

memory:
  queue_maxsize: 1000
  worker_count: 2

observability:
  otlp_endpoint: ""
  prometheus_enabled: true
  metrics_prefix: context_agent

auth:
  enabled: false
  secret_key: ""
  api_keys: []
```

### 3.1 字段说明

#### `service`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `name` | `str` | `context-agent` | 服务标识，用于日志、追踪和观测归属 |
| `environment` | `str` | `development` | 环境标识 |
| `log_level` | `str` | `INFO` | 日志级别 |
| `debug` | `bool` | `false` | 调试开关 |

#### `http`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `host` | `str` | `0.0.0.0` | HTTP 监听地址 |
| `port` | `int` | `8080` | HTTP 服务端口 |

#### `redis`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `url` | `str` | `redis://localhost:6379/0` | hot tier / 缓存 Redis 地址 |
| `pool_max_connections` | `int` | `50` | Redis 连接池上限 |

#### `storage.s3`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `endpoint_url` | `str` | `""` | 外部对象存储地址 |
| `bucket` | `str` | `context-agent-versions` | 版本快照 bucket |
| `access_key` | `str` | `""` | 对象存储访问密钥 |
| `secret_key` | `str` | `""` | 对象存储访问密钥 |

#### `llm`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `base_url` | `str` | `http://localhost:11434` | ContextAgent 内部压缩/摘要用 LLM 地址 |
| `model` | `str` | `qwen2.5:7b` | ContextAgent 内部压缩/摘要模型 |
| `timeout_s` | `float` | `30.0` | LLM 请求超时 |
| `max_retries` | `int` | `2` | LLM 最大重试次数 |

#### `integrations.openjiuwen`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `config_path` | `str` | `openjiuwen.yaml` | openJiuwen 配置文件路径。相对路径相对于 `context_agent.yaml` 所在目录解析 |

#### `budgets.latency`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `hot_tier_timeout_ms` | `float` | `20.0` | hot tier 超时预算 |
| `warm_tier_timeout_ms` | `float` | `100.0` | warm tier 超时预算 |
| `cold_tier_timeout_ms` | `float` | `300.0` | cold tier 超时预算 |
| `aggregation_timeout_ms` | `float` | `200.0` | 聚合总超时预算 |

#### `budgets.tokens`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `default_token_budget` | `int` | `4096` | 默认上下文注入预算 |
| `tool_result_token_limit` | `int` | `1024` | 工具结果裁剪预算 |

#### `memory`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `queue_maxsize` | `int` | `1000` | 异步记忆写入队列上限 |
| `worker_count` | `int` | `2` | 异步记忆 worker 数量 |

#### `observability`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `otlp_endpoint` | `str` | `""` | OTLP 导出地址 |
| `prometheus_enabled` | `bool` | `true` | 是否暴露 Prometheus 指标 |
| `metrics_prefix` | `str` | `context_agent` | 指标名前缀 |

#### `auth`

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `false` | 是否启用 Bearer 认证 |
| `secret_key` | `str` | `""` | 认证密钥 |
| `api_keys` | `list[str]` | `[]` | 可接受的 API keys |

### 3.2 填写建议

- 本地开发最少先确认 `http.port` 和 `integrations.openjiuwen.config_path`
- 生产环境优先补齐 `auth`、`redis`、`storage.s3`、`observability`
- 不要把向量库连接字段挪到 `context_agent.yaml`

---

## 4. `.local/config/openjiuwen.yaml` 结构与职责

当前正式示例：

```yaml
user_id: context-agent

llm_config:
  provider: openai
  model: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  timeout: 30
  max_retries: 2

embedding_config:
  provider: openai
  model: text-embedding-3-large
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  dimension: 3072
  batch_size: 32

vector_store:
  backend: pgvector
  dsn: postgresql://postgres@127.0.0.1:55432/context_agent
  schema: public
  table_name: ltm_memory
  embedding_dimension: 3072
  distance: cosine
  index_type: ivfflat
  lists: 100
  metadata_fields:
    - scope_id
    - session_id
    - memory_type
    - source
    - created_at
    - updated_at
    - tags

memory_config:
  top_k: 10
  score_threshold: 0.3
  enable_user_profile: true
  enable_semantic_memory: true
  enable_episodic_memory: true
  enable_summary_memory: true
```

### 4.1 关键规则

- `vector_store.backend` 默认推荐 `pgvector`
- `embedding_config.dimension` 与 `vector_store.embedding_dimension` 必须一致
- `vector_store.table_name` 默认是 `ltm_memory`
- 切换 qdrant / milvus 时，只改 `openjiuwen.yaml`

### 4.2 哪些内容必须留在 openJiuwen 配置里

- 模型提供方、模型名、API Key
- embedding 配置
- 向量数据库连接、集合/表名、索引参数
- 长期记忆召回阈值和启用项

这些字段不要回写进 `context_agent.yaml`。

---

## 5. 正式配置与示例配置

正式默认配置：

- 运行态配置：`.local/config/context_agent.yaml`
- 运行态配置：`.local/config/openjiuwen.yaml`

按后端分类的标准样例：

- `examples/configs/pgvector/context_agent.yaml`
- `examples/configs/pgvector/openjiuwen.yaml`
- `examples/configs/qdrant/context_agent.yaml`
- `examples/configs/qdrant/openjiuwen.yaml`
- `examples/configs/milvus/context_agent.yaml`
- `examples/configs/milvus/openjiuwen.yaml`

建议流程：

1. 先以 `.local/config/` 下运行态配置启动
2. 如需切换向量后端，再参考 `examples/configs/<backend>/`
3. 修改完成后保持 `context_agent.yaml` 和 `openjiuwen.yaml` 同目录

---

## 6. 启动与接入

### 6.1 本地启动

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e ".[dev,openjiuwen]"
.venv/bin/python3 -m uvicorn context_agent.api.http_handler:app --host 0.0.0.0 --port 8080
```

### 6.2 安装脚本

```bash
bash scripts/install.sh --start
```

安装脚本会：

1. 确保 `.venv` 可用
2. 生成或保留 `.local/config/context_agent.yaml`
3. 生成或保留 `.local/config/openjiuwen.yaml`
4. 默认按 pgvector 进行初始化

### 6.3 升级脚本

```bash
bash scripts/upgrade.sh
```

升级脚本会：

1. 备份正式配置与 `.env`
2. 在 pgvector 场景下尝试做逻辑备份
3. 执行非破坏性配置迁移与幂等 schema 迁移
4. 保留历史数据并做健康检查

---

## 7. 代码接入入口

### 7.1 SDK 方式

```python
from context_agent.config.settings import get_settings
from context_agent.config.openjiuwen import build_default_api_router

settings = get_settings()
router = build_default_api_router(settings=settings)
```

### 7.2 HTTP 方式

直接启动 `context_agent.api.http_handler:app` 即可。服务内部会读取正式配置并构建默认 router。

### 7.3 OpenClaw 方式

OpenClaw 插件接入请参考：

- `docs/openclaw-integration.md`

该接入方式默认复用同一套正式配置文件，不需要额外在业务代码里直连向量库。

---

## 8. 默认记忆链路

当前默认装配链路如下：

```text
HTTP / OpenClaw ingest
    -> MemoryOrchestrator
    -> WorkingMemoryManager
    -> AsyncMemoryProcessor
    -> OpenJiuwenLTMAdapter
    -> openJiuwen LongTermMemory
    -> pgvector（默认）/ qdrant / milvus
```

关键点：

1. working memory 先保证当前会话立即可用
2. 长期记忆的真实写入由 openJiuwen 完成
3. ContextAgent 负责分类、治理、检索、压缩与装配

---

## 9. 故障排查

### 9.1 修改了 `context_agent.yaml` 但不生效

先确认：

- 文件路径优先看 `.local/config/context_agent.yaml`
- `integrations.openjiuwen.config_path` 是正确的相对或绝对路径
- YAML 缩进正确

### 9.2 openJiuwen 长期记忆未启用

先检查：

- `.local/config/openjiuwen.yaml` 是否存在
- `vector_store.backend` 是否填写正确
- `llm_config` / `embedding_config` 是否具备真实可用的凭据

### 9.3 pgvector 已启动但没有数据

先检查：

- `vector_store.table_name` 是否仍为 `ltm_memory`
- `embedding_config.dimension` 与 `vector_store.embedding_dimension` 是否一致
- 业务写入是否经过 `OpenJiuwenLTMAdapter`

---

## 10. 推荐阅读顺序

1. 先看 `.local/config/context_agent.yaml`
2. 再看 `.local/config/openjiuwen.yaml`
3. 然后看 `examples/configs/<backend>/`
4. 如需接入 OpenClaw，再看 `docs/openclaw-integration.md`
5. 如需理解测试范围，再看 `tests/README.md`
6. 如需规划 benchmark 评测体系，再看 `docs/benchmark-evaluation-guide.md`

---

## 11. 用例验证入口

如果你希望按需求文档中的用例来验证当前实现，建议对照：

- 需求来源：`docs/requirements-analysis.md`
- 测试覆盖矩阵：`tests/README.md`
- 关键性能 smoke tests：`tests/performance/test_usecase_latency.py`

推荐命令：

```bash
python3 -m pytest \
  tests/unit/core/memory/test_tiered_router.py \
  tests/unit/core/memory/test_async_processor.py \
  tests/unit/test_api_router_outputs.py \
  tests/unit/core/monitoring/test_monitoring.py \
  tests/performance/test_usecase_latency.py
```

如果要验证更完整的主链路，再补跑：

```bash
python3 -m pytest \
  tests/integration/test_e2e_pipeline.py \
  tests/integration/test_sub_agent_flow.py \
  tests/unit/test_openclaw_bridge.py
```
