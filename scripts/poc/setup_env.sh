#!/usr/bin/env bash
# POC 环境搭建：项目本地 venv（D 盘，隔离），安装 agent 底座 + 检索栈
set -e
cd /d/work_buddy/personal-agent

PY="C:/Users/17680/.workbuddy/binaries/python/versions/3.13.12/python.exe"

echo "=== 1. 创建 venv ==="
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
if ! .venv/Scripts/python -m pip --version >/dev/null 2>&1; then
  echo "--- pip 缺失，ensurepip 恢复 ---"
  .venv/Scripts/python -m ensurepip --upgrade
fi
# 注意：不执行 pip self-upgrade —— 沙箱 safe-delete 会拦 pip.exe 替换

echo "=== 2. pydantic-ai + openai（agent 底座）==="
.venv/Scripts/pip install "pydantic-ai[openai]" -q

echo "=== 3. torch CUDA 版（RTX 4060，cu126；避免 PyPI 默认 CPU/CUDA 混乱）==="
.venv/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cu126 -q
.venv/Scripts/python -c "import torch; print('torch', torch.__version__, '| cuda_available:', torch.cuda.is_available(), '| device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"

echo "=== 4. llama-index 检索栈 ==="
.venv/Scripts/pip install llama-index-core llama-index-llms-openai llama-index-embeddings-huggingface llama-index-vector-stores-chroma chromadb -q

echo "=== 5. mcp ==="
.venv/Scripts/pip install mcp -q

echo "=== 6. 版本核对 ==="
.venv/Scripts/pip list | grep -iE "pydantic-ai|llama-index|chromadb|torch|sentence-transformers|mcp" || true
echo "SETUP DONE"
