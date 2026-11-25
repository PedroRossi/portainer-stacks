#!/usr/bin/env bash
# Qwen3.6-35B-A3B (Unsloth UD-Q2_K_XL, MTP GGUF) on a 6 GB GTX 16xx card + 32 GB RAM
# Native 256K context (262,144 tokens), OpenAI-compatible API + web UI on :8080
#
# Memory layout: attention / Gated-DeltaNet / shared-expert weights + 4-bit (q4_0) KV cache on the GPU,
# the 256 routed experts per layer (bulk of the 35B params) in system RAM (mmap, page cache).
# Only 10 of 40 layers are full attention (2 KV heads x 256 dim) -> ~5.6 KB/token with q4_0 KV:
# 256K tokens = ~1.4 GB (fits on the GPU); 512K needs YaRN x2 + CUDA unified memory (spills to RAM past ~400K).
# Settings come from env (qwen.sh mode 256k|512k writes ~/llm/qwen36.env): CTX, KV, UB, YARN, GGML_CUDA_ENABLE_UNIFIED_MEMORY.
# The native service gets them from systemd (EnvironmentFile); the Docker stack mounts the same file and sets QWEN_ENV_FILE.
set -euo pipefail
if [ -n "${QWEN_ENV_FILE:-}" ] && [ -f "$QWEN_ENV_FILE" ]; then set -a; . "$QWEN_ENV_FILE"; set +a; fi
BIN="${BIN:-$HOME/llm/llama.cpp-v72/build/bin/llama-server}"
MODEL="${MODEL:-$HOME/llm/models/qwen3.6-35b-a3b-mtp/Qwen3.6-35B-A3B-UD-Q2_K_XL.gguf}"
CTX="${CTX:-262144}"
# defaults = "256k" mode (no spill); qwen.sh mode 512k overrides via ~/llm/qwen36.env
UB="${UB:-1024}"
KV="${KV:-q4_0}"   # KV-cache type; llama.cpp Hadamard-rotates quantized K/V automatically
# beyond the native 262,144 window: YaRN rope scaling (factor = window / 262144)
ROPE=(); [ -n "${YARN:-}" ] && ROPE=(--rope-scaling yarn --rope-scale "$YARN" --yarn-orig-ctx 262144)
# image input (vision): MMPROJ = the projector GGUF that ships next to the model; MMPROJ_OFFLOAD=0 runs the
# image encoder on the CPU (no GPU memory, slower images). Unset MMPROJ = text only.
MM=(); if [ -n "${MMPROJ:-}" ]; then MM=(--mmproj "$MMPROJ"); [ "${MMPROJ_OFFLOAD:-1}" = 0 ] && MM+=(--no-mmproj-offload); fi
export CUDA_CACHE_MAXSIZE=4294967296
exec "$BIN" -m "$MODEL" --alias qwen3.6-35b-a3b \
  -c "$CTX" -np 1 "${ROPE[@]}" "${MM[@]}" \
  -ngl 99 --n-cpu-moe 40 -fa on -ctk "$KV" -ctv "$KV" \
  -t 8 -b 2048 -ub "$UB" \
  --jinja --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0 \
  --cache-ram "${CRAM:-3072}" \
  --host 0.0.0.0 --port "${PORT:-8080}" --metrics \
  "$@"
