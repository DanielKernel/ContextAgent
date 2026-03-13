# ContextAgent 记忆与上下文召回优化路线图

本文档用于持续记录两类内容：

1. 基于 `Awesome-Agent-Memory` 论文库得到的结构化分析结论。
2. 这些结论在 ContextAgent 中的实际落地进展、验证结果与后续待办。

---

## 1. 文档目标与使用方式

本路线图不追求一次性覆盖全部论文，而是采用“高相关优先、持续增量更新”的方式推进。

每一轮分析都按以下结构追加：

- 论文或论文批次
- 核心机制摘要
- 对 ContextAgent 当前实现的启发
- 可落地改造建议
- 优先级、收益、风险与验证方案
- 实际完成内容与后续待办

后续新增分析时，优先补充与以下模块直接相关的论文：

- `context_agent/orchestration/context_aggregator.py`
- `context_agent/core/memory/tiered_router.py`
- `context_agent/core/retrieval/search_coordinator.py`
- `context_agent/core/memory/orchestrator.py`
- `context_agent/core/memory/working_memory.py`
- `context_agent/adapters/ltm_adapter.py`
- `context_agent/orchestration/sub_agent_manager.py`

---

## 2. ContextAgent 当前实现基线

### 2.1 已有能力

当前代码已经具备一个较完整的“基础版 memory system”骨架：

| 方向 | 当前实现 |
| --- | --- |
| 多源聚合 | `ContextAggregator` 并行聚合 LTM、working memory、JIT refs，并支持超时降级 |
| 分层召回 | `TieredMemoryRouter` 已区分 hot / warm / cold，并按时延预算逐层召回 |
| 混合检索 | `UnifiedSearchCoordinator` 已支持 hybrid / graph / LTM 并行与 RRF 融合 |
| 工作记忆 | `WorkingMemoryManager` 支持 session 级 notes 与 items，Redis 不可用时可降级到进程内存 |
| 异步写入 | `MemoryOrchestrator` + `AsyncMemoryProcessor` 已支持 working memory 立即写入、LTM 异步持久化 |
| 基础分类 | 当前已区分 `VARIABLE / EPISODIC / SEMANTIC / PROCEDURAL`，并映射到 `PROFILE / PREFERENCES / EVENTS` 等类别 |
| 质量路径 | `ContextAggregator` 已保留 `mode=quality` 路径，可接入更强的 agentic retrieval |
| 压缩降级 | `CompressionStrategyRouter` 具备策略路由与失败回退机制 |

### 2.2 当前明显缺口

结合现有实现，当前主要缺口不是“没有记忆”，而是“记忆组织与召回策略还比较朴素”：

1. `MemoryOrchestrator._classify_message()` 仍以轻量规则为主，缺少 episode 边界识别、记忆 consolidation 和抽象层次建模。
2. `ContextAggregator` 目前已经接入轻量 `task-conditioned retrieval` 重排序，但整体仍以“并行抓取 + score 排序 + token budget 截断”为主，缺少跨 turn carryover、coverage-aware pruning、信息瓶颈式候选压缩与叙事级重建。
3. `TieredMemoryRouter` 的 hot tier 只缓存 `VARIABLE`，对 episodic / semantic / profile 的热点管理还不够细，也缺少 turn / episode / topic 维度的 gating。
4. `UnifiedSearchCoordinator` 已有 RRF、hotness blending 与 task-aware reordering，但还没有真正的“scope-before-routing”“memory shard gating”“cue-anchor expansion”“episode/topic eligibility masking”等更强 routing 策略。
5. 用户记忆与 agent 经验记忆虽然在概念上已区分，但当前写入、召回、评估策略还没有围绕“偏好演化、长期稳定画像、技能记忆”形成强约束分流。
6. 多 agent handoff 已有基础能力，但还未形成“episodic reconstruction + compressed handoff + delegated local reasoning + evidence extraction”的完整链路。

因此，第一阶段的优化重点应放在：**记忆组织、候选筛选、召回策略、叙事重建、分层结构增强**，而不是先去做底层存储替换。

---

## 3. 第一阶段论文筛选原则

本阶段优先选择与当前代码缺口高度相关的论文，而不是按时间顺序通读。

筛选标准如下：

1. 能直接改善长时程记忆检索质量，而不是仅讨论通用 agent 框架。
2. 能映射到当前已有模块，而不是必须先重写整套架构。
3. 机制上可拆分、可分阶段落地，能在单模块内先试点验证。
4. 能给出明确的离线或回归测试目标。

---

## 4. 第一阶段高优先级论文批次

本轮优先分析以下 6 篇：

| 论文 | 关注点 | 与 ContextAgent 的关联度 |
| --- | --- | --- |
| [TraceMem](https://arxiv.org/abs/2602.09712) | 对话轨迹叙事化、episode 切分、层级 consolidation | 很高 |
| [STaR](https://arxiv.org/abs/2602.09255) | task-conditioned retrieval、信息瓶颈式候选压缩 | 很高 |
| [MEMORA](https://arxiv.org/abs/2602.03315) | 抽象与细节平衡、cue anchor、多入口召回 | 很高 |
| [E-mem](https://arxiv.org/abs/2601.21714) | episodic context reconstruction、多 assistant 局部推理 | 很高 |
| [Darwinian Memory](https://arxiv.org/abs/2601.22528) | 动态记忆生态、utility-driven pruning | 中高 |
| [ShardMemo](https://arxiv.org/abs/2601.21545) | 分片路由、scope-before-routing、tiered memory service | 很高 |

---

## 5. 逐篇分析与可落地建议

### 5.1 TraceMem

**核心机制**

TraceMem 的关键贡献不只是“存更多对话”，而是把用户长期对话轨迹拆成 episode，再经过多阶段 consolidation，最终形成带主题和时间演化关系的 narrative memory schema。

**对 ContextAgent 的启发**

ContextAgent 现在已有 working / episodic / semantic / procedural 的基础类型，但从 `MemoryOrchestrator` 当前实现看，episodic 与 semantic 的形成仍偏“句级分类”，缺少：

- episode 边界识别
- 对话片段到 episodic summary 的 consolidation
- 用户长期 narrative thread
- 用户记忆卡（稳定偏好、阶段性目标、关键事件）的层级组织

**建议落地点**

1. 在 `MemoryOrchestrator` 之上新增“memory consolidation”阶段，而不是直接把原始消息送入 LTM。
2. 为 `WorkingMemoryManager` 或新增组件引入 `episode_id`、`episode_summary`、`theme`、`timeline_position` 等结构化字段。
3. 在 `OpenJiuwenLTMAdapter.add_messages()` 之前，先做一次 session 内 episode 聚合：
   - 短期：基于 turn 数、topic shift、任务状态切换做规则切分
   - 中期：增加 LLM/embedding 辅助的 episode segmentation
4. 新增“user memory card”视图，作为 `PROFILE / PREFERENCES / EVENTS` 之上的稳定聚合层，用于 personalization recall。

**优先级**

P0。因为它直接改善用户长期记忆组织方式，而且能在当前代码结构上增量实现。

**建议验证**

- 针对长会话构造多主题测试集，验证跨 topic / 跨时间的 multi-hop recall。
- 对比“原始消息直写 LTM”和“episode consolidation 后写入”的召回准确率与 token 使用量。

---

### 5.2 STaR

**核心机制**

STaR 的重点是 task-conditioned retrieval：不是先取“大而全”的候选，再交给下游模型，而是按任务条件压缩成紧凑、非冗余、信息密度高的候选集。

**对 ContextAgent 的启发**

当前 `ContextAggregator` 和 `UnifiedSearchCoordinator` 都有召回，但仍以 query 驱动为主，对 `task_type`、`agent_role`、当前阶段状态的利用还比较浅。

**建议落地点**

1. 扩展 `AggregationRequest` 和 `RetrievalPlan`，让 `task_type`、`agent_role`、阶段标签真正进入召回打分。
2. 在 `UnifiedSearchCoordinator` 前增加 task-conditioned candidate pruning：
   - 先召回 2x~4x 候选
   - 再按 task-conditioned features 做信息瓶颈式压缩
3. 在 `ContextAggregator.aggregate()` 中将“去重”升级为“去重 + 去冗余 + 信息覆盖最大化”。
4. 将 `CompressionStrategyRouter` 与 retrieval 串联，支持“先轻量召回压缩，再做最终压缩输出”。

**优先级**

P0。对当前主链路最容易形成直接收益，尤其适合现有 `task_type` 字段已经存在但尚未深用的现状。

**建议验证**

- 按 `task_type` 构造回归集，比较 task-conditioned rerank 前后 Top-K recall 与最终回答质量。
- 跟踪 token_count、latency、冗余片段占比。

---

### 5.3 MEMORA

**核心机制**

MEMORA 试图解决“抽象提升可扩展性，但会损失细节”这个经典矛盾。它通过 primary abstractions + concrete memory values + cue anchors，把抽象层和细节层连接起来，并且让召回不只依赖直接语义相似度。

**对 ContextAgent 的启发**

虽然 `ContextAggregator` 已支持 `ABSTRACT / OVERVIEW / DETAIL` 三层 detail level，但当前实现更像“内容粒度过滤”，还不是“抽象节点驱动细节展开”的结构化记忆图。

**建议落地点**

1. 将现有 `ContextLevel` 从“过滤标签”升级为“层级索引结构”：
   - L0: abstract memory card / episode headline
   - L1: overview summary
   - L2: raw detail
2. 为 `ContextItem.metadata` 引入 anchor 关系：
   - `parent_memory_id`
   - `related_memory_ids`
   - `cue_terms`
   - `abstraction_of`
3. 在 `UnifiedSearchCoordinator` 中加入 cue-anchor expansion：
   - 命中抽象项后，自动扩展其相关 detail 候选
4. 为 `TieredMemoryRouter` 增加“先 abstract 后 detail”的预算分配策略。

**优先级**

P0-P1。因为当前代码已经有 `ContextLevel`，具备天然切入点。

**建议验证**

- 长会话下比较“只用 detail 相似度召回”与“abstract + anchor expansion”在 multi-hop / temporal questions 上的表现。
- 跟踪 token 利用率：相同 token budget 下是否能覆盖更多关键上下文。

---

### 5.4 E-mem

**核心机制**

E-mem 反对过度预处理记忆，强调 episodic context reconstruction：不是把所有历史压成静态 embedding 或图结构，而是在需要时激活相关 episode，由局部 agent 在原始上下文段内做上下文敏感推理，再把证据汇总给主 agent。

**对 ContextAgent 的启发**

这与 ContextAgent 的 `SubAgentContextManager`、`JITResolver`、`quality mode` 很契合，但当前这些能力还没有被真正编织成“激活 episode → 局部推理 → 汇总 handoff”的检索链路。

**建议落地点**

1. 在 `ContextAggregator` 的 `mode=quality` 路径中引入 episodic reconstruction 分支。
2. 当 query 命中多个相关 episode 时，不直接拼接所有片段，而是：
   - 先选 episode
   - 再让局部 sub-agent / helper 对单个 episode 做证据提炼
   - 最后聚合成 `ContextSnapshot`
3. 为 `SubAgentContextManager` 增加“memory evidence extraction”模式，而不仅是普通上下文委托。
4. 为 `JITResolver` 增加 episode ref 解析能力。

**优先级**

P1。因为这条线收益高，但需要把 retrieval、sub-agent、handoff 三块连起来。

**建议验证**

- 构造跨 episode、多跳推理问题，比较直接召回 vs episodic reconstruction。
- 关注 token 成本和 latency，验证是否能像论文中那样在降低 token 的同时保持甚至提升效果。

---

### 5.5 Darwinian Memory

**核心机制**

Darwinian Memory 的重点是把记忆当作动态生态系统，按 utility 做自然选择和持续淘汰，避免静态累积带来的 context pollution。

**对 ContextAgent 的启发**

当前系统已有 `hotness`、`mark_used()`、健康检查与压缩，但还缺少“长期 utility 评分 + 风险抑制 + 自动淘汰”的显式机制。

**建议落地点**

1. 在 `ContextItem.metadata` 或独立索引中引入 utility signal：
   - successful_use_count
   - contradiction_count
   - last_successful_task_type
   - staleness_score
2. 扩展 `compute_hotness()`，让热度不再等同于“新近 + 被点过”，而是综合 utility / risk / freshness。
3. 定期执行 memory pruning / archiving：
   - 高频低收益记忆降权
   - 高风险冲突记忆隔离
   - 长期未命中但高价值记忆转冷存档
4. 将 `ContextHealthChecker` 与 pruning 策略打通。

**优先级**

P1。适合在已有监控与热度机制上迭代增强。

**建议验证**

- 对长期运行数据比较 pruning 前后 hallucination / contradiction / distractor 比例。
- 监测命中率、成功率、平均候选数与平均 token 开销。

---

### 5.6 ShardMemo

**核心机制**

ShardMemo 强调 tiered memory service + scope-before-routing + shard-level gated probing。核心思想是：先用结构化约束排除不可能相关的 shard，再在剩余 shard 上做预算受控的路由和 ANN 搜索。

**对 ContextAgent 的启发**

这几乎就是 `TieredMemoryRouter` 与 `UnifiedSearchCoordinator` 的下一阶段形态。当前系统已有 tier，但尚未真正做到：

- 结构化 eligibility masking
- shard family / scope family 路由
- budgeted probing
- skill library / procedure-specific retrieval

**建议落地点**

1. 在 `RetrievalPlan.filters` 基础上新增 scope-before-routing：
   - `scope_id`
   - `session_id`
   - `memory_type`
   - `category`
   - `task_type`
   - `agent_role`
2. 在 `UnifiedSearchCoordinator` 外围加入 shard family 概念：
   - profile shard
   - episodic shard
   - working-state shard
   - procedure / tool shard
3. 将 `top_k` 搜索改造成 `probe_budget + per_shard_top_k` 模式。
4. 将 procedural / tool memory 独立为类似 Tier C 的“skill library”。

**优先级**

P0-P1。因为它与当前现有模块边界高度一致，且可分阶段实现。

**建议验证**

- 比较“全局召回”与“scope-before-routing + shard probing”在 p95 latency、Top-K 精度、无关候选比例上的差异。
- 对多 agent / 多 session 混合数据验证误召回是否下降。

---


### 5.7 ContextAgent 与 openJiuwen 能力对照（面向多轮交互体验）

**当前能力边界**

从当前实现看，`openJiuwen` 已经提供了比较强的长期记忆 substrate：`LongTermMemory` 负责消息写入、用户记忆搜索、向量/混合/图检索后端接入；`ContextAgent` 则主要负责 working memory、召回编排、压缩、上下文装配、暴露治理与 sub-agent handoff。

这条边界本身是合理的，但**多轮对话体验所需的结构化信号还没有被真正透传到 openJiuwen，也没有在 ContextAgent 编排层成为一等输入**。

| 方向 | 当前能力 | 现状问题 | 更适合的优化位置 |
| --- | --- | --- | --- |
| 长期记忆写入 | `OpenJiuwenLTMAdapter.add_messages()` 已调用 openJiuwen `LongTermMemory.add_messages()`，并启用 profile / semantic / episodic / summary memory 开关 | 当前仍以 flat message list 写入，缺少 `turn_index`、`episode_id`、`topic`、`resolution_state` 等 hint | ContextAgent 先做 episode consolidation，再通过 adapter 传 richer metadata 给 openJiuwen |
| 长期记忆检索 | `OpenJiuwenLTMAdapter.search()` 已调用 `search_user_mem`，支持基础 `filters` | 目前更多是把 openJiuwen 当作通用搜索引擎，缺少 episode/topic/session/task 维度的显式 gating | ContextAgent 构建 retrieval plan / filters，adapter 负责透传 |
| 工作记忆 | `WorkingMemoryManager` 已提供 session 级 note/item 存储和 `mark_used()` 反馈 | 只有 session 粒度，没有 turn / episode / unresolved issue / current topic 粒度 | ContextAgent working-memory schema 扩展 |
| 聚合装配 | `ContextAggregator` 已支持多源并发、detail level、task-aware rerank | 仍偏 stateless query aggregation，对“上一个 turn 用过什么 / 还缺什么”几乎无感知 | ContextAgent aggregation request 与 selection 逻辑扩展 |
| 压缩输出 | `CompressionStrategyRouter` 已有策略路由与回退 | 当前压缩对象仍是 flat items，不保留问答对、决议、未解决项等 dialogue acts | ContextAgent compression strategy 升级 |
| 多 agent 隔离 | `SubAgentContextManager` 已能创建 child scope 与 merge result | 还不是对话线程级 handoff，没有局部 episode evidence extraction | ContextAgent orchestration / quality path |

**结论**

1. 不应绕过 `openJiuwen` 直接在业务代码里操作向量库或长期记忆后端。
2. 多轮体验优化的主战场仍然是 `ContextAgent` 的编排层：先把 turn / episode / topic / preference-evolution 这些结构化信号组织起来。
3. 当这些信号稳定后，再通过 `OpenJiuwenLTMAdapter` 把 metadata、filters、search hints 更充分地透传给 `openJiuwen`，才能真正释放其 LTM 能力。
4. 因此，roadmap 里优先级应从“更换底层存储”转向“强化编排输入与记忆结构”，然后再做更精细的 routing / retrieval / reconstruction。

---


## 6. 面向多轮交互体验的重规划

### 6.1 本轮重规划的目标

这轮不再只问“哪个 memory 机制先进”，而是优先回答：**哪个优化最能直接改善真实多轮对话中的交互体验**。

重点关注以下 6 类体验指标：

1. **连续性**：系统能否理解“这是同一段对话的延续”，而不是每轮都从零召回。
2. **少重复**：连续多个 turn 是否反复注入同一批上下文，造成模型输出重复。
3. **个性化演化**：用户偏好、阶段目标、风格要求是否会随对话更新，而不是静态 profile。
4. **长会话可读性**：压缩后的上下文是否保留问答关系、决策与未解决事项，而不是碎片拼接。
5. **topic 切换恢复能力**：在多个 topic / subtask / episode 来回切换时，能否快速回到正确上下文。
6. **委托后的连续性**：sub-agent 是否能在受控上下文下延续主线程，并回传可复用证据而不是裸结果。

### 6.2 面向交互体验的优先级改造清单

#### P0：对多轮体验最直接的改造

1. **Turn-aware context carryover + anti-redundancy selection**
   - 目标模块：`OpenClaw assemble`、`ContextAPIRouter`、`ContextAggregator`、`task_conditioning.py`
   - 对应论文/启发：STaR、E-mem
   - 目标收益：减少连续 turn 的重复注入，让系统知道“上轮已经给过什么、这轮还缺什么”
   - 说明：这是当前最缺失、但对体感最直接的能力；应把 `turn_index`、`previous_context_ids`、`dialogue_topic`、`resolution_state` 之类信号纳入请求与排序

2. **Episode consolidation + narrative memory before LTM write**
   - 目标模块：`MemoryOrchestrator`、`AsyncMemoryProcessor`、`WorkingMemoryManager`、`OpenJiuwenLTMAdapter`
   - 对应论文：TraceMem
   - 目标收益：把多轮对话从“消息碎片堆积”升级为“episode / narrative thread”，显著提升跨 turn continuity 与跨 topic 回忆质量
   - 说明：这是长会话体验的基础设施，也会为后续 episode gating、episodic reconstruction 提供结构前提

3. **Dialogue-aware compression for long_session / compaction**
   - 目标模块：`CompressionStrategyRouter`、压缩策略注册表、`openclaw_handler.compact`
   - 对应论文/启发：STaR、TraceMem、E-mem
   - 目标收益：压缩结果保留问答对、关键决议、未决事项和状态变化，提升长会话下的可读性与可继续性
   - 说明：当前压缩是 flat-item driven，这对多轮交互体验损伤很大，应尽快补齐

4. **Scope-before-routing + episode/topic gating**
   - 目标模块：`UnifiedSearchCoordinator`、`TieredMemoryRouter`、`OpenJiuwenLTMAdapter`
   - 对应论文：ShardMemo
   - 目标收益：用户切 topic、回到旧任务、跨 session 回忆时，更快定位正确记忆范围，减少无关干扰
   - 说明：需优先支持 `session_id`、`episode_id`、`topic`、`task_type`、`agent_role` 级 filters

5. **Task-conditioned retrieval 从 rerank 升级为 pruning + coverage-aware selection**
   - 目标模块：`task_conditioning.py`、`ContextAggregator`、`UnifiedSearchCoordinator`
   - 对应论文：STaR、MEMORA
   - 目标收益：在固定 token budget 下减少冗余，提高每轮注入的信息密度
   - 说明：该方向已做轻量重排序，应作为“已部分落地的 P0”继续深化，而不是重起炉灶

6. **User preference evolution / personalized memory card**
   - 目标模块：`MemoryOrchestrator`、`WorkingMemoryManager`、`OpenJiuwenLTMAdapter`
   - 对应论文：TraceMem、Darwinian Memory
   - 目标收益：让系统能识别“新偏好覆盖旧偏好”“阶段性目标变化”“长期稳定画像与临时偏好并存”
   - 说明：这对助手类、多轮协作类场景的主观体验提升非常明显

#### P1：建立在 P0 结构之上的增强能力

1. **Abstract-first recall + cue-anchor expansion**
   - 目标模块：`ContextItem`、`ContextAggregator`、`UnifiedSearchCoordinator`
   - 对应论文：MEMORA
   - 适合在 episode / anchor metadata 到位后推进

2. **Episodic reconstruction in quality mode + delegated evidence extraction**
   - 目标模块：`ContextAggregator(mode=quality)`、`SubAgentContextManager`、`JITResolver`
   - 对应论文：E-mem
   - 适合在 episode consolidation 与 scope gating 初步稳定后推进

3. **Utility-driven pruning + contradiction-aware suppression**
   - 目标模块：`WorkingMemoryManager`、`ContextHealthChecker`、LTM metadata、hotness 计算
   - 对应论文：Darwinian Memory
   - 重点解决长期运行后的 context pollution、冲突记忆与低价值高频记忆问题

4. **Agent skill card / procedure shard**
   - 目标模块：`OpenJiuwenLTMAdapter`、`UnifiedSearchCoordinator`、`TieredMemoryRouter`
   - 对应论文：ShardMemo、TraceMem
   - 适合在用户记忆与 agent 经验记忆分流之后推进

#### P2：中长期演进

1. 学习式 memory routing / policy optimization
2. 多轮连续性质量评估器（continuity / redundancy / recovery benchmarks）
3. 多 agent 共享记忆协议与 delegated memory evidence exchange
4. 更强的长期个性化稳定性/漂移控制机制

---

## 7. 建议的落地顺序（按多轮体验收益排序）

### Phase 1：先补足多轮连续性的基础信号

- 为请求链路补入 `turn_index`、`previous_context_ids`、`dialogue_topic`、`resolution_state`
- 将现有 task-conditioned retrieval 升级为 anti-redundancy + coverage-aware selection
- 明确用于评估的多轮体验指标：重复率、continuity、topic recovery、压缩可读性

### Phase 2：把消息流改造成 episode / narrative 结构

- 在 LTM 写入前增加 episode consolidation
- 给 working memory / LTM metadata 补 `episode_id`、`topic`、`timeline_position`、`preference_scope`
- 建立 user memory card / preference evolution 的基础结构

### Phase 3：升级召回与压缩体验

- 实现 scope-before-routing + episode/topic gating
- 引入 dialogue-aware compression，优先用于 `long_session` / `compaction`
- 在固定 token budget 下做到更少重复、更多关键信息保留

### Phase 4：增强复杂问题与多 agent 场景

- abstract-first recall + cue-anchor expansion
- episodic reconstruction + delegated evidence extraction
- utility-driven pruning / contradiction-aware suppression / skill shard

---

## 8. 本轮实际完成内容

本轮已完成以下工作：

1. 阅读 `Awesome-Agent-Memory` 仓库的 taxonomy 与论文索引，确认该仓库适合采用“高相关优先”的持续分析策略。
2. 结合 ContextAgent 当前代码，梳理出第一阶段最相关的优化方向：
   - task-conditioned retrieval
   - episode consolidation
   - abstract-first memory organization
   - scope-before-routing / shard probing
   - episodic reconstruction
   - utility-driven pruning
3. 选定首批 6 篇高优先级论文，并完成逐篇分析：
   - TraceMem
   - STaR
   - MEMORA
   - E-mem
   - Darwinian Memory
   - ShardMemo
4. 建立本文档，作为后续持续追加“论文分析 + 实际落地进展”的主文档。
5. 在已有论文分析基础上，重新以“多轮对话交互体验”为目标审视 `ContextAgent` 与 `openJiuwen` 的真实能力边界，并把 roadmap 从“机制导向”重排为“体验收益导向”。

---

## 9. 已落地进展

### 9.1 Task-conditioned retrieval / candidate pruning

**状态**

done

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

**当前效果**

当前实现已经能让系统在不引入额外外部依赖的情况下，按任务类型更偏向：

- `qa`：semantic / profile / preferences
- `task`：variable / procedural / patterns / hot tier
- `long_session`：episodic / events / overview
- `realtime`：hot / variable / abstract
- `compaction`：abstract / overview

这属于路线图中的 P0 第一阶段：先让已有字段真正参与召回，而不是停留在接口层。

**改动文件**

- `context_agent/core/retrieval/task_conditioning.py`
- `context_agent/orchestration/context_aggregator.py`
- `context_agent/core/retrieval/search_coordinator.py`
- `context_agent/api/router.py`
- `tests/unit/test_aggregator.py`
- `tests/unit/core/retrieval/test_search_coordinator.py`
- `tests/unit/test_api_router_outputs.py`

**验证结果**

已通过：

- 聚合链路回归测试
- 搜索协调器回归测试
- API 搜索输出回归测试
- 变更文件的 focused Ruff 检查

执行命令：

```bash
.venv/bin/python3 -m ruff check --select F401,I001,E501,UP041,B905 \
  context_agent/core/retrieval/task_conditioning.py \
  context_agent/orchestration/context_aggregator.py \
  context_agent/api/router.py \
  context_agent/core/retrieval/search_coordinator.py \
  tests/unit/test_aggregator.py \
  tests/unit/core/retrieval/test_search_coordinator.py \
  tests/unit/test_api_router_outputs.py

.venv/bin/python3 -m pytest \
  tests/unit/test_aggregator.py \
  tests/unit/core/retrieval/test_search_coordinator.py \
  tests/unit/test_api_router_outputs.py
```

结果：

- Ruff focused checks passed
- `18 passed`

**局限**

当前还是规则型 task conditioning，不是学习式路由，也没有引入信息瓶颈式 candidate selection。

后续建议继续推进：

1. 将 `task_type`、`agent_role` 进入 `RetrievalPlan.filters`，形成真正的 scope-before-routing。
2. 将“去重”升级为“去冗余 + coverage-aware selection”。
3. 加入 anchor expansion 和 abstract-first retrieval。

---

## 10. 后续更新约定

后续每完成一项实际改造，都应在本文档补充：

| 字段 | 说明 |
| --- | --- |
| 改造项 | 例如：task-conditioned retrieval |
| 对应论文 | 来源论文或组合来源 |
| 代码路径 | 实际改动文件 |
| 状态 | planned / in_progress / done |
| 验证 | 单测、集成测试、性能回归、定性案例 |
| 结果 | 指标提升、风险、是否继续扩展 |

建议后续每一轮只新增一个小批次论文，并至少把其中 1 个建议推进到“代码 + 测试 + 文档回写”。
