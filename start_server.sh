#!/bin/bash
# 启动Agent API服务器
set -euo pipefail
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONDA_BIN="${CONDA_BIN:-D:/ProgramData/miniconda3/condabin/conda}"
CONDA_ENV="${CONDA_ENV:-install_deb_refactor}"

echo "=========================================="
echo "启动 GraphAI Agents API 服务器"
echo "=========================================="

if [ ! -f "$CONDA_BIN" ]; then
    echo "错误: 未检测到 conda ($CONDA_BIN)"
    echo "请确认 miniconda3 已安装"
    exit 1
fi

eval "$("$CONDA_BIN" shell.bash hook)"
conda activate "$CONDA_ENV" 2>/dev/null || {
    echo "错误: conda 环境 $CONDA_ENV 不存在"
    echo "请先创建: conda create -n $CONDA_ENV python=3.13"
    exit 1
}

CONFIG_JSON="config/agent_config.json"
CONFIG_JSON_EXAMPLE="config/agent_config.json.example"

if [ ! -f "$CONFIG_JSON" ]; then
    echo "错误: 找不到 $CONFIG_JSON"
    if [ -f "$CONFIG_JSON_EXAMPLE" ]; then
        echo "请先复制 $CONFIG_JSON_EXAMPLE 为 $CONFIG_JSON 并配置 API 密钥"
    else
        echo "请先创建 $CONFIG_JSON 并填入 API 配置"
    fi
    exit 1
fi

echo ""
echo "启动服务器..."
echo "API地址: http://localhost:8072"
echo "API文档: http://localhost:8072/docs"
echo ""
echo "按 Ctrl+C 停止服务器"
echo "=========================================="
echo ""

python server.py
