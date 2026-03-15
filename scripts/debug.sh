#!/bin/bash
# ContextAgent 统一调试脚本入口
# 该脚本会自动检查并安装调试所需的 Python 依赖，然后启动 Python 调试工具。

set -e

# 获取脚本所在目录的上一级目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python3"
VENV_PIP="$PROJECT_ROOT/.venv/bin/pip"

# 1. 检查虚拟环境是否存在
if [ ! -f "$VENV_PYTHON" ]; then
    echo "⚠️  未找到虚拟环境，正在初始化..."
    python3 -m venv "$PROJECT_ROOT/.venv"
    "$VENV_PIP" install --upgrade pip
    
    # 安装项目基本依赖（如果存在 setup.py 或 pyproject.toml）
    if [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
        echo "📦 安装项目依赖..."
        "$VENV_PIP" install -e "$PROJECT_ROOT"
    fi
fi

# 2. 检查并安装调试专用依赖
# 调试脚本依赖: rich (美化输出), typer (命令行解析), python-dotenv (环境变量)
REQUIRED_PKGS=("rich" "typer" "python-dotenv")
MISSING_PKGS=()

for pkg in "${REQUIRED_PKGS[@]}"; do
    if ! "$VENV_PYTHON" -c "import $pkg" &> /dev/null; then
        # 注意：python import 名称可能与包名不同 (如 python-dotenv -> dotenv)
        # 这里简单处理，如果 import 失败则标记缺失
        if [ "$pkg" == "python-dotenv" ]; then
             if ! "$VENV_PYTHON" -c "import dotenv" &> /dev/null; then
                 MISSING_PKGS+=("$pkg")
             fi
        else
             MISSING_PKGS+=("$pkg")
        fi
    fi
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "📦 检测到缺失调试依赖，正在安装: ${MISSING_PKGS[*]} ..."
    "$VENV_PIP" install "${MISSING_PKGS[@]}"
fi

# 3. 运行 Python 调试脚本
# 将所有传入的参数转发给 python 脚本
exec "$VENV_PYTHON" "$SCRIPT_DIR/debug.py" "$@"
