# ContextAgent 记忆能力全景与优化路线图

本文档用于同时承载四类内容：

1. `ContextAgent` 与 `openJiuwen` 当前记忆能力的**全景盘点**。
2. `Awesome-Agent-Memory` 论文库对这些能力空间的**全量覆盖映射**。
3. 多个开源记忆项目清单对这些能力空间的**工程实践映射**。
4. 基于不同优化目标生成的**可切换路线图**；当前第一条路线聚焦“改善多轮对话体验”。

---

## 1. 文档目标与使用方式

本文档不再以“逐篇论文长文分析”为主，而改为**能力矩阵驱动**。

这样做有四个原因：

1. `Awesome-Agent-Memory` 论文库已经很大，当前上游 README 中可解析的论文/资源条目已达到 **221** 条，继续按论文平均展开会迅速失控。
2. 新增的三个 “awesome memory” 仓库收录了大量**开源项目、框架、MCP、存储后端、benchmark 与工程实践**，如果不单独建模，会把“方法论”和“工程借鉴对象”混在一起。
3. `ContextAgent` 与 `openJiuwen` 的演进需要的是“能力缺口 -> 能力增强/新增 -> 优先级”的映射，而不是只积累论文摘要。
4. 后续路线图会按不同目标切换优先级，因此需要一张稳定的能力全景表作为底座。

**推荐阅读顺序**：

1. 先看“语料全景与覆盖方式”，理解论文库与开源项目库如何被映射进能力空间。
2. 再看“ContextAgent / openJiuwen 当前能力清单”，了解当前真实基线。
3. 然后看“能力全景与对比矩阵”，判断哪些属于增强型能力、哪些属于新增型能力，以及有哪些可直接借鉴的工程实践。
4. 最后按当前优化目标查看对应路线；当前第一条路线聚焦“多轮对话体验”。

---

## 2. 语料全景与覆盖方式

### 2.1 论文语料来源与当前规模

分析对象来自：

- `https://github.com/AgentMemoryWorld/Awesome-Agent-Memory`

该仓库自述以 taxonomy 方式整理 foundation agent memory 方向论文。当前 README 中可解析出：

- **221** 条论文/资源项
- taxonomy 主维度：
  - **Memory Substrate**：external / internal
  - **Memory Cognitive Mechanism**：sensory / working / episodic / semantic / procedural
  - **Memory Subject**：user-centric / agent-centric

> 注：仓库简介中仍写“218 key articles”，但当前 README 实际条目数已更高，说明论文库仍在持续更新。后续应以最新 README 解析结果为准。

### 2.2 项目 / 实践语料来源与当前规模

除论文语料外，当前还纳入以下三个“项目 / 工程实践”仓库：

- `https://github.com/XiaomingX/awesome-ai-memory`
- `https://github.com/topoteretes/awesome-ai-memory`
- `https://github.com/IAAR-Shanghai/Awesome-AI-Memory`

这三个仓库的价值并不相同：

| 来源 | 主要价值 | 对 roadmap 的补充作用 |
| --- | --- | --- |
| `XiaomingX/awesome-ai-memory` | 偏“项目选型与工程实践分层” | 帮助识别 integrated memory layer、MCP、本地记忆工具、基础设施、持续学习等**落地形态** |
| `topoteretes/awesome-ai-memory` | 偏“AI memory 工具市场图谱” | 帮助建立 memory tool / framework / storage 的**生态对比视角** |
| `IAAR-Shanghai/Awesome-AI-Memory` | 同时包含 papers、systems/open source、benchmarks/tasks | 帮助补齐 **系统实现、benchmark 与 control/evaluation** 视角 |

从结构上看，这些仓库提供了三类关键增量：

1. **直接可借鉴的记忆系统实现**：如 `Mem0`、`Zep`、`Graphiti`、`LangMem`、`Letta`、`cognee`、`GraphRAG`。
2. **可作为外围集成或后端能力的生态组件**：如 `Neo4j`、`Chroma`、`Milvus`、`Qdrant`、`Weaviate`、`FalkorDB`。
3. **不应直接等同于核心记忆能力、但对规划有启发的相邻实践**：如 benchmark/tasks、continual learning、online RLHF、distributed training、MCP skill ecosystem。

### 2.3 双轴覆盖策略

本路线图采用“**按能力项聚合**”作为主视图，并为每个能力项保留两条映射轴：

也就是说：

- **不是**为 221 篇论文和多个开源项目逐条写对称篇幅的评述。
- **而是**先将全部论文与项目/实践吸收到统一的能力空间中，再对每个能力簇判断：
  - ContextAgent 是否已有基础
  - openJiuwen 是否已有 substrate / backend / retrieval 支撑
  - 这是“增强型能力”还是“新增型能力”
  - 有哪些可直接借鉴的工程实践
  - 是否与当前优化目标强相关

两条映射轴分别是：

1. **论文轴**
   - 提供机制、范式、评测、方法论依据。
2. **项目 / 实践轴**
   - 提供实现形态、架构取舍、生态依赖和集成参考。

为了避免误判，本路线图还会对项目 / 实践增加三类标记：

- **类型**：`memory tool` / `framework` / `MCP` / `storage` / `benchmark` / `infra` / `training`
- **相关度**：
  - `direct`：可以直接映射为 ContextAgent 记忆能力
  - `adjacent`：与记忆能力强相关，但更像外围实现或配套模块
  - `ecosystem`：更多是生态支撑，不应直接计入核心能力
- **借鉴方式**：
  - `直接增强`
  - `参考实现`
  - `生态配套`

### 2.4 论文库 taxonomy 覆盖快照

| 维度 | 标签 | 当前可解析条目数 | 对 ContextAgent 的意义 |
| --- | --- | ---: | --- |
| Substrate | `external` | 181 | 对应外部长期记忆、向量库、日志、数据库、记忆服务，和 ContextAgent 当前架构最相关 |
| Substrate | `internal` | 31 | 对应长上下文、KV cache、参数化/internal memory，更偏后续增强方向 |
| Mechanism | `semantic` | 89 | 抽象知识、用户画像、稳定事实、summary memory |
| Mechanism | `episodic` | 84 | 对话轨迹、经验回放、episode reconstruction、narrative memory |
| Mechanism | `working` | 69 | scratchpad、任务状态、短时变量、当前回合上下文 |
| Mechanism | `procedural` | 37 | 技能库、tool pattern、policy、经验反思、技能演化 |
| Mechanism | `sensory` | 25 | 多模态/流式/高频输入记忆，目前超出 ContextAgent 主链路但值得预留 |
| Subject | `agent` | 139 | agent 自身轨迹、策略、技能、反思与自我改进 |
| Subject | `user` | 64 | 用户事实、偏好、历史与个性化持续性 |

### 2.5 从语料库到“可落地能力簇”

为了让语料库能服务工程规划，本文把所有论文进一步吸收进下列能力簇：

1. 外部长时记忆 substrate
2. working memory / scratchpad
3. episodic consolidation / narrative memory
4. semantic abstraction / memory card
5. procedural / skill memory
6. user-centric personalization
7. agent-centric experience memory
8. retrieval routing / gating / rerank
9. cross-turn carryover / anti-redundancy
10. compression / compaction / abstraction balancing
11. multi-agent handoff / delegated evidence extraction
12. sensory / multimodal memory
13. utility governance / privacy / contradiction control
14. evaluation / benchmark / policy learning

这 14 个能力簇共同覆盖了当前论文语料和项目 / 实践语料的主干能力空间；后续所有新增条目都应优先映射到这些能力簇之一或若干簇。

### 2.6 项目 / 实践语料的额外观察

与纯论文语料相比，项目 / 实践语料还暴露了几个此前在文档里不够显式的问题：

1. **记忆层不等于存储层**
   - 像 `Mem0`、`Zep`、`Graphiti`、`LangMem`、`Letta`、`cognee` 这类项目提供的是更接近“memory layer / memory service”的能力。
   - 像 `Neo4j`、`Qdrant`、`Chroma`、`Milvus`、`Weaviate` 则更偏 substrate / storage。
   - 对 `ContextAgent` 来说，真正可直接借鉴的通常是前者；后者更适合作为 `openJiuwen` 后端生态的一部分。
2. **MCP / 本地工具强调的是“外部工作记忆接口”**
   - `Basic Memory`、`meMCP`、`memento-mcp`、`agentcortex-mcp` 一类项目，本质上强化的是可读写、可审计、可本地持久化的外部记忆接口。
   - 这对 `ContextAgent` 的启发是：working memory / scratchpad 不必只存在于进程内或 Redis，还可以抽象成更可审计的 file/DB/tool backed working memory。
3. **Benchmark / continual learning / online RLHF 更像规划边界提醒**
   - 这些资源不意味着要把 `ContextAgent` 立刻改造成训练平台。
   - 但它们提醒：长期对话体验的优化不能只做“召回更聪明”，还要补 continuity / redundancy / recovery / drift 的评测与治理闭环。

---

## 3. ContextAgent 与 openJiuwen 当前能力清单

### 3.1 ContextAgent 当前已落地能力

| 能力方向 | 当前状态 | 主要位置 | 说明 |
| --- | --- | --- | --- |
| 多源上下文聚合 | 已有 | `ContextAggregator` | 并行聚合 LTM、working memory、JIT refs，并支持 token budget 与降级 |
| 分层召回 | 已有 | `TieredMemoryRouter` | 区分 hot / warm / cold，并按时延预算逐层召回 |
| 混合检索与融合 | 已有 | `UnifiedSearchCoordinator` | 支持 hybrid / graph / LTM 并行以及 RRF 融合 |
| 工作记忆 | 已有 | `WorkingMemoryManager` | session 级 notes / items；Redis 不可用时回退到进程内存 |
| 异步长期写入 | 已有 | `MemoryOrchestrator` + `AsyncMemoryProcessor` | 当前链路已打通 working memory -> async -> LTM |
| 基础记忆分类 | 已有但较轻量 | `MemoryOrchestrator._classify_message()` | 已区分 `VARIABLE / EPISODIC / SEMANTIC / PROCEDURAL`，但仍偏规则化 |
| 压缩路由 | 已有 | `CompressionStrategyRouter` | 已支持策略路由和 fallback，但压缩对象仍偏 flat items |
| 子代理上下文隔离 | 已有基础 | `SubAgentContextManager` | 已有 child scope / exposure policy / result merge |
| OpenClaw 生命周期接入 | 已有 | `openclaw_handler.py` | 已接管 bootstrap / ingest / assemble / compact / after-turn |
| task-conditioned retrieval（轻量版） | 已落地第一阶段 | `task_conditioning.py`、`ContextAggregator`、`UnifiedSearchCoordinator` | 已做 task-aware rerank，但尚未做 pruning / carryover / scope gating |

### 3.2 openJiuwen 在当前集成中的可用能力

| 能力方向 | 当前状态 | 当前接入方式 | 说明 |
| --- | --- | --- | --- |
| LongTermMemory substrate | 已有 | `OpenJiuwenLTMAdapter` | 作为长期记忆唯一正式边界 |
| 外部向量/检索后端 | 已有 | openJiuwen config + adapter | 已通过配置对接 pgvector / qdrant / milvus 等能力边界 |
| 长期写入接口 | 已有 | `add_messages()` | 当前已启用 profile / semantic / episodic / summary memory 开关 |
| 用户记忆搜索 | 已有 | `search_user_mem` | 当前能接受 query 和基础 filters |
| 作用域配置 | 已有 | `register_store()` / `set_config()` / `set_scope_config()` | 当前启动链路已做 bootstrap |
| 检索器/agentic search 能力 | 具备潜在能力 | `agentic_search()` fallback 接口 | 当前 ContextAgent 还没有把 turn / episode / topic 等 richer hints 充分透传 |
| 更强的记忆组织语义 | 潜在可用但未被充分消费 | adapter 边界 | 当前 ContextAgent 仍把 openJiuwen 更多当作 LTM substrate，而非高层 memory semantics provider |

### 3.3 当前最关键的能力缺口

当前主要问题不是“没有 memory system”，而是**多轮连续性、记忆组织和目标感知没有成为一等输入**。

集中体现在：

1. 缺少 episode consolidation 与 narrative thread。
2. 缺少 cross-turn carryover 与 anti-redundancy selection。
3. 缺少 scope / episode / topic 级 gating。
4. 压缩尚未保留 dialogue acts、决议与未决事项。
5. 个性化记忆仍缺少“演化”层，而不只是静态 profile。
6. sub-agent handoff 仍偏可见性过滤，而非基于 episode 的证据提炼和连续推理。

---

## 4. 能力全景与对比矩阵

下表是本文档的核心：它把 `ContextAgent`、`openJiuwen`、论文语料库和工程落地策略放在同一张表中。

字段说明：

- **当前状态**：是否已有能力基础。
- **增强 / 新增**：
  - **增强型**：当前已有结构或相邻能力，可在原链路上升级。
  - **新增型**：当前基本缺失，需要新数据结构、新链路或新模块。
- **实现主位**：优先由 `ContextAgent` 编排层、`openJiuwen` 能力边界，还是二者协同完成。
- **项目 / 实践映射**：代表可直接借鉴或可作为生态支撑的开源项目。

| 能力簇 | ContextAgent 当前状态 | openJiuwen 当前状态 | 论文覆盖与代表论文 | 项目 / 实践映射 | 能力类型 | 实现主位 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 外部长时记忆 substrate | 已有基础 | 已有基础 | 语料主流集中在 `external`（181）；代表：TraceMem、STaR、ShardMemo、Memoria | `Mem0`、`Zep`、`Letta`、`cognee`、`Graphiti`、`LangMem`（direct） | 增强型 | openJiuwen + adapter | 当前主链路已具备，不应绕过 openJiuwen |
| Working memory / scratchpad | 已有 | 间接支撑 | `working`（69）；代表：TraceMem、STaR、Mem-T、ShardMemo | `Basic Memory`、`meMCP`、`agentcortex-mcp`、`Khoj`（direct/adjacent） | 增强型 | ContextAgent | 当前已有 session 级 working memory，但缺 turn / issue / topic 结构 |
| Episodic consolidation / narrative memory | 仅有轻量基础 | 潜在可承载 | `episodic`（84）；代表：TraceMem、E-mem、MEMORA、MemWeaver | `Memobase`、`Graphiti`、`NovelGenerator`、`SimpleMem`（direct） | 新增型偏增强 | ContextAgent 主导，openJiuwen 承载 | 需要先在写入前形成 episode / summary / timeline |
| Semantic abstraction / memory card | 有基础但较弱 | 有基础 | `semantic`（89）；代表：MEMORA、TraceMem、Memoria | `LangMem`、`Mem0`、`MemAlign`、`Zep`（direct） | 增强型 | ContextAgent + openJiuwen | 当前 semantic 更像标签分类，缺抽象层次与 memory card |
| Procedural / skill memory | 基础很弱 | 可承载 | `procedural`（37）；代表：Darwinian Memory、ShardMemo、ReMe、SEAL | `cognee`、`DSPy`、`Moltbot Skills`、`ToolMem` 类实践（adjacent） | 新增型偏增强 | 二者协同 | 当前需要把 tool pattern / skill shard 从普通记忆中分离 |
| User-centric personalization | 有基础但不连续 | 有基础 | `user`（64）；代表：TraceMem、Memoria、Mem-PAL、Me-Agent | `Memobase`、`Mem0`、`Zep`、`MemWeaver`（direct） | 增强型 | ContextAgent 主导 | 关键在“偏好演化”“临时偏好 vs 稳定画像” |
| Agent-centric experience memory | 基础较弱 | 可承载 | `agent`（139）；代表：Darwinian Memory、ShardMemo、AMA、BMAM | `SimpleMem`、`GraphRAG`、`cognee`、`HybridAGI`（adjacent） | 新增型偏增强 | ContextAgent + openJiuwen | 当前 agent 经验记忆与用户记忆尚未真正分流 |
| Retrieval routing / gating / shard probing | 有基础 | filters 已可透传 | 代表：STaR、ShardMemo、MEMORA、MemWeaver | `GraphRAG`、`nano-graphrag`、`LlamaIndex`、`Haystack`（direct/adjacent） | 增强型 | ContextAgent 主导 | 当前已有 RRF / task-aware rerank，但未形成真正 scope-before-routing |
| Cross-turn carryover / anti-redundancy | 基本缺失 | 无直接现成语义 | 代表：STaR、E-mem、TraceMem | `Letta`、`Mem0`、`Zep`、`Basic Memory`（direct） | 新增型 | ContextAgent | 对多轮体验最直接 |
| Compression / compaction / abstraction balancing | 有基础但 flat | 无主导能力 | 代表：MEMORA、STaR、TraceMem、QwenLong-L1.5 | `Letta`、`Zep`、`LangMem`、`MemAlign`（direct/adjacent） | 增强型 | ContextAgent | 当前压缩仍以 flat items 为主，未显式保留问答结构 |
| Multi-agent handoff / delegated evidence extraction | 有基础 | 无直接主导能力 | 代表：E-mem、BMAM、AMA、Topology Matters | `DeMAC`、`Agentic-Sync`、`Nexus Agents`、`LEGOMem`（adjacent） | 新增型偏增强 | ContextAgent | 当前 child scope 已有，但未进入 evidence extraction 阶段 |
| Sensory / multimodal memory | 很弱 | 潜在可扩展 | `sensory`（25）；代表：MemOCR、VideoARM、WorldMM、MemVerse | `StoryMaker`、`IP-Adapter`、`ConsistI2V`、`Amphion`（adjacent） | 新增型 | 二者协同 | 目前不是当前主线，但需在 schema 上预留 |
| Utility governance / privacy / contradiction control | 有零散基础 | 可存储 metadata | 代表：Darwinian Memory、Forgetful but Faithful、Topology Matters | `Basic Memory`、`memento-mcp`、privacy benchmark / governance practices（adjacent） | 增强型 | ContextAgent 主导 | 当前有 hotness 和 health check，但缺长期 utility / privacy / contradiction policy |
| Evaluation / benchmark / policy learning | 基本缺失 | 无直接主导能力 | 代表：survey、Mem-T、benchmark 类论文 | `IAAR` benchmark/tasks、`HaluMem`、`Evo-Memory`、online RLHF / continual learning resources（adjacent/ecosystem） | 新增型 | ContextAgent | 后续需要 continuity / redundancy / recovery 等目标导向评测 |

### 4.1 哪些更适合视为“增强型能力”

这些方向当前已经有可落脚的模块边界，因此优先按增强来做：

- working memory 结构化增强
- semantic abstraction / memory card
- retrieval routing / task-conditioned pruning / scope gating
- compression / abstraction balancing
- user-centric personalization
- utility governance / contradiction suppression

### 4.2 哪些更适合视为“新增型能力”

这些方向当前在代码中只有非常弱的前置能力，通常需要新增结构或链路：

- episode consolidation / narrative memory
- cross-turn carryover / anti-redundancy
- delegated evidence extraction
- sensory / multimodal memory
- evaluation / benchmark / policy learning


### 4.3 全量论文的主能力簇分布

为保证“所有论文都被纳入本路线图”，本文对当前可解析的 **221** 条论文/资源项都指定了一个**主能力簇**。
这不意味着论文只属于单一能力；而是为了让全景矩阵可维护、可排序、可统计。

| 主能力簇 | 主映射条目数 | 能力类型 | 说明 |
| --- | ---: | --- | --- |
| 外部长时记忆 substrate | 11 | 增强型 | 底层外部记忆 substrate、Memory OS、数据库与通用记忆框架 |
| Working memory / scratchpad | 14 | 增强型 | 短时任务态、scratchpad、controller |
| Episodic consolidation / narrative memory | 9 | 新增型偏增强 | episode、history、narrative、reconstruction |
| Semantic abstraction / memory card | 18 | 增强型 | 抽象知识、summary、memory card、generalization |
| Procedural / skill memory | 23 | 新增型偏增强 | 技能、policy、tool pattern、experience reuse |
| User-centric personalization | 45 | 增强型 | 用户画像、偏好、persona、个性化对话 |
| Agent-centric experience memory | 7 | 新增型偏增强 | agent 经验、长期自我改进、轨迹积累 |
| Retrieval routing / gating / shard probing | 18 | 增强型 | 检索路由、筛选、召回路径控制 |
| Cross-turn carryover / anti-redundancy | 7 | 新增型 | 跨 turn 连续性与去重复注入 |
| Compression / compaction / abstraction balancing | 9 | 增强型 | 抽象压缩、长会话压缩、compaction |
| Multi-agent handoff / delegated evidence extraction | 22 | 新增型偏增强 | 多 agent 记忆流转、证据回传 |
| Sensory / multimodal memory | 25 | 新增型 | 视频/视觉/流式/多模态记忆 |
| Utility governance / privacy / contradiction control | 5 | 增强型 | 遗忘、隐私、冲突、污染与治理 |
| Evaluation / benchmark / policy learning | 8 | 新增型 | 评测、指标、benchmark、学习式记忆策略 |

### 4.4 开源项目 / 实践能力沙盘

为了避免项目列表过于离散，这里把新增三份仓库中的代表项目按“对 ContextAgent 的借鉴关系”汇总如下：

| 项目 / 实践簇 | 代表项目 | 相关度 | 对 ContextAgent 的借鉴价值 | 更适合落点 |
| --- | --- | --- | --- | --- |
| Integrated memory layer | `Mem0`、`Zep`、`Letta`、`LangMem`、`cognee`、`Memobase`、`Graphiti` | direct | 提供 memory layer / profile / summary / graph+vector / hierarchy 的成熟产品形态 | `ContextAgent` 编排层 + `openJiuwen` adapter 边界 |
| Local-first / MCP memory tools | `Basic Memory`、`meMCP`、`memento-mcp`、`agentcortex-mcp`、`mcp-memory` | direct | 强化外部工作记忆、审计性、用户可见记忆编辑、本地隐私控制 | `WorkingMemoryManager`、外部 working memory adapter |
| Retrieval / Graph memory patterns | `GraphRAG`、`nano-graphrag`、`LlamaIndex` Property Graph、`HybridAGI` | direct / adjacent | 提示应把 graph、topic、entity、episode 作为 first-class retrieval hints，而不只做向量召回 | `UnifiedSearchCoordinator`、`TieredMemoryRouter` |
| Framework-level memory abstractions | `LangChain`、`LlamaIndex`、`Haystack`、`Rasa` | adjacent | 适合借鉴抽象接口设计，不适合作为 ContextAgent 核心能力本身 | API / adapter / integration layer |
| Storage substrate ecosystem | `Neo4j`、`FalkorDB`、`NebulaGraph`、`Chroma`、`Milvus`、`Qdrant`、`Weaviate`、`Faiss` | ecosystem | 主要补齐后端选择，不应替代 ContextAgent 的 memory orchestration 设计 | `openJiuwen` config / backend |
| Benchmark / evaluation resources | `IAAR` benchmarks/tasks、`HaluMem`、`Evo-Memory` | adjacent | 直接提示要补 continuity、hallucination、recovery、long-term consistency 评测 | `tests/`、docs、evaluation harness |
| Continual learning / online alignment | `ContinualLM`、`CURLoRA`、`OpenRLHF`、`Online-RLHF` | ecosystem | 目前不应直接纳入主链路，但提醒长期个性化与漂移控制不能只靠检索层 | 远期研究 / policy learning |
| Multi-agent coordination systems | `DeMAC`、`Agentic-Sync`、`Nexus Agents` | adjacent | 启发 shared memory、delegated state sync、memory leakage 控制 | `SubAgentContextManager`、handoff contracts |

### 4.5 当前最值得借鉴的能力清单

从“能较快改善多轮对话体验”的角度，当前最值得优先吸收的不是底层存储，而是以下几类实践：

1. **Profile / memory card 演化机制**
   - 参考：`Mem0`、`Memobase`、`LangMem`、`Zep`
   - 借鉴方式：直接增强
   - 适合目标：把 `SEMANTIC` 记忆从静态标签升级成可更新的 user/profile/topic memory card
2. **本地可审计 working memory**
   - 参考：`Basic Memory`、`meMCP`、`memento-mcp`
   - 借鉴方式：直接增强
   - 适合目标：让外部 scratchpad / 结构化 notes / unresolved items 成为一等对象，改善多轮连续性与人工可控性
3. **Graph + topic aware retrieval**
   - 参考：`Graphiti`、`GraphRAG`、`nano-graphrag`、`LlamaIndex`
   - 借鉴方式：参考实现
   - 适合目标：把当前 task-conditioned rerank 推进到 episode/topic/entity gating
4. **层级压缩与冷热分层**
   - 参考：`Letta`、`Zep`、`MemAlign`
   - 借鉴方式：参考实现
   - 适合目标：把 flat compression 升级成 turn → episode → profile / topic summary 的层级压缩链
5. **多代理状态与证据同步**
   - 参考：`DeMAC`、`Agentic-Sync`、`Nexus Agents`
   - 借鉴方式：参考实现
   - 适合目标：把当前 sub-agent 可见性隔离升级为“任务态连续 + 证据回传”

### 4.6 当前不应误判为“核心记忆能力”的项目类别

以下项目/实践很有参考价值，但不应被直接计入 ContextAgent 当前的核心记忆能力完成度：

- 纯存储后端（如 `Qdrant`、`Milvus`、`Neo4j`、`Chroma`）
- 通用框架（如 `LangChain`、`Haystack`）
- 训练 / 对齐 / 持续学习框架（如 `OpenRLHF`、`ContinualLM`）
- 多模态一致性工具（如 `StoryMaker`、`ConsistI2V`）

这些项目更多回答“如何配套”和“如何长期演进”，而不是“当前 ContextAgent 已经具备哪种记忆能力”。

---


## 5. 与当前代码最相关的高价值论文 / 项目样本

虽然主文档不再按论文或项目逐条展开，但仍保留一组“高价值样本”，作为路线图的解释锚点。

### 5.1 TraceMem

- 关键词：episode segmentation、narrative memory、user memory card
- 对应能力簇：episodic consolidation、semantic abstraction、user-centric personalization
- 对 ContextAgent 的意义：把“原始消息写入 LTM”升级成“episode / narrative thread 写入 LTM”

### 5.2 STaR

- 关键词：task-conditioned retrieval、candidate compression、信息密度最大化
- 对应能力簇：retrieval routing、cross-turn carryover、anti-redundancy selection
- 对 ContextAgent 的意义：把已有 task-aware rerank 升级成真正的 pruning + coverage-aware selection

### 5.3 MEMORA

- 关键词：abstraction vs specificity、cue anchors、multi-entry recall
- 对应能力簇：semantic abstraction、compression balancing、abstract-first recall
- 对 ContextAgent 的意义：把现有 `ContextLevel` 从过滤标签升级为层级记忆结构

### 5.4 E-mem

- 关键词：episodic reconstruction、multi-agent evidence extraction
- 对应能力簇：multi-agent handoff、quality path、episode-based local reasoning
- 对 ContextAgent 的意义：让 `mode=quality` 真正具备 episode 激活和局部证据提炼能力

### 5.5 Darwinian Memory

- 关键词：utility-driven pruning、自调节记忆生态
- 对应能力簇：utility governance、procedural evolution、contradiction suppression
- 对 ContextAgent 的意义：当前 hotness / health check 可以成为长期 utility policy 的前置基础

### 5.6 ShardMemo

- 关键词：scope-before-routing、masked MoE、sharded memory
- 对应能力簇：retrieval routing、procedure shard、agent-centric experience memory
- 对 ContextAgent 的意义：与 `TieredMemoryRouter` / `UnifiedSearchCoordinator` 的边界高度贴合

### 5.7 Mem0 / Zep / LangMem（项目簇）

- 关键词：memory layer、profile extraction、summary update、cross-session memory
- 对应能力簇：semantic abstraction、user-centric personalization、cross-turn continuity
- 对 ContextAgent 的意义：说明“长期记忆能力”在工程上通常会被包装成更高层的 memory service，而不是直接暴露为原始向量库调用

### 5.8 Graphiti / GraphRAG（项目簇）

- 关键词：temporal graph、entity relation、graph-aware retrieval
- 对应能力簇：episodic consolidation、retrieval routing、topic recovery
- 对 ContextAgent 的意义：说明 topic / entity / timeline 结构应进入召回主链路，而不只是作为 metadata 附件

### 5.9 Basic Memory / meMCP / memento-mcp（项目簇）

- 关键词：local-first、auditable memory、external working memory、user-editable memory
- 对应能力簇：working memory / scratchpad、utility governance、privacy control
- 对 ContextAgent 的意义：对多轮体验而言，可审计的工作记忆与可控写入策略同样重要，不应只强调自动召回

---

## 6. 目标导向路线图框架

本路线图以后不只维护一条“唯一优先级”，而改成：

- **能力全景层**：稳定展示能力空间与论文 / 项目实践覆盖
- **目标导向路线层**：按不同目标重排优先级

### 6.1 后续可支持的目标路线

当前建议至少维护以下几条路线：

1. **多轮对话体验**
   - 关注 continuity、少重复、topic recovery、长会话可继续性、偏好演化
2. **延迟 / 成本优化**
   - 关注 routing、shard gating、token efficiency、压缩开销、预算调度
3. **长期个性化与用户记忆质量**
   - 关注 profile stability、preference evolution、user memory card、privacy-aware forgetting
4. **多 agent 协同质量**
   - 关注 evidence extraction、delegated memory、memory leakage、scope isolation
5. **可靠性与治理**
   - 关注 contradiction suppression、memory poisoning、privacy、evaluation harness

这些路线后续不仅可以从论文中抽取候选能力，也可以从项目 / 实践语料里抽取：

- 可直接复用的设计模式
- 值得增加的 adapter / metadata / contract
- 应纳入评测体系的体验指标

### 6.2 为什么当前先做“多轮对话体验”

因为当前最直接影响体感的问题都集中在这里，而且项目 / 实践语料也给出了很一致的信号：

- 每一轮仍偏 stateless retrieval
- 长会话仍容易碎片化
- 压缩仍不能表达对话结构
- 偏好和阶段目标演化感弱
- topic 切换时恢复上下文仍不稳定

对应的工程侧佐证包括：

- `Mem0` / `Zep` / `LangMem` 一类项目都在强调 profile / summary 持续更新
- `Basic Memory` / `meMCP` 一类工具强调外部可审计 working memory
- `Graphiti` / `GraphRAG` 一类项目强调 topic / entity / relation 级检索

因此，当前第一条目标导向路线仍然应该聚焦多轮体验，而不是先做底层存储替换。

---

## 7. 第一条目标路线：改善多轮对话体验

### 7.1 目标

本路线优先改善以下 6 项体验指标：

1. **连续性**：系统知道“这是同一段对话的延续”
2. **少重复**：连续 turn 不再重复注入相同上下文
3. **个性化演化**：用户偏好、阶段目标和风格要求可持续更新
4. **长会话可读性**：压缩后仍保留问答关系、决议和未决事项
5. **topic 切换恢复能力**：在多个 subtask / episode 间切换后能快速回到正确上下文
6. **委托后的连续性**：sub-agent 能延续主线程并回传证据而不是裸结果

### 7.2 P0：最直接改善多轮体验的能力

1. **Turn-aware context carryover + anti-redundancy selection**
   - 能力类型：新增型
   - 对应能力簇：cross-turn carryover、retrieval routing
   - 代表论文：STaR、E-mem
   - 代表项目 / 实践：`Letta`、`Mem0`、`Zep`
   - 目标模块：`OpenClaw assemble`、`ContextAPIRouter`、`ContextAggregator`、`task_conditioning.py`

2. **Episode consolidation + narrative memory before LTM write**
   - 能力类型：新增型偏增强
   - 对应能力簇：episodic consolidation、user-centric personalization
   - 代表论文：TraceMem、MemWeaver、Memoria
   - 代表项目 / 实践：`Memobase`、`Graphiti`、`NovelGenerator`
   - 目标模块：`MemoryOrchestrator`、`AsyncMemoryProcessor`、`WorkingMemoryManager`、`OpenJiuwenLTMAdapter`

3. **Dialogue-aware compression for long_session / compaction**
   - 能力类型：增强型
   - 对应能力簇：compression / abstraction balancing
   - 代表论文：MEMORA、TraceMem、STaR
   - 代表项目 / 实践：`Letta`、`Zep`、`MemAlign`
   - 目标模块：`CompressionStrategyRouter`、压缩策略注册表、`openclaw_handler.compact`

4. **Scope-before-routing + episode/topic gating**
   - 能力类型：增强型
   - 对应能力簇：retrieval routing / gating
   - 代表论文：ShardMemo、STaR
   - 代表项目 / 实践：`Graphiti`、`GraphRAG`、`nano-graphrag`
   - 目标模块：`UnifiedSearchCoordinator`、`TieredMemoryRouter`、`OpenJiuwenLTMAdapter`

5. **User preference evolution / personalized memory card**
   - 能力类型：增强型
   - 对应能力簇：semantic abstraction、user-centric personalization
   - 代表论文：TraceMem、Memoria、Mem-PAL
   - 代表项目 / 实践：`Mem0`、`LangMem`、`Memobase`
   - 目标模块：`MemoryOrchestrator`、`WorkingMemoryManager`、`OpenJiuwenLTMAdapter`

6. **Task-conditioned retrieval 从 rerank 升级为 pruning + coverage-aware selection**
   - 能力类型：增强型
   - 对应能力簇：retrieval routing / anti-redundancy
   - 代表论文：STaR、MEMORA
   - 代表项目 / 实践：`GraphRAG`、`LlamaIndex`、`Haystack`
   - 目标模块：`task_conditioning.py`、`ContextAggregator`、`UnifiedSearchCoordinator`

### 7.3 P1：建立在 P0 之上的增强能力

1. **Abstract-first recall + cue-anchor expansion**
2. **Episodic reconstruction in quality mode + delegated evidence extraction**
3. **Utility-driven pruning + contradiction-aware suppression**
4. **Agent skill card / procedure shard**

### 7.4 P2：中长期演进

1. 学习式 memory routing / policy optimization
2. continuity / redundancy / recovery evaluation harness
3. 多 agent delegated memory exchange
4. 更强的长期个性化稳定性 / 漂移控制机制

### 7.5 建议落地顺序

#### Phase 1：先补足多轮连续性的基础信号

- 引入 `turn_index`、`previous_context_ids`、`dialogue_topic`、`resolution_state`
- 将现有 task-conditioned retrieval 升级为 anti-redundancy + coverage-aware selection
- 定义多轮体验评测指标：重复率、continuity、topic recovery、压缩可读性

#### Phase 2：把消息流改造成 episode / narrative 结构

- 在 LTM 写入前增加 episode consolidation
- 给 working memory / LTM metadata 补 `episode_id`、`topic`、`timeline_position`、`preference_scope`
- 建立 user memory card / preference evolution 基础结构

#### Phase 3：升级召回与压缩体验

- 实现 scope-before-routing + episode/topic gating
- 引入 dialogue-aware compression
- 在固定 token budget 下做到更少重复、更多高价值信息

#### Phase 4：增强复杂问题与多 agent 场景

- abstract-first recall + cue-anchor expansion
- episodic reconstruction + delegated evidence extraction
- utility-driven pruning / contradiction-aware suppression / skill shard

---

## 8. 已落地进展

### 8.1 Task-conditioned retrieval / candidate pruning（第一阶段）

**状态**

done

**对应能力簇**

- retrieval routing / gating
- cross-turn 相关能力的前置基础

**对应论文**

- STaR
- MEMORA
- ShardMemo

**本轮落地内容**

已完成一个低风险版本的 task-conditioned retrieval，实现方式不是引入新的 LLM 路由器，而是在现有聚合与搜索链路中增加轻量 task-aware score adjustment。

具体改动如下：

- 新增 `context_agent/core/retrieval/task_conditioning.py`
  - 根据 `task_type` 与 `agent_role` 对候选进行轻量重排序
  - 当前已覆盖 `qa / task / long_session / realtime / compaction`
  - 结合 `memory_type`、`category`、`tier`、`level`、部分 metadata 字段做 score adjustment
- `ContextAggregator`
  - `AggregationRequest` 新增 `task_type`、`agent_role`
  - 在 dedup 和 token budget 之间接入 task-conditioned reordering
- `ContextAPIRouter`
  - 将 API 层的 `task_type`、`agent_role` 透传给 `AggregationRequest`
  - `SEARCH` 输出路径也会对 tiered results 做 task-conditioned reordering
- `UnifiedSearchCoordinator`
  - `RetrievalPlan` 新增 `task_type`、`agent_role`
  - 在 RRF / rerank 之后追加 task-conditioned reordering

**验证结果**

已通过：

- 聚合链路回归测试
- 搜索协调器回归测试
- API 搜索输出回归测试
- 变更文件的 focused Ruff 检查

结果：

- Ruff focused checks passed
- `18 passed`

**局限**

当前还是规则型 task conditioning，不是学习式路由，也没有引入信息瓶颈式 candidate selection。

**下一步最自然的延伸**

1. 将 `task_type`、`agent_role` 进入 `RetrievalPlan.filters`，形成真正的 scope-before-routing
2. 将“去重”升级为“去冗余 + coverage-aware selection”
3. 加入 anchor expansion 和 abstract-first retrieval

---

## 9. 后续更新约定

后续每轮更新，优先按如下模板增量补充：

| 字段 | 说明 |
| --- | --- |
| 能力簇 | 例如：episodic consolidation / narrative memory |
| 目标路线 | 例如：多轮对话体验 / 延迟成本 / 个性化 |
| 当前状态 | absent / weak / partial / done |
| 能力类型 | 增强型 / 新增型 |
| 代码路径 | 实际落点 |
| 对应论文 | 代表论文 + 相关论文 |
| 对应项目 / 实践 | 代表项目 + direct/adjacent/ecosystem 标记 |
| 验证 | 单测、集成测试、性能回归、定性案例 |
| 备注 | 风险、前置依赖、是否适合作为下一轮工作 |

建议未来的推进节奏是：

1. 先在“能力全景矩阵”里补足论文和项目 / 实践覆盖。
2. 再从某一条“目标导向路线”里选择 1 个能力簇推进到代码落地。
3. 完成后把状态、验证和结果回写到同一文档，而不是新开平行 roadmap。

---

## 10. 附录：全量论文主能力簇映射索引

本附录用于满足“对 `Awesome-Agent-Memory` 当前全部论文进行能力映射”的要求。
映射原则如下：

1. 每篇论文至少映射到一个**主能力簇**。
2. 主能力簇由论文标题语义 + taxonomy 标签（substrate / mechanism / subject）共同决定。
3. 论文往往同时覆盖多个能力簇；主映射只用于建立全景索引，不替代正文中的多簇关联分析。
4. `能力类型` 字段沿用正文矩阵的判定：区分“增强型”“新增型”“新增型偏增强”。

| # | 论文 | 年份 | taxonomy 标签 | 主能力簇 | 能力类型 |
| ---: | --- | --- | --- | --- | --- |
| 1 | [TraceMem: Weaving Narrative Memory Schemata from User Conversational Traces](https://arxiv.org/abs/2602.09712) | 2026 | `external, user, episodic, working, semantic` | Episodic consolidation / narrative memory | 新增型偏增强 |
| 2 | [STaR: Scalable Task-Conditioned Retrieval for Long-Horizon Multimodal Robot Memory](https://arxiv.org/abs/2602.09255) | 2026 | `external, agent, working, semantic` | Retrieval routing / gating / shard probing | 增强型 |
| 3 | [MEMORA: A Harmonic Memory Representation Balancing Abstraction and Specificity](https://arxiv.org/abs/2602.03315) | 2026 | `external, agent, episodic, semantic` | Semantic abstraction / memory card | 增强型 |
| 4 | [Mem-T: Densifying Rewards for Long-Horizon Memory Agents](https://arxiv.org/abs/2601.23014) | 2026 | `internal, agent, working, sensory, semantic, episodic` | Sensory / multimodal memory | 新增型 |
| 5 | [Darwinian Memory: A Training-Free Self-Regulating Memory System for GUI Agent Evolution](https://arxiv.org/abs/2601.22528) | 2026 | `external, agent, procedural, episodic` | Utility governance / privacy / contradiction control | 增强型 |
| 6 | [E-mem: Multi-agent based Episodic Context Reconstruction for LLM Agent Memory](https://arxiv.org/abs/2601.21714) | 2026 | `external, agent, episodic, semantic` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 7 | [ShardMemo: Masked MoE Routing for Sharded Agentic LLM Memory](https://arxiv.org/abs/2601.21545) | 2026 | `external, agent, working, semantic, procedural, episodic` | Retrieval routing / gating / shard probing | 增强型 |
| 8 | [MemOCR: Layout-Aware Visual Memory for Efficient Long-Horizon Reasoning](https://arxiv.org/abs/2601.21468) | 2026 | `internal, agent, working, episodic, semantic` | Sensory / multimodal memory | 新增型 |
| 9 | [MemCtrl: Using MLLMs as Active Memory Controllers on Embodied Agents](https://arxiv.org/abs/2601.20831) | 2026 | `internal, agent, working, episodic, semantic` | Sensory / multimodal memory | 新增型 |
| 10 | [BMAM: Brain-inspired Multi-Agent Memory Framework](https://arxiv.org/abs/2601.20465) | 2026 | `external, agent, episodic, semantic, working, procedural` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 11 | [AMA: Adaptive Memory via Multi-Agent Collaboration](https://arxiv.org/abs/2601.20352) | 2026 | `external, agent, episodic, semantic` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 12 | [Me-Agent: A Personalized Mobile Agent with Two-Level Use](https://arxiv.org/abs/2601.20162) | 2026 | `external, user, semantic, procedural, episodic, sensory` | User-centric personalization | 增强型 |
| 13 | [MAGNET: Towards Adaptive GUI Agents with Memory-Driven Knowledge Evolution](https://arxiv.org/abs/2601.19199) | 2026 | `external, agent, procedural, semantic` | Procedural / skill memory | 新增型偏增强 |
| 14 | [MemWeaver: Weaving Hybrid Memories for Traceable Long-Horizon Agentic Reasoning](https://arxiv.org/abs/2601.18204) | 2026 | `external, agent, semantic, episodic` | Episodic consolidation / narrative memory | 新增型偏增强 |
| 15 | [Self-Evolving Distributed Memory Architecture for Scalable AI Systems](https://arxiv.org/abs/2601.05569) | 2026 | `external, agent, episodic, working` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 16 | [Memoria: A Scalable Agentic Memory Framework for Personalized Conversational AI](https://arxiv.org/abs/2512.12686) | 2025 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 17 | [Forgetful but Faithful: A Cognitive Memory Architecture and Benchmark for Privacy-Aware Generative Agents](https://arxiv.org/abs/2512.12856) | 2025 | `external, agent, episodic, semantic, working` | Utility governance / privacy / contradiction control | 增强型 |
| 18 | [QwenLong-L1.5: Post-Training Recipe for Long-Context Reasoning and Memory Management](https://arxiv.org/abs/2512.12967) | 2025 | `internal, agent, working` | Compression / compaction / abstraction balancing | 增强型 |
| 19 | [V-Rex: Real-Time Streaming Video LLM Acceleration via Dynamic KV Cache Retrieval](https://arxiv.org/abs/2512.12284) | 2025 | `external, agent, sensory, working` | Retrieval routing / gating / shard probing | 增强型 |
| 20 | [VideoARM: Agentic Reasoning over Hierarchical Memory for Long-Form Video Understanding](https://arxiv.org/abs/2512.12360) | 2025 | `external, agent, sensory, episodic, working` | Sensory / multimodal memory | 新增型 |
| 21 | [Unifying Dynamic Tool Creation and Cross-Task Experience Sharing through Cognitive Memory Architecture](https://arxiv.org/abs/2512.11303) | 2025 | `external, agent, episodic, semantic, procedural` | Procedural / skill memory | 新增型偏增强 |
| 22 | [Confucius Code Agent: Scalable Agent Scaffolding for Real-World Codebases](https://arxiv.org/abs/2512.10398) | 2025 | `external, agent, episodic, working` | Working memory / scratchpad | 增强型 |
| 23 | [Remember Me, Refine Me: A Dynamic Procedural Memory Framework for Experience-Driven Agent Evolution](https://arxiv.org/abs/2512.10696) | 2025 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 24 | [DeepCode: Open Agentic Coding](https://arxiv.org/abs/2512.07921) | 2025 | `external, agent, semantic, working` | Working memory / scratchpad | 增强型 |
| 25 | [Topology Matters: Measuring Memory Leakage in Multi-Agent LLMs](https://arxiv.org/abs/2512.04668) | 2025 | `external, user, semantic, working` | Utility governance / privacy / contradiction control | 增强型 |
| 26 | [SEAL: Self-Evolving Agentic Learning for Conversational Question Answering over Knowledge Graphs](https://arxiv.org/abs/2512.04868) | 2025 | `external, agent, working, procedural` | Procedural / skill memory | 新增型偏增强 |
| 27 | [From Static to Adaptive: Immune Memory-based Jailbreak Detection for Large Language Models](https://arxiv.org/abs/2512.03356) | 2025 | `external, agent, episodic` | Utility governance / privacy / contradiction control | 增强型 |
| 28 | [MemVerse: Multimodal Memory for Lifelong Learning Agents](https://arxiv.org/abs/2512.03627) | 2025 | `external, internal, user, sensory, episodic, semantic` | Episodic consolidation / narrative memory | 新增型偏增强 |
| 29 | [WorldMM: Dynamic Multimodal Memory Agent for Long Video Reasoning](https://arxiv.org/abs/2512.02425) | 2025 | `external, agent, sensory, episodic, semantic` | Sensory / multimodal memory | 新增型 |
| 30 | [CuES: A Curiosity-driven and Environment-grounded Synthesis Framework for Agentic RL](https://arxiv.org/abs/2512.01311) | 2025 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 31 | [Describe Anything Anywhere At Any Moment](https://arxiv.org/abs/2512.00565) | 2025 | `external, agent, episodic, semantic` | Semantic abstraction / memory card | 增强型 |
| 32 | [Adapting Like Humans: A Metacognitive Agent with Test-time Reasoning](https://arxiv.org/abs/2511.23262) | 2025 | `external, agent, semantic, working, procedural` | Procedural / skill memory | 新增型偏增强 |
| 33 | [Solving Context Window Overflow in AI Agents](https://arxiv.org/abs/2511.22729) | 2025 | `external, agent, working` | Working memory / scratchpad | 增强型 |
| 34 | [MG-Nav: Dual-Scale Visual Navigation via Sparse Spatial Memory](https://arxiv.org/abs/2511.22609) | 2025 | `external, agent, semantic, working` | Sensory / multimodal memory | 新增型 |
| 35 | [Agentic Learner with Grow-and-Refine Multimodal Semantic Memory](https://arxiv.org/abs/2511.21678) | 2025 | `external, agent, semantic` | Sensory / multimodal memory | 新增型 |
| 36 | [MADRA: Multi-Agent Debate for Risk-Aware Embodied Planning](https://arxiv.org/abs/2511.21460) | 2025 | `external, user, working` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 37 | [Evo-Memory: Benchmarking LLM Agent Test-time Learning with Self-Evolving Memory](https://arxiv.org/abs/2511.20857) | 2025 | `-` | Evaluation / benchmark / policy learning | 新增型 |
| 38 | [Improving Language Agents through BREW](https://arxiv.org/abs/2511.20297) | 2025 | `external, agent, semantic, procedural` | Procedural / skill memory | 新增型偏增强 |
| 39 | [Latent Collaboration in Multi-Agent Systems](https://arxiv.org/abs/2511.20639) | 2025 | `-` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 40 | [General Agentic Memory Via Deep Research](https://arxiv.org/abs/2511.18423) | 2025 | `external, user, semantic, working` | Retrieval routing / gating / shard probing | 增强型 |
| 41 | [Episodic Memory in Agentic Frameworks: Suggesting Next Tasks](https://arxiv.org/abs/2511.17775) | 2025 | `external, agent, episodic` | Episodic consolidation / narrative memory | 新增型偏增强 |
| 42 | [A Simple Yet Strong Baseline for Long-Term Conversational Memory of LLM Agents](https://arxiv.org/abs/2511.17208) | 2025 | `external, user, episodic` | Cross-turn carryover / anti-redundancy | 新增型 |
| 43 | [Mem-PAL: Towards Memory-based Personalized Dialogue Assistants for Long-term User-Agent Interaction](https://arxiv.org/abs/2511.13410) | 2025 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 44 | [Multi-agent In-context Coordination via Decentralized Memory Retrieval](https://arxiv.org/abs/2511.10030) | 2025 | `external, agent, episodic, working` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 45 | [History-Aware Reasoning for GUI Agent](https://arxiv.org/abs/2511.09127) | 2025 | `internal, user, episodic, working` | Episodic consolidation / narrative memory | 新增型偏增强 |
| 46 | [From Experience to Strategy: Empowering LLM Agents with Trainable Graph Memory](https://arxiv.org/abs/2511.07800) | 2025 | `external, agent, episodic, procedural` | Procedural / skill memory | 新增型偏增强 |
| 47 | [Smarter Together: Creating Agentic Communities of Practice through Shared Experiential Learning](https://arxiv.org/abs/2511.08301) | 2025 | `external, agent, semantic, procedural` | Procedural / skill memory | 新增型偏增强 |
| 48 | [Beyond Fact Retrieval: Episodic Memory for RAG with Generative Semantic Workspaces](https://arxiv.org/abs/2511.07587) | 2025 | `external, agent, episodic, semantic` | Retrieval routing / gating / shard probing | 增强型 |
| 49 | [IterResearch: Rethinking Long-Horizon Agents via Markovian State Reconstruction](https://arxiv.org/abs/2511.07327) | 2025 | `external, agent, working` | Retrieval routing / gating / shard probing | 增强型 |
| 50 | [MemoriesDB: A Temporal-Semantic-Relational Database for Long-Term Agent Memory](https://arxiv.org/abs/2511.06179) | 2025 | `external, agent` | 外部长时记忆 substrate | 增强型 |
| 51 | [Nested Learning: The Illusion of Deep Learning Architectures](https://arxiv.org/abs/2512.24695) | 2025 | `internal, agent, semantic, working` | Working memory / scratchpad | 增强型 |
| 52 | [Towards Realistic Project-Level Code Generation via Multi-Agent Collaboration and Semantic Architecture Modeling](https://arxiv.org/abs/2511.03404) | 2025 | `external, agent, semantic, working` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 53 | [HaluMem: Evaluating Hallucinations in Memory Systems of Agents](https://arxiv.org/abs/2511.03506) | 2025 | `-` | Utility governance / privacy / contradiction control | 增强型 |
| 54 | [MemSearcher: Training LLMs to Reason, Search and Manage Memory via End-to-End Reinforcement Learning](https://arxiv.org/abs/2511.02805) | 2025 | `external, agent, working` | Retrieval routing / gating / shard probing | 增强型 |
| 55 | [EvoMem: Improving Multi-Agent Planning with Dual-Evolving Memory](https://arxiv.org/abs/2511.01912) | 2025 | `external, agent, working` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 56 | [LiCoMemory: Lightweight and Cognitive Agentic Memory for Efficient Long-Term Reasoning](https://arxiv.org/abs/2511.01448) | 2025 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 57 | [Dynamic Affective Memory Management for Personalized LLM Agents](https://arxiv.org/abs/2510.27418) | 2025 | `external, user, semantic` | User-centric personalization | 增强型 |
| 58 | [TheraMind: A Strategic and Adaptive Agent for Longitudinal Psychological Counseling](https://arxiv.org/abs/2510.25758) | 2025 | `external, user, episodic, working` | User-centric personalization | 增强型 |
| 59 | [AgentFold: Long-Horizon Web Agents with Proactive Context Management](https://arxiv.org/abs/2510.24699) | 2025 | `external, agent, episodic, working` | Working memory / scratchpad | 增强型 |
| 60 | [MGA: Memory-Driven GUI Agent for Observation-Centric Interaction](https://arxiv.org/abs/2510.24168) | 2025 | `external, agent, episodic, working` | Sensory / multimodal memory | 新增型 |
| 61 | [Evaluating Long-Term Memory for Long-Context Question Answering](https://arxiv.org/abs/2510.23730) | 2025 | `external, user, episodic, semantic, procedural` | User-centric personalization | 增强型 |
| 62 | [DeepAgent: A General Reasoning Agent with Scalable Toolsets](https://arxiv.org/abs/2510.21618) | 2025 | `external, agent, episodic, working` | Procedural / skill memory | 新增型偏增强 |
| 63 | [Memo: Training Memory-Efficient Embodied Agents with Reinforcement Learning](https://arxiv.org/abs/2510.19732) | 2025 | `external, agent, working` | Sensory / multimodal memory | 新增型 |
| 64 | [LightMem: Lightweight and Efficient Memory-Augmented Generation](https://arxiv.org/abs/2510.18866) | 2025 | `external, user, sensory, semantic, working` | User-centric personalization | 增强型 |
| 65 | [Branch-and-Browse: Efficient and Controllable Web Exploration with Tree-Structured Reasoning and Action Memory](https://arxiv.org/abs/2510.19838) | 2025 | `external, agent, episodic, working` | Working memory / scratchpad | 增强型 |
| 66 | [RGMem: Renormalization Group-based Memory Evolution for Language Agent User Profile](https://arxiv.org/abs/2510.16392) | 2025 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 67 | [D-SMART: Enhancing LLM Dialogue Consistency via Dynamic Structured Memory And Reasoning Tree](https://arxiv.org/abs/2510.13363) | 2025 | `external, user, semantic, working` | Cross-turn carryover / anti-redundancy | 新增型 |
| 68 | [MemoTime: Memory-Augmented Temporal Knowledge Graph Enhanced Large Language Model Reasoning](https://arxiv.org/abs/2510.13614) | 2025 | `external, agent, episodic` | Semantic abstraction / memory card | 增强型 |
| 69 | [Memory As Action: Autonomous Context Curation for Long-Horizon Agentic Tasks](https://arxiv.org/abs/2510.12635) | 2025 | `external, agent, working` | Working memory / scratchpad | 增强型 |
| 70 | [PISA: A Pragmatic Psych-Inspired Unified Memory System for Enhanced AI Agency](https://arxiv.org/abs/2510.15966) | 2025 | `external, user, semantic` | User-centric personalization | 增强型 |
| 71 | [EpiCache: Episodic KV Cache Management for Long Conversational Question Answering](https://arxiv.org/abs/2509.17396?) | 2025 | `external, user, working` | Cross-turn carryover / anti-redundancy | 新增型 |
| 72 | [Preference-Aware Memory Update for Long-Term LLM Agents](https://arxiv.org/abs/2510.09720) | 2025 | `semantic` | User-centric personalization | 增强型 |
| 73 | [Seeing, Listening, Remembering, and Reasoning: A Multimodal Agent with Long-Term Memory](https://arxiv.org/abs/2508.09736) | 2025 | `external, agent, episodic, semantic` | 外部长时记忆 substrate | 增强型 |
| 74 | [Multiple Memory Systems for Enhancing the Long-term Memory of Agent](https://arxiv.org/abs/2508.15294) | 2025 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 75 | [MemWeaver: A Hierarchical Memory from Textual Interactive Behaviors for Personalized Generation](https://arxiv.org/abs/2510.07713) | 2025 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 76 | [Scaling LLM Multi-turn RL with End-to-end Summarization-based Context Management](https://arxiv.org/abs/2510.06727) | 2025 | `external, agent, working` | Cross-turn carryover / anti-redundancy | 新增型 |
| 77 | [ToolMem: Enhancing Multimodal Agents with Learnable Tool Capability Memory](https://arxiv.org/abs/2510.06664) | 2025 | `external, agent, episodic, semantic` | Procedural / skill memory | 新增型偏增强 |
| 78 | [CAM: A Constructivist View of Agentic Memory for LLM-Based Reading Comprehension](https://arxiv.org/abs/2510.05520) | 2025 | `external, agent, semantic, working` | 外部长时记忆 substrate | 增强型 |
| 79 | [LEGOMem: Modular Procedural Memory for Multi-agent LLM Systems for Workflow Automation](https://arxiv.org/abs/2510.04851) | 2025 | `external, agent, procedural` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 80 | [Pretraining with hierarchical memories: separating long-tail and common knowledge](https://arxiv.org/abs/2510.02375) | 2025 | `internal, agent, semantic` | Semantic abstraction / memory card | 增强型 |
| 81 | [ACON: Optimizing Context Compression for Long-horizon LLM Agents](https://arxiv.org/abs/2510.00615) | 2025 | `external, agent, working` | Compression / compaction / abstraction balancing | 增强型 |
| 82 | [Mem-α: Learning Memory Construction via Reinforcement Learning](https://arxiv.org/abs/2509.25911) | 2025 | `external, user, episodic, semantic, working` | User-centric personalization | 增强型 |
| 83 | [ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory](https://arxiv.org/abs/2509.25140v1) | 2025 | `external, user, procedural` | User-centric personalization | 增强型 |
| 84 | [ViReSkill: Vision-Grounded Replanning with Skill Memory for LLM-Based Planning in Lifelong Robot Learning](https://arxiv.org/abs/2509.24219v1) | 2025 | `external, agent, procedural` | Episodic consolidation / narrative memory | 新增型偏增强 |
| 85 | [Look Back to Reason Forward: Revisitable Memory for Long-Context LLM Agents](https://arxiv.org/abs/2509.23040) | 2025 | `external, agent, working` | Compression / compaction / abstraction balancing | 增强型 |
| 86 | [ReSum: Unlocking Long-Horizon Search Intelligence via Context Summarization](https://arxiv.org/abs/2509.13313) | 2025 | `external, agent, working` | Retrieval routing / gating / shard probing | 增强型 |
| 87 | [Memory-R1: Enhancing Large Language Model Agents to Manage and Utilize Memories via Reinforcement Learning](https://arxiv.org/abs/2508.19828?) | 2025 | `external, user, semantic` | User-centric personalization | 增强型 |
| 88 | [Learn to Memorize: Optimizing LLM-based Agents with Adaptive Memory Framework](https://arxiv.org/abs/2508.16629) | 2025 | `external, agent, episodic` | 外部长时记忆 substrate | 增强型 |
| 89 | [Memp: Exploring Agent Procedural Memory](https://arxiv.org/abs/2508.06433?) | 2025 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 90 | [Nemori: Self-Organizing Agent Memory Inspired by Cognitive Science](https://arxiv.org/abs/2508.03341) | 2025 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 91 | [MLP Memory: A Retriever-Pretrained Memory for Large Language Models](https://arxiv.org/abs/2508.01832v2) | 2025 | `internal, agent, semantic` | Semantic abstraction / memory card | 增强型 |
| 92 | [MemInsight: Autonomous Memory Augmentation for LLM Agents](https://arxiv.org/abs/2503.21760) | 2025 | `external, user, semantic` | User-centric personalization | 增强型 |
| 93 | [In Prospect and Retrospect: Reflective Memory Management for Long-term Personalized Dialogue Agents](https://arxiv.org/abs/2503.08026) | 2025 | `external, user, semantic` | User-centric personalization | 增强型 |
| 94 | [MemAgent: Reshaping Long-Context LLM with Multi-Conv RL-based Memory Agent](https://arxiv.org/abs/2507.02259v1) | 2025 | `external, agent, working` | Compression / compaction / abstraction balancing | 增强型 |
| 95 | [MIRIX: Multi-Agent Memory System for LLM-Based Agents](https://arxiv.org/abs/2507.07957) | 2025 | `external, user, episodic, semantic, procedural` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 96 | [Evaluating memory in llm agents via incremental multi-turn interactions](https://arxiv.org/abs/2507.05257) | 2025 | `-` | Cross-turn carryover / anti-redundancy | 新增型 |
| 97 | [MemBench: Towards More Comprehensive Evaluation on the Memory of LLM-based Agents](https://arxiv.org/abs/2506.21605) | 2025 | `-` | Evaluation / benchmark / policy learning | 新增型 |
| 98 | [G-Memory: Tracing Hierarchical Memory for Multi-Agent Systems](https://arxiv.org/abs/2506.07398) | 2025 | `external, agent, episodic, procedural` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 99 | [BABILong: Testing the Limits of LLMs with Long Context Reasoning-in-a-Haystack](https://arxiv.org/abs/2406.10149) | 2025 | `-` | Compression / compaction / abstraction balancing | 增强型 |
| 100 | [Memory OS of AI Agent](https://arxiv.org/abs/2506.06326) | 2025 | `external, user, episodic, semantic, working` | 外部长时记忆 substrate | 增强型 |
| 101 | [Optimizing the Interface Between Knowledge Graphs and LLMs for Complex Reasoning](https://arxiv.org/abs/2505.24478) | 2025 | `external, agent, semantic` | Semantic abstraction / memory card | 增强型 |
| 102 | [Rethinking Memory in AI: Taxonomy, Operations, Topics, and Future Directions](https://arxiv.org/abs/2505.00675) | 2025 | `-` | Semantic abstraction / memory card | 增强型 |
| 103 | [Collaborative Memory: Multi-User Memory Sharing in LLM Agents with Dynamic Access Control](https://arxiv.org/abs/2505.18279) | 2025 | `external, agent, semantic` | Semantic abstraction / memory card | 增强型 |
| 104 | [Pre-training Limited Memory Language Models with Internal and External Knowledge](https://arxiv.org/abs/2505.15962) | 2025 | `external, internal, agent, semantic` | Semantic abstraction / memory card | 增强型 |
| 105 | [How Memory Management Impacts LLM Agents: An Empirical Study of Experience-Following Behavior](https://arxiv.org/abs/2505.16067) | 2025 | `external, agent, episodic` | Agent-centric experience memory | 新增型偏增强 |
| 106 | [ReSurgSAM2: Referring Segment Anything in Surgical Video via Credible Long-term Tracking](https://arxiv.org/abs/2505.08581) | 2025 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 107 | [Long Term Memory : The Foundation of AI Self-Evolution](https://arxiv.org/abs/2410.15665) | 2025 | `-` | Semantic abstraction / memory card | 增强型 |
| 108 | [Procedural Memory Is Not All You Need: Bridging Cognitive Gaps in LLM-Based Agents](https://arxiv.org/abs/2505.03434) | 2025 | `external, user, procedural` | User-centric personalization | 增强型 |
| 109 | [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory](https://arxiv.org/abs/2504.19413) | 2025 | `external, user, semantic` | 外部长时记忆 substrate | 增强型 |
| 110 | [Inducing Programmatic Skills for Agentic Tasks](https://arxiv.org/abs/2504.06821) | 2025 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 111 | [SkillWeaver: Web Agents can Self-Improve by Discovering and Honing Skills](https://arxiv.org/abs/2504.07079) | 2025 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 112 | [Advances and Challenges in Foundation Agents: From Brain-Inspired Intelligence to Evolutionary, Collaborative, and Safe Systems](https://arxiv.org/abs/2504.01990) | 2025 | `-` | Semantic abstraction / memory card | 增强型 |
| 113 | [VideoScan: Enabling Efficient Streaming Video Understanding via Frame-level Semantic Carriers](https://arxiv.org/abs/2503.09387) | 2025 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 114 | [Online Dense Point Tracking with Streaming Memory](https://arxiv.org/abs/2503.06471) | 2025 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 115 | [Enhancing Reasoning with Collaboration and Memory](https://arxiv.org/abs/2503.05944) | 2025 | `external, agent, episodic` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 116 | [Interpersonal Memory Matters: A New Task for Proactive Dialogue Utilizing Conversational History](https://arxiv.org/abs/2503.05150) | 2025 | `external, user, episodic` | Cross-turn carryover / anti-redundancy | 新增型 |
| 117 | [LM2: Large Memory Models for Long Context Reasoning](https://arxiv.org/abs/2502.06049) | 2025 | `internal, agent, working` | Compression / compaction / abstraction balancing | 增强型 |
| 118 | [EgoLife: Towards Egocentric Life Assistant](https://arxiv.org/abs/2503.03803) | 2025 | `external, user, episodic` | User-centric personalization | 增强型 |
| 119 | [SeCom: On Memory Construction and Retrieval for Personalized Conversational Agents](https://arxiv.org/abs/2502.05589) | 2025 | `external, user, episodic` | Retrieval routing / gating / shard probing | 增强型 |
| 120 | [Streaming Video Question-Answering with In-context Video KV-Cache Retrieval](https://arxiv.org/abs/2503.00540) | 2025 | `external, agent, sensory` | Retrieval routing / gating / shard probing | 增强型 |
| 121 | [Echo: A Large Language Model with Temporal Episodic Memory](https://arxiv.org/abs/2502.16090) | 2025 | `internal, user, episodic` | Episodic consolidation / narrative memory | 新增型偏增强 |
| 122 | [From RAG to Memory: Non-Parametric Continual Learning for Large Language Models](https://arxiv.org/abs/2502.14802) | 2025 | `external, agent, semantic` | Evaluation / benchmark / policy learning | 新增型 |
| 123 | [MMRC: A Large-Scale Benchmark for Understanding Multimodal Large Language Model in Real-World Conversation](https://arxiv.org/abs/2502.11903) | 2025 | `-` | Evaluation / benchmark / policy learning | 新增型 |
| 124 | [A-Mem: Agentic Memory for LLM Agents](https://arxiv.org/abs/2502.12110) | 2025 | `external, user, semantic` | 外部长时记忆 substrate | 增强型 |
| 125 | [R3Mem: Bridging Memory Retention and Retrieval via Reversible Compression](https://arxiv.org/abs/2502.15957) | 2025 | `external, agent, semantic` | Retrieval routing / gating / shard probing | 增强型 |
| 126 | [Classroom Simulacra: Building Contextual Student Generative Agents in Online Education for Learning Behavioral Simulation](https://arxiv.org/abs/2502.02780) | 2025 | `external, user, episodic` | User-centric personalization | 增强型 |
| 127 | [M+: Extending MemoryLLM with Scalable Long-Term Memory](https://arxiv.org/abs/2502.00592) | 2025 | `internal, agent, working` | 外部长时记忆 substrate | 增强型 |
| 128 | [ChunkKV: Semantic-Preserving KV Cache Compression for Efficient Long-Context LLM Inference](https://arxiv.org/abs/2502.00299) | 2025 | `internal, agent, working` | Compression / compaction / abstraction balancing | 增强型 |
| 129 | [TeachTune: Reviewing Pedagogical Agents Against Diverse Student Profiles with Simulated Students](https://arxiv.org/abs/2410.04078) | 2025 | `external, agent` | User-centric personalization | 增强型 |
| 130 | [Streaming Video Understanding and Multi-round Interaction with Memory-enhanced Knowledge](https://arxiv.org/abs/2501.13468) | 2025 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 131 | [SRMT: Shared Memory for Multi-agent Life-long Pathfinding](https://arxiv.org/abs/2501.13200) | 2025 | `internal, agent, working` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 132 | [Zep: a temporal knowledge graph architecture for agent memory](https://arxiv.org/abs/2501.13956) | 2025 | `external, user, semantic` | User-centric personalization | 增强型 |
| 133 | [Titans: Learning to Memorize at Test Time](https://arxiv.org/abs/2501.00663) | 2024 | `internal, agent, semantic` | Semantic abstraction / memory card | 增强型 |
| 134 | [Longmemeval: Benchmarking chat assistants on long-term interactive memory](https://arxiv.org/abs/2410.10813) | 2024 | `-` | Evaluation / benchmark / policy learning | 新增型 |
| 135 | [RET-LLM: Towards a General Read-Write Memory for Large Language Models](https://arxiv.org/abs/2305.14322) | 2024 | `external, user, semantic` | User-centric personalization | 增强型 |
| 136 | [PolySkill: Learning Generalizable Skills Through Polymorphic Abstraction](https://arxiv.org/abs/2510.15863) | 2024 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 137 | [From Isolated Conversations to Hierarchical Schemas: Dynamic Tree Memory Representation for LLMs](https://arxiv.org/abs/2410.14052) | 2024 | `external, user, semantic` | User-centric personalization | 增强型 |
| 138 | [Personalized Large Language Model Assistant with Evolving Conditional Memory](https://arxiv.org/abs/2312.17257) | 2024 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 139 | [Agents Thinking Fast and Slow: A Talker-Reasoner Architecture](https://arxiv.org/abs/2410.08328) | 2024 | `external, user, working` | User-centric personalization | 增强型 |
| 140 | [Self-updatable large language models by integrating context into model parameters](https://arxiv.org/abs/2410.00487) | 2024 | `internal, user, semantic` | User-centric personalization | 增强型 |
| 141 | [WALT: Web Agents that Learn Tools](https://arxiv.org/abs/2510.01524) | 2024 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 142 | [VideoAgent: A Memory-Augmented Multimodal Agent for Video Understanding](https://arxiv.org/abs/2403.11481) | 2024 | `external, agent, episodic, semantic` | Sensory / multimodal memory | 新增型 |
| 143 | [MemSim: A Bayesian Simulator for Evaluating Memory of LLM-based Personal Assistants](https://arxiv.org/abs/2409.20163) | 2024 | `external, user, episodic` | User-centric personalization | 增强型 |
| 144 | [Crafting Personalized Agents through Retrieval-Augmented Generation on Editable Memory Graphs](https://arxiv.org/abs/2409.19401) | 2024 | `external, user, semantic` | Retrieval routing / gating / shard probing | 增强型 |
| 145 | [MADial-Bench: Towards Real-world Evaluation of Memory-Augmented Dialogue Generation](https://arxiv.org/abs/2409.15240) | 2024 | `-` | Evaluation / benchmark / policy learning | 新增型 |
| 146 | [Agent Workflow Memory](https://arxiv.org/abs/2409.07429) | 2024 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 147 | [MemoRAG: Boosting Long Context Processing with Global Memory-Enhanced Retrieval Augmentation](https://arxiv.org/abs/2409.05591) | 2024 | `external, internal, agent, semantic` | Retrieval routing / gating / shard probing | 增强型 |
| 148 | [VideoLLM-MoD: Efficient Video-Language Streaming with Mixture-of-Depths Vision Computation](https://arxiv.org/abs/2408.16730) | 2024 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 149 | [AI-native Memory: A Pathway from LLMs Towards AGI](https://arxiv.org/abs/2406.18312) | 2024 | `-` | Semantic abstraction / memory card | 增强型 |
| 150 | [SAM 2: Segment Anything in Images and Videos](https://arxiv.org/abs/2408.00714) | 2024 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 151 | [VIPeR: Visual Incremental Place Recognition with Adaptive Mining and Continual Learning](https://arxiv.org/abs/2407.21416) | 2024 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 152 | [A Human-Inspired Reading Agent with Gist Memory of Very Long Contexts](https://arxiv.org/abs/2402.09727) | 2024 | `external, agent, episodic` | Compression / compaction / abstraction balancing | 增强型 |
| 153 | [FinCon: A Synthesized LLM Multi-Agent System with Conceptual Verbal Reinforcement for Enhanced Financial Decision Making](https://arxiv.org/abs/2407.06567) | 2024 | `external, agent, episodic, working, procedural` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 154 | [MemoCRS: Memory-enhanced Sequential Conversational Recommender Systems with Large Language Models](https://arxiv.org/abs/2407.04960) | 2024 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 155 | [Memory3 : Language Modeling with Explicit Memory](https://arxiv.org/abs/2407.01178) | 2024 | `external, internal, agent, working` | Working memory / scratchpad | 增强型 |
| 156 | [Lifelong Robot Library Learning: Bootstrapping Composable and Generalizable Skills for Embodied Control with Language Models](https://arxiv.org/abs/2406.18746) | 2024 | `external, agent, procedural` | Episodic consolidation / narrative memory | 新增型偏增强 |
| 157 | [VideoLLM-online: Online Video Large Language Model for Streaming Video](https://arxiv.org/abs/2406.11816) | 2024 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 158 | [Hello Again! LLM-powered Personalized Agent for Long-term Dialogue](https://arxiv.org/abs/2406.05925) | 2024 | `external, user, episodic` | User-centric personalization | 增强型 |
| 159 | [Buffer of Thoughts: Thought-Augmented Reasoning with Large Language Models](https://arxiv.org/abs/2406.04271) | 2024 | `external, agent, working` | Working memory / scratchpad | 增强型 |
| 160 | [Mobile-Agent-v2: Mobile Device Operation Assistant with Effective Navigation via Multi-Agent Collaboration](https://arxiv.org/abs/2406.01014) | 2024 | `external, agent, sensory, episodic` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 161 | [AutoManual: Constructing Instruction Manuals by LLM Agents via Interactive Environmental Learning](https://arxiv.org/abs/2405.16247) | 2024 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 162 | [Streaming Long Video Understanding with Large Language Models](https://arxiv.org/abs/2405.16009) | 2024 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 163 | [WISE: Rethinking the Knowledge Memory for Lifelong Model Editing of Large Language Models](https://arxiv.org/abs/2405.14768) | 2024 | `internal, agent, semantic` | Episodic consolidation / narrative memory | 新增型偏增强 |
| 164 | [Rethinking Agent Design: From Top-Down Workflows to Bottom-Up Skill Evolution](https://arxiv.org/abs/2505.17673) | 2024 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 165 | [HMT: Hierarchical Memory Transformer for Efficient Long Context Language Processing](https://arxiv.org/abs/2405.06067) | 2024 | `external, agent, sensory` | Compression / compaction / abstraction balancing | 增强型 |
| 166 | [Self-Organized Agents: A LLM Multi-Agent Framework toward Ultra Large-Scale Code Generation and Optimization](https://arxiv.org/abs/2404.02183) | 2024 | `external, agent, working` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 167 | ["My agent understands me better": Integrating Dynamic Human-like Memory Recall and Consolidation in LLM-Based](https://arxiv.org/abs/2404.00573) | 2024 | `external, user, episodic, semantic` | Retrieval routing / gating / shard probing | 增强型 |
| 168 | [EduAgent: Generative Student Agents in Learning](https://arxiv.org/abs/2404.07963) | 2024 | `external, agent` | Agent-centric experience memory | 新增型偏增强 |
| 169 | [AutoGuide: Automated Generation and Selection of Context-Aware Guidelines for Large Language Model Agents](https://arxiv.org/abs/2403.08978v2) | 2024 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 170 | [Online Adaptation of Language Models with a Memory of Amortized Contexts](https://arxiv.org/abs/2403.04317) | 2024 | `internal, agent, episodic` | Agent-centric experience memory | 新增型偏增强 |
| 171 | [Evaluating Very Long-Term Conversational Memory of LLM Agents](https://arxiv.org/abs/2402.17753) | 2024 | `-` | Cross-turn carryover / anti-redundancy | 新增型 |
| 172 | [Beyond Retrieval: Embracing Compressive Memory in Real-World Long-Term Conversations](https://arxiv.org/abs/2402.11975) | 2024 | `external, user, episodic` | Retrieval routing / gating / shard probing | 增强型 |
| 173 | [In Search of Needles in a 11M Haystack: Recurrent Memory Finds What LLMs Miss](https://arxiv.org/abs/2402.10790) | 2024 | `-` | Retrieval routing / gating / shard probing | 增强型 |
| 174 | [User Behavior Simulation with Large Language Model based Agents](https://arxiv.org/abs/2306.02552v3) | 2024 | `external, user, sensory, semantic, working` | User-centric personalization | 增强型 |
| 175 | [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) | 2024 | `external, internal, user` | User-centric personalization | 增强型 |
| 176 | [MEMORYLLM: Towards Self-Updatable Large Language Models](https://arxiv.org/abs/2402.04624) | 2024 | `internal, agent, semantic` | Semantic abstraction / memory card | 增强型 |
| 177 | [QuantAgent: Seeking Holy Grail in Trading by Self-Improving Large Language Model](https://arxiv.org/abs/2402.03755) | 2024 | `external, agent, semantic` | Semantic abstraction / memory card | 增强型 |
| 178 | [RAP: Retrieval-Augmented Planning with Contextual Memory for Multimodal LLM Agents](https://arxiv.org/abs/2402.03610) | 2024 | `external, agent, episodic` | Retrieval routing / gating / shard probing | 增强型 |
| 179 | [A Multi-Agent Conversational Recommender System](https://arxiv.org/abs/2402.01135) | 2024 | `external, user, episodic, semantic, procedural` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 180 | [War and Peace (WarAgent): LLM-based Multi-Agent Simulation of World Wars](https://arxiv.org/abs/2311.17227) | 2024 | `external, agent, episodic` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 181 | [Developing ChemDFM as a Large Language Foundation Model for Chemistry](https://arxiv.org/abs/2401.14818) | 2024 | `internal, agent, semantic` | Semantic abstraction / memory card | 增强型 |
| 182 | [TroVE: Inducing Verifiable and Efficient Toolboxes for Solving Programmatic Tasks](https://arxiv.org/abs/2401.12869) | 2024 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 183 | [From LLM to Conversational Agent: A Memory Enhanced Architecture with Fine-Tuning of Large Language Models](https://arxiv.org/abs/2401.02777) | 2024 | `external, agent, working` | Working memory / scratchpad | 增强型 |
| 184 | [FinMem: A Performance-Enhanced LLM Trading Agent with Layered Memory and Character Design](https://arxiv.org/abs/2311.13743) | 2023 | `external, agent, semantic, working` | Working memory / scratchpad | 增强型 |
| 185 | [Think-in-Memory: Recalling and Post-thinking Enable LLMs with Long-Term Memory](https://arxiv.org/abs/2311.08719) | 2023 | `external, agent, episodic` | Retrieval routing / gating / shard probing | 增强型 |
| 186 | [JARV IS-1: Open-world Multi-task Agents with Memory-Augmented Multimodal Language Models](https://arxiv.org/abs/2311.05997) | 2023 | `external, agent, episodic, semantic` | Sensory / multimodal memory | 新增型 |
| 187 | [Knowledge Editing for Large Language Models: A Survey](https://arxiv.org/abs/2310.16218) | 2023 | `-` | Evaluation / benchmark / policy learning | 新增型 |
| 188 | [Character-LLM: A Trainable Agent for Role-Playing](https://arxiv.org/abs/2310.10158) | 2023 | `internal, user, semantic` | User-centric personalization | 增强型 |
| 189 | [AgentCF: Collaborative Learning with Autonomous Language Agents for Recommender Systems](https://arxiv.org/abs/2310.09233) | 2023 | `external, user, episodic` | User-centric personalization | 增强型 |
| 190 | [GameGPT: Multi-agent Collaborative Framework for Game Development](https://arxiv.org/abs/2310.08067v1) | 2023 | `external, agent, working` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 191 | [MetaAgents: Large Language Model Based Agents for Decision-making on Teaming](https://arxiv.org/abs/2310.06500) | 2023 | `external, agent, episodic` | Agent-centric experience memory | 新增型偏增强 |
| 192 | [RoleLLM: Benchmarking, Eliciting, and Enhancing Role-Playing Abilities of Large Language Models](https://arxiv.org/abs/2310.00746) | 2023 | `external, internal, user, semantic` | Evaluation / benchmark / policy learning | 新增型 |
| 193 | [AutoAgents: A Framework for Automatic Agent Generation](https://arxiv.org/abs/2309.17288) | 2023 | `external, agent, episodic, working, procedural` | Procedural / skill memory | 新增型偏增强 |
| 194 | [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180) | 2023 | `internal, agent, working` | Working memory / scratchpad | 增强型 |
| 195 | [TradingGPT: Multi-Agent System with Layered Memory and Distinct Characters for Enhanced Financial Trading Performance](https://arxiv.org/abs/2309.03736) | 2023 | `external, agent, semantic, working` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 196 | [Recommender AI Agent: Integrating Large Language Models for Interactive](https://arxiv.org/abs/2308.16505) | 2023 | `external, internal, user, episodic, semantic` | User-centric personalization | 增强型 |
| 197 | [RecMind: Large Language Model Powered Agent For Recommendation](https://arxiv.org/abs/2308.14296) | 2023 | `external, internal, user, semantic, working` | User-centric personalization | 增强型 |
| 198 | [Black-box Unsupervised Domain Adaptation with Bi-directional Atkinson-Shiffrin Memory](https://arxiv.org/abs/2308.13236) | 2023 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 199 | [MemoChat: Tuning LLMs to Use Memos for Consistent Long-Range Open-Domain Conversation](https://arxiv.org/abs/2308.08239) | 2023 | `external, user, episodic` | User-centric personalization | 增强型 |
| 200 | [Context-Aware Planning and Environment-Aware Memory for Instruction Following Embodied Agents](https://arxiv.org/abs/2308.07241) | 2023 | `external, agent, sensory, episodic, working` | Sensory / multimodal memory | 新增型 |
| 201 | [ChatHaruhi: Reviving Anime Character in Reality via Large Language Model](https://arxiv.org/abs/2308.09597) | 2023 | `external, user, semantic` | User-centric personalization | 增强型 |
| 202 | [Retroformer: Retrospective Large Language Agents with Policy Gradient Optimization](https://arxiv.org/abs/2308.02151) | 2023 | `external, user, procedural` | User-centric personalization | 增强型 |
| 203 | [MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework](https://arxiv.org/abs/2308.00352) | 2023 | `external, agent, procedural` | Multi-agent handoff / delegated evidence extraction | 新增型偏增强 |
| 204 | [XMem++: Production-level Video Segmentation From Few Annotated Frames](https://arxiv.org/abs/2307.15958) | 2023 | `external, agent, sensory` | Sensory / multimodal memory | 新增型 |
| 205 | [S3 : Social-network Simulation System with Large Language Model-Empowered Agents](https://arxiv.org/abs/2307.14984) | 2023 | `external, user, episodic` | User-centric personalization | 增强型 |
| 206 | [GridMM: Grid Memory Map for Vision-and-Language Navigation](https://arxiv.org/abs/2307.12907) | 2023 | `internal, agent, sensory, working` | Sensory / multimodal memory | 新增型 |
| 207 | [ChatDev: Communicative Agents for Software Development](https://arxiv.org/abs/2307.07924) | 2023 | `external, agent, working` | Working memory / scratchpad | 增强型 |
| 208 | [Synapse: Trajectory-as-Exemplar Prompting with Memory for Computer Control](https://arxiv.org/abs/2306.07863) | 2023 | `external, agent, episodic` | Agent-centric experience memory | 新增型偏增强 |
| 209 | [Augmenting Language Models with Long-Term Memory](https://arxiv.org/abs/2306.07174) | 2023 | `external, internal, agent, working` | 外部长时记忆 substrate | 增强型 |
| 210 | [ChatDB: Augmenting LLMs with Databases as Their Symbolic Memory](https://arxiv.org/abs/2306.03901) | 2023 | `external, agent, semantic` | 外部长时记忆 substrate | 增强型 |
| 211 | [Ghost in the Minecraft: Generally Capable Agents for Open-World Environments via Large Language Models with Text-based Knowledge and Memory](https://arxiv.org/abs/2305.17144) | 2023 | `external, agent, episodic, semantic` | Semantic abstraction / memory card | 增强型 |
| 212 | [AdaPlanner: Adaptive Planning from Feedback with Language Models](https://arxiv.org/abs/2305.16653) | 2023 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 213 | [Reasoning with Language Model is Planning with World Model](https://arxiv.org/abs/2305.14992) | 2023 | `external, agent, working` | Working memory / scratchpad | 增强型 |
| 214 | [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/abs/2305.16291) | 2023 | `external, agent, procedural` | Procedural / skill memory | 新增型偏增强 |
| 215 | [MemoryBank: Enhancing Large Language Models with Long-Term Memory](https://arxiv.org/abs/2305.10250) | 2023 | `external, user, episodic, semantic` | User-centric personalization | 增强型 |
| 216 | [Prompted LLMs as Chatbot Modules for Long Open-domain Conversation](https://arxiv.org/abs/2305.04533) | 2023 | `external, user, working` | User-centric personalization | 增强型 |
| 217 | [Recursively Summarizing Enables Long-Term Dialogue Memory in Large Language Models](https://arxiv.org/abs/2308.15022v3) | 2023 | `external, user, semantic` | User-centric personalization | 增强型 |
| 218 | [SCM:Enhancing Large Language Model with Self-Controlled Memory Framework](https://arxiv.org/abs/2304.13343) | 2023 | `external, agent, episodic` | 外部长时记忆 substrate | 增强型 |
| 219 | [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442) | 2023 | `external, agent, episodic` | Agent-centric experience memory | 新增型偏增强 |
| 220 | [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366) | 2023 | `external, agent, episodic` | Agent-centric experience memory | 新增型偏增强 |
| 221 | [Beyond Goldfish Memory∗: Long-Term Open-Domain Conversation](https://arxiv.org/abs/2107.07567) | 2021 | `-` | Semantic abstraction / memory card | 增强型 |
