# Add an agent that runs Claude Code

This guide adds a kagent Agent that runs **Claude Code** inside a Substrate actor.
It uses the `claude` Harness, so each conversation gets its own gVisor sandbox
with the real Claude Code CLI, its built-in tools and its own session memory.

The finished example is `manifests/claude-agent.yaml` (agent `claude-k8s-helper`).
Tested with kagent 1.0.0-rc3 and Agent Substrate 1.0.0.

## Before you start

- The PoC is running (`./up.sh`), and `./scripts/ui.sh` is running for chat.
- You have an Anthropic API key. Claude Code cannot use the local Ollama model.
- You ran `source scripts/env.sh`, so `kubectl`, `kubectl-ate` and `$KCTX` are set.

## How it fits together

An Agent has two parts. The **template** says what the agent does: prompt,
model and tools. The **Harness** says how and where it runs. For Claude Code you
need four objects:

| Object | Name in the example | Purpose |
| --- | --- | --- |
| Secret | `kagent-anthropic` | Holds the API key. |
| ModelConfig | `anthropic` | Picks the Anthropic provider and model, and points at the Secret. |
| Harness | `claude` | Selects the Claude Code runtime and the Substrate worker pool. |
| Agent | `claude-k8s-helper` | The prompt and tools, plus `harnessRef: claude`. |

The API key never enters the actor. Substrate's egress gateway adds it to
outbound calls to Anthropic. The actor can reach only what its egress policy
allows: the model API and the MCP servers the agent uses.

## Step 1: Store the API key

`read -rs` keeps the key out of your shell history and off the screen.

```bash
read -rs ANTHROPIC_API_KEY
kubectl --context $KCTX -n kagent create secret generic kagent-anthropic \
  --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"
unset ANTHROPIC_API_KEY
```

Never put the key in a manifest in this repo.

## Step 2: Create the ModelConfig

```yaml
apiVersion: api.kagent.dev/v1alpha3
kind: ModelConfig
metadata:
  name: anthropic
  namespace: kagent
spec:
  provider: Anthropic
  model: claude-sonnet-5-5        # claude-haiku-4-5 is cheaper (the chart's default)
  apiKeySecret: kagent-anthropic
  apiKeySecretKey: ANTHROPIC_API_KEY
```

The Claude harness accepts Anthropic API keys and Amazon Bedrock bearer tokens.
It rejects AWS IAM keys and Vertex service-account keys.

## Step 3: Create the Harness

One Harness can serve many agents. Create it once.

```yaml
apiVersion: api.kagent.dev/v1alpha3
kind: Harness
metadata:
  name: claude
  namespace: kagent
spec:
  claude: {}
  substrate:
    workerPoolRef:
      name: kagent-default                  # created by the kagent chart
    snapshotPolicy:
      location: gs://ate-snapshots/kagent/  # RustFS bucket from the Substrate chart
```

You don't set an image. The kagent release supplies a digest-pinned
`claude-harness` image. To use another image, set `spec.workload.image` to a
reference pinned with `@sha256:`.

## Step 4: Create the Agent

```yaml
apiVersion: api.kagent.dev/v1alpha3
kind: Agent
metadata:
  name: claude-k8s-helper
  namespace: kagent
spec:
  template:
    inline:
      description: Kubernetes assistant running Claude Code in a Substrate actor.
      modelConfig:
        name: anthropic
      systemPrompt: |
        You are a concise Kubernetes assistant. Use your tools to look at the
        cluster before answering. You are read-only: never change anything.
      tools:
      - mcp:
          server:
            kind: RemoteMCPServer
            name: kagent-tool-server
  harnessRef:
    name: claude
```

To reuse a prompt across agents, put it in an `AgentTemplate` and use
`template.ref.name` instead of `template.inline`. See
`manifests/shared-harness.yaml`.

## Step 5: Apply and test

Steps 2 to 4 are all in `manifests/claude-agent.yaml`, plus a Microsoft Learn MCP
server (see [Add another MCP server](#add-another-mcp-server-and-what-that-does-to-egress)):

```bash
kubectl --context $KCTX apply -f manifests/claude-agent.yaml
kubectl --context $KCTX -n kagent wait agent/claude-k8s-helper --for=condition=Ready --timeout=5m
AGENT=claude-k8s-helper scripts/chat.sh "Which pods run in ate-system?"
```

To continue the conversation, pass the `contextId` that `chat.sh` prints:

```bash
CTX=<contextId> AGENT=claude-k8s-helper scripts/chat.sh "Which one is the egress proxy?"
```

The agent also shows up in the UI at http://localhost:8080.

To see the actor that Substrate created for the conversation:

```bash
scripts/actors.sh
```

Each conversation is one actor, named `session-<contextId>`. It changes to
`ACTOR_STATE_SUSPENDED` a few seconds after each reply.

## Add another MCP server, and what that does to egress

`manifests/claude-agent.yaml` also gives the agent the public Microsoft Learn MCP
server. Two changes do it: a `RemoteMCPServer` named `mslearn` with
`url: https://learn.microsoft.com/api/mcp`, and a second `mcp` entry under
`tools` that references it.

You don't write an egress rule for it. For each agent revision, kagent builds
the actor's allowlist from what the agent lists: the model endpoint, every MCP
server and the kagent controller. Adding `mslearn` adds a rule for
`learn.microsoft.com:443`. Actors of older revisions keep the old list.

Check the rules of a conversation's actor:

```bash
kubectl-ate --context $KCTX get egress-policy session-<contextId> -a kagent -o yaml
```

Anything not on the list is blocked. A hostname that isn't on the list doesn't
even resolve (Substrate returns NXDOMAIN). To allow a destination that isn't a
model or MCP server, create an `EgressPolicy` and list it in the Agent's
`spec.egressPolicyRefs`.

The `Accepted` / "Discovered N MCP tools" status on a RemoteMCPServer comes from
the kagent controller. The controller isn't behind Substrate's egress proxy, so
discovery can succeed even for a server that no actor is allowed to reach.

## How the agent remembers a conversation

Each turn runs `claude -p --resume <session-id>`. Claude Code reads its own
transcript from the actor's disk. After the reply, Substrate snapshots the actor
and suspends it. The next message in the same conversation restores the
snapshot, so the transcript is back.

kagent keeps a second copy of the conversation in its PostgreSQL. That copy
feeds the UI, the A2A task API, checkpoints and forks. It is not sent to Claude.
A new conversation (no `contextId`) starts with no memory.

## Limits to know

- **All tools on the MCP server.** The Claude harness cannot select single
  tools from an MCP server yet, so a `tools:` list under `mcp` has no effect.
  `kagent-tool-server` includes tools that change the cluster. Only the system
  prompt keeps this agent read-only.
- **Claude Code built-in tools are on.** Bash, file editing and the rest run
  inside the gVisor sandbox, not on your machine or the cluster nodes.
- **Not yet supported** (per the rc3 harness README): setting Claude Code's
  permission mode in the Harness, subagents in separate sessions, and parallel
  tool approvals.

## Change or remove the agent

- **Change the prompt, model or tools:** edit the manifest and apply it again.
  kagent creates a new revision. Existing conversations keep the revision they
  started on, so test changes in a new conversation.
- **Same template on the kagent Go runtime instead:** set
  `harnessRef.name: go-adk-substrate`. You keep the prompt and MCP tools, but
  lose the Claude Code tools and session handling.
- **Remove:**

  ```bash
  kubectl --context $KCTX delete -f manifests/claude-agent.yaml
  kubectl --context $KCTX -n kagent delete secret kagent-anthropic
  ```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Agent stays not Ready | `kubectl -n kagent describe agent claude-k8s-helper`. The conditions name a missing ModelConfig, Harness or Secret. |
| Replies fail after working before | The API key may have expired or been revoked. Replace the Secret and try a new conversation. |
| Reply text is split over many lines | Your `scripts/chat.sh` is older than the fix that joins streamed text parts. Update it. |
| `chat.sh` connection refused | `./scripts/ui.sh` must be running. |
