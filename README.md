# kagent + Agent Substrate — local PoC

A one-command local playground for [kagent](https://github.com/kagent-dev/kagent) 1.0
running its agents as sandboxed, suspend/resume actors on
[Agent Substrate](https://github.com/kagent-dev/substrate). Everything runs in a
single [kind](https://kind.sigs.k8s.io/) cluster in Docker, including the LLM
(Ollama, CPU), so **no API keys** are needed and nothing is exposed on your host.

> Pre-release software. kagent 1.0 is a release candidate (Substrate 1.0.0 is
> out); this repo pins the pair kagent itself pins. Not for production.

## Prerequisites

| Need | Notes |
| --- | --- |
| Linux x86_64 or arm64 | Tested on Linux x86_64. macOS/Docker Desktop is untested (gVisor snapshotting is reported to be flaky there). |
| Docker, running | Your user must be able to run `docker` without sudo. |
| `curl`, `jq`, `openssl`, `tar` | Checked by `scripts/00-tools.sh`. |
| ~8 GB free RAM, 4+ cores | The cluster idles at about 7 GB. More cores = faster CPU inference. |
| ~25 GB free disk | Images plus the 2.5 GB model. |
| Internet access | Pulls charts from ghcr.io, images, and the model. |

`kind`, `kubectl`, `helm`, `kubectl-ate` and the `kagent` CLI are downloaded automatically into
`./bin` at pinned versions; nothing is installed system-wide.

## Quick start

```bash
git clone https://github.com/gbaeke/kagent-substrate.git
cd kagent-substrate
./up.sh                 # ~7 min the first time; safe to re-run
./scripts/ui.sh         # keep running: UI http://localhost:8080, A2A/API http://localhost:8083
```

In a second terminal:

```bash
source scripts/env.sh   # puts ./bin on PATH and sets the kube context
scripts/chat.sh "List the pods in the ate-system namespace"
```

`up.sh` switches your current kubectl context to `kind-kagent-poc`.

## What gets deployed

| Version | |
| --- | --- |
| kagent | 1.0.0-rc3 |
| Agent Substrate | 1.0.0 (the version kagent 1.0.0-rc3 pins in `go/go.mod`) |
| Kubernetes | kind v0.33.0, node v1.35.0 |
| Model | `qwen3:4b-instruct` on in-cluster Ollama |

`scripts/03-kagent.sh` runs `kagent install`, which installs all of it in one go:
it creates Substrate's CA and JWT signing pools, a shared dev PostgreSQL, the
controller's ingress allowlist and the required preview gates, then installs the
Helm releases `substrate-crds`, `substrate-podcert`, `substrate-atelet`,
`substrate`, `kagent-crds` and `kagent`.

- **Substrate** (`ate-system`): API server, controller, atelet, router, egress
  proxy, RustFS (S3 bucket for snapshots).
- **kagent** (`kagent`): controller (A2A gateway), UI, MCP tool server, the
  PostgreSQL that kagent and Substrate share (separate schemas, certificate auth),
  and a WorkerPool of 2 pre-warmed gVisor worker pods (`ateworker-gvisor`).
- **Two sample agents**:
  - `k8s-helper`: read-only Kubernetes assistant with MCP tools (inline template).
  - `haiku-poet`: uses a separate `AgentTemplate` by reference.

  Both reference the shared `go-adk-substrate` Harness. Since rc1 every Agent
  needs a `harnessRef`, and the runtime image comes from the release's built-in
  catalog, so the manifests carry no image digests.

Each conversation becomes its own Substrate actor; it is snapshotted and
suspended after every reply and resumed (~100 ms) on the next message.

## Things to try

```bash
source scripts/env.sh
scripts/chat.sh "Which namespaces exist?"                        # new conversation
CTX=<contextId from output> scripts/chat.sh "Which one is Substrate's?"   # continue it
AGENT=haiku-poet scripts/chat.sh "What is a gVisor sandbox?"
scripts/actors.sh                 # workers, actor templates, actors (Substrate's view)
scripts/fanout-demo.sh 10         # 10 parallel conversations -> 10 actors on 2 pods
kubectl-ate --context $KCTX get egress-policy <actor-name> -a kagent -o yaml
kubectl -n kagent scale workerpool kagent-default --replicas=3
```

### A Claude Code agent (needs an Anthropic API key)

`manifests/claude-agent.yaml` adds `claude-k8s-helper`, which runs Claude Code
through the `claude` Harness instead of the kagent Go runtime. The key stays in a
Secret; Substrate's egress gateway injects it, so it never enters the actor.

```bash
read -rs ANTHROPIC_API_KEY
kubectl -n kagent create secret generic kagent-anthropic --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"
kubectl apply -f manifests/claude-agent.yaml
AGENT=claude-k8s-helper scripts/chat.sh "Which pods run in ate-system?"
```

The Claude harness gets the whole MCP tool server (it cannot select single tools
yet), so its read-only behaviour rests on the system prompt. Full walkthrough:
[docs/claude-code-agent.md](docs/claude-code-agent.md).

### Two-subagent demo with tool approval

`manifests/ops-demo.yaml` adds `ops-lead`. It delegates to a read-only cluster
subagent and a Microsoft Learn subagent, and it may scale `demo/demo-web` only
after you approve. `chat.sh` shows the pending call, and `scripts/approve.sh
<taskId> [yes|no] [reason]` decides it. Walkthrough: [docs/ops-demo.md](docs/ops-demo.md).

In the UI, the **Substrate** page shows worker pools, templates and live actor
states; **Agents** lets you create agents, templates and harnesses.

### Running your own agent on Substrate

[docs/langgraph-on-substrate.md](docs/langgraph-on-substrate.md) runs a LangGraph agent
directly on Substrate, without kagent, in a separate kind cluster built from a
Substrate checkout. It lists the errors we hit and their fixes.

## After a reboot or Docker restart

```bash
./scripts/after-restart.sh
```

The worker pods come back with stale actor networking and every message fails
with `KAGENT_SEND_NOT_ACCEPTED` until they are recycled. This script recycles
them and reverts any actor that crashed in the meantime.

## Configuration

Edit `scripts/env.sh` (versions, cluster name) and
`cluster/kagent-values.yaml` (model, worker count, kagent Helm values).

- **Different Ollama model**: `kubectl -n ollama exec deploy/ollama -- ollama pull <model>`,
  set `providers.ollama.model` in `cluster/kagent-values.yaml`, re-run `scripts/03-kagent.sh`.
  Avoid "thinking" models on CPU (plain `qwen3:4b` takes minutes per reply).
- **Second copy side by side**: `KIND_CLUSTER=my-copy ./up.sh`, then
  `KIND_CLUSTER=my-copy UI_PORT=9080 API_PORT=9083 ./scripts/ui.sh`.
- Changing an agent creates a new revision; existing conversations keep the
  revision (and model) they started with.

## Tear down

```bash
docker stop kagent-poc-control-plane   # pause; later: docker start ... && ./scripts/after-restart.sh
./down.sh                              # delete the cluster and everything in it
```

## Layout

```
up.sh / down.sh                one-shot install / delete
scripts/env.sh                 pinned versions and settings
scripts/00-tools.sh            prerequisite check + download CLIs into bin/
scripts/01..04-*.sh            cluster, ollama, kagent install (incl. Substrate), sample agents
scripts/chat.sh                A2A JSON-RPC client
scripts/approve.sh             approve/reject a paused tool call (HITL)
scripts/ui.sh                  port-forwards for UI and API
scripts/actors.sh              kubectl-ate view of Substrate
scripts/fanout-demo.sh         parallel-session density demo
scripts/after-restart.sh       recovery after node restart
cluster/kind-config.yaml       kind + Substrate feature gates
cluster/kagent-values.yaml     kagent Helm values (fed to `kagent install`)
manifests/                     Ollama and the sample agents (incl. the Claude Code agent)
docs/                          guides (Claude Code agent, two-subagent demo, LangGraph on Substrate)
ref/                           upstream kagent chart values, for reference
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `KAGENT_SEND_NOT_ACCEPTED` on every message | `./scripts/after-restart.sh` |
| `404 model '...' not found` in an old conversation | That conversation is pinned to an earlier agent revision whose model was removed; start a new one. |
| `chat.sh` connection refused | `./scripts/ui.sh` must be running (it holds the port-forward to :8083). |
| Replies are slow | CPU inference. Use a hosted model provider in `cluster/kagent-values.yaml`. |
