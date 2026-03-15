# Debugging Guide

ContextAgent provides a unified CLI tool `scripts/debug.py` to help developers and operators troubleshoot configuration, connectivity, and component health issues.

## 🛠️ Debug CLI Overview

The debug script isolates specific subsystems (LLM, Embedding, Vector Store) from the main application to verify they work independently. This is useful when the main service fails to start or behaves unexpectedly.

### Prerequisites

Ensure you have the project virtual environment set up:

```bash
# If not already installed
make install

# Activate venv (optional, or use .venv/bin/python3 directly)
source .venv/bin/activate
```

The script requires `rich` and `typer` (installed by default in dev dependencies).

## 🔍 Common Commands

Run these commands from the project root.

### 1. Check Environment Health

Validates configuration files, environment variables, and database connectivity.

```bash
python3 scripts/debug.py check-env
```

**What it checks:**
- Presence of `openjiuwen.yaml` config.
- Validity of YAML syntax.
- TCP connectivity to the configured Vector Store (e.g., pgvector).

**Example Output:**
```text
Config Path: /Users/daniel/ContextAgent/config/openjiuwen.yaml
✅ Config file found
Vector Backend: pgvector
DSN: postgresql://postgres@127.0.0.1:55432/context_agent
✅ Database connection successful
```

### 2. View Effective Configuration

Dumps the fully resolved configuration (with environment variables expanded).

```bash
python3 scripts/debug.py config show
```

Use this to verify that `${OPENAI_API_KEY}` or other placeholders are being correctly replaced by your `.env` file.

### 3. Test Embedding Generation

Verifies that the embedding model (e.g., OpenAI, Ollama) is reachable and authentication is correct.

```bash
python3 scripts/debug.py embedding generate "Hello world"
```

**Success means:**
- API Key is valid.
- Network connection to the provider is open.
- Model name is correct.

### 4. Test LLM Invocation

Sends a simple prompt to the configured LLM to verify generation capabilities.

```bash
python3 scripts/debug.py llm invoke "Say hello"
```

### 5. Inspect Vector Memory

Query the underlying vector store directly to see what has been persisted.

**List recent memories:**
```bash
# syntax: memory list <scope_id> [limit]
python3 scripts/debug.py memory list openclaw
```

**Semantic Search:**
```bash
# syntax: memory search <query> <scope_id>
python3 scripts/debug.py memory search "project preference" openclaw
```

## ⚠️ Common Issues & Fixes

### "Database connection failed"
```text
❌ Database connection failed: [Errno 61] Connect call failed
Tip: Ensure pgvector service is running (scripts/start-all.sh)
```
**Fix:**
- Check if PostgreSQL is running: `pg_isready` or `brew services list`.
- Verify the port in `.local/config/openjiuwen.yaml` matches the running service (default 55432).
- If using the local helper script: `bash scripts/start-all.sh`.

### "No embedding model available"
**Symptoms:** Service logs show this error, or `debug.py embedding generate` fails.
**Fix:**
- Check API Keys in `.env`.
- Ensure `openjiuwen.yaml` has a valid `embedding_config` section.
- If using `pgvector`, ensure the `asyncpg` driver is installed.

### "Event loop is closed"
**Symptoms:** `RuntimeError: Event loop is closed` during startup or debug.
**Fix:**
- This usually happens when `openJiuwen` components are initialized in one asyncio loop but used in another.
- The `debug.py` script handles this by creating a fresh loop for each command.
- In the main app, ensure `openJiuwen` adapters are built inside the startup lifespan.

## 📝 Advanced Usage

The debug script loads `dotenv` automatically. You can override specific variables inline:

```bash
OPENAI_API_KEY=sk-new-key... python3 scripts/debug.py llm invoke "test"
```
