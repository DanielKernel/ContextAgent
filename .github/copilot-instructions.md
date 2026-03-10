# Copilot Instructions for ContextAgent

## Project Overview

ContextAgent 是一个基于 **openJiuwen** 框架构建的上下文代理，为多 Agent 系统提供统一的上下文管理中枢。当前处于项目初始化阶段，尚无业务代码。

Reference implementation: https://gitcode.com/openJiuwen/agent-core.git

---

## Architecture

The system is designed around four core operations:

- **Write** – Persist key context outside the main context window (scratchpad, external memory files, structured notes)
- **Select** – Pull relevant context back into the window on demand (just-in-time retrieval, agentic search)
- **Compress** – Summarize, prune, and compact context (rolling summaries, high-fidelity compaction, tool result pruning)
- **Isolate** – Distribute context load across sub-agents with isolated windows and compressed handoffs

### Memory Tiers

| Tier | Content | Priority |
|------|---------|----------|
| Hot  | Current session, recent task state, immediate user preferences | Ultra-low latency |
| Warm | Phase summaries, recent long-term memories | Recall quality |
| Cold | Deep historical knowledge, low-frequency relations, external KBs | Capacity |

### Memory Types (managed separately, not pooled together)

- **Procedural** – Rules, instructions, preferences, constraints ("how to do it")
- **Episodic** – Historical cases, few-shot examples, past task fragments ("what happened")
- **Semantic** – Facts, entities, relationships, domain knowledge ("what is known")

---

## Core Design Principles

1. **Minimum high-signal context** – Inject as little as possible, but enough to complete the current task. Default to lean context.
2. **Relevance first** – Only inject information strongly relevant to the current task.
3. **Context ownership** – The context window must serve the current task goal. Prevent historical or irrelevant recalls from hijacking current reasoning.
4. **Pluggable strategies** – Compression, selection, trimming, and injection strategies must be swappable per scenario—never hardcoded as a single implementation.
5. **Progressive disclosure** – Prefer incremental, just-in-time context loading over bulk upfront loading.
6. **Hybrid retrieval** – Combine embedding search, keyword/grep search, hierarchical signals, graph relations, and reranking. Never rely solely on embeddings.
7. **Tool context governance** – Expose only the tools relevant to the current task. Use retrieval-based tool selection for large toolsets.

---

## Context Failure Modes to Guard Against

| Failure | Description |
|---------|-------------|
| **Context poisoning** | Incorrect information entering context and being amplified across turns |
| **Context distraction** | Too much context diluting model attention |
| **Context confusion** | Irrelevant or redundant information interfering with current task judgment |
| **Context clash** | Conflicting context fragments causing unstable model behavior |

All new context sources, compression strategies, and injection points should be designed with these failure modes in mind.

---

## Performance Targets

- **Critical-path context retrieval: ≤ 300ms**
- Use caching, tiered retrieval, async pre-processing, and incremental updates on hot paths
- External dependencies (vector DB, graph DB) must have fallback/degradation strategies
- Tool outputs must be subject to token budget + pruning to prevent raw results bloating the main context

---

## Key Interface Contracts (Planned)

When implementing modules, align with these planned interface boundaries:

- **Context assembly interface** – standardized input from calling agents, unified output context snapshot
- **Memory adapter layer** – abstraction over openJiuwen built-in memory AND external stores (vector DB, graph DB, document stores)
- **Strategy interface** – pluggable compression, selection, and trimming algorithms configurable per business scenario
- **Sub-agent handoff interface** – compressed task summaries passed between orchestrator and sub-agents; sub-agents return only distilled results
- **External working memory** – structured notes (task plans, key decisions, open questions, risks) persisted outside the main window, re-injected on demand

---

## Scratchpad / Working Memory

Both of these patterns must be supported:

- **File-based**: tool writes structured notes to external files, re-reads them later
- **Runtime state object**: structured fields on in-memory state objects during execution

Distinguish working memory (ephemeral task state) from long-term memory (persisted across sessions).

---

## Retrieval Stack

When implementing retrieval, layer these techniques rather than picking one:

1. Embedding/vector similarity search
2. Keyword / grep-style search
3. Filesystem hierarchy and structural signals
4. Graph relationship traversal
5. Reranking pass over candidates

---

## openJiuwen Framework

This project extends the openJiuwen agent framework. Before implementing new memory or retrieval integrations, check whether openJiuwen already provides the capability natively. External integrations should go through the unified memory adapter layer, not be coupled directly to business logic.
