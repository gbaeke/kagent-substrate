#!/usr/bin/env bash
# Delete the whole PoC (the kind cluster and everything in it, including the downloaded model).
set -euo pipefail
source "$(dirname "$0")/scripts/env.sh"
kind delete cluster --name "$KIND_CLUSTER"
