# Examples 目录说明

本目录提供一组面向不同能力面的示例，帮助你快速理解 ContextAgent 在**上下文聚合、压缩、工具治理、子代理隔离、业务 Agent 集成**以及 **双配置文件（ContextAgent + openJiuwen）**上的典型用法。

## 使用建议

- 大多数 `.py` 示例都可以直接运行：`python examples/<file>.py`
- 这些 Python 示例默认以 **stub / in-memory** 方式演示能力，不要求先完成 openJiuwen 安装
- `examples/configs/<backend>/` 下提供标准命名的配置样例，每个场景目录都直接包含 `context_agent.yaml` 和 `openjiuwen.yaml`
- 如果你想接入真实长期记忆，优先使用运行态配置 `.local/config/context_agent.yaml` 与 `.local/config/openjiuwen.yaml`；仓库 `config/` 目录更适合作为静态模板，示例目录主要用于理解不同后端/场景如何填写

## 示例总览

| 示例 | 对应 UC | 主要能力 | 适合场景 | 如何定制 |
| --- | --- | --- | --- |
| `basic_recall.py` | `UC001` / `UC007` | 最小化上下文召回、`ContextAggregator` | 快速理解“查什么、返回什么” | 替换 `StubLTM`、修改 `AggregationRequest`、调整 `top_k` / `token_budget` |
| `compression_demo.py` | `UC009` | 压缩策略注册、手工策略、压缩路由 | 设计自己的压缩输出格式 | 新增 `CompressionStrategy`、替换 `schedule()`、修改 `ContextSnapshot` 内容 |
| `tool_governance.py` | `UC011` | 工具选择、工具上下文裁剪 | 大工具集场景，避免上下文膨胀 | 修改 `ToolDefinition`、扩展 `task_type`、替换工具描述和分类 |
| `sub_agent_delegation.py` | `UC006` / `UC014` | 子代理上下文隔离、暴露控制、结果回流 | 主 Agent 向子 Agent 委派任务 | 修改 `ExposurePolicy`、替换 parent snapshot、调整 child 可见 source types |
| `business_agent.py` | `UC001` / `UC007` / `UC009` / `UC011` | 业务 Agent 综合集成 | CRM / support / enterprise agent 原型 | 替换 CRM stub 数据、注入真实 LTM、替换压缩策略、接入真实工具治理 |
| `configs/pgvector/context_agent.yaml` + `configs/pgvector/openjiuwen.yaml` | 配置基线 | 默认 pgvector 双配置样例 | 本地 / 默认部署 | 修改端口、日志、DSN、embedding 维度、索引参数、模型配置 |
| `configs/qdrant/context_agent.yaml` + `configs/qdrant/openjiuwen.yaml` | 配置基线 | qdrant 双配置样例 | 轻量试验环境 | 修改 host/port/collection、模型配置、服务参数 |
| `configs/milvus/context_agent.yaml` + `configs/milvus/openjiuwen.yaml` | 配置基线 | milvus 双配置样例 | 高吞吐向量检索场景 | 修改 `uri`、collection、index/search 参数、服务参数 |

## Python 示例详解

### `basic_recall.py`

这个示例展示最基础的一条链路：

1. 构造一个最小的长期记忆 stub
2. 使用 `ContextAggregator` 发起一次 `AggregationRequest`
3. 返回 `ContextSnapshot`

它主要演示：

- `scope_id` / `session_id` / `query` 如何进入聚合流程
- `ContextItem` 的最小字段结构
- `top_k` 和 `token_budget` 如何影响召回结果

常见定制方式：

- 把 `StubLTM.search()` 替换成你自己的适配器
- 调整 `SEED_DATA`，模拟偏好、事实、事件等不同记忆类型
- 增加 `working_memory` 或 `refs`，让示例更接近真实调用链

### `compression_demo.py`

这个示例聚焦在“**如何压缩上下文**”。

它包含两层能力：

- 直接使用自定义 `CompressionStrategy`
- 通过 `CompressionStrategyRouter` + `HybridStrategyScheduler` 路由压缩

它主要演示：

- 如何实现一个新的 `CompressionStrategy`
- 如何把策略注册进 `StrategyRegistry`
- 如何通过自定义 scheduler 固定选择某种压缩策略

常见定制方式：

- 把 `KeywordExtractionStrategy` 替换成适合你业务的摘要格式
- 修改 `build_large_snapshot()`，构造更真实的上下文分布
- 用你的 `task_type` / `agent_role` 替换固定 scheduler，观察路由行为

### `tool_governance.py`

这个示例演示“**工具不是越多越好，而是按任务暴露最相关的工具**”。

它主要覆盖：

- `ToolDefinition` 建模
- `ToolContextGovernor.select_tools()` 选择工具
- `ToolContextGovernor.get_tool_context_items()` 生成可注入上下文

常见定制方式：

- 把 `ALL_TOOLS` 换成你自己的工具清单
- 调整 `required_for_task_types`
- 增加更细的 category / description，让治理效果更稳定

如果你的 Agent 工具集很多，这个示例最适合作为起点。

### `sub_agent_delegation.py`

这个示例演示主 Agent 如何：

1. 准备 parent context
2. 通过 `ExposurePolicy` 控制子代理可见范围
3. 使用 `SubAgentContextManager.delegate()` 下发子任务
4. 在子任务完成后把结果回流到主上下文

它主要覆盖：

- `ExposurePolicy`
- `SubAgentContextManager`
- 子代理上下文隔离与结果合并

常见定制方式：

- 修改 `allowed_source_types`，限制子代理看到的上下文来源
- 替换 parent snapshot 中的敏感内容，验证暴露控制是否生效
- 把 `result_items` 换成真实子代理输出

### `business_agent.py`

这是最完整的综合示例，适合理解 ContextAgent 在业务 Agent 中如何整体协作。

它同时演示：

- 长期记忆查询（这里用 CRM stub）
- 自定义压缩策略
- 工具治理
- 上下文路由
- 业务层请求对象与处理流程

这个示例适合拿来改造成你自己的业务原型，例如：

- 客服 Agent
- CRM / ERP 助手
- 内部运营问答助手

常见定制方式：

- 把 `CRMStubLTM` 替换成真实 openJiuwen LTM 适配器
- 把 `SupportContextStrategy` 改成你自己的场景摘要格式
- 把 `SUPPORT_TOOLS` 换成你的业务工具集
- 在 `handle_enquiry()` 中接入真实大模型调用

## 标准双配置样例详解

### `configs/pgvector/`

这个目录演示默认推荐的 **pgvector 双配置**：

- `context_agent.yaml`：ContextAgent 服务配置
- `openjiuwen.yaml`：openJiuwen 的 LLM / embedding / vector / memory 配置

重点字段：

- `context_agent.yaml`
  - `http.port`
  - `service.log_level`
  - `integrations.openjiuwen.config_path`
- `openjiuwen.yaml`
  - `vector_store.dsn`
  - `vector_store.embedding_dimension`
  - `vector_store.index_type`
  - `llm_config`
  - `embedding_config`

### `configs/qdrant/`

适合轻量试验环境，重点看：

- `context_agent.yaml` 中的分段服务参数是否需要调整
- `openjiuwen.yaml` 中的 `host` / `port`
- `collection_name`
- 模型与 embedding 配置

### `configs/milvus/`

适合更高吞吐或更独立的向量服务部署，重点看：

- `context_agent.yaml` 中的分段服务参数是否需要调整
- `openjiuwen.yaml` 中的 `uri`
- `collection_name`
- `index_type`
- `index_params`
- `search_params`

## 如何从示例迁移到真实项目

推荐按下面顺序做：

1. 先从 `basic_recall.py` 理解最小召回链路
2. 再看 `compression_demo.py`，确定你需要的压缩输出形式
3. 如果工具很多，接着看 `tool_governance.py`
4. 如果存在主从 Agent 协作，再看 `sub_agent_delegation.py`
5. 最后以 `business_agent.py` 为蓝本接入真实业务

如果你希望把示例与测试一一对照，可以同时查看：

- `tests/README.md`：需求用例到测试文件的覆盖矩阵
- `docs/requirements-analysis.md`：UC001–UC016 的原始需求描述

如果你要接入真实长期记忆：

1. 先查看运行态默认配置：`.local/config/context_agent.yaml` 与 `.local/config/openjiuwen.yaml`（不存在时可参考仓库 `config/` 模板）
2. 如果需要切换后端，再参考 `examples/configs/<backend>/` 下的标准样例
3. 需要覆盖路径时，可设置 `CA_CONTEXT_AGENT_CONFIG_PATH` / `CA_OPENJIUWEN_CONFIG_PATH`
4. 通过 `context_agent.config.openjiuwen.build_default_api_router()` 或你自己的启动入口装配

## 定制时的几个注意点

- 长期记忆仍应通过 **openJiuwen** 接入，不要在示例基础上直接绕过 openJiuwen 去连向量库
- `scope_id` 是最重要的隔离键，改造示例时要优先明确它的业务语义
- `MemoryType` 和 `ContextItem` 元数据会影响压缩、过滤和召回质量，建议保留
- 若你把示例改成真实 HTTP 服务，请确保日志和环境变量配置与生产环境一致
