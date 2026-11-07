#!/usr/bin/env bash
# Approve or reject the pending tool calls of a task that is waiting (TASK_STATE_INPUT_REQUIRED).
#   scripts/approve.sh <taskId>                     # approve every pending call
#   scripts/approve.sh <taskId> no "not today"      # reject them, with a reason the model sees
#   AGENT=ops-lead scripts/approve.sh <taskId>      # default agent: ops-lead
# Uses kagent's HITL A2A extension (https://kagent.dev/extensions/hitl/v1).
# Needs the port-forward to :8083 from scripts/ui.sh.
set -euo pipefail
AGENT=${AGENT:-ops-lead}; NS=${NS:-kagent}; PORT=${PORT:-8083}
TASK=${1:?usage: approve.sh <taskId> [yes|no] [reason]}
DECISION=${2:-yes}; REASON=${3:-}
EXT=https://kagent.dev/extensions/hitl/v1
URL="http://localhost:$PORT/agents/$NS/$AGENT"
rpc() { curl -s -m 600 -X POST "$URL" -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -H "A2A-Extensions: $EXT" -d "$1"; }

task=$(rpc "$(jq -nc --arg id "$TASK" '{jsonrpc:"2.0",id:1,method:"GetTask",params:{id:$id}}')")
if echo "$task" | jq -e .error >/dev/null; then echo "$task" | jq .error; exit 1; fi
state=$(echo "$task" | jq -r .result.status.state)
[ "$state" = TASK_STATE_INPUT_REQUIRED ] || { echo "task is $state, nothing to approve"; exit 1; }
ctx=$(echo "$task" | jq -r .result.contextId)
pending=$(echo "$task" | jq -c --arg ext "$EXT" '.result.status.message.metadata[$ext].tools')
echo "$pending" | jq -r '.[] | "pending: \(.name) \(.args|tostring)"'

approved=$([ "$DECISION" = yes ] && echo true || echo false)
body=$(jq -nc --arg task "$TASK" --arg ctx "$ctx" --arg ext "$EXT" --argjson tools "$pending" \
  --argjson ok "$approved" --arg reason "$REASON" --arg mid "m-$(date +%s)-$RANDOM$RANDOM" '
  {jsonrpc:"2.0",id:1,method:"SendMessage",params:{message:{
    messageId:$mid, role:"ROLE_USER", taskId:$task, contextId:$ctx,
    parts:[{text:(if $ok then "Approved." else "Rejected." end)}],
    extensions:[$ext],
    metadata:{($ext):{type:"tool_approval_response",
      approvals:[$tools[] | {id, approved:$ok} + (if ($ok|not) and $reason != "" then {rejection_reason:$reason} else {} end)]}}}}}')
start=$(date +%s.%N)
resp=$(rpc "$body")
end=$(date +%s.%N)
if echo "$resp" | jq -e .error >/dev/null 2>&1; then echo "$resp" | jq .error; exit 1; fi
echo "$resp" | jq -r '[.result.task.artifacts[-1].parts[]?.text // empty] | join("") | if . == "" then "(no text)" else . end'
printf '\n[%s  state=%s  %.1fs]\n' "$( [ "$approved" = true ] && echo approved || echo rejected)" \
  "$(echo "$resp" | jq -r .result.task.status.state)" "$(awk "BEGIN{print $end - $start}")"
