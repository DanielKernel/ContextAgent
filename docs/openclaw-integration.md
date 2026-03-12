# ContextAgent × OpenClaw 3.8 集成指南

> 本文档面向 **OpenClaw 管理员和 Agent 开发者**，介绍如何将 ContextAgent 作为 OpenClaw 的 context-engine 插件接入，以及接入后的工作原理、配置说明和故障排查。

---

## 目录

1. [背景与原理](#1-背景与原理)
2. [快速开始（5分钟接入）](#2-快速开始)
3. [插件配置参考](#3-插件配置参考)
4. [生命周期详解](#4-生命周期详解)
5. [检索模式](#5-检索模式)
6. [多租户 / 多频道部署](#6-多租户--多频道部署)
7. [故障排查](#7-故障排查)
8. [API 端点参考](#8-api-端点参考)
9. [轻量替代：memory-kind 插件](#9-轻量替代memory-kind-插件)

---

## 1. 背景与原理

### OpenClaw context-engine 插件体系

OpenClaw 3.8（PR #22201）引入了 **context-engine 插件槽**，允许第三方服务替换内置的 Pi legacy 上下文管理器。插槽通过 `plugins.slots.contextEngine` 配置激活。

### ContextAgent 接管了什么

接入后，ContextAgent 全权负责：

| 职责 | 说明 |
|------|------|
| 历史上下文注入 | `assemble()` — 检索相关记忆，以 `systemPromptAddition` 形式注入 system prompt |
| 对话记忆持久化 | `ingest()` / `afterTurn()` — 将消息写入分层记忆存储 |
| token 溢出压缩 | `compact()` — 使用可插拔压缩策略（QA / 任务 / 长会话 / 实时 / 压缩归档） |
| 压缩策略选择 | `ownsCompaction: true` — 告知 OpenClaw 跳过内置 Pi 自动压缩 |

### 不接管的部分

- 消息格式转换（仍由 OpenClaw 的 sanitize/validate/limit 管道完成）
- 工具注册 / 工具调用执行（由 OpenClaw 原生处理）
- 身份认证 / 会话持久化（由 OpenClaw 原生处理）

---

## 2. 快速开始

### 步骤 1：启动 ContextAgent 服务

```bash
pip install context-agent

# 启动服务（默认监听 :8000）
uvicorn context_agent.main:app --host 0.0.0.0 --port 8000

# 验证健康状态
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0","uptime_s":2.3}
```

### 步骤 2：安装插件

```bash
# 本地路径安装（开发阶段）
openclaw plugins install /path/to/ContextAgent/plugins/context-agent

# 或从 npm 安装（发布后）
openclaw plugins install @context-agent/context-agent-plugin
```

### 步骤 3：配置激活

编辑 `~/.openclaw/config.yaml`：

```yaml
plugins:
  slots:
    contextEngine: "context-agent"   # 将 context-agent 设为活跃 context engine
  entries:
    context-agent:
      enabled: true
      config:
        baseUrl: "http://localhost:8000"
```

### 步骤 4：测试对话

在 OpenClaw 中发起一轮对话，查看 ContextAgent 日志验证接入：

```
[info] openclaw.assemble completed scope_id=openclaw session_id=xxx latency_ms=45.2 token_count=312
[info] openclaw.after_turn completed scope_id=openclaw session_id=xxx updated_count=2
```

---

## 3. 插件配置参考

```yaml
plugins:
  entries:
    context-agent:
      enabled: true
      config:
        # ── 必填 ──────────────────────────────────────────────────
        baseUrl: "http://localhost:8000"   # ContextAgent 服务地址

        # ── 可选 ──────────────────────────────────────────────────
        apiKey: ""                         # Bearer Token（服务无认证时留空）
        scopeId: "openclaw"                # 记忆命名空间（建议按频道或用户设置）
        timeoutMs: 5000                    # HTTP 超时（毫秒）
        contextTokenBudget: 2048           # 每轮注入的最大 token 数
        retrievalMode: "fast"              # "fast"（混合检索）或 "quality"（LLM 驱动）
        topK: 8                            # 每轮检索的上下文条数
        minScore: 0.01                     # 相关性过滤阈值（0–1），低于此分数不注入
```

### 配置项说明

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `baseUrl` | — | ContextAgent HTTP 服务地址。必填。 |
| `apiKey` | `""` | Bearer 认证 Token。设置了认证的生产部署必填。 |
| `scopeId` | `"openclaw"` | 记忆隔离粒度。同一 `scopeId` 下所有会话共享长期记忆。 |
| `timeoutMs` | `5000` | 超时后插件以 graceful fallback 继续（不阻断对话）。 |
| `contextTokenBudget` | `2048` | 控制注入 system prompt 的上下文量，避免稀释模型注意力。 |
| `retrievalMode` | `"fast"` | 见[检索模式](#5-检索模式)。 |
| `topK` | `8` | 每轮最多注入 K 个上下文片段（实际由 token budget 进一步约束）。 |
| `minScore` | `0.01` | 相关性最低分数阈值；低于此值的片段不注入，避免噪声上下文干扰。 |

---

## 4. 生命周期详解

### 4.1 调用序列（attempt.ts）

```
OpenClaw attempt.ts
│
├── [hadSessionFile=true]  → bootstrap()
│     ContextAgent: 从 messages 构建 ContextItem，写入 working memory
│                   仅恢复会话态，不重复写入长期记忆
│
├── sanitize / validate / limit  （OpenClaw 原生，不经过 ContextAgent）
│
├── assemble()             ← 每轮必调
│     ContextAgent: 检索 top-K 相关上下文
│     返回: systemPromptAddition = "# Relevant Context\n\n{context}"
│     OpenClaw: prepend systemPromptAddition 到 system prompt
│
├── [LLM API call]         （OpenClaw 原生）
│
├── afterTurn()            ← 每轮必调（ContextAgent 优先于 ingestBatch fallback）
│     ContextAgent: mark_used(用到的上下文 IDs) → active_count+1
│                   assistant reply 进入 working memory
│                   若命中偏好 / 事实 / 阶段结论规则，则异步写入 openJiuwen LTM
│
└── [token overflow]       → compact()
      ContextAgent: CompressionStrategyRouter → 压缩后的 messages
```

### 4.2 Mode B 注入策略

ContextAgent 使用 **Mode B（注入模式）**：原始 `messages` 原样透传，检索到的上下文以 `systemPromptAddition` 追加到 system prompt 头部。

**模型感知到的 system prompt 结构：**
```
# Relevant Context

{检索到的相关上下文片段，按 Hotness Score + 相关性排序}

---
{原始 system prompt}
```

### 4.3 Hotness Score 反馈闭环

```
assemble() → 返回 context_item_ids（注入了哪些片段）
          ↓
afterTurn() → 传入 used_context_item_ids（同一批 IDs）
           ↓
mark_used() → active_count += 1（被用到的片段热度上升）
           ↓
下次 assemble() → Hotness Score 权重更高 → 热点记忆优先召回
```

### 4.4 记忆写入策略

当前默认策略参考 Anthropic / OpenAI / OpenClaw 的常见做法，采用“**先写 working memory，再选择性异步沉淀长期记忆**”：

- 所有新消息先进入 session 级 working memory，保证当前会话可立即召回
- 明确的**用户偏好**（如语言、格式、风格约束）会标记为 `procedural + preferences`
- 稳定的**用户画像 / 事实**会标记为 `semantic + profile`
- 阶段性**决定 / 结论 / 完成状态**会标记为 `episodic + events`
- 长期记忆写入统一交给 `AsyncMemoryProcessor -> OpenJiuwenLTMAdapter -> openJiuwen LongTermMemory`

这条链路里，ContextAgent 只负责分类和治理；真正的向量写入仍由 openJiuwen 根据配置完成，默认向量后端为 `pgvector`。

### 4.5 默认部署边界

若启用了 `CA_OPENJIUWEN_CONFIG_PATH`：

- ContextAgent 启动时会装配 `WorkingMemoryManager`
- 同时创建 `MemoryOrchestrator` 与 `AsyncMemoryProcessor`
- 长期记忆后端仍只从 openJiuwen 配置文件读取
- 默认示例配置为 `pgvector`，但 OpenClaw 接入方式本身不绑定具体向量库

---

## 5. 检索模式

### fast 模式（默认，推荐实时对话）

- **机制**：HybridRetriever — 向量相似度 + 关键词并发检索，RRF 融合 + Hotness Score 加权
- **延迟目标**：P95 ≤ 100ms
- **适用**：日常问答、实时消息

### quality 模式（复杂任务）

- **机制**：AgenticRetriever — LLM 分析意图，生成多个 TypedQuery，分类型检索，priority 加权融合
- **延迟目标**：P95 ≤ 300ms  
- **适用**：多步骤任务规划、需要精确上下文的技术分析

**配置切换：**
```yaml
config:
  retrievalMode: "quality"
```

---

## 6. 多租户 / 多频道部署

### 方案一：共享 scopeId（简单部署）

所有频道共享同一记忆命名空间，适合单用户或小团队：

```yaml
config:
  scopeId: "my-assistant"
```

### 方案二：按频道隔离（推荐生产部署）

每个 OpenClaw 频道独立记忆，防止不同对话的上下文互相污染：

```yaml
# 通过环境变量或频道配置派生 scopeId
config:
  scopeId: "channel-general"    # 或 "user-alice"、"project-alpha" 等
```

**记忆隔离原则：**
- 同一 `scopeId` 的所有 `session_id` 共享长期记忆（跨会话记忆迁移）
- 不同 `scopeId` 完全隔离（向量索引独立分区）

---

## 7. 故障排查

### 插件加载失败

```
[error] Failed to load plugin context-agent
```

**检查：**
1. ContextAgent 服务是否运行：`curl http://localhost:8000/health`
2. `baseUrl` 是否正确（无尾随斜杠）
3. 插件目录结构是否完整：`ls plugins/context-agent/`

### assemble 超时

```
[warn] context-agent assemble failed: AbortError: This operation was aborted
```

**处理：** 插件自动 graceful fallback，对话不中断，但此轮无上下文注入。

**排查：**
1. 增大 `timeoutMs`
2. 检查 ContextAgent 服务负载
3. 降低 `topK` 或切换到 `fast` 模式

### 上下文注入但无效

**症状：** assemble 日志显示 token_count > 0 但模型未利用上下文。

**可能原因：**
1. `contextTokenBudget` 太小，重要内容被截断
2. `scopeId` 设置错误，检索到了错误频道的记忆
3. 检索模式设置为 `fast` 但任务复杂度需要 `quality`

---

## 8. API 端点参考

所有端点路径前缀：`POST /v1/openclaw/`

### bootstrap

```json
// 请求
{
  "scope_id": "string",
  "session_id": "string",
  "messages": [{"role": "user|assistant|system", "content": "string"}]
}
// 响应
{"status": "ok", "items_loaded": 5}
```

### ingest

```json
// 请求
{
  "scope_id": "string",
  "session_id": "string",
  "messages": [{"role": "user", "content": "string"}]   // min_length: 1
}
// 响应
{"status": "ok", "ingested_count": 1}
```

### assemble

```json
// 请求
{
  "scope_id": "string",
  "session_id": "string",
  "messages": [...],
  "query": "",              // 可选，空时从最后一条 user 消息派生
  "token_budget": 2048,
  "top_k": 8,
  "mode": "fast",           // "fast" | "quality"
  "min_score": 0.01         // 相关性过滤阈值（0–1），低于此分数的记忆不注入
}
// 响应
{
  "messages": [...],                           // 原样返回（Mode B）
  "system_prompt_addition": "# Relevant Context\n\n...",
  "context_item_ids": ["item-001", "item-002"], // 用于 after-turn 反馈
  "estimated_tokens": 512                       // messages + addition 的估算 token 数
}
```

### compact

```json
// 请求
{
  "scope_id": "string",
  "session_id": "string",
  "messages": [...],
  "token_limit": 8192,
  "force": false,              // 强制压缩（即使未超限）
  "compaction_target": "budget", // "budget" | "threshold"
  "custom_instructions": ""    // 可选：自定义压缩指令
}
// 响应
{
  "messages": [...],           // 压缩后的消息列表
  "tokens_before": 9800,
  "tokens_after": 3200,
  "status": "ok",
  "summary": "..."             // 可选：压缩摘要（前 200 字符）
}
```

### after-turn

```json
// 请求
{
  "scope_id": "string",
  "session_id": "string",
  "assistant_message": {"role": "assistant", "content": "string"},
  "used_context_item_ids": ["item-001", "item-002"]  // 来自 assemble 响应
}
// 响应
{"status": "ok", "updated_count": 2}
```

---

## 9. 轻量替代：memory-kind 插件

如果只需要**工具式记忆**而不需要完整 lifecycle 控制，可使用 `openclaw-memory-plugin`（`plugins/openclaw-memory-plugin/`）。

### 与 context-engine 插件的对比

| | context-engine 插件 | memory-kind 插件 |
|---|---|---|
| **拥有 compaction** | ✅ `ownsCompaction: true` | ❌ |
| **控制 assemble** | ✅ | ❌ |
| **提供 LLM 工具** | ❌ | ✅ 3 个工具 |
| **自动 recall hook** | ❌ | ✅ before_agent_start |
| **适合场景** | 完整上下文生命周期管理 | 轻量记忆工具增强 |

### 安装与配置

```bash
openclaw plugins install /path/to/plugins/openclaw-memory-plugin
```

```yaml
plugins:
  entries:
    context-agent-memory:
      enabled: true
      config:
        baseUrl: "http://localhost:8000"
        scopeId: "openclaw"
        autoRecall: true          # 每轮自动召回
        autoRecallTopK: 5
        autoRecallMinScore: 0.01
        autoCapture: false        # 是否自动存储 assistant 回复
```

### 提供的工具

- **`memory_recall(query)`** — 检索相关记忆，返回格式化文本
- **`memory_store(content, memory_type?)`** — 存储新记忆，返回 item_id
- **`memory_forget(item_id)`** — 删除指定记忆

### 与 context-engine 插件联用

两个插件可以同时启用（`autoRecall: false` 避免双重召回）：

```yaml
plugins:
  slots:
    contextEngine: "context-agent"
  entries:
    context-agent:
      enabled: true
      config:
        baseUrl: "http://localhost:8000"
    context-agent-memory:
      enabled: true
      config:
        baseUrl: "http://localhost:8000"
        autoRecall: false   # context-engine 已负责检索
        autoCapture: false
```
