#!/usr/bin/env bash
# Start N conversations at once and watch Substrate create one actor per session,
# pack them onto the worker pods, then suspend them all when they go idle.
set -euo pipefail
source "$(dirname "$0")/env.sh"
N=${1:-5}
for i in $(seq 1 "$N"); do
  PORT=${PORT:-8083} "$POC_DIR/scripts/chat.sh" "Reply with only the word pong-$i." >"/tmp/fanout-$i.log" 2>&1 &
done
for _ in $(seq 1 20); do
  echo "--- $(date +%T)"
  kubectl-ate --context "$KCTX" get actors -A | awk '{print $2, $4, $5}' | column -t
  running=$(kubectl-ate --context "$KCTX" get actors -A | grep -c RUNNING || true)
  [ "$(jobs -r | wc -l)" -eq 0 ] && [ "$running" -eq 0 ] && break
  sleep 3
done
wait
for i in $(seq 1 "$N"); do head -1 "/tmp/fanout-$i.log"; done
