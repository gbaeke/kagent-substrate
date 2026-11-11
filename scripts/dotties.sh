#!/usr/bin/env bash
# Mini dotties: persistent personal agents built from kagent features only, with their own UI.
# Applies the shared pieces (memory-enabled Harness, embedding model, egress policy), then runs
# the UI on http://localhost:8300. Needs the cluster from ./up.sh. See docs/mini-dotties.md.
set -euo pipefail
source "$(dirname "$0")/env.sh"
command -v uv >/dev/null || { echo "missing prerequisite: uv (https://docs.astral.sh/uv/)"; exit 1; }
K="kubectl --context $KCTX"

# Long-term memory needs an embedding model in the in-cluster Ollama (274 MB).
"$POC_DIR/scripts/ollama-model.sh" nomic-embed-text
$K apply -f "$POC_DIR/dotties/manifests/platform.yaml"
if $K -n kagent get secret kagent-anthropic >/dev/null 2>&1; then
  $K apply -f "$POC_DIR/dotties/manifests/anthropic.yaml"
fi

# The UI talks to kagent's A2A and MCP gateway on :8083; forward it unless something already does.
if ! curl -fs -m 2 -o /dev/null http://localhost:8083/healthz; then
  $K -n kagent port-forward svc/kagent-controller 8083:8083 >/dev/null 2>&1 & pf=$!
  trap 'kill $pf 2>/dev/null' EXIT
  until curl -fs -m 2 -o /dev/null http://localhost:8083/healthz; do sleep 1; done
fi

echo "Mini dotties: http://localhost:${DOTTIES_PORT:-8300}"
uv run "$POC_DIR/dotties/app/server.py"
