#!/usr/bin/env bash
# Install Agent Substrate, a dev PostgreSQL and kagent with the kagent CLI (the supported path since 1.0.0-rc1).
# `kagent install` creates the Substrate CA/JWT pools, the shared database, the controller's
# SPIFFE ingress allowlist, the preview gates and the namespace label, then installs
# substrate-crds, substrate-atelet, substrate, kagent-crds and kagent in that order.
# Re-running it upgrades in place and keeps the existing CAs and database.
set -euo pipefail
source "$(dirname "$0")/env.sh"

# The CLI has no --context flag: give it a kubeconfig that only knows the kind cluster.
export KUBECONFIG="$POC_DIR/bin/kubeconfig"
kind get kubeconfig --name "$KIND_CLUSTER" > "$KUBECONFIG"

cat > "$POC_DIR/bin/kagent-cli.yaml" <<EOF
install:
  defaultModelProvider: Ollama
  kagent:
    version: "$KAGENT_VERSION"
    valuesFiles: ["$POC_DIR/cluster/kagent-values.yaml"]
  substrate:
    version: "$SUBSTRATE_VERSION"
EOF

# The CLI requires OLLAMA_API_KEY for the Ollama provider (it is meant for Ollama Cloud).
# providers.ollama.config.host pins requests to the in-cluster Ollama, which ignores auth,
# so a placeholder is enough. Export a real key only if you switch to a ":cloud" model.
export OLLAMA_API_KEY=${OLLAMA_API_KEY:-local-ollama-needs-no-key}

kagent --config "$POC_DIR/bin/kagent-cli.yaml" install --namespace kagent --timeout 15m
kubectl --context "$KCTX" -n ate-system get pods
kubectl --context "$KCTX" -n kagent get pods
kubectl --context "$KCTX" get workerpools.ate.dev -A
