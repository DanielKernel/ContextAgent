# ContextAgent Memory Plugin for OpenClaw

A lightweight `memory`-kind OpenClaw plugin that adds tool-based memory recall and storage via ContextAgent.

## When to use this vs the context-engine plugin

| | `openclaw-plugin` (context-engine) | `openclaw-memory-plugin` (memory) |
|---|---|---|
| **Controls compaction** | ✅ Yes (`ownsCompaction: true`) | ❌ No |
| **Controls assemble** | ✅ Yes (replaces messages or injects) | ❌ No |
| **Provides tools** | ❌ No | ✅ 3 tools |
| **Auto-recall hook** | ❌ No | ✅ before_agent_start |
| **Auto-capture hook** | ❌ No | ✅ agent_end (opt-in) |
| **Works alongside any context engine** | — | ✅ Yes |
| **Best for** | Full lifecycle ownership | Lightweight memory augmentation |

## Installation

```bash
# From local checkout:
openclaw plugins install /path/to/plugins/openclaw-memory-plugin

# After publishing to npm:
openclaw plugins install @context-agent/openclaw-memory-plugin
```

## Configuration

```yaml
# ~/.openclaw/config.yaml
plugins:
  entries:
    context-agent-memory:
      enabled: true
      config:
        baseUrl: "http://localhost:8000"
        apiKey: "your-token"          # optional
        scopeId: "openclaw"
        timeoutMs: 5000
        autoRecall: true              # auto-inject recalled context before each turn
        autoRecallTopK: 5             # memories to recall per turn
        autoRecallMinScore: 0.01      # minimum relevance score (0–1)
        autoCapture: false            # auto-store assistant replies (opt-in)
```

## Tools provided

### `memory_recall`
Retrieve relevant memories for a natural language query.

```
memory_recall({ query: "What is the user's preferred coding style?" })
```

### `memory_store`
Store a new memory item.

```
memory_store({ content: "User prefers snake_case variable names", memory_type: "variable" })
```

### `memory_forget`
Delete a stored memory by ID.

```
memory_forget({ item_id: "abc123" })
```

## Hooks

- **`before_agent_start`**: If `autoRecall: true`, searches memories using the latest user message as the query and prepends results to the system context.
- **`agent_end`**: If `autoCapture: true`, stores the assistant's reply as a `variable` memory.

## Combining with the context-engine plugin

You can use both plugins simultaneously:

```yaml
plugins:
  slots:
    contextEngine: "context-agent"    # full lifecycle control
  entries:
    context-agent:
      enabled: true
      config:
        baseUrl: "http://localhost:8000"
        scopeId: "openclaw"
    context-agent-memory:
      enabled: true
      config:
        baseUrl: "http://localhost:8000"
        scopeId: "openclaw"
        autoRecall: false             # avoid double recall when using context-engine
        autoCapture: false
```

In this configuration, the context-engine plugin handles compaction and assemble, while the memory plugin exposes tools the LLM can call explicitly.
