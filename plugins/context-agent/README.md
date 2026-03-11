# @context-agent/context-agent-plugin

OpenClaw **context-engine** plugin that delegates all context management to a running [ContextAgent](https://github.com/yourorg/ContextAgent) HTTP service.

> **Requires:** OpenClaw 3.8+ (PR #22201 — context-engine plugin system) and a running ContextAgent service.

---

## What it does

| OpenClaw lifecycle | Plugin action |
|---|---|
| `bootstrap()` | Warms ContextAgent caches with the existing session history |
| `assemble()` | Retrieves relevant context → injects as `systemPromptAddition` (prepended to system prompt) |
| `afterTurn()` | Records which context items were used (Hotness Score feedback) + stores assistant reply |
| `compact()` | Runs ContextAgent's compression pipeline on overflow |
| `dispose()` | Cleans up pending state |

ContextAgent uses **Mode B** for assembly: original `messages` are returned unchanged; retrieved context is returned as `systemPromptAddition`.

---

## Installation

### Option 1 — Local path (development)

```bash
# From OpenClaw config dir
openclaw plugins install /path/to/ContextAgent/plugins/context-agent
```

### Option 2 — npm (once published)

```bash
openclaw plugins install @context-agent/context-agent-plugin
```

---

## Configuration

```yaml
# ~/.openclaw/config.yaml

plugins:
  slots:
    contextEngine: "context-agent"   # activate this plugin as the context engine
  entries:
    context-agent:
      enabled: true
      config:
        # Required
        baseUrl: "http://localhost:8000"

        # Optional
        apiKey: ""                  # Bearer token (leave empty if no auth configured)
        scopeId: "openclaw"         # Namespace for memories; use per-channel for isolation
        timeoutMs: 5000             # HTTP timeout in ms
        contextTokenBudget: 2048    # Max tokens to inject per turn
        retrievalMode: "fast"       # "fast" (hybrid) or "quality" (LLM-driven agentic)
        topK: 8                     # Context items to retrieve per turn
```

### Per-channel scope isolation

To give each OpenClaw channel its own memory namespace, derive `scopeId` from the channel ID:

```yaml
config:
  scopeId: "channel-123"
```

---

## Starting ContextAgent

```bash
# Install ContextAgent
pip install context-agent

# Start the service
uvicorn context_agent.main:app --host 0.0.0.0 --port 8000

# Or with Docker
docker run -p 8000:8000 context-agent:latest
```

Verify the service is ready:

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0","uptime_s":1.2}
```

---

## How retrieval modes differ

| Mode | Latency | Mechanism | Best for |
|------|---------|-----------|----------|
| `fast` | < 100ms | Hybrid (vector + keyword) | Real-time chat |
| `quality` | < 300ms | LLM-driven agentic retrieval | Complex tasks, multi-step reasoning |

---

## Bridge API endpoints (reference)

The plugin calls these ContextAgent endpoints:

| Endpoint | OpenClaw method |
|---|---|
| `POST /v1/openclaw/bootstrap` | `bootstrap()` |
| `POST /v1/openclaw/ingest` | `ingestBatch()` fallback |
| `POST /v1/openclaw/assemble` | `assemble()` |
| `POST /v1/openclaw/compact` | `compact()` |
| `POST /v1/openclaw/after-turn` | `afterTurn()` |

---

## Development

```bash
# No compilation needed — OpenClaw loads TypeScript directly
cd plugins/context-agent

# Type-check only
npx tsc --noEmit
```

---

## Architecture

```
OpenClaw (TypeScript)
  └── ContextAgentEngine (plugins/context-agent/src/engine.ts)
        └── ContextAgentClient (src/client.ts)  — fetch to HTTP bridge
              └── ContextAgent (Python / FastAPI)
                    ├── /v1/openclaw/bootstrap
                    ├── /v1/openclaw/assemble   ← TieredMemoryRouter + HybridRetrieval
                    ├── /v1/openclaw/compact    ← CompressionStrategyRouter
                    └── /v1/openclaw/after-turn ← Hotness Score feedback
```
