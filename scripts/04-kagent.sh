#!/usr/bin/env bash
# Install kagent wired to Substrate. Substrate must be healthy first (controller crash-loops otherwise).
set -euo pipefail
source "$(dirname "$0")/env.sh"
CHART=oci://ghcr.io/kagent-dev/kagent/helm
helm --kube-context "$KCTX" upgrade --install kagent-crds $CHART/kagent-crds \
  --version "$KAGENT_VERSION" --namespace kagent --create-namespace --wait --set kmcp.enabled=false
helm --kube-context "$KCTX" upgrade --install kagent $CHART/kagent \
  --version "$KAGENT_VERSION" --namespace kagent --timeout 10m --wait \
  -f "$POC_DIR/cluster/kagent-values.yaml" \
  --set substrateWorkerPool.replicas="$WORKER_POOL_REPLICAS"
kubectl --context "$KCTX" -n kagent get pods
kubectl --context "$KCTX" get workerpools.ate.dev -A
