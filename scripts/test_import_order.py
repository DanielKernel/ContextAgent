import logging
import sys
import os

sys.path.append(os.getcwd())
from context_agent.utils.logging import configure_logging
configure_logging()

print("1. Importing openjiuwen base...")
try:
    import openjiuwen
except ImportError:
    print("Failed to import openjiuwen")

print("2. Checking/Cleaning handlers...")
common = logging.getLogger("common")
if common.handlers:
    print(f"Found handlers: {common.handlers}. Removing...")
    for h in common.handlers[:]:
        common.removeHandler(h)
else:
    print("No handlers found on common.")

print("3. Importing parser module...")
try:
    import openjiuwen.core.retrieval.indexing.processor.parser.auto_file_parser
except ImportError:
    print("Failed to import parser")

print("4. Done.")
