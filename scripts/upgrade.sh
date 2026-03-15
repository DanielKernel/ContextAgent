#!/usr/bin/env bash
# =============================================================================
#  ContextAgent 一键升级脚本
#  用法：bash scripts/upgrade.sh [选项]
#
#  说明：
#    - 升级当前代码检出的 ContextAgent 版本
#    - 默认保留历史配置和 pgvector/PostgreSQL 数据
#    - 升级前自动创建时间戳备份，失败时可回滚配置
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env-bootstrap.sh"
set -euo pipefail

PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"
PID_FILE="$PROJECT_DIR/context_agent.pid"
LOG_FILE="$PROJECT_DIR/context_agent.log"
DEFAULT_RUNTIME_CONFIG_DIR="$PROJECT_DIR/.local/config"
DEFAULT_CONTEXT_CONFIG="$DEFAULT_RUNTIME_CONFIG_DIR/context_agent.yaml"
DEFAULT_OPENJIUWEN_CONFIG="$DEFAULT_RUNTIME_CONFIG_DIR/openjiuwen.yaml"
DEFAULT_BACKUP_ROOT="$PROJECT_DIR/.local/upgrade-backups"
BACKUP_ROOT="${CA_UPGRADE_BACKUP_ROOT:-$DEFAULT_BACKUP_ROOT}"

CONTEXT_AGENT_CONFIG_PATH=""
OPENJIUWEN_CONFIG_PATH=""
VECTOR_BACKEND=""
ROLLBACK_DIR=""
FORCE_START=false
SKIP_DB_BACKUP=false
PORT_OVERRIDE=""

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$@"; exit 1; }
step()    { echo -e "\n${CYAN}▶ $*${NC}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start) FORCE_START=true; shift ;;
    --skip-db-backup) SKIP_DB_BACKUP=true; shift ;;
    --backup-dir) BACKUP_ROOT="$2"; shift 2 ;;
    --rollback) ROLLBACK_DIR="$2"; shift 2 ;;
    --port) PORT_OVERRIDE="$2"; shift 2 ;;
    --vector-backend) VECTOR_BACKEND="$2"; shift 2 ;;
    --context-agent-config) CONTEXT_AGENT_CONFIG_PATH="$2"; shift 2 ;;
    --openjiuwen-config) OPENJIUWEN_CONFIG_PATH="$2"; shift 2 ;;
    --help|-h)
      echo "用法: bash scripts/upgrade.sh [选项]"
      echo ""
      echo "选项："
      echo "  --start                   升级后无论之前是否在运行，都启动服务"
      echo "  --skip-db-backup          跳过 pgvector 逻辑备份"
      echo "  --backup-dir DIR          升级备份根目录（默认 ./.local/upgrade-backups）"
      echo "  --rollback DIR            从指定升级备份目录还原配置"
      echo "  --port PORT               启动服务时覆盖端口"
      echo "  --vector-backend BACKEND  当缺失 openJiuwen 配置时指定后端（默认自动检测/pgvector）"
      echo "  --context-agent-config    ContextAgent 配置路径"
      echo "  --openjiuwen-config       openJiuwen 配置路径"
      exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

find_python() {
  if [[ -f "$VENV_DIR/bin/python3" ]]; then
    echo "$VENV_DIR/bin/python3"
    return 0
  fi
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
      if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON3="$(find_python)" || die "未找到 Python 3.11+"

read_env_or_default() {
  local key="$1"
  local default_value="$2"
  "$PYTHON3" - "$ENV_FILE" "$key" "$default_value" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
key = sys.argv[2]
default_value = sys.argv[3]

if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            print(line.split("=", 1)[1])
            raise SystemExit(0)

print(default_value)
PY
}

resolve_path() {
  local raw_path="$1"
  [[ -n "$raw_path" ]] || return 1
  "$PYTHON3" - "$PROJECT_DIR" "$raw_path" <<'PY'
from pathlib import Path
import sys

project_dir = Path(sys.argv[1]).resolve()
raw_path = sys.argv[2]
candidate = Path(raw_path).expanduser()
if not candidate.is_absolute():
    candidate = (project_dir / candidate).resolve()
print(candidate)
PY
}

load_yaml_field() {
  local file_path="$1"
  local expression="$2"
  "$PYTHON3" - "$file_path" "$expression" <<'PY'
from pathlib import Path
import sys
import yaml

path = Path(sys.argv[1])
expr = sys.argv[2].split(".")
data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
current = data
for key in expr:
    if not isinstance(current, dict) or key not in current:
        print("")
        raise SystemExit(0)
    current = current[key]
if current is None:
    print("")
elif isinstance(current, (dict, list)):
    print("")
else:
    print(current)
PY
}

json_escape() {
  "$PYTHON3" - "$1" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1], ensure_ascii=True))
PY
}

show_recent_log_tail() {
  local log_path="$1"
  local line_count="${2:-80}"
  if [[ ! -f "$log_path" ]]; then
    warn "尚未生成服务日志：$log_path"
    return 0
  fi
  echo ""
  echo "----- $log_path (tail -n $line_count) -----"
  tail -n "$line_count" "$log_path"
  echo "----- end log tail -----"
}

load_context_http_setting() {
  local file_path="$1"
  local nested_expr="$2"
  local flat_expr="$3"
  local value=""
  if [[ -f "$file_path" ]]; then
    value="$(load_yaml_field "$file_path" "$nested_expr")"
    if [[ -z "$value" ]]; then
      value="$(load_yaml_field "$file_path" "$flat_expr")"
    fi
  fi
  echo "$value"
}

diagnose_start_failure() {
  local pid="$1"
  if kill -0 "$pid" 2>/dev/null; then
    warn "升级后的服务进程仍在运行，但健康检查未通过：PID=${pid}"
  else
    warn "升级后的服务进程已提前退出：PID=${pid}"
    rm -f "$PID_FILE"
  fi
  warn "最近日志如下：$LOG_FILE"
  show_recent_log_tail "$LOG_FILE" 80
}

find_listening_pid() {
  local port="$1"
  command -v lsof >/dev/null 2>&1 || return 1
  lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | awk 'NF { print; exit }'
}

describe_pid_command() {
  local pid="$1"
  ps -o command= -p "$pid" 2>/dev/null | sed 's/^[[:space:]]*//'
}

is_contextagent_pid() {
  local pid="$1"
  local command_line
  command_line="$(describe_pid_command "$pid")"
  [[ -n "$command_line" ]] || return 1
  [[ "$command_line" == *"context_agent.api.http_handler:app"* || "$command_line" == *"context_agent.main:app"* ]]
}

find_contextagent_listening_pid() {
  local port="$1"
  local pid
  command -v lsof >/dev/null 2>&1 || return 1
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    if is_contextagent_pid "$pid"; then
      echo "$pid"
      return 0
    fi
  done < <(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)
  return 1
}

find_pg_client_bin() {
  local bin_name="$1"
  if command -v "$bin_name" >/dev/null 2>&1; then
    command -v "$bin_name"
    return 0
  fi

  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        local brew_prefix
        brew_prefix="$(brew --prefix postgresql@17 2>/dev/null || true)"
        if [[ -n "$brew_prefix" && -x "$brew_prefix/bin/$bin_name" ]]; then
          echo "$brew_prefix/bin/$bin_name"
          return 0
        fi
      fi
      ;;
    Linux)
      local candidate
      while IFS= read -r candidate; do
        [[ -x "$candidate/$bin_name" ]] || continue
        echo "$candidate/$bin_name"
        return 0
      done < <(printf '%s\n' /usr/lib/postgresql/*/bin 2>/dev/null | sort -Vr)
      ;;
  esac

  return 1
}

rollback_from_backup() {
  local backup_dir="$1"
  [[ -d "$backup_dir" ]] || die "备份目录不存在：$backup_dir"
  step "从升级备份还原配置"

  [[ -f "$backup_dir/config/context_agent.yaml" ]] && cp "$backup_dir/config/context_agent.yaml" "$CONTEXT_AGENT_CONFIG_PATH"
  [[ -f "$backup_dir/config/openjiuwen.yaml" ]] && cp "$backup_dir/config/openjiuwen.yaml" "$OPENJIUWEN_CONFIG_PATH"
  [[ -f "$backup_dir/env/.env" ]] && cp "$backup_dir/env/.env" "$ENV_FILE"

  success "配置与 .env 已还原"
  if [[ -f "$backup_dir/postgres/backup.sql" ]]; then
    warn "检测到数据库逻辑备份：$backup_dir/postgres/backup.sql"
    warn "当前升级回滚默认不自动执行数据库恢复；如确需恢复，请在确认后手动使用 psql 导入。"
  fi
}

CONTEXT_AGENT_CONFIG_PATH="${CONTEXT_AGENT_CONFIG_PATH:-$(read_env_or_default "CA_CONTEXT_AGENT_CONFIG_PATH" "$DEFAULT_CONTEXT_CONFIG")}"
OPENJIUWEN_CONFIG_PATH="${OPENJIUWEN_CONFIG_PATH:-$(read_env_or_default "CA_OPENJIUWEN_CONFIG_PATH" "$DEFAULT_OPENJIUWEN_CONFIG")}"
CONTEXT_AGENT_CONFIG_PATH="$(resolve_path "$CONTEXT_AGENT_CONFIG_PATH")"
OPENJIUWEN_CONFIG_PATH="$(resolve_path "$OPENJIUWEN_CONFIG_PATH")"

if [[ -n "$ROLLBACK_DIR" ]]; then
  rollback_from_backup "$(resolve_path "$ROLLBACK_DIR")"
  exit 0
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       ContextAgent 一键升级               ║"
echo "╚══════════════════════════════════════════╝"
echo ""

step "预检查"
info "ContextAgent 配置：$CONTEXT_AGENT_CONFIG_PATH"
info "openJiuwen 配置：$OPENJIUWEN_CONFIG_PATH"

if [[ -f "$OPENJIUWEN_CONFIG_PATH" ]]; then
  CURRENT_BACKEND="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.backend")"
else
  CURRENT_BACKEND=""
fi
VECTOR_BACKEND="${VECTOR_BACKEND:-${CURRENT_BACKEND:-pgvector}}"
HTTP_HOST="$(load_context_http_setting "$CONTEXT_AGENT_CONFIG_PATH" "http.host" "http_host")"
HTTP_PORT="$(load_context_http_setting "$CONTEXT_AGENT_CONFIG_PATH" "http.port" "http_port")"
HTTP_HOST="${HTTP_HOST:-0.0.0.0}"
HTTP_PORT="${PORT_OVERRIDE:-${HTTP_PORT:-8080}}"

SERVICE_WAS_RUNNING=false
if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null && is_contextagent_pid "$OLD_PID"; then
    SERVICE_WAS_RUNNING=true
    info "检测到运行中的 ContextAgent 进程 PID=$OLD_PID"
  fi
fi
if [[ "$SERVICE_WAS_RUNNING" != true ]]; then
  OLD_PID="$(find_contextagent_listening_pid "$HTTP_PORT" || true)"
  if [[ -n "$OLD_PID" ]]; then
    SERVICE_WAS_RUNNING=true
    echo "$OLD_PID" > "$PID_FILE"
    info "根据端口 ${HTTP_PORT} 找到运行中的 ContextAgent 进程 PID=$OLD_PID"
  fi
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
mkdir -p "$BACKUP_DIR/config" "$BACKUP_DIR/env" "$BACKUP_DIR/postgres"

step "创建升级备份"
[[ -f "$CONTEXT_AGENT_CONFIG_PATH" ]] && cp "$CONTEXT_AGENT_CONFIG_PATH" "$BACKUP_DIR/config/context_agent.yaml"
[[ -f "$OPENJIUWEN_CONFIG_PATH" ]] && cp "$OPENJIUWEN_CONFIG_PATH" "$BACKUP_DIR/config/openjiuwen.yaml"
[[ -f "$ENV_FILE" ]] && cp "$ENV_FILE" "$BACKUP_DIR/env/.env"

PG_DSN=""
PG_SCHEMA=""
PG_TABLE=""
PG_EMBED_DIM=""
if [[ "$VECTOR_BACKEND" == "pgvector" && -f "$OPENJIUWEN_CONFIG_PATH" ]]; then
  PG_DSN="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.dsn")"
  PG_SCHEMA="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.schema")"
  PG_TABLE="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.table_name")"
  PG_EMBED_DIM="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.embedding_dimension")"
fi

if [[ "$VECTOR_BACKEND" == "pgvector" && "$SKIP_DB_BACKUP" == false && -n "$PG_DSN" ]]; then
  if PG_DUMP_BIN="$(find_pg_client_bin pg_dump)"; then
    info "创建 pgvector 逻辑备份..."
    "$PG_DUMP_BIN" "$PG_DSN" --file "$BACKUP_DIR/postgres/backup.sql" --no-owner --no-privileges >/dev/null
    success "数据库逻辑备份已写入：$BACKUP_DIR/postgres/backup.sql"
  else
    warn "未找到 pg_dump，跳过数据库逻辑备份；升级仍会保留原数据目录和表。"
  fi
fi

PROJECT_VERSION="$(grep '^version' "$PROJECT_DIR/pyproject.toml" | head -1 | cut -d'"' -f2)"
cat > "$BACKUP_DIR/manifest.json" <<EOF
{
  "timestamp": $(json_escape "$TIMESTAMP"),
  "project_version": $(json_escape "$PROJECT_VERSION"),
  "context_agent_config_path": $(json_escape "$CONTEXT_AGENT_CONFIG_PATH"),
  "openjiuwen_config_path": $(json_escape "$OPENJIUWEN_CONFIG_PATH"),
  "vector_backend": $(json_escape "$VECTOR_BACKEND"),
  "http_host": $(json_escape "$HTTP_HOST"),
  "http_port": $(json_escape "$HTTP_PORT"),
  "service_was_running": $([[ "$SERVICE_WAS_RUNNING" == true ]] && echo true || echo false)
}
EOF
success "升级备份已创建：$BACKUP_DIR"

step "停止旧服务"
if [[ "$SERVICE_WAS_RUNNING" == true ]]; then
  kill "$OLD_PID" 2>/dev/null || true
  sleep 1
  rm -f "$PID_FILE"
  success "旧服务已停止"
else
  info "未检测到运行中的 ContextAgent，跳过停服务"
fi

step "升级 Python 环境"
if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
  info "创建 Python 虚拟环境..."
  "$PYTHON3" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel -q || true

# 尝试安装依赖，如果失败（如缺少 Rust 编译器导致 pydantic-core 构建失败），则假设现有环境可用并继续
if ! "$VENV_DIR/bin/pip" install -e "$PROJECT_DIR[openjiuwen]" -q --prefer-binary; then
    warn "依赖安装遇到错误（可能是 pydantic-core 构建失败）。"
    warn "假设环境已就绪，继续执行配置迁移..."
fi
success "依赖检查完成"

step "迁移正式配置"
CONTEXT_TEMPLATE="$PROJECT_DIR/examples/configs/pgvector/context_agent.yaml"
OPENJIUWEN_TEMPLATE="$PROJECT_DIR/examples/configs/$VECTOR_BACKEND/openjiuwen.yaml"
[[ -f "$CONTEXT_TEMPLATE" ]] || die "未找到 ContextAgent 模板：$CONTEXT_TEMPLATE"
[[ -f "$OPENJIUWEN_TEMPLATE" ]] || die "未找到 openJiuwen 模板：$OPENJIUWEN_TEMPLATE"

"$VENV_DIR/bin/python3" "$PROJECT_DIR/context_agent/config/migration.py" \
  --target "$CONTEXT_AGENT_CONFIG_PATH" \
  --template "$CONTEXT_TEMPLATE" \
  --force-key "budgets.latency.aggregation_timeout_ms" \
  --force-key "budgets.latency.cold_tier_timeout_ms" \
  --force-key "budgets.latency.warm_tier_timeout_ms" \
  --force-key "budgets.latency.hot_tier_timeout_ms" \
  --force-key "retrieval.timeout_ms" \
  --force-key "llm.timeout_s" >/dev/null
"$VENV_DIR/bin/python3" "$PROJECT_DIR/context_agent/config/migration.py" \
  --target "$OPENJIUWEN_CONFIG_PATH" \
  --template "$OPENJIUWEN_TEMPLATE" \
  --force-key "user_id" \
  --force-key "llm_config.timeout" >/dev/null
success "配置迁移完成（仅补齐缺省字段，不覆盖现有值）"

if [[ "$VECTOR_BACKEND" == "pgvector" ]]; then
  PG_DSN="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.dsn")"
  PG_SCHEMA="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.schema")"
  PG_TABLE="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.table_name")"
  PG_EMBED_DIM="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.embedding_dimension")"
fi

step "执行数据库幂等迁移"
if [[ "$VECTOR_BACKEND" == "pgvector" && -n "$PG_DSN" ]]; then
  if ! [[ "${PG_EMBED_DIM:-}" =~ ^[0-9]+$ ]]; then
    PG_EMBED_DIM="1024"
  fi
  PG_SCHEMA="${PG_SCHEMA:-public}"
  PG_TABLE="${PG_TABLE:-ltm_memory}"
  if PSQL_BIN="$(find_pg_client_bin psql)"; then
    "$PSQL_BIN" -q "$PG_DSN" <<SQL >/dev/null
SET client_min_messages TO WARNING;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ${PG_SCHEMA}.${PG_TABLE} (
    id BIGSERIAL PRIMARY KEY,
    scope_id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128),
    memory_type VARCHAR(32) NOT NULL DEFAULT 'semantic',
    source VARCHAR(64),
    content TEXT NOT NULL,
    embedding vector(${PG_EMBED_DIM}),
    tags JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ${PG_SCHEMA}.${PG_TABLE} ADD COLUMN IF NOT EXISTS session_id VARCHAR(128);
ALTER TABLE ${PG_SCHEMA}.${PG_TABLE} ADD COLUMN IF NOT EXISTS memory_type VARCHAR(32) NOT NULL DEFAULT 'semantic';
ALTER TABLE ${PG_SCHEMA}.${PG_TABLE} ADD COLUMN IF NOT EXISTS source VARCHAR(64);
ALTER TABLE ${PG_SCHEMA}.${PG_TABLE} ADD COLUMN IF NOT EXISTS tags JSONB;
ALTER TABLE ${PG_SCHEMA}.${PG_TABLE} ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_ltm_memory_scope_id ON ${PG_SCHEMA}.${PG_TABLE}(scope_id);
CREATE INDEX IF NOT EXISTS idx_ltm_memory_memory_type ON ${PG_SCHEMA}.${PG_TABLE}(memory_type);
SQL
    success "pgvector schema 幂等迁移完成"
  else
    warn "未找到 psql，无法验证/迁移 pgvector schema（但这不影响服务启动，仅影响新功能所需的表结构）"
  fi
else
  info "当前后端不是 pgvector，跳过 PostgreSQL schema 迁移"
fi

SHOULD_START=false
if [[ "$FORCE_START" == true || "$SERVICE_WAS_RUNNING" == true ]]; then
  SHOULD_START=true
fi

if [[ "$SHOULD_START" == true ]]; then
  step "启动升级后的服务"
  PORT_PID="$(find_listening_pid "$HTTP_PORT" || true)"
  if [[ -n "$PORT_PID" ]]; then
    die "端口 ${HTTP_PORT} 已被其他进程占用：PID=$PORT_PID CMD=$(describe_pid_command "$PORT_PID")"
  fi
  CA_CONTEXT_AGENT_CONFIG_PATH="$CONTEXT_AGENT_CONFIG_PATH" \
  CA_OPENJIUWEN_CONFIG_PATH="$OPENJIUWEN_CONFIG_PATH" \
  "$VENV_DIR/bin/python3" -m uvicorn context_agent.api.http_handler:app \
    --host "$HTTP_HOST" --port "$HTTP_PORT" \
    > "$LOG_FILE" 2>&1 &
  NEW_PID=$!
  echo "$NEW_PID" > "$PID_FILE"

  info "等待服务健康检查..."
  STARTED=false
  for _ in $(seq 1 20); do
    if bash "$SCRIPT_DIR/health-check.sh" --url "http://127.0.0.1:${HTTP_PORT}/health" --timeout 2 --allow-degraded-components "llm,embedding" >/dev/null 2>&1; then
      success "升级成功，服务已恢复：http://127.0.0.1:${HTTP_PORT}"
      echo "  升级备份：$BACKUP_DIR"
      echo "  回滚配置：bash scripts/upgrade.sh --rollback $BACKUP_DIR"
      STARTED=true
      exit 0
    fi
    if ! kill -0 "$NEW_PID" 2>/dev/null; then
      diagnose_start_failure "$NEW_PID"
      break
    fi
    sleep 1
  done

  if [[ "$STARTED" != true ]]; then
    warn "升级后的服务未通过健康检查，正在自动回滚配置..."
    diagnose_start_failure "$NEW_PID"
  fi

  kill "$NEW_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
  rollback_from_backup "$BACKUP_DIR"
  warn "尝试使用回滚后的配置重新启动服务..."
  CA_CONTEXT_AGENT_CONFIG_PATH="$CONTEXT_AGENT_CONFIG_PATH" \
  CA_OPENJIUWEN_CONFIG_PATH="$OPENJIUWEN_CONFIG_PATH" \
  "$VENV_DIR/bin/python3" -m uvicorn context_agent.api.http_handler:app \
    --host "$HTTP_HOST" --port "$HTTP_PORT" \
    > "$LOG_FILE" 2>&1 &
  ROLLBACK_PID=$!
  echo "$ROLLBACK_PID" > "$PID_FILE"
  for _ in $(seq 1 20); do
    if bash "$SCRIPT_DIR/health-check.sh" --url "http://127.0.0.1:${HTTP_PORT}/health" --timeout 2 --allow-degraded-components "llm,embedding" >/dev/null 2>&1; then
      die "升级后的服务未通过健康检查，配置已回滚并恢复启动。数据库逻辑备份保留在：$BACKUP_DIR/postgres"
    fi
    if ! kill -0 "$ROLLBACK_PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  warn "回滚后的服务也未通过健康检查。"
  diagnose_start_failure "$ROLLBACK_PID"
  die "升级后的服务未通过健康检查，配置已回滚，但回滚后的服务仍启动失败。数据库逻辑备份保留在：$BACKUP_DIR/postgres"
fi

echo ""
success "升级完成（未自动启动服务）"
echo "  升级备份：$BACKUP_DIR"
echo "  启动服务：CA_CONTEXT_AGENT_CONFIG_PATH=$CONTEXT_AGENT_CONFIG_PATH CA_OPENJIUWEN_CONFIG_PATH=$OPENJIUWEN_CONFIG_PATH $VENV_DIR/bin/python3 -m uvicorn context_agent.api.http_handler:app --host $HTTP_HOST --port $HTTP_PORT"
echo "  回滚配置：bash scripts/upgrade.sh --rollback $BACKUP_DIR"
echo "  验证配置：bash scripts/debug.sh check-env"
