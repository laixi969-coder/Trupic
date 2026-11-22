#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
weights=${TRUPIC_VISION_MODEL_DIR:-"$root/.trupic/models/Qwen3-VL-2B-Instruct"}
model="$weights/Qwen3VL-2B-Instruct-Q4_K_M.gguf"
projector="$weights/mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"

if ! command -v llama-server >/dev/null || [ ! -r "$model" ] || [ ! -r "$projector" ]; then
  echo "需要 llama-server 和 Qwen3-VL-2B-Instruct 的 Q4_K_M 权重及 Q8_0 视觉投影文件。目录为 $weights" >&2
  exit 1
fi
exec llama-server -m "$model" --mmproj "$projector" --alias Qwen3-VL-2B-Instruct \
  --host 127.0.0.1 --port "${TRUPIC_LOCAL_VISION_PORT:-7395}" -c 16384 -np 1 --temp 0 --image-max-tokens 768
