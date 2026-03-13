#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/service-common.sh"

TIMEOUT_SECONDS="${CA_HEALTH_TIMEOUT:-5}"
STRICT_SKIPPED=false
HEALTH_URL="${CA_HEALTH_URL:-}"
ALLOW_DEGRADED_COMPONENTS="${CA_HEALTH_ALLOW_DEGRADED_COMPONENTS:-llm,embedding}"
STRICT_DEGRADED=false
EXPLICIT_URL=false
if [[ -n "$HEALTH_URL" ]]; then
  EXPLICIT_URL=true
fi

usage() {
  cat <<'EOF'
用法：
  bash scripts/health-check.sh [--url URL] [--timeout SECONDS] [--strict-skipped] [--strict-degraded] [--allow-degraded-components a,b]

选项：
  --url URL           指定健康检查地址，默认根据运行态配置推导。
  --timeout SECONDS   curl 超时时间，默认 5 秒。
  --strict-skipped    将 skipped 组件也视为失败。
  --strict-degraded   将所有 degraded 组件都视为失败（覆盖默认的 llm,embedding 宽松策略）。
  --allow-degraded-components CSV
                      允许指定组件 degraded 但仍返回成功；默认是 llm,embedding。
  -h, --help          显示帮助。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      [[ $# -ge 2 ]] || die "--url 需要一个参数"
      HEALTH_URL="$2"
      EXPLICIT_URL=true
      shift 2
      ;;
    --timeout)
      [[ $# -ge 2 ]] || die "--timeout 需要一个参数"
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --strict-skipped)
      STRICT_SKIPPED=true
      shift
      ;;
    --strict-degraded)
      STRICT_DEGRADED=true
      ALLOW_DEGRADED_COMPONENTS=""
      shift
      ;;
    --allow-degraded-components)
      [[ $# -ge 2 ]] || die "--allow-degraded-components 需要一个参数"
      ALLOW_DEGRADED_COMPONENTS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "未知参数：$1"
      ;;
  esac
done

if [[ -z "$HEALTH_URL" ]]; then
  load_contextagent_runtime
  if [[ "$HTTP_HOST" == "0.0.0.0" || "$HTTP_HOST" == "::" ]]; then
    HEALTH_HOST="127.0.0.1"
  else
    HEALTH_HOST="$HTTP_HOST"
  fi
  CONFIGURED_PORT="$HTTP_PORT"
  ACTIVE_PORT="$(find_any_contextagent_listener_port || true)"
  if [[ -n "$ACTIVE_PORT" ]] && [[ "$ACTIVE_PORT" != "$CONFIGURED_PORT" ]]; then
    warn "检测到 ContextAgent 实际监听端口为 ${ACTIVE_PORT}（当前配置端口 ${CONFIGURED_PORT}），优先使用实际监听端口"
    HTTP_PORT="$ACTIVE_PORT"
  fi
  HEALTH_URL="http://${HEALTH_HOST}:${HTTP_PORT}/health"
fi

info "执行健康检查：$HEALTH_URL"

component_is_allowed_degraded() {
  local name="$1"
  local item
  IFS=',' read -r -a _allowed_items <<< "$ALLOW_DEGRADED_COMPONENTS"
  for item in "${_allowed_items[@]}"; do
    item="${item#"${item%%[![:space:]]*}"}"
    item="${item%"${item##*[![:space:]]}"}"
    [[ -n "$item" ]] || continue
    [[ "$item" == "$name" ]] && return 0
  done
  return 1
}

fetch_health() {
  curl -fsS --max-time "$TIMEOUT_SECONDS" "$1" 2>/dev/null
}

if ! HEALTH_BODY="$(fetch_health "$HEALTH_URL")"; then
  if [[ "$EXPLICIT_URL" != true ]]; then
    DISCOVERED_PORT="$(find_any_contextagent_listener_port || true)"
    if [[ -n "$DISCOVERED_PORT" ]]; then
      DISCOVERED_URL="http://127.0.0.1:${DISCOVERED_PORT}/health"
      if [[ "$DISCOVERED_URL" != "$HEALTH_URL" ]]; then
        warn "默认健康检查地址不可达，检测到 ContextAgent 正在监听端口 ${DISCOVERED_PORT}，改用 ${DISCOVERED_URL}"
        HEALTH_URL="$DISCOVERED_URL"
        HEALTH_BODY="$(fetch_health "$HEALTH_URL")" || die "健康检查请求失败：$HEALTH_URL"
      else
        die "健康检查请求失败：$HEALTH_URL"
      fi
    else
      die "健康检查请求失败：$HEALTH_URL"
    fi
  else
    die "健康检查请求失败：$HEALTH_URL"
  fi
fi

CHECK_OUTPUT="$(
  HEALTH_JSON="$HEALTH_BODY" \
  STRICT_SKIPPED="$STRICT_SKIPPED" \
  ALLOW_DEGRADED_COMPONENTS="$ALLOW_DEGRADED_COMPONENTS" \
  "$PYTHON3" - <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["HEALTH_JSON"])
strict_skipped = os.environ.get("STRICT_SKIPPED", "false").lower() == "true"
allowed_degraded = {
    item.strip()
    for item in os.environ.get("ALLOW_DEGRADED_COMPONENTS", "").split(",")
    if item.strip()
}
status = str(payload.get("status", "unknown"))
version = payload.get("version", "?")
uptime = payload.get("uptime_s", "?")
components = payload.get("components", {}) or {}

exit_code = 0
if status != "ok" and not components:
    exit_code = 1

print(f"service\t{status}\tversion={version}, uptime_s={uptime}")

for name in sorted(components):
    component = components.get(name, {}) or {}
    component_status = str(component.get("status", "unknown"))
    configured = component.get("configured", False)
    detail = str(component.get("detail", ""))
    metadata = component.get("metadata", {}) or {}
    metadata_text = ", ".join(f"{key}={metadata[key]}" for key in sorted(metadata))
    suffix = detail
    if metadata_text:
        suffix = f"{detail} ({metadata_text})" if detail else metadata_text
    print(f"component\t{name}\t{component_status}\t{configured}\t{suffix}")

    if component_status == "degraded" and name not in allowed_degraded:
        exit_code = 1
    if strict_skipped and component_status == "skipped":
        exit_code = 1

raise SystemExit(exit_code)
PY
)" || CHECK_EXIT=$?

CHECK_EXIT="${CHECK_EXIT:-0}"

while IFS=$'\t' read -r record_type col1 col2 col3 col4; do
  [[ -n "$record_type" ]] || continue
  if [[ "$record_type" == "service" ]]; then
    case "$col1" in
      ok) success "服务健康：$col2" ;;
      degraded) warn "服务降级：$col2" ;;
      *) warn "服务状态未知（${col1}）：${col2}" ;;
    esac
    continue
  fi

  if [[ "$record_type" == "component" ]]; then
    component_name="$col1"
    component_status="$col2"
    configured="$col3"
    detail="$col4"
    message="${component_name}: ${detail:-无额外信息}"
    case "$component_status" in
      ok) success "$message" ;;
      skipped)
        if [[ "$configured" == "True" || "$detail" == *"running service process"* ]]; then
          warn "$message"
        else
          info "$message"
        fi
        if [[ "$detail" == *"running service process"* ]]; then
          warn "${component_name}: 当前 shell 中若已更新相关环境变量，请重启 ContextAgent 以重新加载配置"
        fi
        ;;
      degraded)
        if component_is_allowed_degraded "$component_name"; then
          warn "$message"
        else
          error "$message"
        fi
        ;;
      *) warn "${component_name}: 状态=${component_status} ${detail}" ;;
    esac
  fi
done <<< "$CHECK_OUTPUT"

if [[ "$CHECK_EXIT" -ne 0 ]]; then
  die "健康检查未通过"
fi

success "健康检查通过"
