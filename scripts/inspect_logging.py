import logging
import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

# 1. Configure logging
try:
    from context_agent.utils.logging import configure_logging
    configure_logging()
except ImportError:
    print("Could not import configure_logging")

# 2. Trigger openjiuwen (simulating import that adds handlers)
try:
    import openjiuwen
    import openjiuwen.core.retrieval.indexing.processor.parser.auto_file_parser
    print("Imported openjiuwen")
except ImportError:
    print("Could not import openjiuwen")

print("-" * 20)
common = logging.getLogger("common")
print(f"Before fix: common logger handlers: {common.handlers}")

# 3. Simulate Fix
print("Applying fix...")
if common.handlers:
    for handler in common.handlers[:]:
        common.removeHandler(handler)

print(f"After fix: common logger handlers: {common.handlers}")

# 4. Log something
print("-" * 20)
print("Logging test message:")
common.info("Test log message from common logger")
