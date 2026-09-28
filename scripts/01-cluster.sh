#!/usr/bin/env bash
# Create the kind cluster with the feature gates Substrate needs.
set -euo pipefail
source "$(dirname "$0")/env.sh"
if kind get clusters | grep -qx "$KIND_CLUSTER"; then
  echo "cluster $KIND_CLUSTER already exists"
else
  kind create cluster --name "$KIND_CLUSTER" --config "$POC_DIR/cluster/kind-config.yaml" --image "$KIND_NODE_IMAGE" --wait 120s
fi
kubectl --context "$KCTX" api-resources | grep -E 'clustertrustbundles|podcertificaterequests'
