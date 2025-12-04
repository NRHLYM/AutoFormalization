#!/bin/bash


CONDA_ENV_NAME="Formalizer"

# [默认参数]
DEFAULT_INPUT="data/mathverse/data.jsonl"
DEFAULT_LIMIT="5"
DEFAULT_OUTPUT=""
ENABLE_MULTIMODAL="false"

# --- 2. 定位脚本路径 ---
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

if command -v conda >/dev/null 2>&1; then
    CONDA_BASE=$(conda info --base)
    if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        source "$CONDA_BASE/etc/profile.d/conda.sh"
        echo "🔌 激活 Conda 环境: '$CONDA_ENV_NAME'..."
        conda activate "$CONDA_ENV_NAME"
    else
        echo "❌ 错误: 找不到 conda.sh，无法激活环境。"
    fi
else
    echo "❌ 错误: 未找到 'conda' 命令。"
    exit 1
fi

MAIN_PY="$SCRIPT_DIR/Formalizer/main.py"
if [ ! -f "$MAIN_PY" ]; then
    echo "❌ 找不到入口文件: $MAIN_PY"
    exit 1
fi

echo "---------------------------------------------------"
echo "🚀 启动 Aria Formalizer..."
echo "📂 工作目录: $SCRIPT_DIR"

# 基础命令
CMD="python -u \"$MAIN_PY\""

if [[ "$*" != *"--input"* ]]; then
    CMD="$CMD --input \"$DEFAULT_INPUT\""
fi

if [[ "$*" != *"--limit"* ]] && [ "$DEFAULT_LIMIT" != "-1" ]; then
    CMD="$CMD --limit $DEFAULT_LIMIT"
fi

if [[ "$*" != *"--output_dir"* ]] && [ -n "$DEFAULT_OUTPUT" ]; then
    CMD="$CMD --output_dir \"$DEFAULT_OUTPUT\""
fi

if [[ "$*" != *"--multimodal"* ]] && [ "$ENABLE_MULTIMODAL" == "true" ]; then
    CMD="$CMD --multimodal"
fi

CMD="$CMD $@"

echo "▶️  执行: $CMD"
echo "---------------------------------------------------"

# 执行命令
eval $CMD

echo ""
echo "---------------------------------------------------"
echo "✅ 运行结束。"