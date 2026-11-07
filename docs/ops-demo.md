# Two-subagent demo with tool approval

`manifests/ops-demo.yaml` builds an orchestrator, `ops-lead`. It delegates to
two subagents and may scale a Deployment only after a person approves the call.
It shows three kagent features: Shared subagents, a tool behind approval, and a
conversation that waits suspended for a decision.

Tested with kagent 1.0.0-rc3 and Agent Substrate 1.0.0.

```
ops-lead          Agent, kagent Go ADK harness, Claude model
├── cluster-inspector   AgentTemplate: read-only Kubernetes tools
├── azure-docs          AgentTemplate: Microsoft Learn MCP
└── k8s_scale           MCP tool with requireApproval: true
```

The manifest also creates a namespace `demo` with an nginx Deployment
`demo-web` (1 replica) to inspect and scale.

## Before you start

Do steps 1 to 5 of [claude-code-agent.md](claude-code-agent.md) first. This demo
reuses the `kagent-anthropic` Secret, the `anthropic` ModelConfig and the
`mslearn` RemoteMCPServer. Keep `./scripts/ui.sh` running.

## Run it

```bash
source scripts/env.sh
kubectl --context $KCTX apply -f manifests/ops-demo.yaml
kubectl --context $KCTX -n kagent wait agent/ops-lead --for=condition=Ready --timeout=5m
```

**Delegation.** One question that needs both subagents:

```bash
AGENT=ops-lead scripts/chat.sh "How many replicas does demo-web in namespace demo have, and per Microsoft Learn, what is the default AKS cluster autoscaler scan interval?"
```

The reply combines both: the replica count from `cluster-inspector`, and
"10 seconds" plus a Learn URL from `azure-docs`.

**Approval.** Ask for a change:

```bash
AGENT=ops-lead scripts/chat.sh "Scale demo-web in namespace demo to 3 replicas."
```

The task stops in `TASK_STATE_INPUT_REQUIRED`. `chat.sh` prints the pending call
and the command to decide on it:

```
approval needed: k8s_scale {"name":"demo-web","namespace":"demo","replicas":3}
-> scripts/approve.sh <taskId> [yes|no] [reason]   (AGENT=ops-lead)
```

While it waits, the conversation's actor is `ACTOR_STATE_SUSPENDED`
(`scripts/actors.sh`). It uses no CPU or memory and can wait for hours. Then:

```bash
scripts/approve.sh <taskId>                                  # approve: demo-web goes to 3
scripts/approve.sh <taskId> no "max 3 replicas on kind"      # reject: the model sees the reason
kubectl --context $KCTX -n demo get deploy demo-web
```

The same approval prompt appears in the UI.

## How it works

**Subagents are a hand-off, not a function call.** In rc3 a Shared subagent
(`tools[].subAgent.templateRef`) is compiled into the parent's runtime. On the
kagent Go harness it becomes a Google ADK sub-agent. ADK sub-agents take over
the conversation by transfer: by default the sub-agent answers the user and the
parent never sees the result. The prompts in the manifest work around this. The
orchestrator splits the request, and each subagent states its facts and
transfers back to its parent. Without those lines, only one subagent answers.

**One actor, one egress policy.** Shared subagents run in the parent's actor, so
the conversation has a single allowlist: the union of everything the tree uses
(`kagent-controller`, `kagent-tools`, `api.anthropic.com`,
`learn.microsoft.com`). `azure-docs` could technically reach the Kubernetes tool
server. Dedicated subagents, each with its own Agent, Session and actor, are
deferred upstream (the `agentRef` field is commented out in the API).

**Approval is per tool binding.** `requireApproval: true` on an MCP binding
pauses before every call of the tools that binding lists (here only
`k8s_scale`). The pause uses kagent's HITL A2A extension
(`https://kagent.dev/extensions/hitl/v1`):

1. The status message carries a `tool_approval_request` with each call's `id`,
   name and arguments.
2. kagent stores the event and Substrate suspends the actor at that point.
3. `approve.sh` reads the request with `GetTask`. It sends a message on the same
   task and context, with a `tool_approval_response` in the message metadata.
4. The actor resumes and runs, or skips, the exact pending call. A rejection
   reaches the model as `Tool call was rejected by user. Reason: ...`.

**Why not the Claude harness for the orchestrator?** It supports Shared
subagents, but its local subagents can't use MCP tools yet. So `ops-lead` runs
on the Go ADK harness with the same Anthropic model.

## Clean up

```bash
kubectl --context $KCTX delete -f manifests/ops-demo.yaml
```
