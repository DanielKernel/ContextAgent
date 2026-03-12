# ContextAgent Benchmark 评测建议

> 本文档汇总针对 ContextAgent 的上下文与记忆系统评测建议，重点回答三件事：哪些 benchmark 最值得关注、哪些应该第一期接入、以及它们如何映射到 `docs/requirements-analysis.md` 中的 UC001–UC016。

---

## 1. 先看结论

如果目标是 **尽快为 ContextAgent 建立一套可信、可复现、可演进的外部评测基线**，建议按下面顺序推进：

### 第一期开源 benchmark 核心三件套

- `BEIR`
- `LongMemEval`
- `LongBench v2`

这三者分别对应：

- 检索 / RAG 底座能力
- 长期记忆系统能力
- 长上下文理解与压缩后保真能力

### 第一期开源 benchmark 增强五件套

在核心三件套基础上，再补：

- `LoCoMo`
- `RULER`

补齐后，评测体系会更完整：

- `LoCoMo`：补长对话记忆与事件摘要
- `RULER`：补长上下文长度退化曲线

### 暂不建议第一期纳入主线

- `KILT`
- `InfiniteBench`
- `BABILong`
- `Needle-in-a-Haystack`

原因不是它们不重要，而是对第一期来说：

- `KILT` 更适合第二阶段强化知识密集任务与 evidence / provenance
- `InfiniteBench` 与 `LongBench v2` 在第一期存在一定覆盖重叠
- `BABILong`、`Needle-in-a-Haystack` 更适合作为压力测试，而不是主线能力基线

---

## 2. 为什么推荐这三件套

### 2.1 `BEIR`

`BEIR` 是检索 / RAG 领域最常见的零样本评测基线之一，适合验证：

- embedding 质量
- dense / sparse / hybrid 检索组合
- rerank 是否有效
- 检索质量是否跨数据集稳定

对 ContextAgent 来说，`BEIR` 最直接支撑：

- `UC005` 混合式召回策略
- `UC012` 结构化存储与混合检索
- `UC001` 多源聚合前的检索质量底座

### 2.2 `LongMemEval`

`LongMemEval` 更像是“长期记忆系统 benchmark”，而不只是“长上下文 benchmark”。它重点测：

- 跨 session 记忆
- temporal reasoning
- knowledge update
- abstention

对 ContextAgent 来说，它最直接：

- 检验记忆链路到底是否可用
- 检验更新后的记忆是否一致
- 检验系统是否能在记不住时正确 abstain

它最贴近：

- `UC004`
- `UC010`
- `UC013`

### 2.3 `LongBench v2`

`LongBench v2` 更适合评测“ContextAgent 给模型喂进去的大上下文到底有没有被真正理解和利用”。它覆盖：

- 单文档 / 多文档 QA
- 长对话历史理解
- 代码仓库理解
- 长结构化数据理解

对 ContextAgent 来说，它最适合做：

- 聚合后上下文效果验证
- 压缩前后质量对比
- 接口输出形式对最终任务效果的影响分析

它最贴近：

- `UC001`
- `UC007`
- `UC009`
- `UC015`

---

## 3. benchmark 分层建议

建议把所有评测对象分成四层，而不是混成一个列表。

### 3.1 主 benchmark 套件

优先接入：

- 长上下文：`LongBench v2`
- 检索 / RAG：`BEIR`
- 长期记忆：`LongMemEval`

### 3.2 补充 benchmark

用于补盲区：

- `LoCoMo`
- `RULER`
- `InfiniteBench`

### 3.3 压力测试层

用于极限长度、定位与噪声压力：

- `BABILong`
- `Needle-in-a-Haystack`

这层只能说明“系统在压力下会怎样退化”，不能代表 ContextAgent 的整体能力。

### 3.4 ContextAgent 自建评测层

必须保留一层自建评测，因为公开 benchmark 很难覆盖以下系统特性：

- 多源聚合编排
- 热 / 温 / 冷层路由
- 工具上下文治理
- 子代理上下文隔离与摘要回传
- 监控、告警、版本回滚

---

## 4. benchmark 到 UC001–UC016 的映射

说明：

- `主`：该 benchmark 可以作为该 UC 的主评测来源
- `辅`：可覆盖子能力或间接验证
- `自建`：外部 benchmark 不足，建议 ContextAgent 自建场景评测

| UC | 能力 | LongBench v2 | RULER | BEIR | KILT | LoCoMo | LongMemEval | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `UC001` | 多源上下文聚合 | 主 | 辅 | 辅 | 辅 | 辅 | - | 外部 benchmark 可辅助，但仍需自建“多源聚合”编排评测 |
| `UC002` | 分层分级记忆管理 | - | 辅 | 辅 | - | 辅 | 辅 | **自建为主** |
| `UC003` | 动态上下文更新与管理 | 辅 | 主 | - | - | 辅 | 辅 | 外部 + 自建混合 |
| `UC004` | 即时上下文检索 | 辅 | 主 | 辅 | 辅 | 主 | 主 | 公开 benchmark 对齐度高 |
| `UC005` | 混合式召回策略 | - | - | 主 | 主 | - | - | `BEIR + KILT` 最贴近 |
| `UC006` | 上下文暴露控制 | - | - | - | - | 辅 | - | **自建为主** |
| `UC007` | Agent 上下文接口调用 | 主 | 辅 | - | - | 辅 | 辅 | 仍需自建接口契约评测 |
| `UC008` | 记忆异步处理与更新 | - | - | - | - | 辅 | 主 | 偏系统行为，需自建 + `LongMemEval` |
| `UC009` | 上下文压缩与摘要 | 主 | 主 | - | - | 主 | 辅 | 公开 benchmark 对齐度高 |
| `UC010` | 结构化笔记与工作记忆管理 | - | - | - | - | 主 | 主 | `LoCoMo + LongMemEval` 最贴近 |
| `UC011` | 工具上下文治理 | - | - | - | - | - | - | **基本只能自建** |
| `UC012` | 结构化存储与混合检索 | - | - | 主 | 主 | - | - | `BEIR + KILT` 最贴近 |
| `UC013` | 上下文版本管理与回滚 | - | - | - | - | 辅 | 主 | 需自建版本/回滚场景 |
| `UC014` | 子代理上下文隔离与摘要回传 | - | - | - | - | 辅 | - | **自建为主** |
| `UC015` | 多语言与多模态上下文扩展 | 主 | - | 辅 | - | 辅 | - | 外部 + 自建混合 |
| `UC016` | 召回质量与时延监控 | - | 辅 | 辅 | 辅 | 辅 | 辅 | benchmark 可提供 workload，监控本身需自建 |

### 总结

最适合用外部 benchmark 直接评的 UC：

- `UC004`
- `UC005`
- `UC009`
- `UC010`
- `UC012`

最适合“外部 benchmark + 自建场景”混合评的 UC：

- `UC001`
- `UC003`
- `UC007`
- `UC008`
- `UC013`
- `UC015`
- `UC016`

应直接自建评测、不必等待外部 benchmark 的 UC：

- `UC002`
- `UC006`
- `UC011`
- `UC014`

---

## 5. 每个 benchmark 如何在 ContextAgent 中落地

建议把 benchmark 执行分成三种模式：

- **离线评测**：完整 benchmark，用于版本对比和能力基线
- **回归集**：小样本抽样，用于常规回归
- **压力测试**：观察长度、吞吐、退化曲线

### 5.1 `BEIR`

适合接到：

- `UnifiedSearchCoordinator`
- `TieredMemoryRouter` 的 warm/cold 检索路径
- rerank 逻辑

重点指标：

- `nDCG@k`
- `Recall@k`
- `MRR`
- rerank 前后增益

角色：

- `UC005` / `UC012` 的离线主基线

### 5.2 `LongMemEval`

适合接到：

- working memory 写入路径
- async memory write 路径
- openJiuwen LTM 写入与检索路径

重点指标：

- QA accuracy
- temporal reasoning accuracy
- knowledge update consistency
- abstention accuracy

角色：

- `UC004` / `UC010` / `UC013` 的离线主基线

### 5.3 `LongBench v2`

适合对比三种上下文模式：

- raw context
- compressed context
- retrieve-then-inject context

重点指标：

- task accuracy
- 压缩前后质量差值
- token 使用量
- latency / degraded_sources

角色：

- `UC001` / `UC007` / `UC009` 的长上下文主基线

### 5.4 `LoCoMo`

适合验证：

- 长对话记忆召回
- 事件级摘要
- 会话型 QA

角色：

- `LongMemEval` 的补充件，强化 `UC009` / `UC010`

### 5.5 `RULER`

适合验证：

- accuracy vs context length
- effective context length
- degradation slope

角色：

- `UC003` / `UC004` / `UC009` 的退化曲线观察工具

---

## 6. 建议的实施顺序

如果后续要真正落地，建议按下面顺序推进：

1. 先接 `BEIR`
   - 最快建立检索基线
2. 再接 `LongMemEval`
   - 最快回答“记忆系统是否可用”
3. 再接 `LongBench v2`
   - 最快回答“长上下文注入 / 压缩是否真的有效”
4. 然后补 `LoCoMo`
   - 强化会话记忆与摘要
5. 最后补 `RULER`
   - 观察退化曲线与长度边界

---

## 7. 最终建议

一句话总结：

> **第一期先用 `BEIR + LongMemEval + LongBench v2` 建立检索、记忆、长上下文三条主基线；同时明确 `UC002 / UC006 / UC011 / UC014 / UC016` 主要依赖 ContextAgent 自建评测。**

如果资源允许，再补：

> **`LoCoMo + RULER`，分别强化会话记忆 / 摘要与长上下文退化曲线分析。**
