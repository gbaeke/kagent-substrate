# /// script
# requires-python = ">=3.12"
# dependencies = ["fastapi>=0.115", "uvicorn>=0.30", "httpx>=0.27"]
# ///
"""Mini dotties: a small UI for persistent personal agents that are nothing but kagent resources.

A dottie is a kagent Agent. This server keeps no state of its own:
  - dotties        -> Agent objects (kubectl), marked with the label dotties.dev/dottie
  - conversations  -> kagent Sessions, read through kagent's MCP gateway (/mcp)
  - chat           -> kagent's A2A gateway (/agents/<namespace>/<name>), streamed
  - asleep/awake   -> the state of the Session's actor on Agent Substrate (kubectl-ate)
  - schedules      -> kagent scheduled runs (ScheduledRunService, over gRPC-Web as kagent's own UI does)

Run it with scripts/dotties.sh.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from urllib.parse import unquote
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

NAMESPACE = os.environ.get("DOTTIES_NAMESPACE", "kagent")
KCTX = os.environ.get("KCTX", "kind-kagent-poc")
GATEWAY = os.environ.get("KAGENT_GATEWAY", "http://localhost:8083")  # A2A + MCP gateway of the kagent controller
PORT = int(os.environ.get("DOTTIES_PORT", "8300"))
HARNESS = "dottie"  # Go ADK runtime with long-term memory
HARNESS_PLAIN = "dottie-plain"  # the same without memory: the only kind kagent 1.0.0 can run on a schedule
WEB_POLICY = "dottie-web"
LABEL = "dotties.dev/dottie"
ANN = "dotties.dev/"  # annotation prefix: emoji, personality, toolkits, approval
HITL = "https://kagent.dev/extensions/hitl/v1"
STATIC = Path(__file__).parent / "static"

K8S_TOOLS = ["k8s_get_resources", "k8s_describe_resource", "k8s_get_pod_logs", "k8s_get_events"]
TOOLKITS = {
    "messaging": "Write to other dotties (kagent's MCP gateway: list_agents, invoke_agent)",
    "web": f"Reach the sites allowed by the {WEB_POLICY} egress policy from its shell",
    "kubernetes": "Look at this cluster, read-only (kagent's built-in tool server)",
}


# --- the cluster ------------------------------------------------------------------------------------------------------


async def run(*cmd: str, stdin: str | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(stdin.encode() if stdin is not None else None)
    if proc.returncode != 0:
        raise HTTPException(502, err.decode().strip() or f"{cmd[0]} failed")
    return out.decode()


async def kubectl(*args: str, stdin: str | None = None) -> str:
    return await run("kubectl", "--context", KCTX, "-n", NAMESPACE, *args, stdin=stdin)


async def mcp(tool: str, arguments: dict[str, Any], timeout: float = 600) -> dict[str, Any]:
    """Call one tool on kagent's stateless MCP endpoint."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    headers = {"Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{GATEWAY}/mcp", json=body, headers=headers)
    resp.raise_for_status()
    payload = next((json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")), None)
    if payload is None:
        payload = resp.json()
    if "error" in payload:
        raise HTTPException(502, payload["error"].get("message", "MCP error"))
    result = payload["result"]
    if result.get("isError"):
        raise HTTPException(502, " ".join(c.get("text", "") for c in result.get("content", [])))
    return result.get("structuredContent") or {}


_actors: tuple[float, dict[str, str]] = (0.0, {})


async def actor_states() -> dict[str, str]:
    """Session id -> actor state (RUNNING, SUSPENDED, ...), straight from Agent Substrate."""
    global _actors
    if time.monotonic() - _actors[0] < 1.5:
        return _actors[1]
    try:
        raw = await run("kubectl-ate", "--context", KCTX, "get", "actors", "-a", NAMESPACE, "-o", "json")
        states = {
            a["metadata"]["name"].removeprefix("session-"): a["status"]["state"].removeprefix("ACTOR_STATE_")
            for a in json.loads(raw).get("actors", [])
        }
    except (HTTPException, ValueError, KeyError):
        states = _actors[1]
    _actors = (time.monotonic(), states)
    return states


# --- a dottie is an Agent ---------------------------------------------------------------------------------------------


class NewDottie(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,30}$")
    emoji: str = "🟣"
    role: str = Field(default="", max_length=120)
    personality: str = Field(min_length=1, max_length=4000)
    model: str = "default-model-config"
    toolkits: list[str] = []
    approval: bool = False
    memory: bool = True


def system_prompt(d: NewDottie) -> str:
    lines = [
        f"You are {d.name}, a dottie: a small personal agent that sleeps until someone writes to it.",
        "",
        d.personality.strip(),
        "",
        "How you work:",
        "- Keep answers short and to the point. Use your tools instead of guessing.",
        "- You have a shell (the bash tool) on Alpine Linux in your own sandbox. Files in /data/workspace last for"
        " this conversation. There is no curl, python or sudo, and nothing can be installed.",
    ]
    if d.memory:
        lines.append(
            "- Memory: call save_memory for facts worth keeping about the user or your work (preferences, names,"
            " decisions). Memory is shared by all your conversations; load_memory searches it."
        )
    else:
        lines.append("- You have no long-term memory: each conversation starts fresh.")
    if "web" in d.toolkits:
        lines.append(
            "- Web: use `wget -qO- -T 15 <url>` in the shell. Only a few sites are allowed (en.wikipedia.org,"
            " api.github.com, wttr.in); everything else is blocked, so say so instead of retrying."
        )
    else:
        lines.append("- Your sandbox has no internet access.")
    if "messaging" in d.toolkits:
        lines.append(
            f'- Other dotties: list_agents with {{"namespace": "{NAMESPACE}"}} shows who exists. To write to one,'
            f' call invoke_agent with {{"agent": {{"namespace": "{NAMESPACE}", "name": "<name>"}}, "message": "..."}};'
            " the result has their reply in `text` and a `session_id` you can pass (instead of agent) to continue."
        )
    if "kubernetes" in d.toolkits:
        lines.append("- Kubernetes: you can read this cluster with the k8s_* tools. You cannot change it.")
    return "\n".join(lines)


def manifest(d: NewDottie) -> dict[str, Any]:
    tools: list[dict[str, Any]] = []
    if "messaging" in d.toolkits:
        tools.append({"server": {"kind": "RemoteMCPServer", "name": "kagent-api"}, "tools": ["list_agents", "invoke_agent"]})
    if "kubernetes" in d.toolkits:
        tools.append({"server": {"kind": "RemoteMCPServer", "name": "kagent-tool-server"}, "tools": K8S_TOOLS})
    for t in tools:
        if d.approval:
            t["requireApproval"] = True  # kagent pauses the task and asks the user (human-in-the-loop)
    inline: dict[str, Any] = {
        "description": d.role or f"{d.name}, a dottie",
        "modelConfig": {"name": d.model},
        "systemPrompt": system_prompt(d),
    }
    if tools:
        inline["tools"] = [{"mcp": t} for t in tools]
    spec: dict[str, Any] = {"template": {"inline": inline}, "harnessRef": {"name": HARNESS if d.memory else HARNESS_PLAIN}}
    if "web" in d.toolkits:
        spec["egressPolicyRefs"] = [{"name": WEB_POLICY}]
    return {
        "apiVersion": "api.kagent.dev/v1alpha3",
        "kind": "Agent",
        "metadata": {
            "name": d.name,
            "namespace": NAMESPACE,
            "labels": {LABEL: "true"},
            "annotations": {
                ANN + "emoji": d.emoji,
                ANN + "personality": d.personality.strip(),
                ANN + "toolkits": ",".join(d.toolkits),
                ANN + "approval": str(d.approval).lower(),
                ANN + "memory": str(d.memory).lower(),
            },
        },
        "spec": spec,
    }


def view(agent: dict[str, Any], states: dict[str, str], sessions: list[dict[str, Any]]) -> dict[str, Any]:
    meta, ann = agent["metadata"], agent["metadata"].get("annotations", {})
    inline = agent["spec"]["template"].get("inline", {})
    conditions = {c["type"]: c for c in agent.get("status", {}).get("conditions", [])}
    ready = conditions.get("Ready", {})
    mine = [s for s in sessions if s["agent"] == f"{NAMESPACE}/{meta['name']}"]
    awake = sum(1 for s in mine if states.get(s["id"]) not in (None, "SUSPENDED"))
    return {
        "name": meta["name"],
        "emoji": ann.get(ANN + "emoji", "🟣"),
        "role": inline.get("description", ""),
        "personality": ann.get(ANN + "personality", ""),
        "model": inline.get("modelConfig", {}).get("name", ""),
        "toolkits": [t for t in ann.get(ANN + "toolkits", "").split(",") if t],
        "approval": ann.get(ANN + "approval") == "true",
        "memory": agent["spec"]["harnessRef"]["name"] == HARNESS,
        "ready": ready.get("status") == "True",
        "status": ready.get("message") or "Preparing",
        "awake": awake > 0,
        "conversations": len(mine),
        "last_active": max((s["updated_at"] for s in mine), default=None),
        "created": meta["creationTimestamp"],
    }


async def get_agents() -> list[dict[str, Any]]:
    return json.loads(await kubectl("get", "agents.api.kagent.dev", "-l", f"{LABEL}=true", "-o", "json"))["items"]


async def get_agent(name: str) -> dict[str, Any]:
    agent = json.loads(await kubectl("get", "agents.api.kagent.dev", name, "-o", "json", "--ignore-not-found") or "null")
    if not agent or agent["metadata"].get("labels", {}).get(LABEL) != "true":
        raise HTTPException(404, "No such dottie")
    return agent


async def list_sessions(agent: str | None = None) -> list[dict[str, Any]]:
    args: dict[str, Any] = {"all_states": True, "page_size": 100}
    if agent:
        args["agent"] = {"namespace": NAMESPACE, "name": agent}
    sessions: list[dict[str, Any]] = []
    while True:
        page = await mcp("list_sessions", args, timeout=20)
        sessions += page.get("sessions") or []
        if not page.get("next_page_token"):
            return sessions
        args["page_token"] = page["next_page_token"]


# --- schedules: kagent's scheduled runs -------------------------------------------------------------------------------
# kagent stores and fires schedules itself (ScheduledRunService). That API is gRPC only: it is not in the MCP
# gateway or the CLI. The controller also serves gRPC-Web under /api, which is what kagent's own UI calls, so a
# few lines of protobuf wire format do the job without a generated client. Field numbers are those of
# proto/kagent/api/v1/scheduled_runs.proto in the kagent repository.


def _varint(n: int) -> bytes:
    out = bytearray()
    while n > 0x7F:
        out.append(n & 0x7F | 0x80)
        n >>= 7
    return bytes(out + bytes([n]))


def pb(*fields: tuple[int, str | bytes | bool | int | None]) -> bytes:
    """Encode (field number, value) pairs: text and nested messages length-delimited, numbers as varints."""
    out = b""
    for number, value in fields:
        if value is None or value == "" or value is False:
            continue
        if isinstance(value, (bool, int)):
            out += _varint(number << 3) + _varint(int(value))
        else:
            data = value.encode() if isinstance(value, str) else value
            out += _varint(number << 3 | 2) + _varint(len(data)) + data
    return out


def pb_read(buf: bytes) -> dict[int, list[Any]]:
    """Decode one message into {field number: [values]}; nested messages stay bytes for another pb_read."""
    fields: dict[int, list[Any]] = {}
    i = 0

    def varint() -> int:
        nonlocal i
        shift = n = 0
        while True:
            byte = buf[i]
            i += 1
            n |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                return n

    while i < len(buf):
        key = varint()
        number, wire = key >> 3, key & 7
        if wire == 0:
            value: Any = varint()
        elif wire == 2:
            size = varint()
            value = buf[i : i + size]
            i += size
        else:  # fixed 64 or 32 bit: not used by this API, skipped
            size = 8 if wire == 1 else 4
            value = buf[i : i + size]
            i += size
        fields.setdefault(number, []).append(value)
    return fields


def _text(msg: dict[int, list[Any]], number: int) -> str:
    return msg[number][0].decode() if number in msg else ""


def _time(msg: dict[int, list[Any]], number: int) -> str | None:
    if number not in msg:
        return None
    seconds = pb_read(msg[number][0]).get(1, [0])[0]
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds")


async def schedule_rpc(method: str, request: bytes) -> dict[int, list[Any]]:
    frame = b"\x00" + len(request).to_bytes(4, "big") + request
    headers = {"Content-Type": "application/grpc-web+proto", "X-Grpc-Web": "1"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{GATEWAY}/api/kagent.api.v1.ScheduledRunService/{method}", content=frame, headers=headers)
    resp.raise_for_status()
    status, detail, message, raw, i = resp.headers.get("grpc-status"), resp.headers.get("grpc-message", ""), b"", resp.content, 0
    while i + 5 <= len(raw):
        flag, size = raw[i], int.from_bytes(raw[i + 1 : i + 5], "big")
        body = raw[i + 5 : i + 5 + size]
        i += 5 + size
        if flag & 0x80:  # the trailers frame carries the gRPC status
            trailers = dict(line.split(":", 1) for line in body.decode().strip().split("\r\n") if ":" in line)
            status, detail = trailers.get("grpc-status", status), trailers.get("grpc-message", detail)
        else:
            message = body
    if (status or "0").strip() != "0":
        raise HTTPException(502, unquote(detail.strip()) or f"kagent {method} failed")
    return pb_read(message)


EXECUTION_STATES = {1: "pending", 2: "running", 3: "succeeded", 4: "failed", 5: "timed out"}


def schedule_view(raw: bytes) -> dict[str, Any]:
    run = pb_read(raw)
    agent, config = pb_read(run[11][0]), pb_read(run[5][0])
    return {
        "id": _text(run, 1),
        "agent": f"{_text(agent, 1)}/{_text(agent, 2)}",
        "name": _text(config, 1),
        "cron": _text(config, 2),
        "time_zone": _text(config, 3) or "UTC",
        "prompt": _text(config, 4),
        "paused": bool(config.get(5, [0])[0]),
        "next": _time(run, 7),
    }


async def list_schedules(agent: str | None = None) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    token = ""
    while True:
        page = await schedule_rpc("ListScheduledRuns", pb((1, pb((1, 100), (2, token)))))
        runs += [schedule_view(r) for r in page.get(1, [])]
        token = _text(pb_read(page[2][0]), 1) if 2 in page else ""
        if not token:
            break
    return [r for r in runs if agent is None or r["agent"] == f"{NAMESPACE}/{agent}"]


async def last_execution(schedule_id: str) -> dict[str, Any] | None:
    page = await schedule_rpc("ListScheduledRunExecutions", pb((1, schedule_id), (2, pb((1, 50)))))
    runs = []
    for raw in page.get(1, []):
        e = pb_read(raw)
        runs.append({
            "at": _time(e, 7), "state": EXECUTION_STATES.get(e.get(10, [0])[0], "unknown"), "session_id": _text(e, 9),
            "manual": 5 in e, "failure": _text(e, 13),
        })
    if not runs:
        return None
    last = max(runs, key=lambda r: r["at"] or "")
    last["runs"] = len(runs)
    if last["session_id"] and last["state"] == "succeeded":
        with suppress(HTTPException):
            turns = (await mcp("get_session", {"session_id": last["session_id"], "last_turns": 1}, timeout=15)).get("turns") or []
            last["reply"] = (turns[-1].get("reply") or "")[:600] if turns else ""
    return last


class NewSchedule(BaseModel):
    cron: str = Field(min_length=1, max_length=256)
    prompt: str = Field(min_length=1, max_length=2000)
    time_zone: str = "UTC"


async def seed() -> None:
    """First run: create the sample dotties, so the page is not empty."""
    if await get_agents():
        return
    models = await kubectl("get", "modelconfigs.api.kagent.dev", "-o", "name")
    model = "claude-haiku" if "/claude-haiku" in models else "default-model-config"
    for sample in json.loads((Path(__file__).parent / "samples.json").read_text()):
        await kubectl("apply", "-f", "-", stdin=json.dumps(manifest(NewDottie(model=model, **sample))))


@asynccontextmanager
async def lifespan(_: FastAPI):
    with suppress(Exception):
        await seed()
    yield


app = FastAPI(title="Mini dotties", lifespan=lifespan)


# --- API --------------------------------------------------------------------------------------------------------------


@app.get("/api/meta")
async def meta() -> dict[str, Any]:
    models = json.loads(await kubectl("get", "modelconfigs.api.kagent.dev", "-o", "json"))["items"]
    return {
        "namespace": NAMESPACE,
        "toolkits": TOOLKITS,
        "models": [
            {"name": m["metadata"]["name"], "label": f"{m['spec'].get('provider', '')} · {m['spec']['model']}"}
            for m in models
            if "embed" not in m["spec"]["model"]
        ],
    }


@app.get("/api/dotties")
async def dotties() -> list[dict[str, Any]]:
    agents, states, sessions = await asyncio.gather(get_agents(), actor_states(), list_sessions())
    return sorted((view(a, states, sessions) for a in agents), key=lambda d: d["created"])


@app.post("/api/dotties", status_code=201)
async def create_dottie(d: NewDottie) -> dict[str, str]:
    unknown = set(d.toolkits) - set(TOOLKITS)
    if unknown:
        raise HTTPException(422, f"Unknown toolkits: {', '.join(sorted(unknown))}")
    if await kubectl("get", "agents.api.kagent.dev", d.name, "--ignore-not-found", "-o", "name"):
        raise HTTPException(409, f"An agent named {d.name} already exists")
    await kubectl("apply", "-f", "-", stdin=json.dumps(manifest(d)))
    return {"name": d.name}


@app.get("/api/dotties/{name}/manifest")
async def dottie_manifest(name: str) -> dict[str, Any]:
    agent = await get_agent(name)
    for key in ("managedFields", "resourceVersion", "uid", "generation", "creationTimestamp"):
        agent["metadata"].pop(key, None)
    agent["metadata"].get("annotations", {}).pop("kubectl.kubernetes.io/last-applied-configuration", None)
    agent.pop("status", None)
    return agent


@app.delete("/api/dotties/{name}", status_code=204)
async def delete_dottie(name: str) -> None:
    await get_agent(name)
    for s in await list_sessions(name):
        with suppress(HTTPException):
            await mcp("delete_session", {"session_id": s["id"]}, timeout=60)
    for run in await list_schedules(name):
        with suppress(HTTPException):
            await schedule_rpc("DeleteScheduledRun", pb((1, run["id"])))
    await kubectl("delete", "agents.api.kagent.dev", name)


@app.get("/api/dotties/{name}/conversations")
async def conversations(name: str) -> list[dict[str, Any]]:
    sessions, states = await asyncio.gather(list_sessions(name), actor_states())
    return sorted(
        ({"id": s["id"], "name": s.get("name") or "", "updated_at": s["updated_at"], "created_at": s["created_at"],
          "actor": states.get(s["id"], "NONE")} for s in sessions),
        key=lambda s: s["updated_at"], reverse=True,
    )


@app.get("/api/conversations/{session_id}")
async def conversation(session_id: str) -> dict[str, Any]:
    data = await mcp("get_session", {"session_id": session_id, "max_bytes": 400_000}, timeout=30)
    states = await actor_states()
    return {"id": session_id, "actor": states.get(session_id, "NONE"), "turns": data.get("turns") or []}


@app.delete("/api/conversations/{session_id}", status_code=204)
async def delete_conversation(session_id: str) -> None:
    await mcp("delete_session", {"session_id": session_id}, timeout=60)


@app.get("/api/dotties/{name}/schedules")
async def schedules(name: str) -> list[dict[str, Any]]:
    runs = await list_schedules(name)
    for run, last in zip(runs, await asyncio.gather(*(last_execution(r["id"]) for r in runs)), strict=True):
        run["last"] = last
    return runs


@app.post("/api/dotties/{name}/schedules", status_code=201)
async def add_schedule(name: str, s: NewSchedule) -> dict[str, Any]:
    await get_agent(name)
    config = pb((1, s.prompt[:80]), (2, s.cron), (3, s.time_zone), (4, s.prompt))
    request = pb((5, pb((1, NAMESPACE), (2, name))), (3, uuid.uuid4().hex), (4, config))
    return schedule_view((await schedule_rpc("CreateScheduledRun", request))[1][0])


async def own_schedule(name: str, sched_id: str) -> None:
    if not any(r["id"] == sched_id for r in await list_schedules(name)):
        raise HTTPException(404, "No such schedule")


@app.delete("/api/dotties/{name}/schedules/{sched_id}", status_code=204)
async def delete_schedule(name: str, sched_id: str) -> None:
    await own_schedule(name, sched_id)
    await schedule_rpc("DeleteScheduledRun", pb((1, sched_id)))


@app.post("/api/dotties/{name}/schedules/{sched_id}/run", status_code=202)
async def run_now(name: str, sched_id: str) -> dict[str, str]:
    await own_schedule(name, sched_id)
    await schedule_rpc("TriggerScheduledRun", pb((1, sched_id), (2, uuid.uuid4().hex)))
    return {"status": "started"}


# --- chat: kagent's A2A stream, reduced to the few events the page needs ----------------------------------------------


class Message(BaseModel):
    text: str = ""
    session_id: str | None = None
    # answering a tool approval request (human-in-the-loop)
    task_id: str | None = None
    approve: bool | None = None
    tools: list[dict[str, Any]] = []


def a2a_request(m: Message) -> dict[str, Any]:
    message: dict[str, Any] = {"messageId": f"m-{uuid.uuid4()}", "role": "ROLE_USER", "parts": [{"text": m.text}]}
    if m.session_id:
        message["contextId"] = m.session_id  # a kagent Session is the A2A context
    if m.task_id and m.approve is not None:
        message |= {
            "taskId": m.task_id,
            "parts": [{"text": "Approved." if m.approve else "Rejected."}],
            "extensions": [HITL],
            "metadata": {HITL: {"type": "tool_approval_response", "approvals": [{"id": t["id"], "approved": m.approve} for t in m.tools]}},
        }
    return {"jsonrpc": "2.0", "id": 1, "method": "SendStreamingMessage", "params": {"message": message}}


def simplify(event: dict[str, Any]) -> list[dict[str, Any]]:
    """One A2A stream event -> zero or more small events for the page."""
    if "error" in event:
        return [{"type": "error", "message": event["error"].get("message", "error")}]
    result = event.get("result", {})
    out: list[dict[str, Any]] = []
    if (art := result.get("artifactUpdate")) is not None:
        artifact, final = art["artifact"], art.get("lastChunk", False)
        for part in artifact.get("parts", []):
            if "text" in part:
                out.append({"type": "text", "id": artifact["artifactId"], "text": part["text"], "final": final})
            elif isinstance(data := part.get("data"), dict) and "args" in data:
                out.append({"type": "tool_call", "id": data.get("id"), "name": data.get("name"), "args": data["args"]})
            elif isinstance(data, dict) and "response" in data:
                out.append({"type": "tool_result", "id": data.get("id"), "name": data.get("name"), "result": data["response"]})
        usage = artifact.get("metadata", {}).get("kagent.dev/a2a/usage")
        if final and usage:
            out.append({"type": "usage", "tokens": usage.get("totalTokenCount")})
    status = (result.get("statusUpdate") or result.get("task") or {}).get("status")
    if status:
        src = result.get("statusUpdate") or result["task"]
        ev: dict[str, Any] = {"type": "state", "state": status["state"].removeprefix("TASK_STATE_"),
                              "session_id": src.get("contextId"), "task_id": src.get("taskId") or src.get("id")}
        msg = status.get("message") or {}
        hitl = msg.get("metadata", {}).get(HITL)
        if hitl and hitl.get("type") == "tool_approval_request":
            ev["approval"] = [{"id": t["id"], "name": t["name"], "args": t.get("args")} for t in hitl.get("tools", [])]
        elif ev["state"] == "FAILED":
            ev["message"] = " ".join(p.get("text", "") for p in msg.get("parts", []))
        out.append(ev)
    return out


@app.post("/api/dotties/{name}/messages")
async def send(name: str, m: Message) -> StreamingResponse:
    await get_agent(name)
    headers = {"A2A-Version": "1.0", "A2A-Extensions": HITL, "Accept": "text/event-stream"}

    async def stream():
        named = bool(m.session_id)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=10)) as client:
                async with client.stream("POST", f"{GATEWAY}/agents/{NAMESPACE}/{name}", json=a2a_request(m), headers=headers) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        for ev in simplify(json.loads(line[5:])):
                            if named is False and ev.get("session_id"):
                                named = True  # a new Session: name it after the first message
                                with suppress(Exception):
                                    await mcp("rename_session", {"session_id": ev["session_id"], "name": m.text.strip()[:60]}, timeout=10)
                            yield f"data: {json.dumps(ev)}\n\n"
        except httpx.HTTPError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': f'kagent gateway: {exc!r}'})}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    if not re.match(r"^[\w.-]+$", KCTX):
        raise SystemExit("bad KCTX")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
