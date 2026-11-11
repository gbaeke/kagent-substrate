# Mini dotties: persistent personal agents from kagent features only

A *dottie* is a small personal agent that sleeps almost all the time. It has a
personality, a few tools, a long-term memory and a computer of its own. It wakes
when you write to it, when a schedule is due or when another dottie writes to
it, does the work, answers and goes back to sleep.

This demo builds that idea out of what kagent 1.0 and Agent Substrate already
do, plus a small web page to talk to the dotties. The page keeps no state of
its own: delete its server and every dottie, conversation, memory and schedule
is still in kagent, and the schedules keep firing.

Tested with kagent 1.0.0 and Agent Substrate 1.0.0, on the local
`qwen3:4b-instruct` model.

## Run it

```bash
./up.sh                 # the cluster, if it is not up yet
scripts/dotties.sh      # keep running: http://localhost:8300
```

The first run creates three sample dotties: `scout` (web, messaging and
long-term memory), `muse` (no tools, no memory, so it can be scheduled) and
`ops` (reads the cluster, asks before every tool call).

The local model is slow and weak at tool use. To run dotties on Claude, store a
key first; `scripts/dotties.sh` then adds a `claude-haiku` ModelConfig that you
can pick when you create a dottie:

```bash
read -rs ANTHROPIC_API_KEY
kubectl -n kagent create secret generic kagent-anthropic --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"
```

## Which kagent feature carries what

| Dottie idea | kagent / Substrate feature | Where |
| --- | --- | --- |
| A dottie with a personality | an `Agent` with an inline template (system prompt, model, tools) | written by the page, see the About tab |
| Sleeps, wakes on a message | every conversation is a Substrate actor; kagent suspends it after each reply and resumes it on the next message | nothing to configure |
| Conversations | kagent Sessions | read through kagent's MCP gateway |
| Long-term memory | `spec.kagent.memory` on the `Harness`: the runtime gets `save_memory` and `load_memory`, and recalls across Sessions | `dotties/manifests/platform.yaml` |
| Its own computer | the built-in `bash` and file tools in the actor's gVisor sandbox, workspace `/data/workspace` | nothing to configure |
| Web access | an `EgressPolicy` the Agent references; everything else stays blocked | `dotties/manifests/platform.yaml` |
| Dotties writing to each other | kagent's own MCP gateway, registered by the chart as the `RemoteMCPServer` `kagent-api`: `list_agents` and `invoke_agent` | the messaging toolkit |
| Ask me first | `requireApproval` on a tool; kagent pauses the task until the user decides | the "Ask me first" option |
| Looking at the cluster | kagent's built-in tool server (`kagent-tool-server`), read-only tools | the kubernetes toolkit |
| Chat with streaming | kagent's A2A gateway, `SendStreamingMessage` | `dotties/app/server.py` |
| Schedules | kagent scheduled runs (`ScheduledRunService`): kagent stores and fires them, and its own UI lists them | the Schedules tab, see below |

## The pieces

```
dotties/manifests/platform.yaml   embedding ModelConfig, the dottie Harness (memory on), dottie-plain (memory off), the dottie-web EgressPolicy
dotties/manifests/anthropic.yaml  optional Claude ModelConfig
dotties/app/server.py             the page's server: about 500 lines, no database
dotties/app/samples.json          the three sample dotties
dotties/app/static/               the page (plain HTML, CSS and JavaScript, no build step)
scripts/dotties.sh                applies the manifests and runs the server
```

The server talks to four things:

- **`kubectl`** to create, list and delete the `Agent` objects. A dottie is an
  Agent with the label `dotties.dev/dottie`; its face and personality are
  annotations.
- **kagent's MCP gateway** (`http://localhost:8083/mcp`) for Sessions:
  `list_sessions`, `get_session`, `rename_session` and `delete_session`. It is
  the same endpoint the dotties use to write to each other.
- **kagent's A2A gateway** (`/agents/kagent/<name>`) for chat. The stream
  carries text, tool calls, tool results and approval requests; the server
  reduces them to a handful of small events for the page.

- **kagent's scheduled runs API** for schedules (see below).

Asleep or awake is the state of the Session's actor, read with `kubectl ate get
actors`.

## What a dottie looks like in the cluster

The About tab shows the live object. In short:

```yaml
apiVersion: api.kagent.dev/v1alpha3
kind: Agent
metadata:
  name: scout
  labels: {dotties.dev/dottie: "true"}
  annotations:
    dotties.dev/emoji: "🔭"
spec:
  harnessRef: {name: dottie}            # Go ADK runtime with long-term memory
  egressPolicyRefs: [{name: dottie-web}]
  template:
    inline:
      modelConfig: {name: default-model-config}
      systemPrompt: |
        You are scout, a dottie: ...
      tools:
      - mcp:
          server: {kind: RemoteMCPServer, name: kagent-api}
          tools: [list_agents, invoke_agent]
```

## Schedules

Schedules are kagent scheduled runs: a cron expression, a time zone and a
prompt, attached to an Agent. kagent stores them in its database and fires them
itself; every run starts a new Session. A schedule made in the dotties page
shows up under **Schedules** in the kagent UI, and the other way round.

The scheduled runs API is gRPC only. It is not a Kubernetes resource, and it is
not in the MCP gateway or the CLI. The controller also serves gRPC-Web under
`/api` (that is what kagent's own UI calls), so `server.py` speaks that with a
few lines of protobuf wire format instead of a generated client.

**Schedules and memory do not combine in kagent 1.0.0.** A scheduled run
reaches the agent without a caller identity, and long-term memory refuses to
work without one: the run fails with `preload memory search failed: memory
requires caller identity`. That is why memory is an option per dottie. A dottie
with memory uses the `dottie` Harness and cannot be scheduled; one without uses
`dottie-plain` and can. The page says so on the Schedules tab.

## Things we learned

- **Memory needs pgvector.** The dev PostgreSQL that `kagent install` deploys
  has no pgvector, and with memory on every run fails with `preload memory
  search failed`. The fix is in this repo's install: a PostgreSQL image with
  pgvector (`cluster/postgres-pgvector`, set through `bundledPostgresImage`)
  and `config.database.vectorEnabled: true` in `cluster/kagent-values.yaml`.
  The Debian-based `pgvector/pgvector` image does not work: the install runs
  PostgreSQL as uid 70, the Alpine image's postgres user.
- **Memory needs 768-dimension embeddings.** `nomic-embed-text` on the
  in-cluster Ollama fits.
- **Files belong to a conversation, memory to the dottie.** Each Session is its
  own actor with its own `/data/workspace`. What a dottie should know in every
  conversation has to go to memory.
- **The sandbox is bare.** The runtime image is Alpine with `wget` and `git`,
  no `curl`, `python` or package installs. The system prompt says so, otherwise
  a model wastes turns trying.
- **Egress is an allowlist of origins.** A dottie with the web toolkit reaches
  `en.wikipedia.org`, `api.github.com` and `wttr.in`; add origins in
  `platform.yaml`.
- **`invoke_agent` wants an object.** `{"agent": {"namespace": "kagent",
  "name": "muse"}}`, not a name. It returns the other agent's reply and a
  `session_id` to continue with. The system prompt spells this out.
- **Approval covers MCP tools only.** `requireApproval` is set per MCP server
  entry, so the built-in shell cannot ask first.
- **`list_sessions` pages at 100.**
- **Not everything kagent can do is a Kubernetes resource.** Scheduled runs
  exist only in the controller's API and database, so `kubectl api-resources`
  does not show them.

## What is left out on purpose

Compared with the full Dottie project: no sign-in or per-user ownership, no
wiki you can edit by hand (kagent memory is not browsable from here), no
Telegram, and no skills. Skills would be the next kagent feature to add: an
Agent can load them from git or an OCI image.
