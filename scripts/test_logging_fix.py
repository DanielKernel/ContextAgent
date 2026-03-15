import logging
import sys
import os

sys.path.append(os.getcwd())
from context_agent.utils.logging import configure_logging
configure_logging()

print("1. Pre-initializing openjiuwen logging...")
try:
    from openjiuwen.core.common.logging import _ensure_initialized
    _ensure_initialized()
    print("Initialized.")
except ImportError:
    print("Failed to import/init openjiuwen logging")

print("2. Cleaning handlers...")
loggers_to_clean = [
    "common", "interface", "performance", "prompt_builder", 
    "agent", "multi_agent", "workflow", "session", "controller", 
    "runner", "sys_operation", "llm", "tool", "prompt", "store", 
    "memory", "retrieval", "context_engine", "graph", "operator", "mcp"
]

cleaned_count = 0
for name in loggers_to_clean:
    l = logging.getLogger(name)
    if l.handlers:
        print(f"Cleaning {name}: {l.handlers}")
        for h in l.handlers[:]:
            l.removeHandler(h)
        cleaned_count += 1

print(f"Cleaned {cleaned_count} loggers.")

print("3. Importing parser (should NOT duplicate logs)...")
try:
    import openjiuwen.core.retrieval.indexing.processor.parser.auto_file_parser
except ImportError:
    print("Failed to import parser")

print("4. Done.")
