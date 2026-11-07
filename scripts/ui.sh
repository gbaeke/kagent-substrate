#!/usr/bin/env bash
# Port-forward the kagent UI (8080) and controller/A2A API (8083). Ctrl-C stops both.
# kubectl port-forward exits on "lost connection to pod" (for example after a broken
# browser connection or a pod restart), so each forward restarts itself.
source "$(dirname "$0")/env.sh"
forward() { # svc local remote
  while true; do
    kubectl --context "$KCTX" -n kagent port-forward "svc/$1" "$2:$3" >/dev/null 2>&1
    sleep 1
  done
}
forward kagent-ui "${UI_PORT:-8080}" 8080 & p1=$!
forward kagent-controller "${API_PORT:-8083}" 8083 & p2=$!
trap 'kill $p1 $p2 2>/dev/null; pkill -P $p1 2>/dev/null; pkill -P $p2 2>/dev/null' EXIT INT TERM
echo "UI: http://localhost:${UI_PORT:-8080}   A2A/API: http://localhost:${API_PORT:-8083}"
wait
