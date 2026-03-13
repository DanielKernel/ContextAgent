#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/service-common.sh"

stop_contextagent
if maybe_load_pgvector_runtime; then
  stop_pgvector
  start_pgvector
fi
start_contextagent
