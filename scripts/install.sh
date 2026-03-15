#!/usr/bin/env bash
# =============================================================================
#  ContextAgent 一键安装脚本
#  用法：bash scripts/install.sh [--start] [--port PORT] [--vector-backend BACKEND]
#
#  选项：
#    --start        安装完成后自动在后台启动服务（默认不启动）
#    --port PORT    服务监听端口（默认 8000）
#    --vector-backend BACKEND
#                   openJiuwen 向量库后端（默认 pgvector，可选 qdrant / milvus）
#    --context-agent-config PATH
#                   ContextAgent 配置文件路径（默认 ./.local/config/context_agent.yaml）
#    --openjiuwen-config PATH
#                   openJiuwen 配置文件路径（默认 ./.local/config/openjiuwen.yaml）
#    --help         显示帮助
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env-bootstrap.sh"
set -euo pipefail

PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
PORT=8000
START_SERVICE=false
VECTOR_BACKEND="pgvector"
RUNTIME_CONFIG_DIR="$PROJECT_DIR/.local/config"
CONTEXT_AGENT_CONFIG_PATH="$RUNTIME_CONFIG_DIR/context_agent.yaml"
OPENJIUWEN_CONFIG_PATH="$RUNTIME_CONFIG_DIR/openjiuwen.yaml"
LOG_FILE="$PROJECT_DIR/context_agent.log"
PID_FILE="$PROJECT_DIR/context_agent.pid"
ENV_FILE="$PROJECT_DIR/.env"

# ── 颜色输出 ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$@"; exit 1; }

# ── 参数解析 ──────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --start)       START_SERVICE=true; shift ;;
    --port)        PORT="$2"; shift 2 ;;
    --vector-backend) VECTOR_BACKEND="$2"; shift 2 ;;
    --context-agent-config) CONTEXT_AGENT_CONFIG_PATH="$2"; shift 2 ;;
    --openjiuwen-config) OPENJIUWEN_CONFIG_PATH="$2"; shift 2 ;;
    --help|-h)
      echo "用法: bash scripts/install.sh [--start] [--port PORT] [--vector-backend BACKEND] [--context-agent-config PATH] [--openjiuwen-config PATH]"
      echo "  --start       安装后自动在后台启动服务"
      echo "  --port PORT   服务端口（默认 8000）"
      echo "  --vector-backend BACKEND   向量库后端（默认 pgvector，可选 qdrant / milvus）"
      echo "  --context-agent-config PATH   ContextAgent 运行态配置文件输出路径"
      echo "  --openjiuwen-config PATH   openJiuwen 运行态配置文件输出路径"
      exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

upsert_env_var() {
  local key="$1"
  local value="$2"
  "$PYTHON3" - "$ENV_FILE" "$key" "$value" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = []
if env_path.exists():
    lines = env_path.read_text(encoding="utf-8").splitlines()

updated = False
for idx, line in enumerate(lines):
    if line.startswith(f"{key}="):
        lines[idx] = f"{key}={value}"
        updated = True
        break

if not updated:
    lines.append(f"{key}={value}")

env_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
PY
}

ensure_context_agent_config() {
  local target_path="$1"
  local target_dir example_file
  target_dir="$(dirname "$target_path")"
  mkdir -p "$target_dir"
  if [[ -f "$target_path" ]]; then
    info "检查 ContextAgent 配置更新：$target_path"
    
    # Expand env vars in template to handle potential placeholders
    local temp_template="$(mktemp "${TMPDIR:-/tmp}/context-agent-template-expanded.XXXXXX.yaml")"
    cp "$PROJECT_DIR/examples/configs/pgvector/context_agent.yaml" "$temp_template"
    
    # Currently context_agent.yaml doesn't use env vars in the default template,
    # but we support it for consistency if added later.
    "$PYTHON3" - "$temp_template" <<'PY'
import sys
import os
from pathlib import Path

config_path = Path(sys.argv[1])
if config_path.exists():
    content = config_path.read_text(encoding="utf-8")
    # Generic expansion for any ${VAR} in the template that matches an env var
    for key, val in os.environ.items():
        if f"${{{key}}}" in content or f"${key}" in content:
            content = content.replace(f"${{{key}}}", val)
            content = content.replace(f"${key}", val)
    config_path.write_text(content, encoding="utf-8")
PY

    "$VENV_DIR/bin/python3" "$PROJECT_DIR/context_agent/config/migration.py" \
      --target "$target_path" \
      --template "$temp_template" \
      --force-key budgets.latency.aggregation_timeout_ms \
      --force-key budgets.latency.cold_tier_timeout_ms \
      --force-key budgets.latency.warm_tier_timeout_ms \
      --force-key budgets.latency.hot_tier_timeout_ms \
      --force-key retrieval.timeout_ms \
      --force-key llm.timeout_s >/dev/null 2>&1 || warn "配置迁移失败，跳过"
    
    rm -f "$temp_template"
    return 0
  fi
  example_file="$PROJECT_DIR/examples/configs/pgvector/context_agent.yaml"
  [[ -f "$example_file" ]] || die "未找到 ContextAgent 默认配置模板：$example_file"
  cp "$example_file" "$target_path"
  success "已生成 ContextAgent 配置：$target_path"
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

diagnose_start_failure() {
  local pid="$1"
  if kill -0 "$pid" 2>/dev/null; then
    warn "服务进程仍在运行，但健康检查未通过：PID=${pid}"
  else
    warn "服务进程已提前退出：PID=${pid}"
    rm -f "$PID_FILE"
  fi
  warn "最近日志如下：$LOG_FILE"
  show_recent_log_tail "$LOG_FILE" 80
  die "ContextAgent 启动失败。请根据上述日志排查依赖、配置或端口占用问题。"
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

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       ContextAgent 一键安装               ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 第 1 步：检查 Python 3.11+ ────────────────────────────────────────────────
info "检查 Python 版本..."
PYTHON3=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" &>/dev/null; then
    # 验证版本 >= 3.11
    if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
      PYTHON3="$(command -v "$candidate")"
      break
    fi
  fi
done
[[ -z "$PYTHON3" ]] && die "未找到 Python 3.11+。请先安装：https://python.org/downloads/"

PY_VERSION=$("$PYTHON3" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
success "Python $PY_VERSION ($PYTHON3)"

# ── 第 2 步：检查虚拟环境健康状态 ────────────────────────────────────────────
cd "$PROJECT_DIR"

_venv_healthy() {
  # 检查 python3 可执行文件存在且可运行，且版本 >= 3.11
  local venv_py="$VENV_DIR/bin/python3"
  [[ -x "$venv_py" ]] || return 1
  "$venv_py" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null || return 1
  # 检查 pip 可用
  [[ -x "$VENV_DIR/bin/pip" ]] || return 1
  return 0
}

if [[ -d "$VENV_DIR" ]]; then
  if _venv_healthy; then
    VENV_PY_VER=$("$VENV_DIR/bin/python3" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
    info "虚拟环境已存在且健康（Python $VENV_PY_VER）"
  else
    warn "虚拟环境存在但不健康（Python 版本不符或文件损坏），正在重建..."
    rm -rf "$VENV_DIR"
    info "创建 Python 虚拟环境..."
    "$PYTHON3" -m venv "$VENV_DIR"
    success "虚拟环境重建完成：$VENV_DIR"
  fi
else
  info "创建 Python 虚拟环境（$VENV_DIR）..."
  "$PYTHON3" -m venv "$VENV_DIR"
  success "虚拟环境创建完成：$VENV_DIR"
fi

# 升级 pip
info "升级 pip..."
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel -q
success "pip 升级完成"

# ── 第 3 步：安装依赖 ─────────────────────────────────────────────────────────
info "安装 ContextAgent 及 openJiuwen 依赖..."
"$VENV_DIR/bin/pip" install -e "$PROJECT_DIR[openjiuwen]" -q --prefer-binary
success "ContextAgent 安装完成"

# ── 第 3.5 步：准备 ContextAgent 与 openJiuwen 配置 ────────────────────────────
info "准备 ContextAgent 主配置..."
ensure_context_agent_config "$CONTEXT_AGENT_CONFIG_PATH"
upsert_env_var "CA_CONTEXT_AGENT_CONFIG_PATH" "$CONTEXT_AGENT_CONFIG_PATH"
success "ContextAgent 配置已就绪，已写入 .env：CA_CONTEXT_AGENT_CONFIG_PATH=$CONTEXT_AGENT_CONFIG_PATH"

info "准备 openJiuwen 配置（向量库后端：$VECTOR_BACKEND）..."
bash "$SCRIPT_DIR/setup-vector-backend.sh" \
  --backend "$VECTOR_BACKEND" \
  --config "$OPENJIUWEN_CONFIG_PATH"
upsert_env_var "CA_OPENJIUWEN_CONFIG_PATH" "$OPENJIUWEN_CONFIG_PATH"
success "openJiuwen 配置已就绪，已写入 .env：CA_OPENJIUWEN_CONFIG_PATH=$OPENJIUWEN_CONFIG_PATH"

# ── 第 4 步：验证安装 ─────────────────────────────────────────────────────────
info "验证安装..."
"$VENV_DIR/bin/python3" -c "import importlib.util; assert importlib.util.find_spec('context_agent') is not None; print('  context_agent 包已安装')"
success "安装验证通过"

# ── 第 5 步：（可选）启动服务 ─────────────────────────────────────────────────
if $START_SERVICE; then
  info "启动 ContextAgent 服务（端口 $PORT）..."

  # 停止已有进程
  if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null && is_contextagent_pid "$OLD_PID"; then
      warn "发现已运行的进程 PID=$OLD_PID，正在停止..."
      kill "$OLD_PID" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$PID_FILE"
  fi

  EXISTING_PID="$(find_contextagent_listening_pid "$PORT" || true)"
  if [[ -n "$EXISTING_PID" ]]; then
    warn "检测到端口 $PORT 上已有 ContextAgent，准备替换旧进程：PID=$EXISTING_PID"
    kill "$EXISTING_PID" 2>/dev/null || true
    for _ in $(seq 1 15); do
      if ! kill -0 "$EXISTING_PID" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    if kill -0 "$EXISTING_PID" 2>/dev/null; then
      die "旧的 ContextAgent 未能在端口 $PORT 上正常退出：PID=$EXISTING_PID"
    fi
  fi

  PORT_PID="$(find_listening_pid "$PORT" || true)"
  if [[ -n "$PORT_PID" ]]; then
    die "端口 $PORT 已被其他进程占用：PID=$PORT_PID CMD=$(describe_pid_command "$PORT_PID")"
  fi

  CA_CONTEXT_AGENT_CONFIG_PATH="$CONTEXT_AGENT_CONFIG_PATH" \
  CA_OPENJIUWEN_CONFIG_PATH="$OPENJIUWEN_CONFIG_PATH" \
  "$VENV_DIR/bin/python3" -m uvicorn context_agent.api.http_handler:app \
    --host 0.0.0.0 --port "$PORT" \
    > "$LOG_FILE" 2>&1 &
  NEW_PID=$!
  echo "$NEW_PID" > "$PID_FILE"

  # 等待服务就绪
  info "等待服务启动..."
  STARTED=false
  for i in $(seq 1 15); do
    if bash "$SCRIPT_DIR/health-check.sh" --url "http://127.0.0.1:$PORT/health" --timeout 2 --allow-degraded-components "llm,embedding" >/dev/null 2>&1; then
      success "服务已就绪：http://localhost:$PORT"
      echo "  日志：$LOG_FILE"
      echo "  PID 文件：$PID_FILE"
      STARTED=true
      break
    fi
    if ! kill -0 "$NEW_PID" 2>/dev/null; then
      diagnose_start_failure "$NEW_PID"
    fi
    sleep 1
  done
  if [[ "$STARTED" != true ]]; then
    warn "服务未在 15 秒内通过健康检查。"
    diagnose_start_failure "$NEW_PID"
  fi
fi

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅  安装成功！                            ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  手动启动服务："
echo "    # 脚本/Makefile 会自动加载 ~/.bashrc 与 .env 中的变量"
echo "    export CA_CONTEXT_AGENT_CONFIG_PATH=$CONTEXT_AGENT_CONFIG_PATH"
echo "    export CA_OPENJIUWEN_CONFIG_PATH=$OPENJIUWEN_CONFIG_PATH"
echo "    make run-dev"
echo "  或："
echo "    source .venv/bin/activate"
echo "    export CA_CONTEXT_AGENT_CONFIG_PATH=$CONTEXT_AGENT_CONFIG_PATH"
echo "    export CA_OPENJIUWEN_CONFIG_PATH=$OPENJIUWEN_CONFIG_PATH"
echo "    python3 -m uvicorn context_agent.api.http_handler:app --host 0.0.0.0 --port $PORT"
echo ""
echo "  接入 OpenClaw（安装服务后执行）："
echo "    bash scripts/setup-openclaw.sh"
echo ""
