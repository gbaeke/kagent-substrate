#!/usr/bin/env bash
# Run Ollama inside the cluster and pull the model.
set -euo pipefail
source "$(dirname "$0")/env.sh"
K="kubectl --context $KCTX"
$K apply -f "$POC_DIR/manifests/ollama.yaml"
$K -n ollama rollout status deploy/ollama --timeout=10m
$K -n ollama exec deploy/ollama -- ollama pull "$OLLAMA_MODEL"
$K -n ollama exec deploy/ollama -- ollama list
