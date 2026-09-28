#!/usr/bin/env bash
# Deploy the sample agents and wait until Substrate has their golden snapshots.
set -euo pipefail
source "$(dirname "$0")/env.sh"
K="kubectl --context $KCTX"
$K apply -f "$POC_DIR/manifests/k8s-helper.yaml" -f "$POC_DIR/manifests/shared-harness.yaml"
for a in k8s-helper haiku-poet; do
  $K -n kagent wait agent/$a --for=condition=Ready --timeout=5m
done
$K -n kagent get agents
