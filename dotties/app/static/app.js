// Mini dotties: a thin page over kagent. All state lives in the cluster; this file only draws it.
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const state = { dotties: [], current: null, session: null, tab: "chat", busy: false, meta: null };

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let detail = res.statusText;
    try { const body = await res.json(); detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail); } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

const hue = (name) => [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const ago = (iso) => {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
};
const statusOf = (d) => (!d.ready ? "preparing" : d.awake || (state.busy && d.name === state.current) ? "awake" : "asleep");

// A small, safe markdown subset: code blocks, inline code, bold, lists, paragraphs.
function markdown(src) {
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  const inline = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  let html = "", list = null;
  const closeList = () => { if (list) { html += `</${list}>`; list = null; } };
  const blocks = src.split(/```/);
  blocks.forEach((block, i) => {
    if (i % 2) { closeList(); html += `<pre>${esc(block.replace(/^[a-z]*\n/, ""))}</pre>`; return; }
    for (const para of block.split(/\n{2,}/)) {
      for (const line of para.split("\n")) {
        const ul = line.match(/^\s*[-*] (.*)/), ol = line.match(/^\s*\d+[.)] (.*)/), h = line.match(/^#{1,4} (.*)/);
        if (ul || ol) {
          const kind = ul ? "ul" : "ol";
          if (list !== kind) { closeList(); html += `<${kind}>`; list = kind; }
          html += `<li>${inline((ul || ol)[1])}</li>`;
        } else if (line.trim()) {
          closeList();
          html += h ? `<p><b>${inline(h[1])}</b></p>` : `<p>${inline(line)}</p>`;
        }
      }
      closeList();
    }
  });
  return html;
}

// --- sidebar ----------------------------------------------------------------------------------------------------------

function avatar(d, large) {
  const a = el("div", `avatar ${large ? "lg " : ""}${{ awake: "awake", preparing: "pending", asleep: "" }[statusOf(d)]}`, d.emoji);
  a.style.setProperty("--hue", hue(d.name));
  return a;
}

function drawList() {
  const list = $("dottie-list");
  list.replaceChildren(...state.dotties.map((d) => {
    const b = el("button", `dottie${d.name === state.current ? " on" : ""}`);
    const meta = el("div", "meta");
    meta.append(el("b", null, d.name), el("span", null, `${statusOf(d)} · ${d.role || "a dottie"}`));
    b.append(avatar(d), meta);
    b.onclick = () => select(d.name);
    return b;
  }));
  if (!state.dotties.length) list.append(el("p", "foot", "No dotties yet."));
}

function drawHead() {
  const d = state.dotties.find((x) => x.name === state.current);
  $("empty").hidden = !!d;
  $("dottie").hidden = !d;
  if (!d) return;
  $("h-avatar").replaceWith(Object.assign(avatar(d, true), { id: "h-avatar" }));
  $("h-name").textContent = d.name;
  $("h-role").textContent = d.role;
  const s = statusOf(d);
  $("h-state").className = `pill ${s === "awake" ? "awake" : ""}`;
  $("h-state").textContent = s === "awake" ? "● awake" : s === "asleep" ? "asleep" : d.status;
}

async function refresh() {
  try { state.dotties = await api("/api/dotties"); } catch { return; }
  if (state.current && !state.dotties.some((d) => d.name === state.current)) { state.current = null; state.session = null; }
  drawList();
  drawHead();
}

async function select(name) {
  if (state.busy) return;
  state.current = name;
  state.session = null;
  location.hash = name;
  drawList();
  drawHead();
  $("messages").replaceChildren();
  showTab(state.tab);
  const convs = await loadConversations();
  if (convs.length) openConversation(convs[0].id); else greet();
}

function showTab(tab) {
  state.tab = tab;
  for (const b of document.querySelectorAll(".tabs button")) b.classList.toggle("on", b.dataset.tab === tab);
  for (const t of ["chat", "schedules", "about"]) $(`tab-${t}`).hidden = t !== tab;
  if (tab === "schedules") drawSchedules();
  if (tab === "about") drawAbout();
}
for (const b of document.querySelectorAll(".tabs button")) b.onclick = () => showTab(b.dataset.tab);

// --- conversations ----------------------------------------------------------------------------------------------------

async function loadConversations() {
  if (!state.current) return [];
  let convs = [];
  try { convs = await api(`/api/dotties/${state.current}/conversations`); } catch {}
  $("conv-list").replaceChildren(...convs.map((c) => {
    const b = el("button", `conv${c.id === state.session ? " on" : ""}`);
    const sub = el("span");
    const awake = c.actor !== "SUSPENDED" && c.actor !== "NONE";
    sub.append(el("i", `dot${awake ? " awake" : ""}`), `${awake ? "awake" : "asleep"} · ${ago(c.updated_at)}`);
    b.append(el("b", null, c.name || `Conversation ${c.id.slice(-6)}`), sub);
    b.title = `kagent Session ${c.id}\nSubstrate actor: ${c.actor}`;
    b.onclick = () => openConversation(c.id);
    return b;
  }));
  return convs;
}

function greet() {
  const d = state.dotties.find((x) => x.name === state.current);
  $("messages").replaceChildren(el("div", "note", d && !d.ready ? "Substrate is still preparing this dottie's snapshot…" : "New conversation. It is asleep; your message wakes it."));
}

async function openConversation(id) {
  if (state.busy) return;
  state.session = id;
  loadConversations();
  const box = $("messages");
  box.replaceChildren(el("div", "note", "Loading…"));
  try {
    const conv = await api(`/api/conversations/${id}`);
    if (state.session !== id) return;
    box.replaceChildren();
    for (const t of conv.turns) {
      if (t.user) box.append(el("div", "msg user", t.user));
      for (const call of t.tool_calls || []) box.append(toolChip(call.name, null, true));
      if (t.reply) box.append(agentBubble(t.reply));
      if (t.state && !["TASK_STATE_COMPLETED"].includes(t.state)) box.append(el("div", "note", t.state.replace("TASK_STATE_", "").toLowerCase().replace("_", " ")));
    }
    if (!conv.turns.length) greet();
  } catch (e) {
    box.replaceChildren(el("div", "note error", e.message));
  }
  box.scrollTop = box.scrollHeight;
}

$("new-conv").onclick = () => { if (state.busy) return; state.session = null; loadConversations(); greet(); $("input").focus(); };

// --- chat -------------------------------------------------------------------------------------------------------------

function agentBubble(text) {
  const b = el("div", "msg agent");
  b.innerHTML = markdown(text);
  return b;
}

function toolChip(name, args, done) {
  const d = el("details", "tool");
  const s = el("summary");
  s.append(done ? el("span", "ok", "✓") : el("span", "spin"), el("b", null, name));
  if (args) s.append(el("span", null, JSON.stringify(args).slice(0, 90)));
  d.append(s);
  if (args) d.append(el("pre", null, JSON.stringify(args, null, 2)));
  return d;
}

function scrollDown() { const box = $("messages"); box.scrollTop = box.scrollHeight; }

async function send(payload, userText) {
  if (state.busy || !state.current) return;
  state.busy = true;
  $("send").disabled = true;
  drawList(); drawHead();
  const box = $("messages");
  if (!state.session || box.querySelector(".note:only-child")) box.querySelector(".note:only-child")?.remove();
  if (userText) box.append(el("div", "msg user", userText));
  const note = el("div", "note");
  note.append(el("span", "spin"), el("span", null, "waking up…"));
  box.append(note);
  scrollDown();

  const bubbles = new Map(), chips = new Map();
  const place = (node) => { box.insertBefore(node, note); scrollDown(); };
  let failed = null;
  try {
    const res = await fetch(`/api/dotties/${state.current}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, session_id: state.session }) });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith("data:")) continue;
        const ev = JSON.parse(line.slice(5));
        if (ev.type === "text") {
          let b = bubbles.get(ev.id);
          if (!b) { b = { node: agentBubble(""), text: "" }; bubbles.set(ev.id, b); place(b.node); }
          b.text = ev.final ? ev.text : b.text + ev.text;
          if (b.text.trim()) b.node.innerHTML = markdown(b.text); else if (ev.final) b.node.remove();
          scrollDown();
        } else if (ev.type === "tool_call") {
          const chip = toolChip(ev.name, ev.args, false);
          chips.set(ev.id, chip); place(chip);
        } else if (ev.type === "tool_result") {
          const chip = chips.get(ev.id) || toolChip(ev.name, null, false);
          if (!chips.has(ev.id)) place(chip);
          const out = typeof ev.result === "string" ? ev.result : JSON.stringify(ev.result, null, 2);
          if (/requires confirmation/.test(out)) continue; // kagent's placeholder while it waits for approval
          const mark = chip.querySelector(".spin");
          if (mark) mark.replaceWith(el("span", "ok", "✓"));
          chip.append(el("pre", null, out.length > 4000 ? out.slice(0, 4000) + "\n…" : out));
        } else if (ev.type === "state") {
          if (ev.session_id && !state.session) { state.session = ev.session_id; loadConversations(); }
          const label = { SUBMITTED: "waking up…", WORKING: "working…", INPUT_REQUIRED: "waiting for you" }[ev.state];
          if (label) note.lastChild.textContent = label;
          if (ev.approval) place(approvalCard(ev));
          if (ev.state === "FAILED") failed = ev.message || "The run failed.";
        } else if (ev.type === "error") {
          failed = ev.message;
        }
      }
    }
  } catch (e) {
    failed = e.message;
  }
  note.remove();
  for (const chip of chips.values()) chip.querySelector(".spin")?.replaceWith(el("span", null, "•"));
  if (failed) box.append(el("div", "note error", failed));
  state.busy = false;
  $("send").disabled = false;
  scrollDown();
  refresh();
  loadConversations();
}

function approvalCard(ev) {
  const card = el("div", "approval");
  card.append(el("b", null, "Approval needed"), el("div", "muted small", "kagent paused this task until you decide."));
  for (const t of ev.approval) card.append(el("pre", null, `${t.name} ${JSON.stringify(t.args ?? {}, null, 2)}`));
  const actions = el("div", "actions");
  const decide = (approve) => {
    actions.replaceChildren(el("span", "muted small", approve ? "Approved" : "Rejected"));
    send({ task_id: ev.task_id, approve, tools: ev.approval }, null);
  };
  const yes = el("button", "btn primary sm", "Approve"), no = el("button", "btn ghost sm", "Reject");
  yes.onclick = () => decide(true); no.onclick = () => decide(false);
  actions.append(yes, no);
  card.append(actions);
  return card;
}

$("composer").onsubmit = (e) => {
  e.preventDefault();
  const input = $("input"), text = input.value.trim();
  if (!text || state.busy) return;
  input.value = ""; input.style.height = "auto";
  send({ text }, text);
};
$("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); } });
$("input").addEventListener("input", (e) => { e.target.style.height = "auto"; e.target.style.height = `${e.target.scrollHeight}px`; });

// --- schedules --------------------------------------------------------------------------------------------------------

async function drawSchedules() {
  const name = state.current;
  if (!name) return;
  const d = state.dotties.find((x) => x.name === name);
  $("sched-blocked").hidden = !d?.memory;
  $("sched-form").hidden = !!d?.memory;
  let runs;
  try { runs = await api(`/api/dotties/${name}/schedules`); } catch (e) { $("sched-list").replaceChildren(el("p", "error", e.message)); return; }
  if (name !== state.current || state.tab !== "schedules") return;
  const list = $("sched-list");
  list.replaceChildren(...runs.map((s) => {
    const row = el("div", "sched");
    const main = el("div");
    const next = s.paused ? "paused" : s.next ? `next ${new Date(s.next).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}` : "";
    main.append(el("b", null, s.prompt), el("div", "when", `cron ${s.cron} (${s.time_zone}) · ${next}`));
    const ops = el("div", "ops");
    const run = el("button", "btn ghost sm", "Run now"), del = el("button", "btn ghost sm", "Remove");
    run.onclick = async () => { run.disabled = true; try { await api(`/api/dotties/${name}/schedules/${s.id}/run`, { method: "POST" }); } catch (e) { alert(e.message); } drawSchedules(); };
    del.onclick = async () => { await api(`/api/dotties/${name}/schedules/${s.id}`, { method: "DELETE" }); drawSchedules(); };
    ops.append(run, del);
    row.append(main, ops);
    if (s.last) {
      const last = el("div", "last");
      const how = s.last.manual ? "run by hand" : "on schedule";
      last.textContent = `Last run ${ago(s.last.at)} (${how}) · ${s.last.state} · ${s.last.runs} run${s.last.runs === 1 ? "" : "s"} so far\n${s.last.failure || s.last.reply || ""}`;
      if (s.last.session_id) {
        const open = el("button", "btn ghost sm", "Open conversation");
        open.style.marginTop = "8px"; open.style.display = "block";
        open.onclick = () => { showTab("chat"); openConversation(s.last.session_id); };
        last.append(open);
      }
      row.append(last);
    }
    return row;
  }));
  if (!runs.length && !d?.memory) list.append(el("p", "muted", "No schedules yet."));
}

$("sched-preset").onchange = (e) => { $("sched-cron-wrap").hidden = e.target.value !== ""; };
$("sched-form").onsubmit = async (e) => {
  e.preventDefault();
  const cron = $("sched-preset").value || $("sched-cron").value.trim(), prompt = $("sched-prompt").value.trim();
  if (!cron || !prompt) return;
  try {
    const time_zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    await api(`/api/dotties/${state.current}/schedules`, { method: "POST", body: JSON.stringify({ cron, prompt, time_zone }) });
    $("sched-prompt").value = "";
    drawSchedules();
  } catch (err) { alert(err.message); }
};

// --- about ------------------------------------------------------------------------------------------------------------

async function drawAbout() {
  const d = state.dotties.find((x) => x.name === state.current);
  if (!d) return;
  const dl = $("about");
  const row = (k, v) => { const dd = el("dd"); if (v instanceof Node) dd.append(v); else dd.textContent = v; dl.append(el("dt", null, k), dd); };
  dl.replaceChildren();
  row("Personality", d.personality);
  row("Model", d.model);
  const kits = el("span");
  for (const k of ["shell", ...(d.memory ? ["memory"] : []), ...d.toolkits]) kits.append(el("span", "chip", k));
  row("Can do", kits);
  row("Approval", d.approval ? "Asks before messaging or Kubernetes tool calls" : "Acts on its own");
  row("Conversations", `${d.conversations} (kagent Sessions), last active ${ago(d.last_active)}`);
  row("Runtime", d.status);
  $("manifest").textContent = "…";
  try { $("manifest").textContent = JSON.stringify(await api(`/api/dotties/${d.name}/manifest`), null, 2); } catch (e) { $("manifest").textContent = e.message; }
}

$("delete").onclick = async () => {
  if (!confirm(`Delete ${state.current} and its conversations?`)) return;
  await api(`/api/dotties/${state.current}`, { method: "DELETE" });
  state.current = null; location.hash = "";
  refresh();
};

// --- new dottie -------------------------------------------------------------------------------------------------------

$("new-dottie").onclick = () => {
  $("f-model").replaceChildren(...state.meta.models.map((m) => Object.assign(el("option", null, `${m.name} (${m.label})`), { value: m.name })));
  const preferred = state.meta.models.find((m) => /anthropic/i.test(m.label));
  if (preferred) $("f-model").value = preferred.name;
  $("f-toolkits").replaceChildren(...Object.entries(state.meta.toolkits).map(([k, v]) => {
    const l = el("label", "check");
    const box = Object.assign(el("input"), { type: "checkbox", value: k, checked: k === "messaging" });
    const text = el("span"); text.append(el("b", null, k), el("small", null, v));
    l.append(box, text);
    return l;
  }));
  $("dlg-error").hidden = true;
  $("dlg").showModal();
};
$("dlg-cancel").onclick = () => $("dlg").close();
$("dlg-form").onsubmit = async (e) => {
  e.preventDefault();
  const body = {
    name: $("f-name").value.trim(), emoji: $("f-emoji").value.trim() || "🟣", role: $("f-role").value.trim(),
    personality: $("f-personality").value.trim(), model: $("f-model").value, approval: $("f-approval").checked, memory: $("f-memory").checked,
    toolkits: [...$("f-toolkits").querySelectorAll("input:checked")].map((i) => i.value),
  };
  $("dlg-create").disabled = true;
  try {
    await api("/api/dotties", { method: "POST", body: JSON.stringify(body) });
    $("dlg").close(); $("dlg-form").reset();
    await refresh();
    select(body.name);
  } catch (err) {
    $("dlg-error").textContent = err.message; $("dlg-error").hidden = false;
  }
  $("dlg-create").disabled = false;
};

window.addEventListener("hashchange", () => {
  const name = decodeURIComponent(location.hash.slice(1));
  if (name && name !== state.current && state.dotties.some((d) => d.name === name)) select(name);
});

// --- start ------------------------------------------------------------------------------------------------------------

(async () => {
  state.meta = await api("/api/meta");
  await refresh();
  const wanted = decodeURIComponent(location.hash.slice(1));
  const first = state.dotties.find((d) => d.name === wanted) || state.dotties[0];
  if (first) select(first.name);
  setInterval(() => { refresh(); if (!state.busy && state.tab === "chat") loadConversations(); if (state.tab === "schedules") drawSchedules(); }, 3000);
})();
