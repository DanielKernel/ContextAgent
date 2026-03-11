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
#    --uninstall        从 OpenClaw 中移除 ContextAgent 插件并还原备份
#    --rollback         列出可用备份并交互式还原
#    --rollback FILE    直接还原指定备份文件
#    --list-backups     列出所有 ContextAgent 相关备份
#    --help             显示帮助
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLUGIN_DIR="$PROJECT_DIR/plugins/context-agent"
MEMORY_PLUGIN_DIR="$PROJECT_DIR/plugins/openclaw-memory-plugin"

OC_CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-$HOME/.openclaw}"
OC_CONFIG_FILE="$OC_CONFIG_DIR/openclaw.json"
# 备份目录：放在 openclaw 配置目录里，以免丢失
BACKUP_DIR="$OC_CONFIG_DIR/backups"
BACKUP_PREFIX="openclaw.json.context-agent"

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
ROLLBACK_FILE=""
LIST_BACKUPS=false

# ── 颜色输出 ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$@"; exit 1; }
step()    { echo -e "\n${CYAN}▶ $*${NC}"; }

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
    --rollback)
      # --rollback 后面可选跟一个文件路径
      if [[ $# -gt 1 && "${2:-}" != --* && -n "${2:-}" ]]; then
        ROLLBACK_FILE="$2"; shift 2
      else
        ROLLBACK_FILE="INTERACTIVE"; shift
      fi ;;
    --list-backups)  LIST_BACKUPS=true; shift ;;
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
      echo "  --uninstall        移除插件并还原最近备份"
      echo "  --rollback [FILE]  交互式或直接还原指定备份"
      echo "  --list-backups     列出所有可用备份"
      exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

# ── 备份工具函数 ──────────────────────────────────────────────────────────────

_backup_config() {
  # 创建带时间戳的备份，返回备份文件路径
  mkdir -p "$BACKUP_DIR"
  local ts; ts=$(date +%Y%m%d_%H%M%S)
  local backup_file="$BACKUP_DIR/${BACKUP_PREFIX}.${ts}.json"
  if [[ -f "$OC_CONFIG_FILE" ]]; then
    cp "$OC_CONFIG_FILE" "$backup_file"
    echo "$backup_file"
  else
    echo ""
  fi
}

_list_backups() {
  local backups=()
  if [[ -d "$BACKUP_DIR" ]]; then
    while IFS= read -r f; do
      backups+=("$f")
    done < <(ls -t "$BACKUP_DIR/${BACKUP_PREFIX}".*.json 2>/dev/null || true)
  fi
  if [[ ${#backups[@]} -eq 0 ]]; then
    echo "  （无可用备份）"
  else
    local i=1
    for f in "${backups[@]}"; do
      local ts; ts=$(basename "$f" | grep -Eo '[0-9]{8}_[0-9]{6}' || echo "unknown")
      local size; size=$(wc -c < "$f" | tr -d ' ')
      echo "  [$i] $ts  ($size bytes)  $f"
      ((i++))
    done
  fi
  printf '%s\n' "${backups[@]+"${backups[@]}"}"
}

_restore_backup() {
  local backup_file="$1"
  [[ -f "$backup_file" ]] || die "备份文件不存在：$backup_file"
  cp "$backup_file" "$OC_CONFIG_FILE"
  success "已从备份还原：$backup_file"
}

# ── 列出备份模式 ──────────────────────────────────────────────────────────────
if $LIST_BACKUPS; then
  echo ""
  echo "可用备份（$BACKUP_DIR）："
  _list_backups > /dev/null   # just for output
  echo ""
  exit 0
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   ContextAgent × OpenClaw 一键对接        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 回滚模式 ──────────────────────────────────────────────────────────────────
if [[ -n "$ROLLBACK_FILE" ]]; then
  command -v openclaw &>/dev/null || die "未找到 openclaw"
  step "回滚 OpenClaw 配置"

  if [[ "$ROLLBACK_FILE" == "INTERACTIVE" ]]; then
    echo "可用备份："
    mapfile -t BACKUPS < <(_list_backups | grep -E '^\s+\[' | sed 's/.*  //' | awk '{print $NF}' || true)
    # 重新扫描
    mapfile -t BACKUPS < <(ls -t "$BACKUP_DIR/${BACKUP_PREFIX}".*.json 2>/dev/null || true)
    if [[ ${#BACKUPS[@]} -eq 0 ]]; then
      die "没有可用备份"
    fi
    local_i=1
    for f in "${BACKUPS[@]}"; do
      ts=$(basename "$f" | grep -Eo '[0-9]{8}_[0-9]{6}' || echo "unknown")
      size=$(wc -c < "$f" | tr -d ' ')
      echo "  [$local_i] $ts  ($size bytes)  $(basename "$f")"
      ((local_i++))
    done
    echo ""
    read -r -p "选择要还原的备份编号（1-${#BACKUPS[@]}）: " CHOICE
    [[ "$CHOICE" =~ ^[0-9]+$ ]] && (( CHOICE >= 1 && CHOICE <= ${#BACKUPS[@]} )) \
      || die "无效选择：$CHOICE"
    ROLLBACK_FILE="${BACKUPS[$((CHOICE-1))]}"
  fi

  info "还原备份：$ROLLBACK_FILE"
  _restore_backup "$ROLLBACK_FILE"

  info "移除 ContextAgent 插件..."
  openclaw plugins uninstall context-agent 2>/dev/null || true
  openclaw plugins uninstall context-agent-memory 2>/dev/null || true

  success "回滚完成，OpenClaw 已恢复到备份状态"
  exit 0
fi

# ── 卸载模式 ──────────────────────────────────────────────────────────────────
if $UNINSTALL; then
  command -v openclaw &>/dev/null || die "未找到 openclaw"
  step "卸载 ContextAgent 插件"

  info "卸载插件..."
  openclaw plugins uninstall context-agent 2>/dev/null || warn "插件未安装，跳过"
  openclaw plugins uninstall context-agent-memory 2>/dev/null || true

  # 找最近的备份并还原
  LATEST_BACKUP=$(ls -t "$BACKUP_DIR/${BACKUP_PREFIX}".*.json 2>/dev/null | head -1 || true)
  if [[ -n "$LATEST_BACKUP" ]]; then
    info "还原最近备份：$LATEST_BACKUP"
    _restore_backup "$LATEST_BACKUP"
  else
    warn "未找到备份，手动清除配置键..."
    openclaw config unset plugins.slots.contextEngine 2>/dev/null || true
    openclaw config unset plugins.entries.context-agent 2>/dev/null || true
    openclaw config unset plugins.entries.context-agent-memory 2>/dev/null || true
    warn "无备份可还原，已仅清除 context-agent 相关配置键"
  fi

  success "卸载完成"
  echo ""
  echo "  查看所有备份：bash scripts/setup-openclaw.sh --list-backups"
  echo "  手动回滚：    bash scripts/setup-openclaw.sh --rollback"
  exit 0
fi

# ── 第 1 步：检查 OpenClaw ────────────────────────────────────────────────────
step "检查前置条件"
info "检查 OpenClaw 安装..."
command -v openclaw &>/dev/null || die "未找到 openclaw。请先安装：https://openclaw.io"
OC_VERSION=$(openclaw --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9.-]+' | head -1 || echo "unknown")
success "OpenClaw $OC_VERSION"

# ── 第 2 步：检查 ContextAgent 服务 ──────────────────────────────────────────
info "检查 ContextAgent 服务 ($CA_BASE_URL)..."
if curl -sf --max-time 5 "$CA_BASE_URL/health" &>/dev/null; then
  SVC_VERSION=$(curl -sf --max-time 5 "$CA_BASE_URL/health" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('version','?'))" 2>/dev/null || echo "?")
  success "ContextAgent 服务在线 (v$SVC_VERSION)"
else
  warn "ContextAgent 服务未响应 ($CA_BASE_URL)"
  warn "请先启动服务：bash scripts/install.sh --start"
  echo ""
  read -r -p "  是否继续配置（服务稍后手动启动）？[y/N] " CONFIRM
  [[ "$CONFIRM" =~ ^[Yy]$ ]] || exit 1
fi

# ── 第 3 步：备份当前 OpenClaw 配置 ──────────────────────────────────────────
step "备份当前 OpenClaw 配置（支持随时回滚）"
BACKUP_FILE=$(_backup_config)
if [[ -n "$BACKUP_FILE" ]]; then
  success "配置已备份：$BACKUP_FILE"
else
  warn "配置文件不存在，跳过备份"
fi

# ── 第 4 步：安装 context-engine 插件 ────────────────────────────────────────
step "安装 context-engine 插件"
[[ -d "$PLUGIN_DIR" ]] || die "插件目录不存在：$PLUGIN_DIR"

# 修复可能遗留的旧插件路径（旧目录名 openclaw-plugin → context-agent）
if [[ -f "$OC_CONFIG_FILE" ]]; then
  python3 - "$OC_CONFIG_FILE" <<'PYEOF' 2>/dev/null || true
import json, sys
path = sys.argv[1]
cfg = json.load(open(path))
changed = False
p = cfg.get("plugins", {})
# Fix stale load.paths
for i, lp in enumerate(p.get("load", {}).get("paths", [])):
    fixed = lp.replace("/plugins/openclaw-plugin", "/plugins/context-agent")
    if fixed != lp:
        p["load"]["paths"][i] = fixed
        changed = True
# Fix stale install records
for k, v in p.get("installs", {}).items():
    for field in ("sourcePath", "installPath"):
        if field in v:
            fixed = v[field].replace("/plugins/openclaw-plugin", "/plugins/context-agent")
            if fixed != v[field]:
                v[field] = fixed
                changed = True
if changed:
    json.dump(cfg, open(path, "w"), indent=4)
    print("[INFO]  已修复旧插件路径引用")
PYEOF
fi

openclaw plugins uninstall context-agent 2>/dev/null && \
  info "已卸载旧版本插件" || true

openclaw plugins install --link "$PLUGIN_DIR"
success "context-engine 插件安装完成"

# ── 第 5 步：配置 OpenClaw ────────────────────────────────────────────────────
step "写入 OpenClaw 配置"

# 清除旧版本遗留的 contextEngine slot 设置（旧版脚本会设置该项，导致
# OpenClaw 启动时报 "Context engine not registered" 错误）
info "清除旧版 contextEngine slot 配置（如有）..."
openclaw config unset plugins.slots.contextEngine 2>/dev/null || true
openclaw config unset plugins.slots 2>/dev/null || true

# Context injection uses before_prompt_build hook — no slot registration needed.
openclaw config set plugins.entries.context-agent.enabled               true              --strict-json
openclaw config set plugins.entries.context-agent.config.baseUrl        "$CA_BASE_URL"
openclaw config set plugins.entries.context-agent.config.scopeId        "$CA_SCOPE_ID"
openclaw config set plugins.entries.context-agent.config.timeoutMs      "$CA_TIMEOUT_MS"    --strict-json
openclaw config set plugins.entries.context-agent.config.contextTokenBudget "$CA_TOKEN_BUDGET" --strict-json
openclaw config set plugins.entries.context-agent.config.retrievalMode  "$CA_RETRIEVAL_MODE"
openclaw config set plugins.entries.context-agent.config.topK           "$CA_TOP_K"         --strict-json
openclaw config set plugins.entries.context-agent.config.minScore       "0.01"              --strict-json

# Allow the plugin to load without the "non-bundled plugin" security warning
openclaw config set plugins.allow '["context-agent"]' --strict-json 2>/dev/null || true

if [[ -n "$CA_API_KEY" ]]; then
  openclaw config set plugins.entries.context-agent.config.apiKey "$CA_API_KEY"
  info "  API Key 已配置"
fi

success "context-engine 配置写入完成"

# ── 第 6 步：（可选）安装 memory-kind 插件 ───────────────────────────────────
if $INSTALL_MEMORY_PLUGIN; then
  step "安装 memory-kind 插件"
  [[ -d "$MEMORY_PLUGIN_DIR" ]] || die "内存插件目录不存在：$MEMORY_PLUGIN_DIR"

  openclaw plugins uninstall context-agent-memory 2>/dev/null || true
  openclaw plugins install --link "$MEMORY_PLUGIN_DIR"

  openclaw config set plugins.entries.context-agent-memory.enabled            true  --strict-json
  openclaw config set plugins.entries.context-agent-memory.config.baseUrl     "$CA_BASE_URL"
  openclaw config set plugins.entries.context-agent-memory.config.scopeId     "$CA_SCOPE_ID"
  openclaw config set plugins.entries.context-agent-memory.config.autoRecall  false --strict-json
  openclaw config set plugins.entries.context-agent-memory.config.autoCapture false --strict-json

  success "memory-kind 插件安装并配置完成"
fi

# ── 第 7 步：验证插件加载 ─────────────────────────────────────────────────────
step "验证插件状态"
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
echo "    Memory 插件       : $($INSTALL_MEMORY_PLUGIN && echo '已安装' || echo '未安装')"
if [[ -n "$BACKUP_FILE" ]]; then
echo ""
echo "  ⚡ 随时可回滚："
echo "    bash scripts/setup-openclaw.sh --rollback $BACKUP_FILE"
echo "    bash scripts/setup-openclaw.sh --rollback        # 交互式选择备份"
echo "    bash scripts/setup-openclaw.sh --list-backups    # 查看所有备份"
fi
echo ""
echo "  排查工具："
echo "    openclaw plugins list"
echo "    openclaw plugins doctor"
echo "    openclaw config get plugins"
echo ""
echo "  卸载（自动还原备份）："
echo "    bash scripts/setup-openclaw.sh --uninstall"
echo ""

