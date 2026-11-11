# kagent + Agent Substrate local PoC

A local playground: kagent 1.0 on Agent Substrate in one kind cluster, with a few demos on top.
Start with README.md; each demo has a guide in docs/.

## Commands

```bash
./up.sh                    # kind cluster, in-cluster Ollama, kagent + Substrate, sample agents (idempotent)
./scripts/ui.sh            # port-forwards: kagent UI :8080 (UI_PORT to change), A2A/MCP/API :8083
./scripts/dotties.sh       # mini dotties UI on :8300 (needs uv); see docs/mini-dotties.md
./scripts/after-restart.sh # after a reboot or Docker restart
./down.sh                  # delete the cluster
source scripts/env.sh      # pinned versions; puts bin/ (kubectl, kubectl-ate, kagent, helm, kind) on PATH
```

There is no test suite. Verify a change by running it against the cluster:
`scripts/chat.sh "question"` for an agent, the page on :8300 for the dotties.
Lint the dotties server with `uvx ruff check dotties/app --select E,F,B --ignore E501`.

## Rules

- Always pass `--context "$KCTX"` (kind-kagent-poc) to kubectl and kubectl-ate. Other kind
  clusters may exist on the machine; never rely on the current context.
- Versions are pinned in scripts/env.sh. kagent and Substrate are a matched pair: take the
  Substrate version kagent pins in its go/go.mod.
- `kagent install` (scripts/03-kagent.sh) owns the install. Change Helm values in
  cluster/kagent-values.yaml and CLI settings in the config that script writes, not by hand in
  the cluster.
- Keep secrets out of the repo. Model keys go in a Kubernetes Secret (see manifests/claude-agent.yaml).

## Things that are easy to get wrong

- Not every kagent feature is a Kubernetes resource. Scheduled runs, Sessions, memory and
  sandboxes live in the controller's API and database. Before saying kagent lacks something,
  check the kagent UI, the MCP gateway's tool list (`POST :8083/mcp`, `tools/list`) and `proto/`
  in the kagent repository.
- The controller's API is gRPC. Over plain HTTP on :8083 it offers the A2A gateway
  (`/agents/<ns>/<name>`), the MCP gateway (`/mcp`) and gRPC-Web under `/api`. An unknown POST
  path answers 200 with an empty body, which looks like success and is not.
- kagent's long-term memory needs pgvector in its PostgreSQL and
  `config.database.vectorEnabled: true`. The image is built from cluster/postgres-pgvector; it
  must stay on the Alpine base, because the install runs PostgreSQL as uid 70.
- A scheduled run cannot use an agent whose Harness has memory on (kagent 1.0.0).
- A conversation is one Substrate actor and is pinned to the agent revision it started on.
  Files in /data/workspace belong to that conversation, not to the agent.
- Egress from an actor is denied unless an EgressPolicy allows the origin.
- Models go into the in-cluster Ollama with scripts/ollama-model.sh; `ollama pull` inside a kind
  pod can be very slow.
- The dotties server is started by scripts/dotties.sh through `uv run`. When stopping it with
  `pkill -f`, make sure the pattern does not also match your own shell command.

## Layout

See the Layout section of README.md. The dotties app is dotties/app/server.py (FastAPI, no
database) plus a plain HTML/CSS/JS page in dotties/app/static; there is no build step.
