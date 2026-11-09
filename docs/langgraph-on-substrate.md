# Running a LangGraph agent on Agent Substrate

This guide runs a LangGraph agent directly on Agent Substrate, without kagent,
in its own kind cluster. It was tested end to end on 2026-11-08 with Agent
Substrate 1.0.0, Anthropic Python SDK 2.6.0 and `claude-haiku-5-5`: the agent
answered through Substrate's egress gateway, was suspended, and resumed with
its conversation intact.

Nothing in this repo deploys it. The commands below create a separate cluster
from a Substrate checkout.

## Which Substrate this is

kagent uses Agent Substrate from
[github.com/agent-substrate/substrate](https://github.com/agent-substrate/substrate)
(the old `kagent-dev/substrate` URL redirects there). Its docs are at
[ate.dev/docs](https://ate.dev/docs/). Google and Solo.io maintain it: 16 of
the 19 maintainers in `MAINTAINERS.md` work at Google, and 3 work at Solo.io,
the company that created kagent.

The Python library at agent-substrate.com (`pip install agent-substrate`) is a
different project with the same name. It has no Kubernetes parts.

kagent depends on Substrate. Substrate does not depend on kagent: any client
that creates actors through the Substrate API can use it.

## What Substrate does and what you do

An actor is a container that serves HTTP. Substrate runs it in a gVisor or
microVM sandbox on a worker pod, snapshots it on request, and restores it on
any free worker.

| Job | Who does it |
| --- | --- |
| Run the actor in a sandbox, snapshot it, restore it | Substrate |
| Resume a suspended actor when a request arrives at `atenet-router` | Substrate, automatically |
| Inject API keys into outbound requests, enforce the egress allowlist | Substrate's egress gateway |
| Create an actor per conversation (or per user, or one for all) | You |
| Route each request to the right actor (`ate-target-actor: <atespace>/<actor>`) | You |
| Suspend an idle actor | You. Substrate has no idle timeout |
| Delete an actor when the conversation ends | You |

kagent's controller does the "You" rows for kagent agents: each A2A `contextId`
becomes an actor, and kagent suspends it after every reply. Running LangGraph
directly means writing that layer yourself.

An actor that nobody suspends keeps its slot on a worker for good. How many
actors run at once depends on the pool's capacity (see step 4). Suspended
actors use no worker.

| Piece | Where it lives | Created with |
| --- | --- | --- |
| `WorkerPool` | Kubernetes CRD (`ate.dev/v1`) | `kubectl apply` |
| Atespace | Substrate API | `kubectl ate create atespace` |
| `ActorTemplate` | Substrate API | `kubectl ate create actor-template -f` |
| `Actor` | Substrate API | `kubectl ate create actor` |
| `EgressPolicy` | Substrate API, one per actor | `kubectl ate create egress-policy` |

Templates, atespaces and actors are not Kubernetes objects. `kubectl get` shows
only the worker pods. Use `kubectl ate get ...` for the rest.

## 1. Create the cluster and install Substrate

Needs Go 1.27, Docker and kubectl. `ate-setup` runs `ko` through `go tool`, so
`ko` does not need to be installed.

```bash
cd ~/Projects
git clone --branch v1.0.0 https://github.com/agent-substrate/substrate.git
cd substrate

hack/create-kind-cluster.sh            # cluster "kind", registry on localhost:5001
export ATE_INSTALL_KIND=true           # set again in every new shell
go run ./cmd/ate-setup deploy ate-system --credential-provider='{"name":"k8s.io"}' \
  --ingress-allowed-spiffe-ids=spiffe://cluster.local/ns/ate-system/sa/atenet-client
kubectl -n ate-system get pods         # all Running, incl. k8s-credential-provider
```

The install builds every image from source: 10 to 20 minutes the first time.

Install the `kubectl ate` plugin:

```bash
go install ./cmd/kubectl-ate
ln -s ~/go/bin/kubectl-ate ~/.local/bin/kubectl-ate
```

The symlink matters with mise: its shell hook rebuilds `PATH` at every prompt
and drops a hand-added `~/go/bin`, so `kubectl ate` reports "unknown command".

## 2. Smoke-test with the counter demo

The counter demo proves actors work. It also deploys a worker pool whose
worker image step 4 reuses.

```bash
go run ./cmd/ate-setup deploy demo counter
kubectl ate create actor my-counter-1 -a ate-demo-counter --template counter
kubectl ate proxy actor my-counter-1 -a ate-demo-counter 8123:80
curl -X POST http://localhost:8123/        # in a second tab; counters go up by 1
```

Use a free local port for `kubectl ate proxy`. The counter counts every request
on any path, so a local tool that polls the proxy's port (here a Claude Code
mod that probed `localhost:8000/api/health` every 10 seconds) inflates the
count.

## 3. Write the agent and build the image

```python
# app.py
import operator, os, ssl
from typing import Annotated, TypedDict

import anthropic
from fastapi import FastAPI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

CA_FILE = "/run/ate/egress-trust-bundle/trust-bundle.pem"
MODEL = os.environ.get("MODEL", "claude-haiku-5-5")

# The egress gateway replaces this placeholder key with the real one.
# It also terminates TLS, so the client must trust the gateway CA.
client = anthropic.Anthropic(
    api_key="placeholder",
    http_client=anthropic.DefaultHttpxClient(verify=ssl.create_default_context(cafile=CA_FILE)),
)

class State(TypedDict):
    messages: Annotated[list[dict], operator.add]

def call_model(state: State):
    resp = client.messages.create(model=MODEL, max_tokens=1024, messages=state["messages"])
    # The reply can start with a thinking block; keep only the text blocks.
    text = "".join(b.text for b in resp.content if b.type == "text")
    return {"messages": [{"role": "assistant", "content": text}]}

builder = StateGraph(State)
builder.add_node("model", call_model)
builder.add_edge(START, "model")
builder.add_edge("model", END)
graph = builder.compile(checkpointer=MemorySaver())

api = FastAPI()

@api.get("/readyz")
def ready():
    return "ok"

@api.post("/invoke")
def invoke(body: dict):
    cfg = {"configurable": {"thread_id": body.get("thread_id", "default")}}
    out = graph.invoke({"messages": [{"role": "user", "content": body["message"]}]}, cfg)
    return {"reply": out["messages"][-1]["content"], "turns": len(out["messages"])}
```

```dockerfile
FROM python:3.13-slim
RUN pip install --no-cache-dir fastapi uvicorn langgraph anthropic
WORKDIR /app
COPY app.py .
CMD ["uvicorn", "app:api", "--host", "0.0.0.0", "--port", "80"]
```

The history lives only in process memory (`MemorySaver`). That is deliberate:
if the history survives a suspend, the memory snapshot worked. For state that
must outlive a lower snapshot fidelity, use a `SqliteSaver` on a `durableDir`
volume.

```bash
docker build -t localhost:5001/langgraph-agent:v1 .
docker push localhost:5001/langgraph-agent:v1
docker inspect --format '{{index .RepoDigests 0}}' localhost:5001/langgraph-agent:v1
```

Reference the image by that digest. Substrate rewrites `localhost:5001` to the
registry's address inside kind.

## 4. Create a worker pool

```bash
WORKER_IMAGE=$(kubectl get workerpool counter -n ate-demo-counter -o jsonpath='{.spec.workerImage}')
```

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: lg-demo
---
apiVersion: ate.dev/v1
kind: WorkerPool
metadata:
  name: langgraph
  namespace: lg-demo
  labels:
    workload: langgraph
spec:
  replicas: 2              # one for the actor, one for building the golden snapshot
  workerImage: $WORKER_IMAGE
  sandboxClasses:
  - name: gvisor
  template:
    resources:
      limits: {cpu: "1", memory: 1Gi}
      requests: {cpu: 250m, memory: 1Gi}
```

Each worker pod runs Substrate's generic worker image, not your code. A worker
hosts several actors, each in its own sandbox, until its capacity runs out: each
actor books its template limits against the pool's limits, and the worker keeps
some memory for itself. With 1Gi workers and 512Mi actors, as here, expect one
actor per worker.

## 5. Create the atespace and the template

```yaml
# template.yaml
metadata:
  atespace: lg-demo
  name: langgraph
workerSelector:
  matchLabels:
    workload: langgraph
containers:
- name: agent
  image: localhost:5001/langgraph-agent@sha256:<digest>
  wakeupProbe:
    httpGet: {path: /readyz, port: 80}
    timeoutSeconds: 120
  volumeMounts:
  - name: system-info
    mountPath: /run/ate/egress-trust-bundle
volumes:
- name: system-info
  systemInfo:
    dataSources:
    - trustBundle:
        names: [egress-mitm.ate.dev, system-roots.ate.dev]
        path: trust-bundle.pem
resources:
  limits:
    cpuMillicores: 1000
    memoryBytes: 536870912
snapshotConfig:
  preferredFidelity: SNAPSHOT_FIDELITY_MEMORY
```

```bash
kubectl ate create atespace lg-demo
kubectl ate create actor-template -f template.yaml
kubectl ate get actor-templates -a lg-demo     # ready when GOLDEN TAG is filled
```

Creating the template starts the app once and snapshots it after `/readyz`
answers. The default probe timeout is 30 seconds. If the app crashes at
startup, the template shows `ERROR` with `GoldenActorCrashed ... connection
refused`. The Python traceback is in the worker pod's logs:
`kubectl -n lg-demo logs <worker-pod> --all-containers`.

A template cannot be changed in place. To ship a new image, delete its actors
and the template, then create both again.

## 6. Store the key and allow the atespace to read it

```bash
kubectl create namespace lg-secrets
printf '%s' "$ANTHROPIC_API_KEY" | \
  kubectl -n lg-secrets create secret generic anthropic --from-file=api-key=/dev/stdin

kubectl -n ate-system patch configmap k8s-credential-provider-namespace-policy --type merge \
  -p '{"data":{"namespace-policy.yaml":"policies:\n- atespace: lg-demo\n  allowedNamespaces:\n  - lg-secrets\n"}}'
kubectl -n ate-system rollout restart deployment/k8s-credential-provider
```

The provider grants no atespace anything by default and reads the policy only
at startup, hence the restart.

## 7. Create an actor and its egress policy

```yaml
# policy.yaml
rules:
- https:
    hostnames: ["api.anthropic.com"]
    effects:
      replaceHeaders:
      # Anthropic SDK 2.x sends the key as "Authorization: Bearer <key>".
      - header: Authorization
        prefix: "Bearer "
        credentialUri: ate-secret://k8s.io/default/lg-secrets/anthropic/api-key
```

```bash
kubectl ate create actor conv-1 -a lg-demo --template langgraph
kubectl ate create egress-policy conv-1 -a lg-demo -f policy.yaml
kubectl ate proxy actor conv-1 -a lg-demo 8123:80
```

In a second tab:

```bash
curl -s -X POST localhost:8123/invoke -H 'content-type: application/json' \
  -d '{"message":"Hi, my name is Geert. Remember that."}'
curl -s -X POST localhost:8123/invoke -H 'content-type: application/json' \
  -d '{"message":"What is my name?"}'
```

## 8. Suspend and resume

```bash
kubectl ate suspend actor conv-1 -a lg-demo
kubectl ate get actors -a lg-demo              # SUSPENDED, no worker pod
curl -s -X POST localhost:8123/invoke -H 'content-type: application/json' \
  -d '{"message":"What is my name again?"}'    # still knows; turns keeps counting
kubectl ate get actors -a lg-demo              # RUNNING, maybe on the other worker
```

The request through the router resumes the actor. The conversation comes back
from the memory snapshot.

## Errors we hit, and the fixes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Template `ERROR`, `GoldenActorCrashed`, probe "connection refused" | `TypeError: ... this SDK uses httpx2`: Anthropic SDK 2.x rejects a plain `httpx.Client` | Pass `anthropic.DefaultHttpxClient(verify=...)` |
| `401 Invalid bearer token` from Anthropic | The policy replaced `x-api-key`, but SDK 2.x sends `Authorization: Bearer placeholder` | Replace `Authorization` with prefix `"Bearer "` |
| `500`, `'ThinkingBlock' object has no attribute 'text'` | The model's reply started with a thinking block | Join the text blocks; never assume `content[0]` is text |
| `kubectl ate`: unknown command | `~/go/bin` not on `PATH` (mise rewrites it) | Symlink `kubectl-ate` into `~/.local/bin` |
| Counter far higher than the requests sent | A local tool polled the proxy port | Proxy on a free port, such as `8123:80` |

Other rules that break a first attempt:

- **Egress is denied by default.** An actor without an egress policy cannot
  resolve any name: DNS answers `NXDOMAIN`. Every outbound host needs a rule,
  including LangSmith and OpenTelemetry exporters.
- **The actor must trust the gateway CA.** An `https` rule makes the gateway
  terminate the actor's TLS so it can inject the key. The `systemInfo` volume
  puts the gateway CA and public roots in one file. Point the HTTP client at it
  explicitly, as `app.py` does.
- **WebSocket and CONNECT are blocked** by the egress gateway. Plain HTTP(S)
  works.

## Tear down

```bash
cd ~/Projects/substrate && ./hack/delete-kind-cluster.sh
```

The script removes the registry container only if Substrate's script created
it.

## Source docs

All in the Substrate repo under `docs/`:

- `get-started/quickstart.md` and `demos/counter/` for the install and a full
  worked actor
- `concepts/architecture.md` for the actor lifecycle and router
- `reference/resource-model.md` and `reference/kubectl-ate.md`
- `guides/egress-traffic.md`, `guides/egress-trust-bundle.md` and
  `guides/egress-credential-injection.md`
