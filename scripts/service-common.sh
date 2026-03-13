#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"
PID_FILE="$PROJECT_DIR/context_agent.pid"
LOG_FILE="$PROJECT_DIR/context_agent.log"
DEFAULT_RUNTIME_CONFIG_DIR="$PROJECT_DIR/.local/config"
DEFAULT_CONTEXT_CONFIG="$DEFAULT_RUNTIME_CONFIG_DIR/context_agent.yaml"
DEFAULT_OPENJIUWEN_CONFIG="$DEFAULT_RUNTIME_CONFIG_DIR/openjiuwen.yaml"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$@"; exit 1; }

find_python() {
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

PYTHON3="${PYTHON3:-$(find_python)}" || die "未找到 Python 3.11+"

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
if not path.exists():
    print("")
    raise SystemExit(0)

data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
current = data
for key in expr:
    if not isinstance(current, dict) or key not in current:
        print("")
        raise SystemExit(0)
    current = current[key]
if current is None or isinstance(current, (dict, list)):
    print("")
else:
    print(current)
PY
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

resolve_runtime_paths() {
  CONTEXT_AGENT_CONFIG_PATH="${CA_CONTEXT_AGENT_CONFIG_PATH:-$(read_env_or_default "CA_CONTEXT_AGENT_CONFIG_PATH" "$DEFAULT_CONTEXT_CONFIG")}"
  OPENJIUWEN_CONFIG_PATH="${CA_OPENJIUWEN_CONFIG_PATH:-$(read_env_or_default "CA_OPENJIUWEN_CONFIG_PATH" "$DEFAULT_OPENJIUWEN_CONFIG")}"
  CONTEXT_AGENT_CONFIG_PATH="$(resolve_path "$CONTEXT_AGENT_CONFIG_PATH")"
  OPENJIUWEN_CONFIG_PATH="$(resolve_path "$OPENJIUWEN_CONFIG_PATH")"
}

load_contextagent_runtime() {
  resolve_runtime_paths
  HTTP_HOST="${CA_HTTP_HOST_OVERRIDE:-$(load_context_http_setting "$CONTEXT_AGENT_CONFIG_PATH" "http.host" "http_host")}"
  HTTP_PORT="${CA_HTTP_PORT_OVERRIDE:-$(load_context_http_setting "$CONTEXT_AGENT_CONFIG_PATH" "http.port" "http_port")}"
  HTTP_HOST="${HTTP_HOST:-0.0.0.0}"
  HTTP_PORT="${HTTP_PORT:-8000}"
}

contextagent_health_url() {
  local host="$HTTP_HOST"
  if [[ "$host" == "0.0.0.0" || "$host" == "::" ]]; then
    host="127.0.0.1"
  fi
  echo "http://${host}:${HTTP_PORT}/health"
}

run_contextagent_health_check() {
  local timeout_seconds="${1:-2}"
  local health_url
  health_url="$(contextagent_health_url)"
  bash "$SCRIPT_DIR/health-check.sh" \
    --url "$health_url" \
    --timeout "$timeout_seconds" \
    >/dev/null 2>&1
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

find_contextagent_listener_pid() {
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

show_recent_log_tail() {
  local log_path="$1"
  local line_count="${2:-80}"
  if [[ ! -f "$log_path" ]]; then
    warn "尚未生成日志：$log_path"
    return 0
  fi
  echo ""
  echo "----- $log_path (tail -n $line_count) -----"
  tail -n "$line_count" "$log_path"
  echo "----- end log tail -----"
}

diagnose_contextagent_start_failure() {
  local pid="$1"
  if kill -0 "$pid" 2>/dev/null; then
    warn "ContextAgent 进程仍在运行，但健康检查未通过：PID=$pid"
  else
    warn "ContextAgent 进程已提前退出：PID=$pid"
    rm -f "$PID_FILE"
  fi
  show_recent_log_tail "$LOG_FILE" 80
  die "ContextAgent 启动失败。"
}

contextagent_is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  is_contextagent_pid "$pid"
}

stop_contextagent() {
  load_contextagent_runtime

  local pid=""
  if [[ -f "$PID_FILE" ]]; then
    pid="$(cat "$PID_FILE")"
  fi

  if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    warn "ContextAgent PID 文件指向的进程已不存在，尝试按端口恢复"
    pid=""
  fi

  if [[ -n "$pid" ]] && ! is_contextagent_pid "$pid"; then
    warn "PID 文件指向的进程不是 ContextAgent，已清理 PID 文件：PID=$pid"
    rm -f "$PID_FILE"
    pid=""
  fi

  if [[ -z "$pid" ]]; then
    pid="$(find_contextagent_listener_pid "$HTTP_PORT" || true)"
    if [[ -n "$pid" ]]; then
      echo "$pid" > "$PID_FILE"
      warn "根据端口 ${HTTP_PORT} 找到正在监听的 ContextAgent，已同步 PID：PID=$pid"
    fi
  fi

  if [[ -z "$pid" ]]; then
    info "ContextAgent 未运行"
    return 0
  fi

  info "停止 ContextAgent（PID=$pid）..."
  kill "$pid"
  for _ in $(seq 1 15); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      success "ContextAgent 已停止"
      return 0
    fi
    sleep 1
  done

  die "ContextAgent 停止超时，请检查进程状态：PID=$pid"
}

start_contextagent() {
  load_contextagent_runtime
  [[ -x "$VENV_DIR/bin/python3" ]] || die "未找到虚拟环境 Python：$VENV_DIR/bin/python3"
  [[ -f "$CONTEXT_AGENT_CONFIG_PATH" ]] || die "未找到 ContextAgent 配置：$CONTEXT_AGENT_CONFIG_PATH"
  [[ -f "$OPENJIUWEN_CONFIG_PATH" ]] || die "未找到 openJiuwen 配置：$OPENJIUWEN_CONFIG_PATH"

  if contextagent_is_running; then
    local pid
    pid="$(cat "$PID_FILE")"
    warn "ContextAgent 已在运行：PID=$pid"
    return 0
  fi

  if [[ -f "$PID_FILE" ]]; then
    rm -f "$PID_FILE"
  fi

  local existing_pid
  existing_pid="$(find_contextagent_listener_pid "$HTTP_PORT" || true)"
  if [[ -n "$existing_pid" ]]; then
    echo "$existing_pid" > "$PID_FILE"
    warn "检测到端口 ${HTTP_PORT} 上已有 ContextAgent，已同步 PID 文件：PID=$existing_pid"
    return 0
  fi

  local port_pid port_command
  port_pid="$(find_listening_pid "$HTTP_PORT" || true)"
  if [[ -n "$port_pid" ]]; then
    port_command="$(describe_pid_command "$port_pid")"
    die "端口 ${HTTP_PORT} 已被其他进程占用：PID=$port_pid CMD=${port_command:-unknown}"
  fi

  info "启动 ContextAgent（${HTTP_HOST}:${HTTP_PORT}）..."
  CA_CONTEXT_AGENT_CONFIG_PATH="$CONTEXT_AGENT_CONFIG_PATH" \
  CA_OPENJIUWEN_CONFIG_PATH="$OPENJIUWEN_CONFIG_PATH" \
  "$VENV_DIR/bin/python3" -m uvicorn context_agent.api.http_handler:app \
    --host "$HTTP_HOST" --port "$HTTP_PORT" \
    > "$LOG_FILE" 2>&1 &

  local pid="$!"
  echo "$pid" > "$PID_FILE"

  for _ in $(seq 1 20); do
    if run_contextagent_health_check 2; then
      success "ContextAgent 已启动：http://127.0.0.1:${HTTP_PORT}"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      diagnose_contextagent_start_failure "$pid"
    fi
    sleep 1
  done

  diagnose_contextagent_start_failure "$pid"
}

find_postgres_bin_dir() {
  local candidate version fallback_pg_bin_dir=""

  if [[ -n "${CA_PGVECTOR_BIN_DIR:-}" ]]; then
    [[ -x "${CA_PGVECTOR_BIN_DIR}/initdb" ]] || die "CA_PGVECTOR_BIN_DIR 未包含 initdb：${CA_PGVECTOR_BIN_DIR}"
    echo "$CA_PGVECTOR_BIN_DIR"
    return 0
  fi

  if command -v initdb >/dev/null 2>&1; then
    echo "$(dirname "$(command -v initdb)")"
    return 0
  fi

  if command -v pg_ctl >/dev/null 2>&1 && command -v pg_isready >/dev/null 2>&1; then
    candidate="$(dirname "$(command -v pg_ctl)")"
    if [[ -x "$candidate/initdb" && -x "$candidate/psql" && -x "$candidate/createdb" ]]; then
      echo "$candidate"
      return 0
    fi
  fi

  while IFS= read -r candidate; do
    [[ -d "$candidate" ]] || continue
    version="$(basename "$(dirname "$candidate")")"
    if [[ -x "$candidate/initdb" && -x "$candidate/pg_ctl" && -x "$candidate/psql" && -x "$candidate/createdb" && -x "$candidate/pg_isready" ]]; then
      if [[ -f "/usr/share/postgresql/$version/extension/vector.control" ]]; then
        echo "$candidate"
        return 0
      fi
      if [[ -z "$fallback_pg_bin_dir" ]]; then
        fallback_pg_bin_dir="$candidate"
      fi
    fi
  done < <(printf '%s\n' /usr/lib/postgresql/*/bin 2>/dev/null | sort -Vr)

  if [[ -n "$fallback_pg_bin_dir" ]]; then
    echo "$fallback_pg_bin_dir"
    return 0
  fi

  return 1
}

run_as_postgres_owner() {
  local owner="$1"
  shift

  if [[ "$(id -u)" -eq 0 ]]; then
    su -s /bin/bash "$owner" -c "$*"
  else
    bash -lc "$*"
  fi
}

load_pgvector_runtime() {
  resolve_runtime_paths
  local backend
  backend="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.backend")"
  PGVECTOR_BACKEND="${backend:-}"
  if [[ "$PGVECTOR_BACKEND" != "pgvector" ]]; then
    return 1
  fi

  local pg_port_default="${CA_PGVECTOR_PORT:-55432}"
  local pg_db_default="${CA_PGVECTOR_DB:-context_agent}"
  local pg_user_default="${CA_PGVECTOR_USER:-${USER:-contextagent}}"
  local default_pg_root="$PROJECT_DIR/.local/postgres"
  if [[ "$(id -u)" -eq 0 ]]; then
    default_pg_root="/var/lib/postgresql/context-agent"
    pg_user_default="${CA_PGVECTOR_USER:-postgres}"
  fi

  PGVECTOR_PORT="${CA_PGVECTOR_PORT:-$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.port")}"
  PGVECTOR_PORT="${PGVECTOR_PORT:-$pg_port_default}"

  local dsn
  dsn="$(load_yaml_field "$OPENJIUWEN_CONFIG_PATH" "vector_store.dsn")"
  if [[ -n "$dsn" ]]; then
    local parsed
    parsed="$("$PYTHON3" - "$dsn" <<'PY'
from urllib.parse import urlparse
import sys

parsed = urlparse(sys.argv[1])
print(parsed.username or "")
print(parsed.port or "")
print((parsed.path or "").lstrip("/"))
PY
)"
    local parsed_user parsed_port parsed_db
    parsed_user="$(printf '%s\n' "$parsed" | sed -n '1p')"
    parsed_port="$(printf '%s\n' "$parsed" | sed -n '2p')"
    parsed_db="$(printf '%s\n' "$parsed" | sed -n '3p')"
    PGVECTOR_USER="${CA_PGVECTOR_USER:-${parsed_user:-$pg_user_default}}"
    PGVECTOR_PORT="${CA_PGVECTOR_PORT:-${parsed_port:-$PGVECTOR_PORT}}"
    PGVECTOR_DB="${CA_PGVECTOR_DB:-${parsed_db:-$pg_db_default}}"
  else
    PGVECTOR_USER="$pg_user_default"
    PGVECTOR_DB="$pg_db_default"
  fi
  PGVECTOR_USER="${PGVECTOR_USER:-$pg_user_default}"
  PGVECTOR_DB="${PGVECTOR_DB:-$pg_db_default}"

  PGVECTOR_ROOT="${CA_PGVECTOR_ROOT:-$default_pg_root}"
  PGVECTOR_DATA_DIR="$PGVECTOR_ROOT/data"
  PGVECTOR_LOG_FILE="$PGVECTOR_ROOT/postgresql.log"
  PGVECTOR_SOCKET_DIR="$PGVECTOR_ROOT/socket"

  PG_BIN_DIR="$(find_postgres_bin_dir)" || die "未找到 PostgreSQL 服务端二进制目录。请设置 CA_PGVECTOR_BIN_DIR 或将 pg_ctl / initdb 加入 PATH。"

  PG_CTL_BIN="$PG_BIN_DIR/pg_ctl"
  PG_ISREADY_BIN="$PG_BIN_DIR/pg_isready"
  [[ -x "$PG_CTL_BIN" ]] || die "未找到 pg_ctl：$PG_CTL_BIN"
  [[ -x "$PG_ISREADY_BIN" ]] || die "未找到 pg_isready：$PG_ISREADY_BIN"
}

require_pgvector_backend() {
  if ! load_pgvector_runtime; then
    die "当前 openJiuwen 后端不是 pgvector，无法执行 pgvector 服务管理。"
  fi
}

maybe_load_pgvector_runtime() {
  if load_pgvector_runtime; then
    return 0
  fi
  warn "当前 openJiuwen 后端不是 pgvector，跳过本地 pgvector 管理。"
  return 1
}

pgvector_is_running() {
  "$PG_ISREADY_BIN" -h "$PGVECTOR_SOCKET_DIR" -p "$PGVECTOR_PORT" >/dev/null 2>&1
}

start_pgvector() {
  require_pgvector_backend
  [[ -s "$PGVECTOR_DATA_DIR/PG_VERSION" ]] || die "未找到 pgvector 数据目录：$PGVECTOR_DATA_DIR。请先运行安装或初始化脚本。"
  mkdir -p "$PGVECTOR_ROOT" "$PGVECTOR_SOCKET_DIR"

  if pgvector_is_running; then
    warn "pgvector 已在运行（端口 $PGVECTOR_PORT）"
    return 0
  fi

  info "启动 pgvector/PostgreSQL（端口 $PGVECTOR_PORT）..."
  if [[ "$(id -u)" -eq 0 ]]; then
    chown -R "${PGVECTOR_USER}:${PGVECTOR_USER}" "$PGVECTOR_ROOT"
    run_as_postgres_owner "$PGVECTOR_USER" "\"$PG_CTL_BIN\" -D \"$PGVECTOR_DATA_DIR\" -l \"$PGVECTOR_LOG_FILE\" -o \"-p $PGVECTOR_PORT -k $PGVECTOR_SOCKET_DIR\" start >/dev/null"
  else
    "$PG_CTL_BIN" -D "$PGVECTOR_DATA_DIR" -l "$PGVECTOR_LOG_FILE" -o "-p $PGVECTOR_PORT -k $PGVECTOR_SOCKET_DIR" start >/dev/null
  fi

  for _ in $(seq 1 20); do
    if pgvector_is_running; then
      success "pgvector 已启动"
      return 0
    fi
    sleep 1
  done

  if [[ -f "$PGVECTOR_LOG_FILE" ]]; then
    show_recent_log_tail "$PGVECTOR_LOG_FILE" 80
  fi
  die "pgvector 启动失败。"
}

stop_pgvector() {
  require_pgvector_backend
  if [[ ! -s "$PGVECTOR_DATA_DIR/PG_VERSION" ]]; then
    warn "pgvector 数据目录不存在，跳过停止：$PGVECTOR_DATA_DIR"
    return 0
  fi

  if ! pgvector_is_running; then
    info "pgvector 未运行"
    return 0
  fi

  info "停止 pgvector/PostgreSQL..."
  if [[ "$(id -u)" -eq 0 ]]; then
    run_as_postgres_owner "$PGVECTOR_USER" "\"$PG_CTL_BIN\" -D \"$PGVECTOR_DATA_DIR\" stop -m fast >/dev/null"
  else
    "$PG_CTL_BIN" -D "$PGVECTOR_DATA_DIR" stop -m fast >/dev/null
  fi

  for _ in $(seq 1 20); do
    if ! pgvector_is_running; then
      success "pgvector 已停止"
      return 0
    fi
    sleep 1
  done

  die "pgvector 停止超时。"
}
