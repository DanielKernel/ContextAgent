#!/usr/bin/env python3
"""
ContextAgent Debug Tool.

Usage:
  python3 scripts/debug.py config show
  python3 scripts/debug.py memory search "query" --scope-id openclaw
  python3 scripts/debug.py embedding generate "text"
  python3 scripts/debug.py llm invoke "prompt"
  python3 scripts/debug.py check-env
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from pprint import pprint

# Configure logging
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("debug")

def setup_path():
    """Ensure context_agent is in python path."""
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

setup_path()

# Import after path setup
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

from context_agent.config.settings import Settings, get_settings
from context_agent.config.openjiuwen import (
    resolve_openjiuwen_config_path,
    load_openjiuwen_config,
    _expand_env_placeholders,
    _build_embedding_model,
    _build_model_configs,
    build_openjiuwen_ltm_adapter_async
)
from context_agent.models.context import MemoryType


async def cmd_config_show(args):
    """Show effective configuration."""
    print("Loading configuration...")
    try:
        settings = Settings()
        print("\n--- Effective Configuration (JSON) ---")
        print(settings.model_dump_json(indent=2))
        
        print("\n--- Critical Environment Variables ---")
        for key in ["CA_CONTEXT_AGENT_CONFIG_PATH", "CA_OPENJIUWEN_CONFIG_PATH", "CTXLLM_API_KEY", "EMBED_API_KEY"]:
            val = os.environ.get(key)
            masked = f"{val[:4]}...{val[-4:]}" if val and "KEY" in key and len(val) > 8 else val
            print(f"{key}: {masked}")
            
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        import traceback
        traceback.print_exc()


async def cmd_memory_search(args):
    """Search long-term memory."""
    query = args.query
    scope_id = args.scope_id
    limit = args.limit
    
    print(f"Initializing Memory Adapter (scope={scope_id})...")
    settings = get_settings()
    config_path = resolve_openjiuwen_config_path(settings.openjiuwen_config_path)
    
    if not config_path:
        print("Error: OpenJiuwen config path not resolved.")
        return

    try:
        adapter = await build_openjiuwen_ltm_adapter_async(config_path)
        if not adapter:
            print("Error: Could not build OpenJiuwenLTMAdapter")
            return

        print(f"Searching for: '{query}'")
        results = await adapter.search(
            query=query,
            scope_id=scope_id,
            limit=limit,
            memory_types=[MemoryType.SEMANTIC] 
        )
        
        print(f"\nFound {len(results)} results:")
        for idx, res in enumerate(results):
            content_display = res.content[:200] + "..." if len(res.content) > 200 else res.content
            print(f"--- [{idx+1}] Score: {res.score:.4f} ---")
            print(f"Content: {content_display}")
            print(f"Metadata: {json.dumps(res.metadata, ensure_ascii=False)}")
            
    except Exception as e:
        logger.error(f"Search failed: {e}")
        import traceback
        traceback.print_exc()


async def cmd_embedding_generate(args):
    """Generate embedding for text."""
    text = args.text
    print(f"Initializing Embedding Model...")
    
    settings = get_settings()
    config_path = resolve_openjiuwen_config_path(settings.openjiuwen_config_path)
    if not config_path:
        print("Error: OpenJiuwen config path not resolved.")
        return

    try:
        config = _expand_env_placeholders(load_openjiuwen_config(config_path))
        model = _build_embedding_model(config)
        
        if not model:
            print("Error: Could not build embedding model (check config)")
            return
            
        print(f"Generating embedding for: '{text}'")
        
        # Try common interfaces
        vector = None
        if hasattr(model, "embed_query"):
             if asyncio.iscoroutinefunction(model.embed_query):
                 vector = await model.embed_query(text)
             else:
                 vector = model.embed_query(text)
        elif hasattr(model, "get_text_embedding"):
             if asyncio.iscoroutinefunction(model.get_text_embedding):
                 vector = await model.get_text_embedding(text)
             else:
                 vector = model.get_text_embedding(text)
        elif hasattr(model, "embed_documents"):
             if asyncio.iscoroutinefunction(model.embed_documents):
                 res = await model.embed_documents([text])
                 vector = res[0]
             else:
                 vector = model.embed_documents([text])[0]
        else:
             print(f"Unknown model interface: {type(model)}")
             print(dir(model))
             return

        if vector:
            print(f"Success! Vector dimension: {len(vector)}")
            print(f"First 5 values: {vector[:5]}")
        
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        import traceback
        traceback.print_exc()


async def cmd_llm_invoke(args):
    """Invoke LLM."""
    prompt = args.prompt
    print("Initializing LLM...")
    
    settings = get_settings()
    config_path = resolve_openjiuwen_config_path(settings.openjiuwen_config_path)
    if not config_path:
        print("Error: OpenJiuwen config path not resolved.")
        return

    try:
        config = _expand_env_placeholders(load_openjiuwen_config(config_path))
        request_config, client_config = _build_model_configs(config)
        
        if not client_config:
            print("Error: Could not build LLM config")
            return

        import openai
        
        api_key = client_config.api_key
        base_url = client_config.api_base
        model = getattr(request_config, "model_name", getattr(request_config, "model", ""))
        
        print(f"Invoking LLM '{model}' at '{base_url}'...")
        
        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=client_config.timeout,
            max_retries=client_config.max_retries
        )
        
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=request_config.temperature,
            max_tokens=request_config.max_tokens
        )
        
        content = response.choices[0].message.content
        print(f"\nResponse:\n{content}")
            
    except Exception as e:
        logger.error(f"LLM invocation failed: {e}")
        import traceback
        traceback.print_exc()


async def cmd_check_env(args):
    """Check environment dependencies."""
    settings = get_settings()
    
    # 1. Config
    config_path = resolve_openjiuwen_config_path(settings.openjiuwen_config_path)
    print(f"Config Path: {config_path}")
    if not config_path or not config_path.exists():
        print("❌ Config file missing")
    else:
        print("✅ Config file found")

    # 2. DB
    try:
        config = _expand_env_placeholders(load_openjiuwen_config(config_path))
        vector_store = config.get("vector_store", {})
        backend = vector_store.get("backend")
        dsn = vector_store.get("dsn")
        print(f"Vector Backend: {backend}")
        print(f"DSN: {dsn}")
        
        if backend == "pgvector" and dsn:
            # Normalize DSN for asyncpg connect
            # It expects 'postgresql://' or 'postgres://'
            clean_dsn = dsn.replace("postgresql+asyncpg://", "postgres://").replace("postgresql://", "postgres://")
            
            import asyncpg
            try:
                conn = await asyncpg.connect(clean_dsn)
                await conn.close()
                print("✅ Database connection successful")
            except Exception as e:
                print(f"❌ Database connection failed: {e}")
                print("Tip: Ensure pgvector service is running (scripts/start-all.sh)")
        else:
             print(f"Skipping DB check for backend: {backend}")
                 
    except Exception as e:
        print(f"❌ Config parsing/DB check failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="ContextAgent Debug Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # config show
    p_config = subparsers.add_parser("config", help="Configuration commands")
    p_config.add_argument("action", choices=["show"], help="Action to perform")
    
    # memory search
    p_mem = subparsers.add_parser("memory", help="Memory commands")
    p_mem.add_argument("action", choices=["search"], help="Action")
    p_mem.add_argument("query", help="Search query")
    p_mem.add_argument("--scope-id", default="openclaw", help="Scope ID (default: openclaw)")
    p_mem.add_argument("--limit", type=int, default=5, help="Max results")
    
    # embedding generate
    p_embed = subparsers.add_parser("embedding", help="Embedding commands")
    p_embed.add_argument("action", choices=["generate"], help="Action")
    p_embed.add_argument("text", help="Text to embed")
    
    # llm invoke
    p_llm = subparsers.add_parser("llm", help="LLM commands")
    p_llm.add_argument("action", choices=["invoke"], help="Action")
    p_llm.add_argument("prompt", help="Prompt to send")

    # check-env
    p_check = subparsers.add_parser("check-env", help="Check environment")

    args = parser.parse_args()
    
    if args.command == "config":
        asyncio.run(cmd_config_show(args))
    elif args.command == "memory":
        asyncio.run(cmd_memory_search(args))
    elif args.command == "embedding":
        asyncio.run(cmd_embedding_generate(args))
    elif args.command == "llm":
        asyncio.run(cmd_llm_invoke(args))
    elif args.command == "check-env":
        asyncio.run(cmd_check_env(args))

if __name__ == "__main__":
    main()
