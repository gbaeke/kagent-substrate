#!/usr/bin/env bash
# Talk to a kagent Agent over A2A (JSON-RPC) from the terminal.
#   scripts/chat.sh "your question"                 # new conversation with k8s-helper
#   AGENT=other CTX=<contextId> scripts/chat.sh "…"  # continue a conversation / other agent
# Needs: kubectl -n kagent port-forward svc/kagent-controller 8083:8083  (scripts/ui.sh does it)
set -euo pipefail
AGENT=${AGENT:-k8s-helper}; NS=${NS:-kagent}; PORT=${PORT:-8083}
MSG=${1:?usage: chat.sh "message"}
body=$(jq -nc --arg t "$MSG" --arg id "m-$(date +%s)-$RANDOM$RANDOM" --arg ctx "${CTX:-}" \
  '{jsonrpc:"2.0",id:1,method:"SendMessage",params:{message:({messageId:$id,role:"ROLE_USER",parts:[{text:$t}]}
     + (if $ctx != "" then {contextId:$ctx} else {} end))}}')
start=$(date +%s.%N)
resp=$(curl -s -m 600 -X POST "http://localhost:$PORT/agents/$NS/$AGENT" \
  -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -H 'A2A-Extensions: https://kagent.dev/extensions/hitl/v1' -d "$body")
end=$(date +%s.%N)
if echo "$resp" | jq -e .error >/dev/null 2>&1; then echo "$resp" | jq .error; exit 1; fi
echo "$resp" | jq -r '[.result.task.artifacts[-1].parts[]?.text // empty] | join("") | if . == "" then "(no text)" else . end'
state=$(echo "$resp" | jq -r .result.task.status.state)
if [ "$state" = TASK_STATE_INPUT_REQUIRED ]; then   # paused for a human decision
  echo "$resp" | jq -r '.result.task.status.message.metadata["https://kagent.dev/extensions/hitl/v1"]
    | if .type == "tool_approval_request" then (.tools[] | "approval needed: \(.name) \(.args|tostring)")
      else (.questions[]?.question // "input needed") end'
  echo "-> scripts/approve.sh $(echo "$resp" | jq -r .result.task.id) [yes|no] [reason]   (AGENT=$AGENT)"
fi
printf '\n[state=%s  contextId=%s  %.1fs]\n' \
  "$(echo "$resp" | jq -r .result.task.status.state)" \
  "$(echo "$resp" | jq -r .result.task.contextId)" "$(awk "BEGIN{print $end - $start}")"
