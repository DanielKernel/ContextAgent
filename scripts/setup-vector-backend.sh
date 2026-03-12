#!/usr/bin/env bash
# =============================================================================
#  Prepare openJiuwen vector-store configuration for local development.
#  pgvector is the default backend. Other backends remain selectable, but their
#  service installation is left to the local environment/tooling.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BACKEND="pgvector"
CONFIG_PATH="$PROJECT_DIR/config/openjiuwen.yaml"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$@"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2 ;;
    --config) CONFIG_PATH="$2"; shift 2 ;;
    --help|-h)
      echo "用法: bash scripts/setup-vector-backend.sh [--backend BACKEND] [--config PATH]"
      echo "  --backend BACKEND   向量库后端（默认 pgvector，可选 qdrant / milvus）"
      echo "  --config PATH       openJiuwen 配置文件输出路径（默认 config/openjiuwen.yaml）"
      exit 0 ;;
    *) die "未知参数: $1" ;;
  esac
done

CONFIG_DIR="$(dirname "$CONFIG_PATH")"
mkdir -p "$CONFIG_DIR"

find_linux_pg_bin_dir() {
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

  while IFS= read -r candidate; do
    [[ -d "$candidate" ]] || continue
    version="$(basename "$(dirname "$candidate")")"
    if [[ -x "$candidate/initdb" && -x "$candidate/pg_ctl" && -x "$candidate/psql" && -x "$candidate/createdb" && -x "$candidate/pg_isready" ]]; then
      if [[ -f "/usr/share/postgresql/$version/extension/vector.control" ]]; then
        echo "$candidate"
        return 0
      fi
      if [[ -z "${fallback_pg_bin_dir:-}" ]]; then
        fallback_pg_bin_dir="$candidate"
      fi
    fi
  done < <(printf '%s\n' /usr/lib/postgresql/*/bin 2>/dev/null | sort -Vr)

  if [[ -n "${fallback_pg_bin_dir:-}" ]]; then
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

copy_example_config() {
  local example_file="$PROJECT_DIR/examples/openjiuwen.$BACKEND.yaml.example"
  [[ -f "$example_file" ]] || die "未找到示例配置：$example_file"
  cp "$example_file" "$CONFIG_PATH"
  success "已生成 openJiuwen 配置：$CONFIG_PATH"
}

setup_pgvector_backend() {
  local pg_port="${CA_PGVECTOR_PORT:-5432}"
  local pg_db_name="${CA_PGVECTOR_DB:-context_agent}"
  local pg_user="${CA_PGVECTOR_USER:-${USER:-contextagent}}"
  local default_pg_root="$PROJECT_DIR/.local/postgres"
  local pg_root=""
  local pg_data_dir=""
  local pg_log_file=""
  local pg_bin_dir=""
  local initdb_bin=""
  local pg_ctl_bin=""
  local pg_isready_bin=""
  local createdb_bin=""
  local psql_bin=""

  case "$(uname -s)" in
    Darwin)
      command -v brew >/dev/null 2>&1 || die "pgvector 本地一键安装需要 Homebrew。请先安装 brew。"
      brew list postgresql@17 >/dev/null 2>&1 || brew install postgresql@17
      brew list pgvector >/dev/null 2>&1 || brew install pgvector
      pg_bin_dir="$(brew --prefix postgresql@17)/bin"
      ;;
    Linux)
      command -v apt-get >/dev/null 2>&1 || die "当前仅支持基于 apt 的 Linux 自动安装 pgvector。"
      command -v sudo >/dev/null 2>&1 || die "Linux 自动安装 pgvector 需要 sudo。"
      sudo apt-get update
      sudo apt-get install -y postgresql postgresql-contrib
      if ! sudo apt-get install -y postgresql-17-pgvector; then
        if ! sudo apt-get install -y postgresql-16-pgvector; then
          die "未找到可用的 pgvector 扩展包，请手动安装 pgvector 后重试。"
        fi
      fi
      pg_bin_dir="$(find_linux_pg_bin_dir)" || die "未找到 PostgreSQL 服务端二进制目录，请确认已安装 postgresql 服务端包。"
      if [[ "$(id -u)" -eq 0 ]]; then
        pg_user="${CA_PGVECTOR_USER:-postgres}"
        default_pg_root="/var/lib/postgresql/context-agent"
      fi
      ;;
    *)
      die "当前平台暂不支持 pgvector 自动安装：$(uname -s)"
      ;;
  esac

  pg_root="${CA_PGVECTOR_ROOT:-$default_pg_root}"
  pg_data_dir="$pg_root/data"
  pg_log_file="$pg_root/postgresql.log"

  mkdir -p "$pg_root"

  initdb_bin="$pg_bin_dir/initdb"
  pg_ctl_bin="$pg_bin_dir/pg_ctl"
  pg_isready_bin="$pg_bin_dir/pg_isready"
  createdb_bin="$pg_bin_dir/createdb"
  psql_bin="$pg_bin_dir/psql"

  [[ -x "$initdb_bin" ]] || die "未找到 initdb：$initdb_bin"
  [[ -x "$pg_ctl_bin" ]] || die "未找到 pg_ctl：$pg_ctl_bin"
  [[ -x "$pg_isready_bin" ]] || die "未找到 pg_isready：$pg_isready_bin"
  [[ -x "$createdb_bin" ]] || die "未找到 createdb：$createdb_bin"
  [[ -x "$psql_bin" ]] || die "未找到 psql：$psql_bin"

  if [[ ! -s "$pg_data_dir/PG_VERSION" ]]; then
    info "初始化本地 PostgreSQL 数据目录..."
    if [[ "$(id -u)" -eq 0 ]]; then
      chown -R "$pg_user":"$pg_user" "$pg_root"
      run_as_postgres_owner "$pg_user" "\"$initdb_bin\" -D \"$pg_data_dir\" -U \"$pg_user\" --auth-local=trust --auth-host=trust >/dev/null"
    else
      "$initdb_bin" -D "$pg_data_dir" -U "$pg_user" --auth-local=trust --auth-host=trust >/dev/null
    fi
  fi

  if ! "$pg_isready_bin" -h 127.0.0.1 -p "$pg_port" >/dev/null 2>&1; then
    info "启动本地 PostgreSQL（端口 $pg_port）..."
    if [[ "$(id -u)" -eq 0 ]]; then
      chown -R "$pg_user":"$pg_user" "$pg_root"
      run_as_postgres_owner "$pg_user" "\"$pg_ctl_bin\" -D \"$pg_data_dir\" -l \"$pg_log_file\" -o \"-p $pg_port\" start >/dev/null"
    else
      "$pg_ctl_bin" -D "$pg_data_dir" -l "$pg_log_file" -o "-p $pg_port" start >/dev/null
    fi
  fi

  for _ in $(seq 1 20); do
    if "$pg_isready_bin" -h 127.0.0.1 -p "$pg_port" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  "$pg_isready_bin" -h 127.0.0.1 -p "$pg_port" >/dev/null 2>&1 || die "PostgreSQL 启动失败，请查看日志：$pg_log_file"

  "$createdb_bin" -h 127.0.0.1 -p "$pg_port" -U "$pg_user" "$pg_db_name" >/dev/null 2>&1 || true
  "$psql_bin" -h 127.0.0.1 -p "$pg_port" -U "$pg_user" -d "$pg_db_name" -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null

  cat > "$CONFIG_PATH" <<EOF
user_id: context-agent

llm_config:
  provider: openai
  model: gpt-4o-mini
  api_key: \${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  timeout: 30
  max_retries: 2

embedding_config:
  provider: openai
  model: text-embedding-3-large
  api_key: \${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  dimension: 3072
  batch_size: 32

vector_store:
  backend: pgvector
  dsn: postgresql://$pg_user@127.0.0.1:$pg_port/$pg_db_name?sslmode=disable
  schema: public
  table_name: ltm_memory
  embedding_dimension: 3072
  distance: cosine
  index_type: ivfflat
  lists: 100
  metadata_fields:
    - scope_id
    - session_id
    - memory_type
    - source
    - created_at
    - updated_at
    - tags

memory_config:
  top_k: 10
  score_threshold: 0.3
  enable_user_profile: true
  enable_semantic_memory: true
  enable_episodic_memory: true
  enable_summary_memory: true
EOF

  success "pgvector 已完成本地初始化，openJiuwen 配置已写入：$CONFIG_PATH"
}

case "$BACKEND" in
  pgvector)
    setup_pgvector_backend
    ;;
  qdrant|milvus)
    copy_example_config
    warn "已生成 $BACKEND 的 openJiuwen 配置，但当前脚本不会自动安装该服务。"
    warn "请先按该后端的本地安装方式启动服务，再使用生成的配置启动 ContextAgent。"
    ;;
  *)
    die "不支持的向量库后端：$BACKEND（支持：pgvector / qdrant / milvus）"
    ;;
esac
