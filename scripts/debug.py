#!/usr/bin/env python3
"""
ContextAgent Debug Script

Usage:
    python3 scripts/debug.py memory search <query> <scope_id>
    python3 scripts/debug.py memory list <scope_id>
    python3 scripts/debug.py embedding generate <text>
    python3 scripts/debug.py llm invoke <prompt>
    python3 scripts/debug.py config show
    python3 scripts/debug.py check-env
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in path
project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))

try:
    from rich import print as rprint
    from rich.table import Table
    import typer
except ImportError:
    print("Please install dependencies: pip install rich typer")
    sys.exit(1)

from context_agent.config.openjiuwen import (
    build_openjiuwen_ltm_adapter_async,
    resolve_openjiuwen_config_path,
    load_openjiuwen_config,
    _expand_env_placeholders,
    _build_embedding_model,
    _build_model_configs,
)
from context_agent.config.settings import get_settings
from context_agent.utils.logging import configure_logging

app = typer.Typer()
memory_app = typer.Typer()
llm_app = typer.Typer()
embedding_app = typer.Typer()
config_app = typer.Typer()

app.add_typer(memory_app, name="memory")
app.add_typer(llm_app, name="llm")
app.add_typer(embedding_app, name="embedding")
app.add_typer(config_app, name="config")


async def _get_ltm(config_path=None):
    configure_logging("WARNING")
    settings = get_settings()
    path = config_path or resolve_openjiuwen_config_path(settings.openjiuwen_config_path)
    if not path:
        rprint("[red]Error: openJiuwen config not found[/red]")
        sys.exit(1)
    
    # Load env vars manually if not already loaded by settings
    from dotenv import load_dotenv
    load_dotenv(override=False)

    rprint(f"[blue]Loading config from: {path}[/blue]")
    try:
        return await build_openjiuwen_ltm_adapter_async(path)
    except Exception as e:
        rprint(f"[red]Failed to build LTM adapter: {e}[/red]")
        if hasattr(e, "details"):
            rprint(f"[yellow]Details: {e.details}[/yellow]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@memory_app.command("search")
def search_memory(query: str, scope_id: str, top_k: int = 5):
    """Search vector memory."""
    async def _run():
        ltm = await _get_ltm()
        try:
            results = await ltm.search(scope_id=scope_id, query=query, top_k=top_k)
            if not results:
                rprint("[yellow]No results found.[/yellow]")
                return

            table = Table(title=f"Search Results for '{query}' (scope: {scope_id})")
            table.add_column("Score", justify="right", style="cyan")
            table.add_column("Content", style="white")
            table.add_column("Metadata", style="dim")
            
            for item in results:
                content_display = item.content[:100] + "..." if len(item.content) > 100 else item.content
                table.add_row(
                    f"{item.score:.4f}",
                    content_display,
                    json.dumps(item.metadata)
                )
            rprint(table)
        finally:
            await ltm.close()

    asyncio.run(_run())


@memory_app.command("list")
def list_memory(scope_id: str, limit: int = 10):
    """List recent memories (via empty search)."""
    search_memory(query="", scope_id=scope_id, top_k=limit)


@embedding_app.command("generate")
def generate_embedding(text: str):
    """Generate embedding for text to verify model config."""
    async def _run():
        configure_logging("WARNING")
        # Ensure env vars are loaded
        from dotenv import load_dotenv
        load_dotenv(override=False)
        
        settings = get_settings()
        config_path = resolve_openjiuwen_config_path(settings.openjiuwen_config_path)
        config = _expand_env_placeholders(load_openjiuwen_config(config_path))
        
        rprint(f"[blue]Building embedding model from {config_path}...[/blue]")
        model = _build_embedding_model(config)
        
        if not model:
            rprint("[red]Failed to build embedding model (returned None)[/red]")
            return

        try:
            rprint(f"[blue]Generating embedding for: '{text}'[/blue]")
            # Check for common embedding interfaces
            if hasattr(model, "embed_query"):
                vector = await model.embed_query(text)
            elif hasattr(model, "get_text_embedding"):
                vector = await model.get_text_embedding(text)
            elif hasattr(model, "embed_documents"): # LangChain style
                vector = (await model.embed_documents([text]))[0]
            else:
                # Fallback: inspect model to see available methods
                rprint(f"[yellow]Unknown model interface: {type(model)}[/yellow]")
                rprint(f"Available methods: {[m for m in dir(model) if not m.startswith('_')]}")
                return

            rprint(f"[green]Success![/green] Vector dimension: {len(vector)}")
            rprint(f"First 5 values: {vector[:5]}")
        except Exception as e:
            rprint(f"[red]Error generating embedding: {e}[/red]")
            # import traceback
            # traceback.print_exc()

    asyncio.run(_run())


@llm_app.command("invoke")
def invoke_llm(prompt: str):
    """Invoke LLM with a prompt."""
    async def _run():
        configure_logging("WARNING")
        from dotenv import load_dotenv
        load_dotenv(override=False)
        
        settings = get_settings()
        config_path = resolve_openjiuwen_config_path(settings.openjiuwen_config_path)
        config = _expand_env_placeholders(load_openjiuwen_config(config_path))
        
        request_config, client_config = _build_model_configs(config)
        
        if not client_config:
            rprint("[red]Failed to build LLM config[/red]")
            return

        try:
            # Use OpenAI client directly to avoid internal complexity if possible,
            # but using openJiuwen's client structure is safer if we want to test that.
            # Here we just use openai package with config values.
            import openai
            
            api_key = client_config.api_key
            base_url = client_config.api_base
            model = getattr(request_config, "model_name", getattr(request_config, "model", ""))
            
            rprint(f"[blue]Invoking LLM '{model}' at '{base_url}' with prompt: '{prompt}'[/blue]")
            
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
            rprint(f"[green]Response:[/green] {content}")
            
        except Exception as e:
            rprint(f"[red]Error invoking LLM: {e}[/red]")
            # import traceback
            # traceback.print_exc()

    asyncio.run(_run())


@config_app.command("show")
def show_config():
    """Show effective configuration."""
    from dotenv import load_dotenv
    load_dotenv(override=False)
    
    settings = get_settings()
    config_path = resolve_openjiuwen_config_path(settings.openjiuwen_config_path)
    config = _expand_env_placeholders(load_openjiuwen_config(config_path))
    rprint(config)


@app.command("check-env")
def check_env():
    """Check environment dependencies (DB, Config, Keys)."""
    async def _run():
        from dotenv import load_dotenv
        load_dotenv(override=False)
        settings = get_settings()
        
        # 1. Check Config
        config_path = resolve_openjiuwen_config_path(settings.openjiuwen_config_path)
        rprint(f"[bold]Config Path:[/bold] {config_path}")
        if not config_path or not config_path.exists():
            rprint("[red]❌ Config file missing[/red]")
        else:
            rprint("[green]✅ Config file found[/green]")
            
        # 2. Check DB Connection
        try:
            config = _expand_env_placeholders(load_openjiuwen_config(config_path))
            vector_store = config.get("vector_store", {})
            backend = vector_store.get("backend")
            dsn = vector_store.get("dsn")
            rprint(f"[bold]Vector Backend:[/bold] {backend}")
            rprint(f"[bold]DSN:[/bold] {dsn}")
            
            if backend == "pgvector" and dsn:
                # Try simple connection
                import asyncpg
                from urllib.parse import urlparse
                
                # Normalize DSN for asyncpg connect: asyncpg doesn't like 'postgresql+asyncpg://'
                # It expects 'postgresql://' or 'postgres://'
                clean_dsn = dsn.replace("postgresql+asyncpg://", "postgres://").replace("postgresql://", "postgres://")
                
                try:
                    conn = await asyncpg.connect(clean_dsn)
                    await conn.close()
                    rprint("[green]✅ Database connection successful[/green]")
                except Exception as e:
                    rprint(f"[red]❌ Database connection failed: {e}[/red]")
                    rprint("[yellow]Tip: Ensure pgvector service is running (scripts/start-all.sh)[/yellow]")
            else:
                 rprint(f"[yellow]Skipping DB check for backend: {backend}[/yellow]")
                 
        except Exception as e:
            rprint(f"[red]❌ Config parsing failed: {e}[/red]")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
