import logging
import sys
import os

sys.path.append(os.getcwd())
from context_agent.utils.logging import configure_logging
configure_logging()

print("1. Importing openjiuwen.core.common.logging...")
try:
    # Try importing the logging module explicitly
    # Assuming it's openjiuwen.core.common.logging based on directory listing
    import openjiuwen.core.common.logging
    print("Imported openjiuwen.core.common.logging")
except ImportError:
    print("Failed to import openjiuwen.core.common.logging, trying openjiuwen.core.common")
    try:
        import openjiuwen.core.common
    except ImportError:
        print("Failed to import openjiuwen.core.common")

print("2. Checking handlers...")
common = logging.getLogger("common")
if common.handlers:
    print(f"Found handlers: {common.handlers}. Removing...")
    for h in common.handlers[:]:
        common.removeHandler(h)
else:
    print("No handlers found.")

print("3. Importing parser (which logs)...")
try:
    import openjiuwen.core.retrieval.indexing.processor.parser.auto_file_parser
except ImportError:
    print("Failed to import parser")

print("4. Done.")
