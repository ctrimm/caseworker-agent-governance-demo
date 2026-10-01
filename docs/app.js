// Plays back docs/traces.js (real runs exported by export_traces.py). No gate logic lives here.
(function () {
  "use strict";
  const T = window.TRACES;

  const SCENARIOS = [
    ["injection", "Injection", "Controls live outside the model",
      "Instructions hidden in the case notes talk the (scripted) model into trying approve_payout, a read of another client's case, and write_record. The gate denies all three. The real job still finishes."],
    ["happy", "Happy path", "Humans at the irreversible step",
      "Read, calculate, draft. The draft waits on a caseworker's approval before it runs."],
    ["messy", "Messy data", "Design for missing data",
      "Income is missing from the case file. The agent hands the case back instead of guessing."],
    ["loop", "Runaway loop", "Bounded budgets",
      "A model stuck re-reading the same file hits the agent file's model-call limit and is halted."],
    ["killswitch", "Kill switch", "Tested kill switch",
      "An operator halts the run after the first step. The next check stops everything."],
    ["failclosed", "Fail closed", "Fail closed",
      "The agent file marks its PII policy required: true. With that policy file missing, the runtime refuses to start the agent at all."],
    ["redherring", "Red herring test", "Test your oversight",
      "A simulated queue of 200 drafts, 5% seeded with known-wrong answers. Two reviewers approve at similar rates but catch very different numbers of errors. The reviewer models are assumptions, not data about real people."],
  ];
  const META = Object.fromEntries(SCENARIOS.map(([k, label, lesson, desc]) => [k, { label, lesson, desc }]));

  // Where each gate rule comes from, for the advanced view.
  const SOURCE = {
    "kill-switch": "runtime (operator)",
    "budget.max_duration_seconds": "agent file: constraints.budget",
    "limits.max_llm_calls": "agent file: constraints.limits",
    "limits.max_tool_calls": "agent file: constraints.limits",
    "default-deny": "agent file: action_space",
    "org.deny_tools": "policy/org-baseline.yaml",
    "org.scope": "policy/org-baseline.yaml",
    "approval": "agent file approval + org approval_tools",
    "allow-listed": "result",
  };
  const VERDICT = { allow: "ALLOW", deny: "DENY", require_approval: "HOLD", halt: "HALT", pass: "pass" };

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtArgs = (a) => Object.entries(a || {}).map(([k, v]) => `${k}=${v}`).join(", ");
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
  };

  const state = { key: "injection", reviewer: "approve", frames: [], i: 0, timer: null, fileTab: 0,
    advanced: store.get("govdemo.advanced") === "1" };

  // ---------------------------------------------------------------- frames
  // Each trace step becomes a few frames: propose, decide, (human), (run).

  function framesFor(t) {
    const F = [{ kind: "intro", step: null }];
    if (!t.startup.ok) {
      F.push({ kind: "startup", step: null }, { kind: "refused", step: null }, { kind: "end", step: null });
      return F;
    }
    F.push({ kind: "startup", step: null });
    for (const s of t.steps) {
      if (s.gate) {
        F.push({ kind: "propose", step: s }, { kind: "decide", step: s });
        if (s.human) F.push({ kind: "human", step: s });
        if (s.result !== undefined) F.push({ kind: "run", step: s });
      } else if (s.audit && s.audit.kind === "handoff") {
        F.push({ kind: "handoff", step: s });
      } else if (s.audit && s.audit.kind === "halt") {
        F.push({ kind: "llmhalt", step: s });
      } else {
        F.push({ kind: "finish", step: s });
      }
      if (s.operator) F.push({ kind: "operator", step: s });
    }
    F.push({ kind: "end", step: null });
    return F;
  }

  function herringFrames() {
    return ["intro", "queue", "stamp", "attentive", "compare"].map((kind) => ({ kind, step: null }));
  }

  const trace = () => T.scenarios[state.key][state.reviewer];

  // ---------------------------------------------------------------- captions

  function caption(f, t) {
    const s = f.step;
    const tool = s && s.audit && s.audit.tool;
    const g = s && s.gate;
    switch (f.kind) {
      case "intro":
        return { v: "info", who: "Caseworker", what: `Draft an eligibility summary for case ${t.case_id}.`,
          why: "The agent may only use the tools its agent file declares, under the org's policies." };
      case "startup":
        return t.startup.ok
          ? { v: "info", who: "Runtime", what: "Agent file loaded. Policies resolved.",
            why: `Loaded: ${t.startup.policies_loaded.join(", ")}. Required by the agent file: ${t.startup.required.join(", ")}.` }
          : { v: "info", who: "Runtime", what: "Loading the agent file and resolving its policies…",
            why: `Required by the agent file: ${t.startup.required.join(", ")}. Found in the registry: ${t.startup.registry.join(", ")}.` };
      case "refused":
        return { v: "refused", who: "Runtime", what: "Refused to start. The agent never ran.", why: t.startup.error };
      case "propose":
        return { v: "info", who: `Agent · step ${s.n}`, what: `Proposes ${tool}(${fmtArgs(s.audit.args)})`,
          why: `Its stated reason: “${s.audit.why}”` };
      case "decide": {
        const v = { allow: "allow", deny: "deny", require_approval: "hold", halt: "halt" }[g.verdict];
        const what = {
          "allow-listed": "Declared tool, and no rule objects. Allow.",
          "default-deny": `${tool} is not in this agent's action space. Deny.`,
          "org.deny_tools": `${tool} is blocked by org policy. Deny.`,
          "org.scope": "That case is not this session's case. Deny.",
          "approval": "This tool needs a human before it runs. Hold.",
        }[g.rule] || `${g.reason}. Halt.`;
        const why = g.verdict === "deny" ? `${g.reason}. Nothing ran. It is in the audit log.`
          : g.verdict === "require_approval" ? `${g.reason}: “${g.message}”`
          : g.verdict === "halt" ? `Rule ${g.rule}. The run stops here.` : `Rule: ${g.rule}`;
        return { v, who: "Gate", what, why };
      }
      case "human":
        return s.human.approved
          ? { v: "allow", who: "Caseworker", what: "Approved. Now it may run.", why: `They were asked: “${s.human.message}”`, pre: s.human.preview }
          : { v: "deny", who: "Caseworker", what: "Rejected. The run stops and nothing ran.", why: `They were asked: “${s.human.message}”`, pre: s.human.preview };
      case "run":
        return { v: "allow", who: "Tool", what: `${tool} runs. The result goes back to the agent.`,
          why: "Shown redacted. The audit log never stores raw PII.", pre: s.result };
      case "handoff":
        return { v: "hold", who: `Agent · step ${s.n}`, what: "Hands the case back to the caseworker.", why: `“${s.audit.reason}”` };
      case "llmhalt":
        return { v: "halt", who: "Gate", what: "Halts the run before the next model call.", why: `${s.audit.reason} (rule ${s.audit.rule}).` };
      case "operator":
        return { v: "halt", who: "Operator", what: "Pulls the kill switch.", why: "Every later check sees it and halts." };
      case "finish":
        return { v: "info", who: "Agent", what: "Done. No more proposals.", why: "" };
      case "end": {
        const danger = t.danger.length ? t.danger.join(", ") : "none";
        const status = { completed: "Completed", rejected: "Stopped by the caseworker", handoff: "Handed back to a human",
          halted: "Halted", refused: "Refused to start" }[t.status] || t.status;
        return { v: t.status === "completed" ? "allow" : t.status === "handoff" ? "hold" : "halt", who: "Outcome",
          what: `${status}. Dangerous tools that actually ran: ${danger}.`,
          why: t.draft ? "Draft for the caseworker (redacted). Nothing was sent:" : (t.detail || ""), pre: t.draft || null };
      }
    }
    return { v: "info", who: "", what: "", why: "" };
  }

  function herringCaption(kind) {
    const [stamp, att] = T.redherring.reviewers;
    const n = T.redherring.items.length, h = stamp.red_herrings;
    return {
      intro: { v: "info", who: "Setup", what: "Can your reviewers tell oversight from a green button?",
        why: "Seed the review queue with drafts you know are wrong, then measure what reviewers do with them." },
      queue: { v: "info", who: "Queue", what: `${n} drafted determinations. ${h} are seeded red herrings.`,
        why: "Each red herring claims the opposite of what its own income and threshold say, so a careful reader can catch it." },
      stamp: { v: "deny", who: "Rubber stamp", what: `Approves ${pct(stamp.approval_rate)}. Catches ${stamp.caught} of ${h}.`,
        why: "Approve is one click. This reviewer barely looks." },
      attentive: { v: "allow", who: "Attentive", what: `Approves ${pct(att.approval_rate)}. Catches ${att.caught} of ${h}.`,
        why: "Reads the numbers. Rarely rejects a good draft." },
      compare: { v: "hold", who: "Takeaway", what: "Similar approval rates, very different catch rates.",
        why: "Approval rate alone tells you nothing. Simulation only: the reviewer models are assumptions." },
    }[kind];
  }
  const pct = (x) => `${Math.round(x * 100)}%`;

  // ---------------------------------------------------------------- diagram

  const NODES = {
    case: [20, 148, "Caseworker", "asks for a draft"],
    agent: [190, 320, "Agent", "model proposes"],
    gate: [390, 530, "Gate", "no model in here"],
    tools: [600, 760, "Tools", "read / calc / draft"],
  };
  const POS = { start: [84, 255], case: [169, 194], agentGate: [355, 194], gate: [460, 194], gateTools: [565, 194],
    approval: [460, 96], bin: [460, 262], ret: [468, 246], caseDone: [84, 255] };

  function diagramState(f, t) {
    const st = { lit: {}, sub: {}, packet: null, approval: null, denied: 0, kill: false };
    const upto = state.frames.slice(0, state.i + 1);
    st.denied = upto.filter((x) => x.kind === "decide" && x.step.gate.verdict === "deny").length;
    st.kill = upto.some((x) => x.kind === "operator");
    const s = f.step;
    const label = s && s.audit && s.audit.tool;
    switch (f.kind) {
      case "intro": st.lit.case = "blue"; st.packet = [POS.case, t.case_id, "blue"]; break;
      case "startup": st.lit.gate = t.startup.ok ? "blue" : "amber"; st.sub.gate = "loading policies"; break;
      case "refused": st.lit.gate = "red"; st.sub.gate = "REFUSED TO START"; break;
      case "propose": st.lit.agent = "blue"; st.packet = [POS.agentGate, label, "ink"]; break;
      case "decide": {
        const v = s.gate.verdict;
        const col = { allow: "green", deny: "red", require_approval: "amber", halt: "red" }[v];
        st.lit.gate = col; st.sub.gate = VERDICT[v];
        if (v === "allow") st.packet = [POS.gateTools, label, "green"];
        if (v === "deny") { st.packet = [POS.bin, label, "red"]; st.lit.bin = "red"; }
        if (v === "require_approval") { st.packet = [POS.approval, label, "amber"]; st.approval = "wait"; }
        if (v === "halt") st.packet = [POS.gate, label, "red"];
        break;
      }
      case "human":
        st.approval = s.human.approved ? "ok" : "no";
        st.lit.gate = s.human.approved ? "green" : "red"; st.sub.gate = s.human.approved ? "ALLOW" : "STOPPED";
        st.packet = s.human.approved ? [POS.gateTools, label, "green"] : [POS.approval, label, "red"];
        break;
      case "run": st.lit.tools = "green"; st.sub.tools = "ran"; st.packet = [POS.ret, "result", "green"]; break;
      case "handoff": st.lit.agent = "amber"; st.lit.case = "amber"; st.sub.case = "handed back"; st.packet = [POS.case, "handoff", "amber"]; break;
      case "llmhalt": st.lit.gate = "red"; st.sub.gate = "HALT"; st.lit.agent = "red"; st.sub.agent = "stopped"; break;
      case "operator": st.lit.gate = "red"; st.sub.gate = "KILL SWITCH"; break;
      case "finish": st.lit.agent = "blue"; st.sub.agent = "done"; break;
      case "end":
        st.lit.case = t.status === "completed" ? "green" : t.status === "handoff" ? "amber" : "red";
        st.sub.case = t.draft ? "draft ready" : t.status;
        if (t.draft) st.packet = [POS.case, "draft", "green"];
        break;
    }
    return st;
  }

  function svgNode(key, x0, x1, y0, y1, title, sub, st) {
    const col = st.lit[key];
    return `<g class="node ${key}${col ? " lit-" + col : ""}">
      <rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" rx="8"/>
      <text class="t" x="${(x0 + x1) / 2}" y="${y0 + (y1 - y0 < 70 ? 23 : 26)}" text-anchor="middle">${esc(title)}</text>
      <text class="s" x="${(x0 + x1) / 2}" y="${y0 + (y1 - y0 < 70 ? 44 : 50)}" text-anchor="middle">${esc(sub)}</text></g>`;
  }

  function drawDiagram(f, t) {
    const st = diagramState(f, t);
    let h = `<svg viewBox="0 0 780 350" role="img" aria-label="Pipeline: caseworker, agent, gate, tools, with an approval station above the gate and a blocked bin below it">
      <defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="arrow" d="M0,0 L10,5 L0,10 z"/></marker></defs>`;
    for (const [a, b] of [[148, 190], [320, 390], [530, 600]]) h += `<path class="wire" d="M${a},194 L${b - 2},194" marker-end="url(#ah)"/>`;
    h += `<path class="wire dash" d="M680,212 L680,240 L255,240 L255,216" marker-end="url(#ah)"/>
      <text class="wire-label" x="300" y="262" text-anchor="middle">result back to the agent</text>
      <path class="wire dash" d="M460,72 L460,118"/><path class="wire dash" d="M460,214 L460,284"/>`;
    for (const [k, [x0, x1, title, sub]] of Object.entries(NODES)) {
      h += svgNode(k, x0, x1, k === "gate" ? 118 : 122, k === "gate" ? 214 : 212, title, st.sub[k] || sub, st);
    }
    const ap = st.approval;
    st.lit.approval = { wait: "amber", ok: "green", no: "red" }[ap];
    h += svgNode("approval", 380, 540, 16, 72, "Approval",
      { wait: "reviewing…", ok: "approved", no: "rejected" }[ap] || "caseworker decides", st);
    st.lit.bin = st.lit.bin || (st.denied ? "red" : undefined);
    h += svgNode("bin", 390, 530, 284, 340, `Blocked × ${st.denied}`, st.kill ? "kill switch pulled" : "denied calls", st);
    $("diagram-base").innerHTML = h + "</svg>";
    movePacket(st.packet);
  }

  // The packet lives in its own persistent overlay so it can glide between positions.
  function movePacket(p) {
    const g = $("packet");
    if (!p) { g.style.opacity = "0"; return; }
    const [[x, y], label, col] = p;
    const w = Math.max(56, String(label).length * 8 + 22);
    g.setAttribute("class", `packet c-${col}`);
    g.style.opacity = "1";
    g.style.transform = `translate(${x}px, ${y}px)`;
    const r = g.querySelector("rect");
    r.setAttribute("x", -w / 2); r.setAttribute("width", w);
    g.querySelector("text").textContent = label;
  }

  // ---------------------------------------------------------------- red herring

  function drawHerring(kind) {
    const rh = T.redherring, items = rh.items;
    const cell = (r) => items.map((it, i) => {
      let c = it.red_herring ? "h" : "";
      if (r) {
        const ok = r.approved[i];
        c = it.red_herring ? (ok ? "missed" : "caught") : (ok ? "ok" : "fr");
      }
      return `<i class="${c}" title="${esc(it.id)}${it.red_herring ? " (red herring)" : ""}"></i>`;
    }).join("");
    const show = { intro: [], queue: [null], stamp: [0], attentive: [0, 1], compare: [0, 1] }[kind];
    const panes = (show.length ? show : [null]).map((ri) => {
      const r = ri === null ? null : rh.reviewers[ri];
      const title = r ? (r.reviewer[0].toUpperCase() + r.reviewer.slice(1)) : "Review queue";
      const stat = r ? `Approval rate ${pct(r.approval_rate)} · caught ${r.caught} of ${r.red_herrings} seeded errors (${pct(r.catch_rate)})`
        : kind === "intro" ? "" : `${items.length} items, ${rh.reviewers[0].red_herrings} seeded red herrings (outlined)`;
      return `<div><h3>${esc(title)}</h3><p class="stat">${esc(stat)}</p><div class="grid">${kind === "intro" ? items.map(() => "<i></i>").join("") : cell(r)}</div></div>`;
    }).join("");
    $("herring").innerHTML = `<div class="grids">${panes}</div>
      <div class="legend"><span style="--sw: var(--green)">red herring caught</span><span style="--sw: var(--red)">red herring approved</span>
      <span style="--sw: var(--t-green)">good draft approved</span><span style="--sw: var(--amber)">good draft rejected</span></div>`;
  }

  // ---------------------------------------------------------------- audit + advanced

  function drawAudit(t) {
    if (state.key === "redherring") {
      $("audit").innerHTML = `<li class="empty">This scenario is a simulation of reviewers, not a gated run.</li>`;
      return;
    }
    const events = [];
    state.frames.slice(0, state.i + 1).forEach((f, idx) => {
      const s = f.step;
      if (!s || !s.audit) return;
      const lands = s.audit.kind !== "tool_call" ? true
        : s.human ? f.kind === "human" : f.kind === "decide";
      if (lands) events.push({ e: s.audit, fresh: idx === state.i });
    });
    if (state.frames.slice(0, state.i + 1).some((f) => f.kind === "refused")) {
      $("audit").innerHTML = `<li class="new"><div class="row1"><span class="tool">agent start</span><span class="pill refused">REFUSED</span></div><div class="why">${esc(t.startup.error)}</div></li>`;
      return;
    }
    if (!events.length) { $("audit").innerHTML = `<li class="empty">Nothing yet.</li>`; return; }
    $("audit").innerHTML = events.map(({ e, fresh }) => {
      const v = e.kind === "tool_call" ? e.verdict : e.kind;
      const label = e.kind === "tool_call" ? `${e.tool}(${fmtArgs(e.args)})` : e.kind;
      const human = e.human ? ` <span class="pill ${e.human}">${e.human.toUpperCase()}</span>` : "";
      const why = e.kind === "tool_call" ? `why: ${e.why}` : e.reason;
      return `<li class="${fresh ? "new" : ""}"><div class="row1"><span class="tool">${e.seq}. ${esc(label)}</span>
        <span><span class="pill ${esc(v)}">${esc(VERDICT[v] || v.toUpperCase())}</span>${human}</span></div>
        <div class="why">${esc(why)}</div></li>`;
    }).join("");
  }

  function checksList(checks, note) {
    if (!checks || !checks.length) return `<p class="note">Not reached.</p>`;
    return `${note ? `<p class="note">${note}</p>` : ""}<ol class="checks">${checks.map((c, i) => {
      const decider = i === checks.length - 1 && c.result !== "pass";
      return `<li class="${decider ? "decider" : ""}"><span><span class="rule">${esc(c.rule)}</span><br><span class="src">${esc(SOURCE[c.rule] || "")}</span></span>
        <span class="pill ${esc(c.result)}">${esc(VERDICT[c.result] || c.result)}</span><span class="detail">${esc(c.detail)}</span></li>`;
    }).join("")}</ol>`;
  }

  function meter(label, n, cap) {
    const w = Math.min(100, (n / cap) * 100);
    return `<div class="meter"><div class="lbl"><span>${esc(label)}</span><span>${n} / ${cap}</span></div>
      <div class="bar"><i class="${n > cap ? "over" : ""}" style="width:${w}%"></i></div></div>`;
  }

  function lastStep() {
    for (let j = state.i; j >= 0; j--) if (state.frames[j].step) return state.frames[j].step;
    return null;
  }

  function drawAdvanced(t) {
    const box = $("adv");
    box.hidden = !state.advanced;
    if (!state.advanced) return;
    const files = Object.entries(T.files);
    const fileCard = `<div class="card wide"><h3>Configuration the gate reads <small>(the same files a reviewer reads)</small></h3>
      <div class="tabs">${files.map(([p], i) => `<button type="button" data-file="${i}" aria-pressed="${i === state.fileTab}">${esc(p)}</button>`).join("")}</div>
      <pre>${esc(files[state.fileTab][1])}</pre></div>`;

    if (state.key === "redherring") {
      const rh = T.redherring;
      const rows = rh.items.map((it, i) => ({ it, i })).filter(({ it }) => it.red_herring);
      box.innerHTML = `<div class="card wide"><h3>The ${rows.length} seeded red herrings</h3>
        <p class="note">Each claims the opposite of what its own numbers say (eligible means income ≤ threshold).</p>
        <pre>${esc(["id       household  income    threshold  draft says     truth          " + rh.reviewers.map((r) => r.reviewer.padEnd(14)).join(""),
          ...rows.map(({ it, i }) => `${it.id}   ${String(it.household).padEnd(9)}  ${String(it.income).padEnd(8)}  ${String(it.threshold).padEnd(9)}  ${(it.claimed_eligible ? "eligible" : "not eligible").padEnd(13)}  ${(it.correct_eligible ? "eligible" : "not eligible").padEnd(13)}  ` +
            rh.reviewers.map((r) => (r.approved[i] ? "approved (miss)" : "rejected (catch)").padEnd(14) + " ").join(""))].join("\n"))}</pre></div>
        <div class="card"><h3>Measured</h3><pre>${esc(JSON.stringify(rh.reviewers.map(({ approved, ...m }) => m), null, 1))}</pre></div>`;
      return;
    }

    const s = lastStep();
    const startup = `<div class="card"><h3>Startup</h3><dl class="kv">
      <dt>case</dt><dd>${esc(t.case_id)}</dd>
      <dt>required</dt><dd>${esc(t.startup.required.join(", "))}</dd>
      ${t.startup.ok ? `<dt>loaded</dt><dd>${esc(t.startup.policies_loaded.join(", "))}</dd>`
        : `<dt>registry has</dt><dd>${esc(t.startup.registry.join(", "))}</dd><dt>result</dt><dd><span class="pill refused">REFUSED</span> ${esc(t.startup.error)}</dd>`}
      </dl>${t.case_file ? `<h3 style="margin-top:12px">Case file <small>(redacted for display)</small></h3><pre>${esc(JSON.stringify(t.case_file, null, 1))}</pre>` : ""}</div>`;
    if (!s) { box.innerHTML = startup + fileCard; return; }

    const g = s.gate;
    const llmCap = t.limits.max_llm_calls, toolCap = t.limits.max_tool_calls;
    const counters = `<div class="card"><h3>Step ${s.n} · run budgets</h3>
      ${meter("model calls (limits.max_llm_calls)", s.llm.calls, llmCap)}
      ${g ? meter("tool calls (limits.max_tool_calls)", g.tool_calls, toolCap) : ""}
      <h3 style="margin-top:12px">Before the model call</h3>${checksList(s.llm.checks)}</div>`;
    const gateCard = `<div class="card"><h3>Gate rules for step ${s.n}${g ? ` <small>· ${esc(s.audit.tool)}</small>` : ""}</h3>
      ${g ? checksList(g.checks, "Rules run in order. The first one that objects decides; later rules are not evaluated.")
        : `<p class="note">${s.audit ? `No tool call: the run ended with <b>${esc(s.audit.kind)}</b>.` : "No tool call: the planner finished."}</p>`}</div>`;
    const detail = `<div class="card"><h3>Step ${s.n} · data</h3><dl class="kv">
      ${s.audit && s.audit.args ? `<dt>args</dt><dd><code>${esc(JSON.stringify(s.audit.args))}</code></dd>` : ""}
      ${g && g.message ? `<dt>approval prompt</dt><dd>${esc(g.message)}</dd>` : ""}
      ${s.human ? `<dt>human</dt><dd><span class="pill ${s.human.approved ? "approved" : "rejected"}">${s.human.approved ? "APPROVED" : "REJECTED"}</span></dd>` : ""}
      ${s.operator ? `<dt>operator</dt><dd>${esc(s.operator)}</dd>` : ""}
      </dl>
      ${s.result !== undefined ? `<h3 style="margin-top:12px">Tool result <small>(redacted)</small></h3><pre>${esc(s.result)}</pre>` : ""}
      ${s.audit ? `<h3 style="margin-top:12px">Audit event <small>(as logged, PII redacted)</small></h3><pre>${esc(JSON.stringify(s.audit, null, 1))}</pre>` : ""}</div>`;
    box.innerHTML = gateCard + counters + detail + startup + fileCard;
  }

  // ---------------------------------------------------------------- render + controls

  function render() {
    const herring = state.key === "redherring";
    const f = state.frames[state.i];
    const t = herring ? null : trace();
    $("diagram").hidden = herring;
    $("herring").hidden = !herring;
    if (herring) drawHerring(f.kind); else drawDiagram(f, t);

    const c = herring ? herringCaption(f.kind) : caption(f, t);
    const cap = $("caption");
    cap.className = `caption v-${c.v}`;
    cap.innerHTML = `<div class="who">${esc(c.who)}</div><div class="what">${esc(c.what)}</div>
      ${c.why ? `<div class="why">${esc(c.why)}</div>` : ""}${c.pre ? `<pre>${esc(c.pre)}</pre>` : ""}`;

    drawAudit(t);
    drawAdvanced(t);

    $("count").textContent = `Step ${state.i + 1} of ${state.frames.length}`;
    $("back").disabled = state.i === 0;
    $("next").disabled = state.i === state.frames.length - 1;
    $("play").textContent = state.timer ? "Pause" : state.i === state.frames.length - 1 ? "Replay" : "Play";
    $("play").setAttribute("aria-label", $("play").textContent);
    $("progress").innerHTML = state.frames.map((_, j) => `<span class="${j <= state.i ? "done" : ""}" data-j="${j}"></span>`).join("");
  }

  function load(key) {
    stop();
    state.key = key;
    state.frames = key === "redherring" ? herringFrames() : framesFor(trace());
    state.i = 0;
    const m = META[key];
    $("intro").innerHTML = `<h2>${esc(m.label)}</h2><p>${esc(m.desc)}</p><span class="lesson">Lesson: ${esc(m.lesson)}</span>`;
    document.querySelectorAll("#scenarios button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.key === key)));
    const hasHuman = key !== "redherring" && T.scenarios[key].approve.steps.some((s) => s.human);
    $("reviewer").hidden = !hasHuman;
    document.querySelectorAll("#reviewer button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.rev === state.reviewer)));
    if (location.hash.slice(1) !== key) history.replaceState(null, "", `#${key}`);
    render();
  }

  function go(i) { state.i = Math.max(0, Math.min(state.frames.length - 1, i)); render(); }
  function stop() { if (state.timer) clearInterval(state.timer); state.timer = null; }
  function play() {
    if (state.timer) { stop(); render(); return; }
    if (state.i === state.frames.length - 1) state.i = 0;
    state.timer = setInterval(() => {
      if (state.i >= state.frames.length - 1) { stop(); render(); return; }
      go(state.i + 1);
    }, 2200);
    render();
  }

  $("scenarios").innerHTML = SCENARIOS.map(([k, label]) => `<button type="button" data-key="${k}" aria-pressed="false">${esc(label)}</button>`).join("");
  $("scenarios").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) load(b.dataset.key); });
  $("reviewer").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.dataset.rev === state.reviewer) return;
    state.reviewer = b.dataset.rev;
    const keep = state.i;
    load(state.key);
    go(Math.min(keep, state.frames.length - 1));
  });
  $("back").addEventListener("click", () => { stop(); go(state.i - 1); });
  $("next").addEventListener("click", () => { stop(); go(state.i + 1); });
  $("restart").addEventListener("click", () => { stop(); go(0); });
  $("play").addEventListener("click", play);
  $("progress").addEventListener("click", (e) => { const j = e.target.dataset.j; if (j !== undefined) { stop(); go(+j); } });
  $("advanced").checked = state.advanced;
  $("advanced").addEventListener("change", (e) => {
    state.advanced = e.target.checked;
    store.set("govdemo.advanced", state.advanced ? "1" : "0");
    render();
  });
  $("adv").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-file]");
    if (b) { state.fileTab = +b.dataset.file; render(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select")) return;
    if (e.key === "ArrowRight") { stop(); go(state.i + 1); }
    else if (e.key === "ArrowLeft") { stop(); go(state.i - 1); }
    else if (e.key === " " && !e.target.closest("button")) { e.preventDefault(); play(); }
  });
  window.addEventListener("hashchange", () => { const k = location.hash.slice(1); if (META[k] && k !== state.key) load(k); });

  load(META[location.hash.slice(1)] ? location.hash.slice(1) : "injection");
})();
