#!/usr/bin/env bash
# =============================================================================
#  ContextAgent 一键安装脚本
#  用法：bash scripts/install.sh [--start] [--port PORT]
#
#  选项：
#    --start        安装完成后自动在后台启动服务（默认不启动）
#    --port PORT    服务监听端口（默认 8000）
#    --help         显示帮助
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
PORT=8000
START_SERVICE=false
LOG_FILE="$PROJECT_DIR/context_agent.log"
PID_FILE="$PROJECT_DIR/context_agent.pid"

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
    --help|-h)
      echo "用法: bash scripts/install.sh [--start] [--port PORT]"
      echo "  --start       安装后自动在后台启动服务"
      echo "  --port PORT   服务端口（默认 8000）"
      exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

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
info "安装依赖（从 requirements.txt）..."
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q --prefer-binary
success "依赖安装完成"

info "安装 ContextAgent 包..."
"$VENV_DIR/bin/pip" install -e "$PROJECT_DIR" --no-deps -q
success "ContextAgent 安装完成"

# ── 第 4 步：验证安装 ─────────────────────────────────────────────────────────
info "验证安装..."
"$VENV_DIR/bin/python3" -c "import context_agent; print('  context_agent 导入成功')"
success "安装验证通过"

# ── 第 5 步：（可选）启动服务 ─────────────────────────────────────────────────
if $START_SERVICE; then
  info "启动 ContextAgent 服务（端口 $PORT）..."

  # 停止已有进程
  if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
      warn "发现已运行的进程 PID=$OLD_PID，正在停止..."
      kill "$OLD_PID" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$PID_FILE"
  fi

  "$VENV_DIR/bin/python3" -m uvicorn context_agent.api.http_handler:app \
    --host 0.0.0.0 --port "$PORT" \
    > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  # 等待服务就绪
  info "等待服务启动..."
  for i in $(seq 1 15); do
    if curl -sf "http://localhost:$PORT/health" &>/dev/null; then
      success "服务已就绪：http://localhost:$PORT"
      echo "  日志：$LOG_FILE"
      echo "  PID 文件：$PID_FILE"
      break
    fi
    [[ $i -eq 15 ]] && { warn "服务未在 15 秒内响应，请查看日志：$LOG_FILE"; }
    sleep 1
  done
fi

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅  安装成功！                            ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  手动启动服务："
echo "    make venv-run"
echo "  或："
echo "    source .venv/bin/activate"
echo "    python3 -m uvicorn context_agent.api.http_handler:app --host 0.0.0.0 --port $PORT"
echo ""
echo "  接入 OpenClaw（安装服务后执行）："
echo "    bash scripts/setup-openclaw.sh"
echo ""
