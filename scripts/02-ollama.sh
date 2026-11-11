#!/usr/bin/env bash
# Run Ollama inside the cluster and load the model (through the host, see scripts/ollama-model.sh).
set -euo pipefail
source "$(dirname "$0")/env.sh"
K="kubectl --context $KCTX"
$K apply -f "$POC_DIR/manifests/ollama.yaml"
$K -n ollama rollout status deploy/ollama --timeout=10m
"$POC_DIR/scripts/ollama-model.sh" "$OLLAMA_MODEL"
$K -n ollama exec deploy/ollama -- ollama list
