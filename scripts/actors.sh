#!/usr/bin/env bash
# Show Substrate's view: workers, actor templates and actors (one per conversation).
source "$(dirname "$0")/env.sh"
echo "== workers";         kubectl-ate --context "$KCTX" get workers
echo; echo "== templates"; kubectl-ate --context "$KCTX" get actor-template -A
echo; echo "== actors";    kubectl-ate --context "$KCTX" get actors -A
