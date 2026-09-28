# kagent + Agent Substrate — local PoC

A one-command local playground for [kagent](https://github.com/kagent-dev/kagent) 1.0
running its agents as sandboxed, suspend/resume actors on
[Agent Substrate](https://github.com/kagent-dev/substrate). Everything runs in a
single [kind](https://kind.sigs.k8s.io/) cluster in Docker, including the LLM
(Ollama, CPU), so **no API keys** are needed and nothing is exposed on your host.

> Pre-release software. kagent 1.0 and Substrate 0.3 are alphas that change
> almost daily; this repo pins a known-good pair. Not for production.

## Prerequisites

| Need | Notes |
| --- | --- |
| Linux x86_64 or arm64 | Tested on Linux x86_64. macOS/Docker Desktop is untested (gVisor snapshotting is reported to be flaky there). |
| Docker, running | Your user must be able to run `docker` without sudo. |
| `curl`, `jq`, `openssl`, `tar` | Checked by `scripts/00-tools.sh`. |
| ~8 GB free RAM, 4+ cores | The cluster idles at about 7 GB. More cores = faster CPU inference. |
| ~25 GB free disk | Images plus the 2.5 GB model. |
| Internet access | Pulls charts from ghcr.io, images, and the model. |

`kind`, `kubectl`, `helm` and `kubectl-ate` are downloaded automatically into
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
| kagent | 1.0.0-alpha5 |
| Agent Substrate | 0.3.0-alpha1 (the version kagent 1.0.0-alpha5 pins) |
| Kubernetes | kind v0.33.0, node v1.35.0 |
| Model | `qwen3:4b-instruct` on in-cluster Ollama |

- **Substrate** (`ate-system`): API server, controller, atelet, router, egress
  proxy, Postgres, RustFS (S3 bucket for snapshots).
- **kagent** (`kagent`): controller (A2A gateway), UI, Postgres, MCP tool server,
  and a WorkerPool of 2 pre-warmed gVisor worker pods.
- **Two sample agents**:
  - `k8s-helper`: read-only Kubernetes assistant with MCP tools (inline template + harness).
  - `haiku-poet`: shows the reusable `Harness` + `AgentTemplate` split.

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

In the UI, the **Substrate** page shows worker pools, templates and live actor
states; **Agents** lets you create agents, templates and harnesses.

## After a reboot or Docker restart

```bash
./scripts/after-restart.sh
```

The worker pods come back with stale actor networking and every message fails
with `KAGENT_SEND_NOT_ACCEPTED` until they are recycled. This script recycles
them and reverts any actor that crashed in the meantime.

## Configuration

Edit `scripts/env.sh` (versions, cluster name, worker count) and
`cluster/kagent-values.yaml` (model provider, model, Helm values).

- **Different Ollama model**: `kubectl -n ollama exec deploy/ollama -- ollama pull <model>`,
  set `providers.ollama.model` in `cluster/kagent-values.yaml`, re-run `scripts/04-kagent.sh`.
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
scripts/01..05-*.sh            cluster, substrate, ollama, kagent, sample agents
scripts/chat.sh                A2A JSON-RPC client
scripts/ui.sh                  port-forwards for UI and API
scripts/actors.sh              kubectl-ate view of Substrate
scripts/fanout-demo.sh         parallel-session density demo
scripts/after-restart.sh       recovery after node restart
cluster/kind-config.yaml       kind + Substrate feature gates
cluster/kagent-values.yaml     kagent Helm values
manifests/                     Ollama and the sample agents
ref/                           upstream kagent chart values, for reference
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `KAGENT_SEND_NOT_ACCEPTED` on every message | `./scripts/after-restart.sh` |
| `404 model '...' not found` in an old conversation | That conversation is pinned to an earlier agent revision whose model was removed; start a new one. |
| kagent controller restarts a few times on first install | Postgres startup race; it settles by itself. |
| `chat.sh` connection refused | `./scripts/ui.sh` must be running (it holds the port-forward to :8083). |
| Replies are slow | CPU inference. Use a hosted model provider in `cluster/kagent-values.yaml`. |
