#!/usr/bin/env bash
# Put a model into the in-cluster Ollama:  scripts/ollama-model.sh qwen3:4b-instruct
# The blobs are downloaded on the host and streamed into the pod, then `ollama pull` verifies them
# (and downloads whatever is still missing). Reason: `ollama pull` from inside a kind pod can be very
# slow (about 200 KB/s on the machine this was built on, against 37 MB/s from the host).
set -euo pipefail
source "$(dirname "$0")/env.sh"
MODEL=${1:?usage: ollama-model.sh <model[:tag]>}
NAME=${MODEL%%:*}; TAG=${MODEL#*:}; [ "$TAG" = "$MODEL" ] && TAG=latest
K="kubectl --context $KCTX -n ollama"
REG=https://registry.ollama.ai/v2/library/$NAME
DIR=/root/.ollama/models

if $K exec deploy/ollama -- ollama list | awk 'NR>1{print $1}' | grep -qx -e "$MODEL" -e "$NAME:$TAG"; then
  echo "$MODEL is already in the cluster"; exit 0
fi

stream() {
  local manifest digest
  manifest=$(curl -fsS -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' "$REG/manifests/$TAG") || return 1
  $K exec deploy/ollama -- mkdir -p "$DIR/blobs" "$DIR/manifests/registry.ollama.ai/library/$NAME"
  for digest in $(echo "$manifest" | jq -r '.config.digest, .layers[].digest'); do
    echo "  $digest"
    curl -fsSL "$REG/blobs/$digest" | $K exec -i deploy/ollama -- sh -c "cat > $DIR/blobs/${digest/:/-}" || return 1
  done
  echo "$manifest" | $K exec -i deploy/ollama -- sh -c "cat > $DIR/manifests/registry.ollama.ai/library/$NAME/$TAG"
}

echo "loading $MODEL through the host"
stream || echo "host download failed; falling back to ollama pull inside the cluster"
$K exec deploy/ollama -- ollama pull "$MODEL" | tail -1
