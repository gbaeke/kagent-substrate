#!/usr/bin/env bash
# Port-forward the kagent UI (8080) and controller/A2A API (8083). Ctrl-C stops both.
source "$(dirname "$0")/env.sh"
kubectl --context "$KCTX" -n kagent port-forward svc/kagent-ui "${UI_PORT:-8080}":8080 & p1=$!
kubectl --context "$KCTX" -n kagent port-forward svc/kagent-controller "${API_PORT:-8083}":8083 & p2=$!
trap 'kill $p1 $p2 2>/dev/null' EXIT INT TERM
echo "UI: http://localhost:${UI_PORT:-8080}   A2A/API: http://localhost:${API_PORT:-8083}"
wait
