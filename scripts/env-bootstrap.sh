#!/usr/bin/env bash

if [[ -n "${CONTEXT_AGENT_ENV_BOOTSTRAPPED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
export CONTEXT_AGENT_ENV_BOOTSTRAPPED=1

_context_agent_bootstrap_env() {
  local bootstrap_dir project_dir env_file entry key value raw_line shell_rc_loader

  bootstrap_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  project_dir="$(dirname "$bootstrap_dir")"
  env_file="$project_dir/.env"

  load_shell_env_defaults() {
    command -v bash >/dev/null 2>&1 || return 0

    shell_rc_loader='
      for file in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
        [[ -r "$file" ]] || continue
        set -a
        . "$file" >/dev/null 2>&1 || true
        set +a
      done
      env -0
    '

    while IFS= read -r -d '' entry; do
      key="${entry%%=*}"
      value="${entry#*=}"
      [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
      if [[ -z "${!key+x}" ]]; then
        printf -v "$key" '%s' "$value"
        export "$key"
      fi
    done < <(bash -lc "$shell_rc_loader" 2>/dev/null)
  }

  load_dotenv_defaults() {
    [[ -r "$env_file" ]] || return 0

    while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
      raw_line="${raw_line#"${raw_line%%[![:space:]]*}"}"
      raw_line="${raw_line%"${raw_line##*[![:space:]]}"}"
      [[ -n "$raw_line" ]] || continue
      [[ "$raw_line" == \#* ]] && continue

      if [[ "$raw_line" =~ ^export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
      elif [[ "$raw_line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
      else
        continue
      fi

      if [[ "$value" =~ ^\"(.*)\"$ ]]; then
        value="${BASH_REMATCH[1]}"
      elif [[ "$value" =~ ^\'(.*)\'$ ]]; then
        value="${BASH_REMATCH[1]}"
      fi

      if [[ -z "${!key+x}" ]]; then
        printf -v "$key" '%s' "$value"
        export "$key"
      fi
    done < "$env_file"
  }

  load_shell_env_defaults
  load_dotenv_defaults
  unset -f load_shell_env_defaults
  unset -f load_dotenv_defaults
}

_context_agent_bootstrap_env
unset -f _context_agent_bootstrap_env

return 0 2>/dev/null || exit 0
