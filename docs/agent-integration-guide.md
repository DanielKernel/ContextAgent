# ContextAgent 业务 Agent 接入指导

> 本文档面向希望将 ContextAgent 接入自有业务 Agent 的开发者，提供从安装配置到生产集成的完整指引。

---

## 目录

1. [快速接入](#1-快速接入)
2. [核心概念](#2-核心概念)
3. [SDK 模式（嵌入式）](#3-sdk-模式嵌入式)
4. [HTTP 服务模式](#4-http-服务模式)
5. [openJiuwen 集成](#5-openjiuwen-集成)
6. [上下文策略配置](#6-上下文策略配置)
7. [压缩策略定制](#7-压缩策略定制)
8. [子代理上下文委托](#8-子代理上下文委托)
9. [监控与告警接入](#9-监控与告警接入)
10. [常见场景配方](#10-常见场景配方)
11. [性能调优参考](#11-性能调优参考)
12. [故障排查](#12-故障排查)

---

## 1. 快速接入

### 安装

```bash
pip install -U openjiuwen
pip install -e ".[dev]"   # 开发环境（含测试工具）
```

### 最简示例（5 行代码）

```python
import asyncio
from context_agent.orchestration.context_aggregator import ContextAggregator, AggregationRequest

async def main():
    aggregator = ContextAggregator(ltm=your_ltm_instance)
    request = AggregationRequest(scope_id="user:123", session_id="sess-001", query="用户的最近偏好")
    snapshot = await aggregator.aggregate(request)
    print(f"获取到 {len(snapshot.items)} 条上下文，共 {snapshot.total_tokens} tokens")

asyncio.run(main())
```

---

## 2. 核心概念

### Scope（作用域）

`scope_id` 是 ContextAgent 中的最小隔离单元，通常映射到一个**用户**或**业务实体**：

| 场景 | scope_id 示例 |
|------|--------------|
| C端用户 | `user:uid-12345` |
| 企业账户 | `org:company-abc` |
| 独立任务 | `task:sprint-42` |
| 子代理 | `user:uid-123:child:analysis` |

### ContextSnapshot（上下文快照）

一次聚合的结果，包含来自多源的 `ContextItem` 列表：

```
ContextSnapshot
  ├── items: List[ContextItem]   # 各上下文片段
  ├── total_tokens: int          # 估算 token 数
  ├── scope_id: str
  └── session_id: str
```

### ContextOutput（压缩输出）

最终注入模型的内容，包含压缩后的文本或结构化数据：

```
ContextOutput
  ├── content: str       # 压缩后文本（可直接拼入 prompt）
  ├── output_type        # RAW | COMPRESSED | STRUCTURED | SNAPSHOT
  └── token_count: int
```

### OutputType 选择指南

| OutputType | 适用场景 |
|-----------|---------|
| `RAW` | 调试、无压缩直传，内容完整但较大 |
| `COMPRESSED` | 生产环境，自动选择最佳压缩策略 |
| `STRUCTURED` | 需要结构化 JSON 输出（compaction 策略） |
| `SNAPSHOT` | 创建版本快照用于回滚/调试 |

---

## 3. SDK 模式（嵌入式）

适合：**同进程调用**，延迟最低，无网络开销。

### 3.1 最小化配置

```python
from context_agent import (
    ContextAPIRouter,
    ContextAggregator,
    get_settings,
)

# 配置（通过环境变量或 .env 文件）
settings = get_settings()

# 构建核心组件（使用 openJiuwen 适配器）
from context_agent.adapters.ltm_adapter import OpenJiuwenLTMAdapter
from openjiuwen.core.memory.long_term_memory import LongTermMemory  # 需安装 openjiuwen

# 不同 openJiuwen 版本的构造签名可能不同，请以当前安装版本为准
ltm_instance = LongTermMemory(settings)
ltm_adapter = OpenJiuwenLTMAdapter(ltm=ltm_instance)

aggregator = ContextAggregator(ltm=ltm_adapter)
router = ContextAPIRouter(aggregator=aggregator)
```

### 3.2 在 Agent 的每轮推理前调用

```python
async def prepare_context(user_id: str, session_id: str, query: str) -> str:
    """返回可直接拼入 system prompt 的上下文字符串。"""
    output, warnings = await router.handle(
        scope_id=f"user:{user_id}",
        session_id=session_id,
        query=query,
        output_type=OutputType.COMPRESSED,
        token_budget=3000,  # 为模型回复预留 1000+ tokens
        task_type="qa",     # 影响压缩策略选择
    )
    return output.content

# 在 Agent 推理链中使用
context_text = await prepare_context("uid-123", "sess-001", user_message)
system_prompt = f"{base_system_prompt}\n\n---\n{context_text}\n---"
```

### 3.3 带工具过滤的完整集成

```python
from context_agent.core.retrieval.tool_governor import ToolContextGovernor, ToolDefinition

tool_governor = ToolContextGovernor(tools=[
    ToolDefinition(tool_id="search", name="搜索", description="搜索知识库",
                   required_for_task_types=["qa"]),
    ToolDefinition(tool_id="calculator", name="计算器", description="数学计算",
                   required_for_task_types=["math", "analysis"]),
    # ... 更多工具
])

async def prepare_full_context(user_id: str, session_id: str, query: str, task_type: str):
    # 上下文
    output, _ = await router.handle(
        scope_id=f"user:{user_id}", session_id=session_id,
        query=query, output_type=OutputType.COMPRESSED,
        task_type=task_type,
    )
    # 工具
    tool_items = await tool_governor.get_tool_context_items(
        scope_id=f"user:{user_id}",
        task_description=query,
        task_type=task_type,
        top_k=8,
    )
    tools = [{"name": t.metadata["tool_id"], "desc": t.content} for t in tool_items]
    return output.content, tools
```

---

## 4. HTTP 服务模式

适合：**跨服务调用**，多个 Agent 进程共享同一上下文服务。

### 4.1 启动服务

```python
# main.py
import uvicorn
from context_agent.api.http_handler import create_app
from context_agent.api.router import ContextAPIRouter
from context_agent.orchestration.context_aggregator import ContextAggregator
from context_agent.adapters.ltm_adapter import OpenJiuwenLTMAdapter

# 构建路由器（同 SDK 模式）
aggregator = ContextAggregator(ltm=your_ltm_adapter)
api_router = ContextAPIRouter(aggregator=aggregator)

app = create_app(api_router=api_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

```bash
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8080 --workers 4
```

### 4.2 HTTP API 调用

**检索上下文（POST /context）**

```bash
curl -X POST http://localhost:8080/context \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "scope_id": "user:uid-123",
    "session_id": "sess-001",
    "query": "用户最近的购买历史",
    "output_type": "compressed",
    "token_budget": 3000,
    "task_type": "support"
  }'
```

响应：

```json
{
  "request_id": "abc123",
  "scope_id": "user:uid-123",
  "session_id": "sess-001",
  "output": {
    "output_type": "compressed",
    "content": "【历史记录】\n• 2024-11 购买了 Pro Plan...",
    "token_count": 312
  },
  "latency_ms": 87.4,
  "warnings": []
}
```

**创建版本快照（指定 output_type=snapshot）**

```bash
curl -X POST http://localhost:8080/context \
  -H "Content-Type: application/json" \
  -d '{"scope_id":"user:123","session_id":"sess","query":"checkpoint","output_type":"snapshot"}'
```

**列举版本历史**

```bash
curl http://localhost:8080/context/user:123/versions?session_id=sess \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### 4.3 Python 客户端封装

```python
import httpx
from typing import Any

class ContextAgentClient:
    def __init__(self, base_url: str, api_key: str = ""):
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def get_context(
        self,
        scope_id: str,
        session_id: str,
        query: str,
        output_type: str = "compressed",
        token_budget: int = 3000,
        task_type: str = "",
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{self._base_url}/context",
                headers=self._headers,
                json={
                    "scope_id": scope_id,
                    "session_id": session_id,
                    "query": query,
                    "output_type": output_type,
                    "token_budget": token_budget,
                    "task_type": task_type,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def health(self) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base_url}/health")
            return resp.json()


# 使用示例
client = ContextAgentClient("http://localhost:8080", api_key="your-key")
result = await client.get_context("user:123", "sess-001", "用户偏好是什么？")
context_text = result["output"]["content"]
```

---

## 5. openJiuwen 集成

### 5.1 LTM 适配器

```python
from context_agent.config.openjiuwen import build_openjiuwen_ltm_adapter

ltm_adapter = build_openjiuwen_ltm_adapter("config/openjiuwen.yaml")
```

### 5.1.1 设计边界：长期记忆必须通过 openJiuwen 接入

ContextAgent **不直接连接**向量数据库、图数据库或外部知识库。  
长期记忆后端（向量库、embedding 模型、索引参数、召回策略）统一由 **openJiuwen `LongTermMemory`** 管理，ContextAgent 只通过 `OpenJiuwenLTMAdapter` 调用：

- `search_user_mem(...)`
- `add_messages(...)`
- `delete_mem_by_id(...)`
- `update_mem_by_id(...)`

这意味着：

1. **向量数据库连接配置写在 openJiuwen**，不写在 ContextAgent 业务代码里。
2. **embedding / LLM 配置写在 openJiuwen**，由 `LongTermMemory` 及检索组件消费。
3. ContextAgent 侧只负责把 openJiuwen 返回的结果转换为 `ContextItem`，并参与后续聚合、压缩、暴露控制和注入。

### 5.1.2 openJiuwen 长期记忆配置模板

下面给出一个推荐的 `LongTermMemory(...)` 配置结构。实际字段名和初始化签名以你们使用的 openJiuwen 版本为准；如有差异，应在 **openJiuwen 配置层** 做适配，而不是在 ContextAgent 中直连数据库。

```python
openjiuwen_ltm_config = {
    "user_id": "context-agent",
    "llm_config": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "${OPENAI_API_KEY}",
        "base_url": "https://api.openai.com/v1",
        "timeout": 30,
        "max_retries": 2,
    },
    "embedding_config": {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "api_key": "${OPENAI_API_KEY}",
        "base_url": "https://api.openai.com/v1",
        "dimension": 3072,
        "batch_size": 32,
    },
    "vector_store": {
        "backend": "pgvector",            # 默认推荐；也可切换 qdrant / milvus
        "dsn": "postgresql://postgres:password@127.0.0.1:5432/context_agent?sslmode=disable",
        "table_name": "ltm_memory",
        "embedding_dimension": 3072,
        "distance": "cosine",
    },
    "memory_config": {
        "top_k": 10,
        "score_threshold": 0.3,
        "enable_user_profile": True,
        "enable_semantic_memory": True,
        "enable_episodic_memory": True,
        "enable_summary_memory": True,
    },
}
```

#### 推荐的 payload / metadata 字段

为了让 ContextAgent 在召回、隔离和过滤上工作更稳定，建议 openJiuwen 写入向量库时至少保留这些字段：

- `scope_id`：租户 / 用户 / 频道隔离键
- `session_id`：会话标识（可选，但推荐）
- `memory_type`：如 `semantic` / `episodic` / `procedural`
- `content`：原始可检索文本
- `source`：来源系统或来源模块
- `created_at`
- `updated_at`
- `tags`

其中 `scope_id` 是最关键字段。ContextAgent 当前默认用 `scope_id` 作为长期记忆隔离边界。

### 5.1.3 向量数据库配置示例

#### 默认推荐：pgvector

ContextAgent 默认推荐通过 **openJiuwen `LongTermMemory` + `pgvector`** 接入长期记忆：

1. **始终通过 openJiuwen `LongTermMemory` 接入**
2. 在 openJiuwen 配置层按 **`pgvector` / PostgreSQL DSN** 风格配置
3. 由 openJiuwen 负责连接、写入、检索、索引和向量字段管理

推荐配置：

```python
openjiuwen_ltm_config = {
    "user_id": "context-agent",
    "llm_config": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "${OPENAI_API_KEY}",
        "base_url": "https://api.openai.com/v1",
        "timeout": 30,
        "max_retries": 2,
    },
    "embedding_config": {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "api_key": "${OPENAI_API_KEY}",
        "base_url": "https://api.openai.com/v1",
        "dimension": 3072,
        "batch_size": 32,
    },
    "vector_store": {
        "backend": "pgvector",
        "dsn": "postgresql://postgres:password@127.0.0.1:5432/context_agent?sslmode=disable",
        "table_name": "ltm_memory",
        "embedding_dimension": 3072,
        "distance": "cosine",
        "index_type": "ivfflat",
        "lists": 100,
        "schema": "public",
        "metadata_fields": [
            "scope_id",
            "session_id",
            "memory_type",
            "source",
            "created_at",
            "updated_at",
            "tags",
        ],
    },
    "memory_config": {
        "top_k": 10,
        "score_threshold": 0.3,
        "enable_user_profile": True,
        "enable_semantic_memory": True,
        "enable_episodic_memory": True,
        "enable_summary_memory": True,
    },
}
```

#### pgvector 建表/索引参考

若你们使用 PostgreSQL + `pgvector`，可参考以下结构准备底层表。

```sql
CREATE TABLE ltm_memory (
    id              BIGSERIAL PRIMARY KEY,
    scope_id        VARCHAR(128) NOT NULL,
    session_id      VARCHAR(128),
    memory_type     VARCHAR(32) NOT NULL,
    source          VARCHAR(64),
    content         TEXT NOT NULL,
    embedding       vector(3072),
    tags            JSONB,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ltm_memory_scope_id ON ltm_memory(scope_id);
CREATE INDEX idx_ltm_memory_memory_type ON ltm_memory(memory_type);

-- 按实际场景选择 ivfflat / hnsw
CREATE INDEX idx_ltm_memory_embedding
ON ltm_memory
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

#### pgvector 接入建议

- DSN 推荐显式带上 `sslmode`
- `embedding_dimension` 必须和 embedding 模型输出维度一致
- 至少对 `scope_id` 建普通索引，保证租户隔离过滤效率
- 根据数据规模和召回延迟目标选择 `ivfflat` 或 `hnsw`
- 若需要切换其他向量库，只调整 openJiuwen 配置即可，ContextAgent 侧不需要直连或改写数据库逻辑

#### Qdrant

```python
openjiuwen_ltm_config = {
    "user_id": "context-agent",
    "llm_config": {...},
    "embedding_config": {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "api_key": "${OPENAI_API_KEY}",
        "dimension": 3072,
    },
    "vector_store": {
        "backend": "qdrant",
        "host": "127.0.0.1",
        "port": 6333,
        "api_key": "",
        "https": False,
        "collection_name": "context_agent_memory",
        "distance": "Cosine",
        "recreate_if_exists": False,
        "payload_schema": {
            "scope_id": "keyword",
            "memory_type": "keyword",
            "session_id": "keyword",
            "created_at": "datetime",
        },
    },
}
```

#### pgvector

```python
openjiuwen_ltm_config = {
    "user_id": "context-agent",
    "llm_config": {...},
    "embedding_config": {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "api_key": "${OPENAI_API_KEY}",
        "dimension": 3072,
    },
    "vector_store": {
        "backend": "pgvector",
        "dsn": "postgresql://postgres:password@127.0.0.1:5432/context_agent",
        "table_name": "ltm_memory",
        "embedding_dimension": 3072,
        "distance": "cosine",
        "index_type": "ivfflat",
        "lists": 100,
    },
}
```

#### Milvus

```python
openjiuwen_ltm_config = {
    "user_id": "context-agent",
    "llm_config": {...},
    "embedding_config": {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "api_key": "${OPENAI_API_KEY}",
        "dimension": 3072,
    },
    "vector_store": {
        "backend": "milvus",
        "uri": "http://127.0.0.1:19530",
        "token": "",
        "collection_name": "context_agent_memory",
        "embedding_dimension": 3072,
        "metric_type": "COSINE",
        "index_type": "HNSW",
        "index_params": {
            "M": 16,
            "efConstruction": 200,
        },
        "search_params": {
            "ef": 64,
        },
    },
}
```

#### 选型建议

- **默认开发/本地环境**：优先 `pgvector`，与 ContextAgent 的本地一键安装路径一致。
- **轻量试验环境**：可选 `Qdrant`，启动快、调试简单。
- **通用生产环境**：优先 `pgvector`，利于与业务数据统一治理。
- **大规模高吞吐向量场景**：优先 `Milvus`。

### 5.1.4 基于 openJiuwen 的 LLM 配置指导

当前 ContextAgent 的长期记忆、检索增强和部分压缩能力，应该通过 openJiuwen 侧的 LLM/Embedding 配置提供底层模型能力。推荐把模型配置分成两类：

#### A. `llm_config`：生成 / 摘要 / agentic retrieval

```python
"llm_config": {
    "provider": "openai",              # 或兼容 OpenAI API 的网关
    "model": "gpt-4o-mini",
    "api_key": "${OPENAI_API_KEY}",
    "base_url": "https://api.openai.com/v1",
    "timeout": 30,
    "max_retries": 2,
}
```

这个配置通常会被 openJiuwen 用于：

- 长期记忆摘要与压缩
- 复杂查询下的 `agentic_retrieve`
- 记忆去重、冲突检测、结构化提取

#### B. `embedding_config`：向量化

```python
"embedding_config": {
    "provider": "openai",
    "model": "text-embedding-3-large",
    "api_key": "${OPENAI_API_KEY}",
    "base_url": "https://api.openai.com/v1",
    "dimension": 3072,
    "batch_size": 32,
}
```

关键要求：

1. `dimension` 必须与向量库集合/表的维度一致。
2. 不同环境不要混用维度不同的 embedding 模型。
3. 如果更换 embedding 模型，通常需要重建索引或重新写入历史向量。

### 5.1.5 推荐的双配置文件写法

当前项目建议把 **ContextAgent** 与 **openJiuwen** 的配置拆成两份标准文件：

- `config/context_agent.yaml`
- `config/openjiuwen.yaml`

其中：

- `context_agent.yaml` 负责服务端口、日志、认证、预算等 ContextAgent 自身配置
- `openjiuwen.yaml` 负责模型、embedding、向量库与记忆策略

`config/context_agent.yaml` 示例：

```yaml
service_name: context-agent
environment: development
log_level: INFO
http_host: 0.0.0.0
http_port: 8080
openjiuwen_config_path: openjiuwen.yaml
default_token_budget: 4096
memory_worker_count: 2
auth_enabled: false
api_keys: []
```

`config/openjiuwen.yaml` 示例：

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
  dsn: postgresql://postgres@127.0.0.1:55432/context_agent?sslmode=disable
  table_name: ltm_memory
  embedding_dimension: 3072
  distance: cosine

memory_config:
  top_k: 10
  score_threshold: 0.3
  enable_user_profile: true
  enable_semantic_memory: true
  enable_episodic_memory: true
  enable_summary_memory: true
```

正式默认配置见：

- `config/context_agent.yaml`
- `config/openjiuwen.yaml`

按后端分类的标准样例见：

- `examples/configs/pgvector/context_agent.yaml`
- `examples/configs/pgvector/openjiuwen.yaml`
- `examples/configs/qdrant/context_agent.yaml`
- `examples/configs/qdrant/openjiuwen.yaml`
- `examples/configs/milvus/context_agent.yaml`
- `examples/configs/milvus/openjiuwen.yaml`

#### 5.1.5.1 配置归属边界

| 配置文件 | 负责范围 | 已由 ContextAgent 自动接管 | 仍需用户/部署方填写 |
| --- | --- | --- | --- |
| `config/context_agent.yaml` | 服务启动、日志、认证、预算、异步处理、观测 | 自动发现默认路径、相对路径解析、环境变量覆盖、默认开发值 | 生产环境端口、认证密钥、Redis/S3 地址、观测端点 |
| `config/openjiuwen.yaml` | openJiuwen 的模型、embedding、长期记忆、向量库 | 自动发现默认路径、在启动阶段装配 `OpenJiuwenLTMAdapter`、默认 pgvector 基线 | API Key、真实模型地址、向量库连接、维度匹配、是否启用各类记忆 |

规则：

1. `context_agent.yaml` 中只保留 `openjiuwen_config_path` 这样的**引用关系**，不展开 `llm_config` / `vector_store` 等 openJiuwen 键。
2. `openjiuwen.yaml` 中不放 `http_port`、`auth_enabled` 这类 ContextAgent 服务配置。
3. 环境变量仍保留为覆盖层，但正式运行默认优先读取 `config/` 下两份标准配置。

#### 5.1.5.2 `context_agent.yaml` 字段总表

| 字段 | 类型 | 默认建议 | 是否必填 | 影响能力 | 默认原因 | 是否已接管 |
| --- | --- | --- | --- | --- | --- | --- |
| `service_name` | `str` | `context-agent` | 否 | 服务标识、日志归属 | 与项目名一致，便于观测检索 | 是 |
| `environment` | `str` | `development` | 否 | 环境区分 | 本地开发默认安全 | 是 |
| `log_level` | `str` | `INFO` | 否 | 日志详细度 | 兼顾排障与噪声控制 | 是 |
| `debug` | `bool` | `false` | 否 | 调试行为 | 生产安全默认关闭 | 是 |
| `http_host` | `str` | `0.0.0.0` | 否 | HTTP 监听地址 | 本地容器/宿主都易接入 | 是 |
| `http_port` | `int` | `8080` | 否 | HTTP 服务端口 | 与项目现有服务默认一致 | 是 |
| `redis_url` | `str` | `redis://localhost:6379/0` | 否 | Hot tier / 缓存 | 本地开发最低门槛 | 否 |
| `redis_pool_max_connections` | `int` | `50` | 否 | Redis 并发 | 中小规模场景通用 | 是 |
| `s3_endpoint_url` | `str` | `""` | 否 | 版本快照外存 | 空值表示不开启外部对象存储 | 否 |
| `s3_bucket` | `str` | `context-agent-versions` | 否 | 版本快照命名 | 表意清晰 | 否 |
| `s3_access_key` | `str` | `""` | 否 | 对象存储认证 | 敏感项不应写死 | 否 |
| `s3_secret_key` | `str` | `""` | 否 | 对象存储认证 | 敏感项不应写死 | 否 |
| `llm_base_url` | `str` | `http://localhost:11434` | 否 | 项目内压缩/摘要 LLM | 保持本地开发可跑 | 否 |
| `llm_model` | `str` | `qwen2.5:7b` | 否 | 项目内压缩/摘要 LLM | 与本地 Ollama 路径兼容 | 否 |
| `llm_timeout_s` | `float` | `30.0` | 否 | LLM 请求超时 | 控制阻塞时间 | 是 |
| `llm_max_retries` | `int` | `2` | 否 | LLM 重试 | 降低瞬时失败影响 | 是 |
| `openjiuwen_config_path` | `str` | `openjiuwen.yaml` | 是 | openJiuwen 配置发现 | 保持双配置文件同目录开箱即用 | 是 |
| `hot_tier_timeout_ms` | `float` | `20.0` | 否 | Hot tier 时延预算 | 对齐架构目标 | 是 |
| `warm_tier_timeout_ms` | `float` | `100.0` | 否 | Warm tier 时延预算 | 对齐架构目标 | 是 |
| `cold_tier_timeout_ms` | `float` | `300.0` | 否 | Cold tier 时延预算 | 对齐架构目标 | 是 |
| `aggregation_timeout_ms` | `float` | `200.0` | 否 | 聚合总预算 | 控制主路径延迟 | 是 |
| `default_token_budget` | `int` | `4096` | 否 | 默认注入 token 预算 | 适合多数对话场景 | 是 |
| `tool_result_token_limit` | `int` | `1024` | 否 | 工具结果裁剪 | 防止工具输出挤占上下文 | 是 |
| `memory_queue_maxsize` | `int` | `1000` | 否 | 异步记忆写入队列 | 兼顾吞吐与内存 | 是 |
| `memory_worker_count` | `int` | `2` | 否 | 异步记忆 worker 数 | 本地默认轻量稳定 | 是 |
| `otlp_endpoint` | `str` | `""` | 否 | OTLP 观测导出 | 空值表示不开启 | 否 |
| `prometheus_enabled` | `bool` | `true` | 否 | 指标暴露 | 默认保留观测入口 | 是 |
| `metrics_prefix` | `str` | `context_agent` | 否 | 指标命名空间 | 防止与其他服务冲突 | 是 |
| `auth_enabled` | `bool` | `false` | 否 | API 鉴权 | 本地开发默认关闭 | 是 |
| `auth_secret_key` | `str` | `""` | 否 | 鉴权密钥 | 敏感项不应写死 | 否 |
| `api_keys` | `list[str]` | `[]` | 条件必填 | Bearer Token 鉴权 | 仅启用鉴权时需要填写 | 否 |

填写建议：

- 本地开发最少只要确认 `openjiuwen_config_path` 与 `http_port`。
- 生产环境优先补齐 `auth_*`、Redis/S3、观测端点。
- 除非明确需要，不建议在 `context_agent.yaml` 中重复填写 openJiuwen 的模型与向量库字段。

#### 5.1.5.3 `openjiuwen.yaml` 字段总表

| 字段 | 类型 | 默认建议 | 是否必填 | 影响能力 | 默认原因 | 是否已接管 |
| --- | --- | --- | --- | --- | --- | --- |
| `user_id` | `str` | `context-agent` | 是 | 默认身份/记忆命名空间 | 便于单机场景直接运行 | 否 |
| `llm_config.provider` | `str` | `openai` | 是 | 长期记忆提取、摘要、冲突检查 | 与示例 API 生态兼容 | 否 |
| `llm_config.model` | `str` | `gpt-4o-mini` | 是 | 长期记忆生成质量/成本 | 兼顾成本与效果 | 否 |
| `llm_config.api_key` | `str` | `${OPENAI_API_KEY}` | 是 | 上游 LLM 调用 | 敏感项通过环境注入 | 否 |
| `llm_config.base_url` | `str` | `https://api.openai.com/v1` | 是 | 上游 LLM 地址 | 默认指向官方兼容接口 | 否 |
| `llm_config.timeout` | `int` | `30` | 否 | 上游 LLM 超时 | 避免长时间阻塞 | 否 |
| `llm_config.max_retries` | `int` | `2` | 否 | 上游 LLM 重试 | 降低瞬时失败影响 | 否 |
| `embedding_config.provider` | `str` | `openai` | 是 | 向量化提供者 | 与默认模型栈一致 | 否 |
| `embedding_config.model` | `str` | `text-embedding-3-large` | 是 | 向量写入/检索质量 | 与 3072 维 pgvector 模板对齐 | 否 |
| `embedding_config.api_key` | `str` | `${OPENAI_API_KEY}` | 是 | embedding 调用 | 敏感项通过环境注入 | 否 |
| `embedding_config.base_url` | `str` | `https://api.openai.com/v1` | 是 | embedding 地址 | 默认指向官方兼容接口 | 否 |
| `embedding_config.dimension` | `int` | `3072` | 是 | 向量维度匹配 | 与默认模型、表结构一致 | 否 |
| `embedding_config.batch_size` | `int` | `32` | 否 | 写入批次大小 | 兼顾吞吐与稳定性 | 否 |
| `vector_store.backend` | `str` | `pgvector` | 是 | 选择向量后端 | 默认推荐后端 | 是（默认推荐） |
| `vector_store.dsn` | `str` | `postgresql://postgres@127.0.0.1:55432/context_agent?sslmode=disable` | pgvector 必填 | pgvector 连接 | 对齐安装脚本默认端口 | 否 |
| `vector_store.schema` | `str` | `public` | pgvector 推荐 | pgvector 表空间 | PostgreSQL 通用默认 | 否 |
| `vector_store.table_name` | `str` | `ltm_memory` | pgvector 必填 | 长期记忆表名 | 与脚本初始化一致 | 是（脚本会初始化） |
| `vector_store.embedding_dimension` | `int` | `3072` | pgvector/milvus 推荐 | 向量表/集合维度 | 必须与 embedding 一致 | 否 |
| `vector_store.distance` | `str` | `cosine` | pgvector/qdrant 推荐 | 相似度度量 | 通用语义检索默认 | 否 |
| `vector_store.index_type` | `str` | `ivfflat` / `HNSW` | 否 | 检索性能 | 匹配不同后端习惯 | 否 |
| `vector_store.lists` | `int` | `100` | pgvector 推荐 | pgvector 索引调优 | 中小规模默认值 | 否 |
| `vector_store.metadata_fields` | `list[str]` | `scope_id/session_id/memory_type/...` | pgvector 推荐 | 过滤与治理 | 保证隔离与类型治理 | 是（项目建议） |
| `vector_store.host` | `str` | `127.0.0.1` | qdrant 必填 | qdrant 地址 | 本地开发默认 | 否 |
| `vector_store.port` | `int` | `6333` | qdrant 必填 | qdrant 地址 | 官方默认端口 | 否 |
| `vector_store.api_key` | `str` | `""` | qdrant 可选 | qdrant 认证 | 本地可空 | 否 |
| `vector_store.https` | `bool` | `false` | qdrant 可选 | qdrant 传输安全 | 本地开发默认关闭 | 否 |
| `vector_store.collection_name` | `str` | `context_agent_memory` | qdrant/milvus 必填 | 集合名称 | 语义明确 | 否 |
| `vector_store.uri` | `str` | `http://127.0.0.1:19530` | milvus 必填 | milvus 地址 | 官方默认端口 | 否 |
| `vector_store.token` | `str` | `""` | milvus 可选 | milvus 认证 | 本地可空 | 否 |
| `vector_store.metric_type` | `str` | `COSINE` | milvus 推荐 | milvus 相似度度量 | 与语义检索习惯一致 | 否 |
| `vector_store.index_params` | `dict` | `{M:16, efConstruction:200}` | milvus 推荐 | milvus 建索引参数 | 当前示例平衡吞吐与质量 | 否 |
| `vector_store.search_params` | `dict` | `{ef:64}` | milvus 推荐 | milvus 搜索参数 | 当前示例平衡吞吐与质量 | 否 |
| `memory_config.top_k` | `int` | `10` | 否 | 默认召回条数 | 适合多数上下文注入场景 | 否 |
| `memory_config.score_threshold` | `float` | `0.3` | 否 | 过滤低相关记忆 | 降低噪声召回 | 否 |
| `memory_config.enable_user_profile` | `bool` | `true` | 否 | 用户画像记忆 | 默认保留长期偏好 | 否 |
| `memory_config.enable_semantic_memory` | `bool` | `true` | 否 | 事实/语义记忆 | 默认保留知识型记忆 | 否 |
| `memory_config.enable_episodic_memory` | `bool` | `true` | 否 | 情节/事件记忆 | 默认保留任务过程结论 | 否 |
| `memory_config.enable_summary_memory` | `bool` | `true` | 否 | 摘要记忆 | 默认保留长会话压缩能力 | 否 |

填写建议：

- `llm_config` 与 `embedding_config` 至少要有一套可用的真实凭据，否则长期记忆只能退化。
- `embedding_config.dimension`、`vector_store.embedding_dimension`、向量表/集合维度必须一致。
- 切换后端时，只改 `openjiuwen.yaml`；不要把数据库连接信息移回 `context_agent.yaml`。
- 若你们使用的是不同 openJiuwen 版本，字段名以该版本 typed config 为准，但仍建议保持这份文件的分层结构不变。

### 5.1.6 在 ContextAgent 中自动加载配置

```python
from context_agent.config.settings import get_settings
from context_agent.config.openjiuwen import build_default_api_router

settings = get_settings()
router = build_default_api_router(settings=settings)
```

默认情况下，启动链路会：

1. 自动读取 `config/context_agent.yaml`
2. 再根据其中的 `openjiuwen_config_path` 读取 `config/openjiuwen.yaml`
3. 最后装配 `OpenJiuwenLTMAdapter`

若需要覆盖默认路径，可通过：

- `CA_CONTEXT_AGENT_CONFIG_PATH`
- `CA_OPENJIUWEN_CONFIG_PATH`

进行显式指定。

### 5.1.7 默认记忆编排链路

当前默认装配不是只把 openJiuwen 当成“一个可搜索的向量库”，而是把它作为**长期记忆底座**：

```text
HTTP/OpenClaw ingest
    -> MemoryOrchestrator
    -> WorkingMemoryManager
    -> AsyncMemoryProcessor
    -> OpenJiuwenLTMAdapter
    -> openJiuwen LongTermMemory
    -> pgvector（默认）/ qdrant / milvus
```

关键点：

1. **Working memory** 保存当前 session 的即时对话与结构化 note。
2. **MemoryOrchestrator** 负责把消息分类成 `procedural / semantic / episodic / variable`。
3. **AsyncMemoryProcessor** 负责异步写入、复用 openJiuwen 侧的去重/冲突检查能力。
4. **向量数据库实现仍不出现在 ContextAgent 业务代码里**，全部通过 openJiuwen 配置切换。

默认分类策略如下：

| 场景 | MemoryType | Category | 默认去向 |
|------|------------|----------|----------|
| 用户格式/语言/风格偏好 | `procedural` | `preferences` | working memory + openJiuwen LTM |
| 稳定身份/事实 | `semantic` | `profile` | working memory + openJiuwen LTM |
| 阶段决定、任务结论、完成状态 | `episodic` | `events` | working memory + openJiuwen LTM |
| 普通轮次消息 | `variable` | `events` | 仅 working memory |

如果调用方显式指定 `memory_type`，ContextAgent 会优先采用显式类型，再交给 openJiuwen 执行长期记忆写入。

### 5.1.8 写入接口示例

除了 `/context` 检索接口，也可以通过 `/context/write` 主动写入记忆：

```bash
curl -X POST http://localhost:8080/context/write \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "scope_id": "user:uid-123",
    "session_id": "sess-001",
    "content": "以后请默认使用中文回答，并用简洁格式输出。",
    "source_type": "user",
    "memory_type": "procedural",
    "metadata": {
      "source": "manual-write"
    }
  }'
```

这个接口会：

- 先把内容写入 `WorkingMemoryManager`
- 再通过 `MemoryOrchestrator` 决定是否进入长期记忆
- 若需要长期保留，则异步提交到 openJiuwen `LongTermMemory.add_messages()`

因此 `/context/write` 依然遵守同一条边界：**ContextAgent 不直接写 pgvector，而是写 openJiuwen。**

### 5.2 检索器适配器

```python
from context_agent.adapters.retriever_adapter import OpenJiuwenRetrieverAdapter
from openjiuwen.core.retrieval.retriever.hybrid_retriever import HybridRetriever
from openjiuwen.core.retrieval.reranker import StandardReranker

retriever = HybridRetriever(config=...)
reranker = StandardReranker(config=...)
retriever_adapter = OpenJiuwenRetrieverAdapter(
    hybrid_retriever=retriever,
    reranker=reranker,
)
```

### 5.3 上下文引擎适配器

```python
from context_agent.adapters.context_engine_adapter import OpenJiuwenContextEngineAdapter
from openjiuwen.core.context_engine.processor.compressor import DialogueCompressor

compressor = DialogueCompressor(config=...)
ce_adapter = OpenJiuwenContextEngineAdapter(
    context_engine=your_context_engine,
    compressor=compressor,
)
```

### 5.4 完整 openJiuwen 接入示例

```python
from context_agent import ContextAPIRouter, ContextAggregator
from context_agent.adapters.retriever_adapter import OpenJiuwenRetrieverAdapter
from context_agent.config.openjiuwen import build_openjiuwen_ltm_adapter
from context_agent.core.memory.tiered_router import TieredMemoryRouter
from context_agent.core.context.jit_resolver import JITResolver
import redis.asyncio as aioredis
from openjiuwen.core.retrieval.retriever.hybrid_retriever import HybridRetriever
from openjiuwen.core.retrieval.reranker import StandardReranker

redis_client = aioredis.from_url("redis://localhost:6379/0")

openjiuwen_cfg = {
    "user_id": "context-agent",
    "llm_config": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "${OPENAI_API_KEY}",
    },
    "embedding_config": {
        "provider": "openai",
        "model": "text-embedding-3-large",
        "api_key": "${OPENAI_API_KEY}",
        "dimension": 3072,
    },
    "vector_store": {
        "backend": "qdrant",
        "host": "127.0.0.1",
        "port": 6333,
        "collection_name": "context_agent_memory",
    },
}

openjiuwen_retriever = HybridRetriever(config=openjiuwen_cfg)
openjiuwen_reranker = StandardReranker(config=openjiuwen_cfg)

ltm_adapter = build_openjiuwen_ltm_adapter("config/openjiuwen.yaml")
retriever_adapter = OpenJiuwenRetrieverAdapter(
    hybrid_retriever=openjiuwen_retriever,
    reranker=openjiuwen_reranker,
)

tiered_router = TieredMemoryRouter(
    ltm=ltm_adapter,
    redis_client=redis_client,
)
jit_resolver = JITResolver(retriever=retriever_adapter, redis_client=redis_client)

aggregator = ContextAggregator(
    ltm=ltm_adapter,
    jit_resolver=jit_resolver,
)
router = ContextAPIRouter(aggregator=aggregator)
```

---

## 6. 上下文策略配置

### 6.1 环境变量配置（.env 文件）

```bash
# .env
CA_REDIS_URL=redis://localhost:6379/0
CA_DEFAULT_TOKEN_BUDGET=4096
CA_HOT_TIER_TIMEOUT_MS=20
CA_WARM_TIER_TIMEOUT_MS=100
CA_COLD_TIER_TIMEOUT_MS=300
CA_AGGREGATION_TIMEOUT_MS=200
CA_LOG_LEVEL=INFO
CA_AUTH_ENABLED=false
CA_API_KEYS=["key1","key2"]   # JSON list
CA_LLM_BASE_URL=http://localhost:11434
CA_LLM_MODEL=qwen2.5:7b
```

### 6.2 ExposurePolicy（上下文暴露控制）

控制哪些上下文片段对当前 Agent 可见：

```python
from context_agent.models.policy import ExposurePolicy
from context_agent.models.context import MemoryType

# 场景一：客服 Agent — 只允许业务相关记忆，屏蔽内部系统工具结果
customer_service_policy = ExposurePolicy(
    scope_id="user:123",
    allowed_source_types=["ltm", "scratchpad"],          # 排除 tool_result
    allowed_memory_types=[MemoryType.EPISODIC, MemoryType.PROCEDURAL, MemoryType.SEMANTIC],
    state_only_fields=["internal_audit_log"],             # 保留状态但不注入模型
)

# 场景二：代码审查 Agent — 只暴露代码相关工具
code_review_policy = ExposurePolicy(
    scope_id="task:pr-456",
    allowed_tool_ids=["git_operations", "test_runner", "code_search"],
)

# 场景三：子代理 — 最小权限原则
child_agent_policy = ExposurePolicy(
    scope_id="task:pr-456",
    allowed_source_types=["ltm"],
    allowed_memory_types=[MemoryType.SEMANTIC],  # 只允许事实知识
    allowed_scratchpad_fields=["current_task", "dependencies"],
)

output, warnings = await router.handle(
    scope_id="user:123",
    session_id="sess-001",
    query=user_query,
    policy=customer_service_policy,
)
```

### 6.3 Token 预算管理

```python
# 根据模型窗口和业务需求设置合理预算
output, _ = await router.handle(
    scope_id=scope_id,
    session_id=session_id,
    query=query,
    token_budget=3000,   # GPT-4o 128k 窗口，预留 1096 tokens 给模型输出
    output_type=OutputType.COMPRESSED,
)

# 检查是否触发降级
if output.degraded:
    logger.warning("context degraded", scope_id=scope_id)
```

---

## 7. 压缩策略定制

### 7.1 内置策略一览

| 策略 ID | 适用场景 | 特点 |
|--------|---------|------|
| `qa_compression` | 问答对话 | 保留高相关片段，截断低分项 |
| `task_compression` | 任务执行 | 保留状态和进度，压缩过程细节 |
| `long_session_compression` | 长会话 | 滚动摘要，保留关键转折点 |
| `realtime_compression` | 高实时场景 | < 5ms，无 LLM 调用，启发式截断 |
| `compaction` | 接近 token 上限 | LLM 高保真压缩，保留决策和约束 |

### 7.2 自定义策略

```python
from context_agent.strategies.base import CompressionStrategy
from context_agent.models.context import ContextOutput, ContextSnapshot, OutputType
from context_agent.strategies.registry import StrategyRegistry

class DomainSpecificStrategy(CompressionStrategy):
    """业务定制策略：针对金融客服场景。"""

    @property
    def strategy_id(self) -> str:
        return "finance_support"

    async def compress(self, snapshot: ContextSnapshot) -> ContextOutput:
        # 按记忆类型分组
        risk_items = [i for i in snapshot.items if "风险" in i.content or "投诉" in i.content]
        regular_items = [i for i in snapshot.items if i not in risk_items]

        sections = []
        if risk_items:
            sections.append("⚠️ 风险/投诉记录：\n" + "\n".join(f"• {i.content}" for i in risk_items))
        if regular_items:
            sections.append("客户背景：\n" + "\n".join(f"• {i.content[:100]}" for i in regular_items[:5]))

        content = "\n\n".join(sections)
        return ContextOutput(
            output_type=OutputType.COMPRESSED,
            scope_id=snapshot.scope_id,
            session_id=snapshot.session_id,
            content=content,
            token_count=len(content) // 4,
        )

    def estimate_tokens(self, snapshot: ContextSnapshot) -> int:
        return snapshot.total_tokens // 3

# 注册（在应用启动时调用一次）
StrategyRegistry.instance().register(DomainSpecificStrategy())
```

### 7.3 通过 HybridStrategyScheduler 控制策略选择

```python
from context_agent.orchestration.strategy_scheduler import (
    HybridStrategyScheduler, StrategySchedule, StrategySelectionContext
)

class MyScheduler(HybridStrategyScheduler):
    def schedule(self, ctx: StrategySelectionContext) -> StrategySchedule:
        # 自定义路由逻辑
        if ctx.task_type == "finance":
            return StrategySchedule(strategy_ids=["finance_support"])
        if ctx.utilisation > 0.9:
            return StrategySchedule(strategy_ids=["realtime_compression", "compaction"])
        return super().schedule(ctx)  # 使用默认逻辑
```

---

## 8. 子代理上下文委托

```python
from context_agent.orchestration.sub_agent_manager import SubAgentContextManager
from context_agent.models.policy import ExposurePolicy

manager = SubAgentContextManager()

# 主代理创建委托
child_view, ticket = await manager.delegate(
    parent_snapshot=current_snapshot,
    task_description="分析竞品定价策略",
    policy=ExposurePolicy(
        scope_id=current_snapshot.scope_id,
        allowed_source_types=["ltm"],                          # 只给公开信息
        allowed_memory_types=[MemoryType.SEMANTIC, MemoryType.EPISODIC],
    ),
    ttl_s=300.0,  # 5分钟超时
)

print(f"子代理作用域: {ticket.child_scope_id}")
print(f"可见上下文: {len(child_view.visible_items)} 条")

# 子代理执行任务后，将结果回传
result_items = await child_agent.execute(child_view, ticket.task_description)
merged = await manager.receive_result(ticket, result_items)

# 将结果合并入主代理上下文
for item in merged:
    main_snapshot.add_item(item)
```

---

## 9. 监控与告警接入

### 9.1 基础监控配置

```python
from context_agent.core.monitoring.collector import MonitoringCollector
from context_agent.core.monitoring.alert_engine import AlertEngine
from context_agent.models.metrics import AlertConfig, MetricRecord

# 配置告警阈值
alert_config = AlertConfig(
    latency_p95_threshold_ms=300.0,   # P95 超过 300ms 告警
    token_budget_threshold=4096,       # token 超预算告警
    health_score_min=0.5,              # 健康分数低于 0.5 告警
    cooldown_s=300.0,                  # 同类告警最小间隔 5 分钟
)

# 启动采集器
collector = MonitoringCollector(batch_size=50, flush_interval_s=10.0)
await collector.start()

# 绑定告警引擎
alert_engine = AlertEngine(config=alert_config, webhook_url="https://hooks.your-app.com/alerts")
collector.subscribe(alert_engine.evaluate_batch)
```

### 9.2 手动上报指标

```python
import time
from context_agent.models.metrics import MetricRecord

t0 = time.monotonic()
output, _ = await router.handle(...)
latency = (time.monotonic() - t0) * 1000

await collector.emit(MetricRecord(
    scope_id="user:123",
    operation="context_retrieval",
    latency_ms=latency,
    token_count=output.token_count,
    status="ok",
))
```

### 9.3 Prometheus 指标

若安装了 `prometheus_client`，以下指标自动可用：

```
context_agent_latency_seconds{operation, scope_id}   # 延迟直方图
context_agent_requests_total{operation, status}       # 请求计数器
```

暴露 metrics 端点：

```python
from prometheus_client import make_asgi_app
from fastapi import FastAPI

app = create_app(api_router=api_router)
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

---

## 10. 常见场景配方

### 场景一：问答型 Agent（RAG + 记忆）

```python
async def qa_agent_context(user_id: str, session_id: str, question: str) -> str:
    output, _ = await router.handle(
        scope_id=f"user:{user_id}",
        session_id=session_id,
        query=question,
        output_type=OutputType.COMPRESSED,
        task_type="qa",
        token_budget=2500,
    )
    return output.content
```

### 场景二：任务执行型 Agent（保留状态）

```python
async def task_agent_context(task_id: str, session_id: str, current_step: str) -> str:
    output, _ = await router.handle(
        scope_id=f"task:{task_id}",
        session_id=session_id,
        query=current_step,
        output_type=OutputType.COMPRESSED,
        task_type="task",
        token_budget=3500,
    )
    return output.content
```

### 场景三：长会话 Agent（滚动摘要）

```python
async def long_session_context(user_id: str, session_id: str, message: str, turn: int) -> str:
    # 超过 20 轮自动触发 long_session_compression
    output, _ = await router.handle(
        scope_id=f"user:{user_id}",
        session_id=session_id,
        query=message,
        output_type=OutputType.COMPRESSED,
        task_type="long_session" if turn > 20 else "qa",
        token_budget=3000,
    )
    return output.content
```

### 场景四：多 Agent 编排（主代理 + 子代理）

```python
# 主代理规划
plan_context, _ = await router.handle(
    scope_id=f"task:{task_id}", session_id=session_id,
    query="制定分析计划", output_type=OutputType.COMPRESSED, task_type="task",
)

# 委托子代理执行检索
child_view, ticket = await sub_agent_manager.delegate(
    parent_snapshot, task_description="检索行业报告",
    policy=ExposurePolicy(scope_id=f"task:{task_id}", allowed_source_types=["ltm"]),
)
research_results = await research_agent.run(child_view)
merged = await sub_agent_manager.receive_result(ticket, research_results)

# 合并后重新压缩
for item in merged:
    parent_snapshot.add_item(item)
```

### 场景五：接近 token 上限时 Compaction

```python
async def check_and_compact(snapshot, token_budget: int = 4096) -> ContextOutput:
    utilisation = snapshot.total_tokens / token_budget
    if utilisation > 0.85:
        ctx = StrategySelectionContext(
            scope_id=snapshot.scope_id,
            task_type="compaction",
            token_used=snapshot.total_tokens,
            token_budget=token_budget,
        )
        return await compression_router.route_and_compress(snapshot, ctx)
    return None
```

---

## 11. 性能调优参考

| 参数 | 默认值 | 调优建议 |
|------|-------|---------|
| `CA_HOT_TIER_TIMEOUT_MS` | 20ms | 生产环境可调整为 15ms |
| `CA_WARM_TIER_TIMEOUT_MS` | 100ms | LTM 响应慢时可调高至 150ms |
| `CA_AGGREGATION_TIMEOUT_MS` | 200ms | 多源并发时建议保持 200ms |
| `CA_DEFAULT_TOKEN_BUDGET` | 4096 | 按模型窗口和业务需求设置 |
| `memory_worker_count` | 2 | 高并发场景可调整为 4-8 |
| `CA_REDIS_POOL_MAX_CONNECTIONS` | 50 | 高 QPS 场景可调整为 100 |

### 热层缓存最佳实践

- 热层（Redis）TTL 默认 300 秒，适合当前会话状态
- 只有 `MemoryType.VARIABLE`（会话变量）自动写入热层
- 对于高频 scope，可主动调用 `tiered_router.warm_cache()` 预热

### JIT 检索缓存

- JIT 解析结果缓存 60 秒（`JIT_RESULT_CACHE_TTL_S`）
- 对同一 ref 的重复解析自动命中本地缓存，Redis 不可用时降级为进程内字典

---

## 12. 故障排查

### 常见问题

**Q: 上下文召回超时（warnings 包含 "timeout"）**

```
原因：某个数据源响应超过 AGGREGATION_TIMEOUT_MS
排查：
  1. 检查 Redis 是否可用：redis-cli ping
  2. 检查 LTM 服务响应时间
  3. 调高 CA_AGGREGATION_TIMEOUT_MS
  4. 确认 ContextAggregator 中 timeout_ms 设置
```

**Q: 压缩后 token_count 仍然很大**

```
排查：
  1. 检查 StrategyRegistry 是否注册了目标策略
  2. 查看 HybridStrategyScheduler 的调度结果（enable logging）
  3. 确认策略的 estimate_tokens() 是否准确
  4. 尝试手动指定 task_type="compaction"
```

**Q: ExposurePolicy 没有生效**

```
排查：
  1. 确认 policy 参数传入了 router.handle()
  2. 检查 allowed_source_types 是否匹配 ContextItem.source_type
  3. 查看 warnings：policy 过滤结果会出现在 warnings 中
```

**Q: openJiuwen 适配器报错**

```
排查：
  1. 确认 openjiuwen 已正确安装：pip show openjiuwen
  2. 确认 LongTermMemory 实例已正确初始化（config 必填字段）
  3. 适配器使用构造注入，确认传入了正确的实例类型
```

### 开启调试日志

```bash
CA_LOG_LEVEL=DEBUG python your_agent.py
```

或在代码中：

```python
from context_agent.utils.logging import configure_logging
configure_logging("DEBUG")
```

---

*更多示例参见 `examples/` 目录：*
- `basic_recall.py` — 最简上下文召回
- `sub_agent_delegation.py` — 子代理委托流程
- `compression_demo.py` — 压缩策略演示
- `tool_governance.py` — 工具治理演示
- `business_agent.py` — 完整 CRM 客服 Agent 集成

---

## 九、OpenViking 借鉴能力使用指南

### 9.1 used() 反馈 API — 驱动 Hotness Score

每次 LLM 调用后，上报哪些上下文 item 被实际使用，ContextAgent 会递增其 `active_count` 并提高后续排名。

```python
import httpx

async def report_used(scope_id: str, session_id: str, item_ids: list[str]):
    async with httpx.AsyncClient() as client:
        await client.post(
            "http://context-agent/context/used",
            json={
                "scope_id": scope_id,
                "session_id": session_id,
                "item_ids": item_ids,
            },
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

# 在 LLM 调用后调用：
snapshot = await context_agent.handle(scope_id, session_id, query)
response = await llm.chat(build_messages(snapshot))

# 上报实际用到的 item_ids（例如注入 system prompt 的条目）
used_ids = [item.item_id for item in snapshot.items[:3]]
await report_used(scope_id, session_id, used_ids)
```

### 9.2 quality 模式 — 复杂任务精准检索

对复杂多步骤任务，使用 `mode="quality"` 激活 `AgenticRetriever`（openJiuwen 原生）进行 LLM 驱动检索，延迟略高但召回精度更好。

```python
output, _ = await router.handle(
    scope_id=scope_id,
    session_id=session_id,
    query="分析 Q3 财务数据并生成执行摘要",
    mode="quality",        # 激活 AgenticRetriever
    token_budget=6000,
)
```

**最佳实践：** 对话消息用 `fast`，复杂规划任务用 `quality`。

### 9.3 MemoryCategory 分类过滤

按语义分类精确控制注入哪类记忆：

```python
from context_agent.models.context import MemoryCategory

# 只注入用户偏好 + 工作模式，不注入历史事件
output, _ = await router.handle(
    scope_id=scope_id,
    session_id=session_id,
    query=query,
    category_filter=[MemoryCategory.PREFERENCES, MemoryCategory.PATTERNS],
)
```

**写入时建议打标：**
```python
item = ContextItem(
    source_type="memory",
    content="用户偏好：输出中文简体，不使用项目符号",
    category=MemoryCategory.PREFERENCES,  # 标记语义分类
    level=ContextLevel.ABSTRACT,          # L0：轻量摘要
)
```

### 9.4 L0/L1/L2 分层上下文

通过 `max_level` 控制注入的上下文详细程度：

```python
from context_agent.models.context import ContextLevel

# 快速对话：只注入摘要（L0）
output, _ = await router.handle(..., max_level=ContextLevel.ABSTRACT)

# 深度任务：允许注入概要（L1）
output, _ = await router.handle(..., max_level=ContextLevel.OVERVIEW)

# 完整内容（默认）
output, _ = await router.handle(..., max_level=ContextLevel.DETAIL)
```

**写入建议：** 为同一内容写入多个层级的 ContextItem，level 字段分别设为 ABSTRACT/OVERVIEW/DETAIL，内容长度递增。

### 9.5 工具性能记忆

工具调用后上报结果，ContextAgent 积累成功率并在下次 `select_tools()` 时优先选择可靠工具：

```python
async def call_tool(tool_id: str, args: dict, gov: ToolContextGovernor):
    import time
    t0 = time.monotonic()
    try:
        result = await execute_tool(tool_id, args)
        gov.record_tool_result(tool_id, success=True, duration_ms=(time.monotonic()-t0)*1000)
        return result
    except Exception as e:
        gov.record_tool_result(tool_id, success=False, duration_ms=(time.monotonic()-t0)*1000)
        raise

# 或通过 HTTP：
await client.post("/tools/result", json={
    "scope_id": scope_id,
    "tool_id": "search_tool",
    "success": True,
    "duration_ms": 142.5,
})
```
