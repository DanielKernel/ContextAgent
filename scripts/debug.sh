#!/usr/bin/env bash
# Wrapper for debug.py that handles venv and python path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"

# Use venv python if available, else system python3
if [[ -f "$VENV_DIR/bin/python3" ]]; then
    PYTHON="$VENV_DIR/bin/python3"
else
    PYTHON="python3"
fi

export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"

# Check for required dependencies
REQUIRED_PKGS="asyncpg openai pyyaml structlog pydantic pydantic-settings"
if ! "$PYTHON" -c "import asyncpg, openai, yaml, structlog, pydantic, pydantic_settings" >/dev/null 2>&1; then
    echo "Installing required dependencies for debug script..."
    "$PYTHON" -m pip install $REQUIRED_PKGS
fi

exec "$PYTHON" "$SCRIPT_DIR/debug.py" "$@"
