import logging
import sys
import os
import inspect

sys.path.append(os.getcwd())
from context_agent.utils.logging import configure_logging
configure_logging()

print("1. Simulating http_handler cleanup logic...")
try:
    import openjiuwen.core.common.logging as oj_logging
    
    # Force logging system initialization
    if hasattr(oj_logging, "_ensure_initialized"):
        oj_logging._ensure_initialized()

    # Dynamically clean all exposed LazyLoggers
    count = 0
    print(f"Inspecting members of {oj_logging}")
    for name, obj in inspect.getmembers(oj_logging):
        if isinstance(obj, oj_logging.LazyLogger):
            print(f"Found LazyLogger: {name}")
            try:
                # Accessing handlers triggers initialization of the underlying logger
                handlers = getattr(obj, "handlers", [])
                print(f"  Handlers for {name}: {handlers}")
                if handlers:
                    print(f"  Cleaning handlers for {name}: {handlers}")
                    for handler in list(handlers):
                        obj.removeHandler(handler)
                    count += 1
            except Exception as e:
                print(f"Error cleaning {name}: {e}")
                pass
    
    if count > 0:
        print(f"Cleaned openJiuwen loggers: {count}")
        
except ImportError:
    print("openJiuwen not installed")

print("2. Importing parser (should be clean)...")
try:
    import openjiuwen.core.retrieval.indexing.processor.parser.auto_file_parser
except ImportError:
    print("Failed to import parser")

print("3. Done.")
