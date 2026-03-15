# 调试指南 (Debugging Guide)

ContextAgent 提供了一个统一的 CLI 工具 `scripts/debug.sh`，用于开发者和运维人员排查配置、连接性和组件健康问题。

## 🛠️ 调试工具概览

调试脚本将从主应用中隔离出特定的子系统（LLM、Embedding、向量数据库），以验证它们是否独立工作。这对于主服务无法启动或行为异常时的故障排查非常有用。

### 环境准备

无需手动安装额外依赖，`scripts/debug.sh` 脚本会自动检查并在虚拟环境中安装所需的调试依赖（如 `openai`, `asyncpg`, `pydantic`）。

```bash
# 直接运行 wrapper 脚本，它会自动处理依赖和 PYTHONPATH
./scripts/debug.sh --help
```

> **注意**: 如果环境缺失 Rust 编译器导致 `pip install` 失败，调试脚本可能无法自动安装 `pydantic` 等依赖。此时请确保基础环境已满足 `pyproject.toml` 中的要求。

## 🔍 常用命令

在项目根目录下运行以下命令。

### 1. 检查环境健康状况 (Check Environment)

验证配置文件、环境变量和数据库连接。

```bash
./scripts/debug.sh check-env
```

**检查内容:**
- `openjiuwen.yaml` 配置文件是否存在。
- YAML 语法是否合法。
- 是否能通过 TCP 连接到配置的向量数据库（如 pgvector）。

**输出示例:**
```text
Config Path: /Users/daniel/ContextAgent/config/openjiuwen.yaml
✅ Config file found
Vector Backend: pgvector
DSN: postgresql://postgres@127.0.0.1:55432/context_agent
✅ Database connection successful
```

### 2. 查看生效配置 (Show Config)

显示完全解析后的配置（已展开环境变量）。

```bash
./scripts/debug.sh config show
```

用此命令验证 `${OPENAI_API_KEY}` 等占位符是否已被 `.env` 文件正确替换。

### 3. 测试 Embedding 生成 (Test Embedding)

验证 Embedding 模型（如 OpenAI, Ollama）是否可达且认证正确。

```bash
./scripts/debug.sh embedding generate "Hello world"
```

**成功意味着:**
- API Key 有效。
- 网络连接畅通。
- 模型名称配置正确。

### 4. 测试 LLM 调用 (Test LLM)

向配置的 LLM 发送简单提示词，验证生成能力。

```bash
./scripts/debug.sh llm invoke "Say hello"
```

### 5. 检查向量记忆 (Inspect Memory)

直接查询底层向量存储，查看已持久化的数据。

**语义搜索:**
```bash
# 语法: memory search <query> [--scope-id <scope_id>] [--limit <limit>]
./scripts/debug.sh memory search "项目偏好" --scope-id openclaw
```

> **注意**: `scope_id` 必须与客户端请求中的 ID 一致（默认通常为 `openclaw`）。

## 🧠 长期记忆写入语义说明

`/context/write` 或 OpenClaw `/v1/openclaw/ingest` 返回成功时，**默认只表示 working memory 写入成功**。

这并不等于消息已经进入长期记忆。

当前 ContextAgent 的长期记忆策略是启发式的，只有以下内容会进入长期记忆异步队列：

- 偏好类信息，例如“以后请始终使用中文”
- 用户画像类信息，例如“我是 Daniel”
- 结论/完成类信息，例如“这个问题已经解决了”
- 显式传入 `memory_type` 的写入请求

普通闲聊或一般 user / assistant 对话，默认会被标记为 `working_memory_only`，因此即使接口返回 `accepted`，`ltm_memory` 也可能仍然为空。

## 📋 长期记忆排查日志

当前版本已补充长期记忆写入链路日志。排查时请重点搜索以下日志关键字：

- `context write accepted`
- `ltm enqueue planned`
- `ltm enqueue skipped`
- `ltm task enqueued`
- `ltm task processing started`
- `ltm task processing succeeded`
- `memory task processing failed`

推荐判断顺序：

1. 如果只有 `context write accepted`，但没有 `ltm enqueue planned`，说明消息只进入了 working memory。
2. 如果出现 `ltm enqueue planned`，但没有 `ltm task enqueued`，说明 enqueue 之前的逻辑有问题。
3. 如果出现 `ltm task enqueued` 和 `ltm task processing started`，但最终出现 `memory task processing failed`，说明异步 LTM 写入失败。
4. 如果出现 `ltm task processing succeeded`，再去检查 `ltm_memory` / 向量库侧数据。

## ⚠️ 常见问题与修复

### "Database connection failed" (数据库连接失败)
```text
❌ Database connection failed: [Errno 61] Connect call failed
Tip: Ensure pgvector service is running (scripts/start-all.sh)
```
**修复:**
- 检查 PostgreSQL 是否运行: `pg_isready` 或 `brew services list`。
- 确认 `.local/config/openjiuwen.yaml` 中的端口与运行的服务匹配（默认 55432）。
- 如果使用本地辅助脚本启动: `bash scripts/start-all.sh`。

### "No embedding model available" (无可用 Embedding 模型)
**症状:** 服务日志显示此错误，或 `debug.sh embedding generate` 失败。
**修复:**
- 检查 `.env` 中的 API Key。
- 确保 `openjiuwen.yaml` 包含有效的 `embedding_config` 部分。
- 如果使用 `pgvector`，确保已安装 `asyncpg` 驱动。

### `/context/write` 返回 `accepted`，但 `ltm_memory` 没有数据
**症状:** 接口返回成功，但长期记忆表仍为空。

**说明:**
- 这是当前设计下的常见现象，不一定代表故障。
- `accepted` 表示 working memory 已接收。
- 是否写入长期记忆，取决于消息分类是否命中长期记忆规则。

**建议排查:**
- 先搜索日志中的 `ltm enqueue skipped`
- 如果消息本应进入长期记忆，可显式传入 `memory_type`
- 如果日志中已有 `ltm task processing failed`，再继续排查 openJiuwen / embedding / 向量库问题

### "Event loop is closed" (事件循环已关闭)
**症状:** 启动或调试时出现 `RuntimeError: Event loop is closed`。
**修复:**
- 这通常发生在 `openJiuwen` 组件在一个 asyncio 循环中初始化但在另一个循环中使用时。
- `debug.py` 脚本通过为每个命令创建新的循环来处理此问题。
- 在主应用中，确保 `openJiuwen` 适配器是在启动生命周期内构建的。

## 📝 高级用法

调试脚本会自动加载 `.env` 文件。你也可以通过命令行内联覆盖特定变量：

```bash
OPENAI_API_KEY=sk-new-key... ./scripts/debug.sh llm invoke "test"
```
