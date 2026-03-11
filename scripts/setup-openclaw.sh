#!/usr/bin/env bash
# =============================================================================
#  ContextAgent × OpenClaw 一键对接脚本
#  用法：bash scripts/setup-openclaw.sh [选项]
#
#  前置条件：ContextAgent 服务已启动（bash scripts/install.sh --start）
#
#  选项：
#    --url URL          ContextAgent 服务地址（默认 http://localhost:8000）
#    --scope SCOPE_ID   记忆命名空间（默认 openclaw）
#    --token BUDGET     注入 token 预算（默认 2048）
#    --mode MODE        检索模式 fast|quality（默认 fast）
#    --top-k N          每轮检索条数（默认 8）
#    --api-key KEY      Bearer 认证 Token（可选）
#    --memory-plugin    同时安装 memory-kind 轻量插件（默认否）
#    --uninstall        从 OpenClaw 中移除 ContextAgent 插件
#    --help             显示帮助
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLUGIN_DIR="$PROJECT_DIR/plugins/openclaw-plugin"
MEMORY_PLUGIN_DIR="$PROJECT_DIR/plugins/openclaw-memory-plugin"

# ── 默认配置（可通过环境变量或参数覆盖）──────────────────────────────────────
CA_BASE_URL="${CA_BASE_URL:-http://localhost:8000}"
CA_SCOPE_ID="${CA_SCOPE_ID:-openclaw}"
CA_TOKEN_BUDGET="${CA_TOKEN_BUDGET:-2048}"
CA_RETRIEVAL_MODE="${CA_RETRIEVAL_MODE:-fast}"
CA_TOP_K="${CA_TOP_K:-8}"
CA_TIMEOUT_MS="${CA_TIMEOUT_MS:-5000}"
CA_API_KEY="${CA_API_KEY:-}"
INSTALL_MEMORY_PLUGIN=false
UNINSTALL=false

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
    --url)           CA_BASE_URL="$2"; shift 2 ;;
    --scope)         CA_SCOPE_ID="$2"; shift 2 ;;
    --token)         CA_TOKEN_BUDGET="$2"; shift 2 ;;
    --mode)          CA_RETRIEVAL_MODE="$2"; shift 2 ;;
    --top-k)         CA_TOP_K="$2"; shift 2 ;;
    --api-key)       CA_API_KEY="$2"; shift 2 ;;
    --memory-plugin) INSTALL_MEMORY_PLUGIN=true; shift ;;
    --uninstall)     UNINSTALL=true; shift ;;
    --help|-h)
      echo "用法: bash scripts/setup-openclaw.sh [选项]"
      echo ""
      echo "选项："
      echo "  --url URL          ContextAgent 服务地址（默认 http://localhost:8000）"
      echo "  --scope SCOPE_ID   记忆命名空间（默认 openclaw）"
      echo "  --token BUDGET     注入 token 预算（默认 2048）"
      echo "  --mode MODE        检索模式 fast|quality（默认 fast）"
      echo "  --top-k N          每轮检索条数（默认 8）"
      echo "  --api-key KEY      Bearer 认证 Token（可选）"
      echo "  --memory-plugin    同时安装 memory-kind 轻量插件（默认否）"
      echo "  --uninstall        从 OpenClaw 中移除 ContextAgent 插件"
      exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   ContextAgent × OpenClaw 一键对接        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 卸载模式 ─────────────────────────────────────────────────────────────────
if $UNINSTALL; then
  info "卸载 ContextAgent 插件..."
  openclaw plugins uninstall context-agent 2>/dev/null || warn "插件未安装，跳过"
  openclaw plugins uninstall context-agent-memory 2>/dev/null || true

  info "清除 OpenClaw 配置..."
  openclaw config unset plugins.slots.contextEngine 2>/dev/null || true
  openclaw config unset plugins.entries.context-agent 2>/dev/null || true
  openclaw config unset plugins.entries.context-agent-memory 2>/dev/null || true

  success "卸载完成"
  exit 0
fi

# ── 第 1 步：检查 OpenClaw ────────────────────────────────────────────────────
info "检查 OpenClaw 安装..."
command -v openclaw &>/dev/null || die "未找到 openclaw。请先安装：https://openclaw.io"
OC_VERSION=$(openclaw --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9.-]+' | head -1 || echo "unknown")
success "OpenClaw $OC_VERSION"

# ── 第 2 步：检查 ContextAgent 服务 ──────────────────────────────────────────
info "检查 ContextAgent 服务 ($CA_BASE_URL)..."
if curl -sf --max-time 5 "$CA_BASE_URL/health" &>/dev/null; then
  SVC_VERSION=$(curl -sf --max-time 5 "$CA_BASE_URL/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('version','?'))" 2>/dev/null || echo "?")
  success "ContextAgent 服务在线 (v$SVC_VERSION)"
else
  warn "ContextAgent 服务未响应 ($CA_BASE_URL)"
  warn "请先启动服务：bash scripts/install.sh --start"
  echo ""
  read -r -p "  是否继续配置（服务稍后手动启动）？[y/N] " CONFIRM
  [[ "$CONFIRM" =~ ^[Yy]$ ]] || exit 1
fi

# ── 第 3 步：安装 context-engine 插件 ────────────────────────────────────────
info "安装 context-engine 插件..."
[[ -d "$PLUGIN_DIR" ]] || die "插件目录不存在：$PLUGIN_DIR"

# 先卸载旧版本（幂等）
openclaw plugins uninstall context-agent 2>/dev/null && \
  info "已卸载旧版本插件" || true

openclaw plugins install --link "$PLUGIN_DIR"
success "context-engine 插件安装完成"

# ── 第 4 步：配置 OpenClaw ────────────────────────────────────────────────────
info "写入 OpenClaw 配置..."

# 激活 context-agent 插件槽
openclaw config set plugins.slots.contextEngine "context-agent"

# 插件条目
openclaw config set plugins.entries.context-agent.enabled true  --strict-json
openclaw config set plugins.entries.context-agent.config.baseUrl      "$CA_BASE_URL"
openclaw config set plugins.entries.context-agent.config.scopeId      "$CA_SCOPE_ID"
openclaw config set plugins.entries.context-agent.config.timeoutMs    "$CA_TIMEOUT_MS"    --strict-json
openclaw config set plugins.entries.context-agent.config.contextTokenBudget "$CA_TOKEN_BUDGET" --strict-json
openclaw config set plugins.entries.context-agent.config.retrievalMode "$CA_RETRIEVAL_MODE"
openclaw config set plugins.entries.context-agent.config.topK          "$CA_TOP_K"         --strict-json
openclaw config set plugins.entries.context-agent.config.minScore      "0.01"              --strict-json

if [[ -n "$CA_API_KEY" ]]; then
  openclaw config set plugins.entries.context-agent.config.apiKey "$CA_API_KEY"
  info "  API Key 已配置"
fi

success "context-engine 配置写入完成"

# ── 第 5 步：（可选）安装 memory-kind 插件 ───────────────────────────────────
if $INSTALL_MEMORY_PLUGIN; then
  info "安装 memory-kind 插件..."
  [[ -d "$MEMORY_PLUGIN_DIR" ]] || die "内存插件目录不存在：$MEMORY_PLUGIN_DIR"

  openclaw plugins uninstall context-agent-memory 2>/dev/null || true
  openclaw plugins install --link "$MEMORY_PLUGIN_DIR"

  openclaw config set plugins.entries.context-agent-memory.enabled   true  --strict-json
  openclaw config set plugins.entries.context-agent-memory.config.baseUrl  "$CA_BASE_URL"
  openclaw config set plugins.entries.context-agent-memory.config.scopeId  "$CA_SCOPE_ID"
  # 与 context-engine 共存时关闭自动召回（避免双重检索）
  openclaw config set plugins.entries.context-agent-memory.config.autoRecall  false --strict-json
  openclaw config set plugins.entries.context-agent-memory.config.autoCapture false --strict-json

  success "memory-kind 插件安装并配置完成"
fi

# ── 第 6 步：验证插件加载 ─────────────────────────────────────────────────────
info "验证插件状态..."
sleep 1
if openclaw plugins list 2>/dev/null | grep -q "context-agent"; then
  success "插件已成功注册到 OpenClaw"
else
  warn "插件列表中未显示 context-agent，请运行 'openclaw plugins doctor' 排查"
fi

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅  对接完成！                            ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  配置摘要："
echo "    ContextAgent 地址 : $CA_BASE_URL"
echo "    命名空间 (scopeId): $CA_SCOPE_ID"
echo "    检索模式          : $CA_RETRIEVAL_MODE"
echo "    Token 预算        : $CA_TOKEN_BUDGET"
echo "    Memory 插件       : $(${INSTALL_MEMORY_PLUGIN} && echo '已安装' || echo '未安装')"
echo ""
echo "  排查工具："
echo "    openclaw plugins list"
echo "    openclaw plugins doctor"
echo "    openclaw config get plugins"
echo ""
echo "  验证对话中的上下文注入："
echo "    curl -s $CA_BASE_URL/health"
echo ""
echo "  卸载："
echo "    bash scripts/setup-openclaw.sh --uninstall"
echo ""
