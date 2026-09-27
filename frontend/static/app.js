// RevForge UI: four separate screens, one per stage, hash-routed.
// Each screen owns its inputs, its real processing calls, and its outputs.
// Shared state is reloaded before every render, so banners never go stale.
// No framework; api() is the single network choke point.
const $ = (id) => document.getElementById(id);

// API base: same-origin by default. Split deployments pass ?api=<url>.
const API_BASE = (window.REVFORGE_API ||
  new URLSearchParams(window.location.search).get("api") || "").replace(/\/$/, "");

const state = {
  screen: "discover",
  hypotheses: [],
  selectedId: null,
  selectedKnowledge: null,
  experiments: [],
  knowledge: [],
};

const SCREENS = ["data", "discover", "hypothesis", "test", "results"];
const STAGES = ["Get data", "Find", "Rank", "Test", "Launch", "Results in", "Decide", "Remember"];

// Plain-English translations of pattern ingredients, so anyone can read a bet.
function patternPlain(pattern) {
  const out = [];
  if (pattern.employees === "150-500") out.push("Mid-size companies (150–500 people)");
  else if (pattern.employees) out.push(`Company size: ${pattern.employees}`);
  if (pattern.new_vp_sales) out.push("A new sales leader just joined");
  if (pattern.sdr_openings_gte) out.push(`Hiring ${pattern.sdr_openings_gte}+ salespeople`);
  if (pattern.sdr_openings && !pattern.sdr_openings_gte) out.push(`${pattern.sdr_openings} open sales roles`);
  if (pattern.tech) out.push(`Uses ${pattern.tech}`);
  if (pattern.intent === "high") out.push("Showing buying interest right now");
  else if (pattern.intent) out.push(`Interest level: ${pattern.intent}`);
  for (const [k, v] of Object.entries(pattern || {})) {
    if (["employees", "new_vp_sales", "sdr_openings_gte", "sdr_openings", "tech", "intent"].includes(k)) continue;
    out.push(`${k}: ${v}`);
  }
  return out.length ? out : ["(no details)"];
}

function meaningSentence(verdict, lift, tRate, cRate) {
  const t = (tRate * 100).toFixed(1), c = (cRate * 100).toFixed(1);
  if (tRate === 0 && cRate === 0) {
    return `Nobody replied in either group — not even ordinary customers. That points at the message or delivery, not the targeting. Fix outreach first, then retest.`;
  }
  if (verdict === "Validated") {
    return `This customer type replied ${lift}x more often (${t}% vs ${c}%). In plain terms: for every 100 you contact, expect about ${Math.round(t)} replies instead of ${Math.round(c)}. Worth chasing.`;
  }
  if (verdict === "Rejected") {
    return `This customer type did worse than average (${t}% vs ${c}%). Don't chase it — the idea looked good in old data but failed the live test.`;
  }
  return `Too close to call (${t}% vs ${c}%). The test was too small or the difference too tiny — test again with more people before deciding.`;
}

// ---------------------------------------------------------------- helpers

function showError(msg) {
  const el = $("err");
  el.textContent = msg;
  el.classList.remove("hidden");
  // Any in-flight action button unlocks: the user can read the error and retry.
  for (const id of ["launch", "sync", "eval", "build", "approve"]) {
    const b = $(id);
    if (b) b.disabled = false;
  }
}

function clearError() {
  $("err").classList.add("hidden");
  $("err").textContent = "";
}

async function api(path, opts = {}) {
  const url = `${API_BASE}${path}`;
  let r;
  try {
    r = await fetch(url, opts);
  } catch (e) {
    throw new Error(
      `backend unreachable at ${API_BASE || window.location.origin} (${e}). ` +
      `Start it: .venv/bin/uvicorn backend.app:app --port 8000, ` +
      `then open http://127.0.0.1:8000/ (same origin, not a file).`
    );
  }
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return r.json();
}

const STATUS_STYLE = {
  Candidate: "bg-slate-600", Prioritized: "bg-sky-600", Testing: "bg-amber-600",
  Validated: "bg-emerald-600", Rejected: "bg-red-600", Inconclusive: "bg-amber-600",
  draft: "bg-slate-600", launched: "bg-amber-600", observed: "bg-sky-600", evaluated: "bg-emerald-600",
};

function statusBadge(s) {
  const words = { Candidate: "New idea", Prioritized: "Approved", Testing: "Testing now",
    Validated: "Proven ✓", Rejected: "Disproven", Inconclusive: "Unclear",
    draft: "Ready", launched: "Outreach live", observed: "Replies in", evaluated: "Decided" };
  return `<span class="px-2 py-0.5 rounded-full text-xs font-semibold ${STATUS_STYLE[s] || "bg-slate-600"}" title="${s}">${words[s] || s}</span>`;
}

function srcBadge(src) {
  const live = src === "live";
  return `<span class="px-2 py-0.5 rounded-full text-xs font-semibold ${live ? "bg-emerald-600" : "bg-slate-500"}">${(src || "?").toUpperCase()}</span>`;
}

function screenHead(title, goal) {
  return `<div class="p-5 rounded-xl bg-slate-900 border border-slate-700">
    <p class="text-xs text-slate-400">${goal}</p>
    <p class="font-bold text-xl mt-1">${title}</p>`;
}

function screenFoot(inner) {
  return `<div class="mt-4">${inner}</div></div>`;
}

function stat(label, value, accent) {
  return `<div class="p-3 rounded-lg bg-slate-800 border border-slate-700 text-center">
    <p class="text-xl font-bold ${accent || "text-slate-100"}">${value}</p>
    <p class="text-xs text-slate-400 mt-1">${label}</p></div>`;
}

// ---------------------------------------------------------------- state + router

function activeHypothesis() {
  return state.hypotheses.find((x) => x.id === state.selectedId) || state.hypotheses[0] || null;
}

function latestExp(h) {
  const list = h ? state.experiments.filter((e) => e.hypothesis_id === h.id) : state.experiments;
  return list.length ? list[list.length - 1] : null;
}

async function refreshAll() {
  // Reload everything before rendering: banners derive from this state,
  // so a sync-after-evaluate (observed again) shows correctly, not stale.
  const [h, e, k, s] = await Promise.all([
    api("/api/hypotheses"), api("/api/experiments"), api("/api/knowledge"),
    api("/api/stats"),
  ]);
  state.hypotheses = h.hypotheses || [];
  state.experiments = e.experiments || [];
  state.knowledge = k.knowledge || [];
  state.stats = s.stats || { n: 0, won: 0, lost: 0, win_rate: 0 };
  if (state.hypotheses.length && !activeHypothesis()) {
    state.selectedId = state.hypotheses[0].id;
  }
}

function stageIndex() {
  const h = activeHypothesis();
  if (!h) return 0;
  if (["Validated", "Rejected", "Inconclusive"].includes(h.status)) return 7;
  const exp = latestExp(h);
  if (exp && exp.status === "evaluated") return 6;
  if (exp && exp.status === "observed") return 5;
  if (exp) return 4;
  if (h.status === "Testing") return 3;
  if (h.status === "Prioritized") return 2;
  return 1;
}

function unlockedScreens() {
  // Strict order: each screen unlocks only when the previous stage produced
  // something. Nothing downstream ever renders ahead of its turn.
  const done = { data: true };
  done.discover = state.dataFetched && ((state.stats && state.stats.n > 0) || state.hypotheses.length > 0);
  done.hypothesis = state.hypotheses.length > 0;
  done.test = state.hypotheses.some((h) => h.status !== "Candidate") || state.experiments.length > 0;
  done.results = state.knowledge.length > 0 ||
    state.experiments.some((e) => e.status === "observed" || e.status === "evaluated");
  return done;
}

function renderChrome() {
  const idx = stageIndex();
  const colors = ["bg-emerald-600", "bg-emerald-600", "bg-sky-600", "bg-sky-600", "bg-amber-600", "bg-amber-600", "bg-violet-600", "bg-violet-600"];
  $("stepper").innerHTML = STAGES.map((s, i) =>
    `<li class="px-2 py-1 rounded-full font-medium ${i <= idx ? colors[i] : "bg-slate-800 text-slate-500"}">${s}</li>`
  ).join("");
  document.querySelectorAll("#tabs a").forEach((x) => {
    const on = x.dataset.tab === state.screen;
    const open = (unlockedScreens()[x.dataset.tab]);
    x.className = `px-3 py-2 rounded-lg text-center text-sm font-semibold ${on ? "bg-emerald-600" : open ? "bg-slate-800" : "bg-slate-900 text-slate-600"}`;
    x.dataset.locked = open ? "" : "1";
  });
  const h = activeHypothesis();
  let msg;
  if (!state.hypotheses.length) {
    msg = state.dataFetched && state.stats && state.stats.n > 0
      ? `👉 Fresh deals loaded (${state.stats.n} total) — continue under <b>Find patterns</b>.`
      : `👉 Start on <b>Get data</b> — press <b>Fetch data</b> for your first batch of past deals.`;
  } else if (h && h.status === "Candidate") {
    msg = `👉 Reviewing <b>${h.id}</b> — press <b>Test this bet</b>. Nothing is sent yet.`;
  } else if (h && h.status === "Prioritized") {
    msg = `👉 <b>${h.id}</b> approved — choose group sizes and press <b>Find test customers</b>.`;
  } else if (h) {
    const exp = latestExp(h);
    if (!exp) msg = `👉 Find test customers for <b>${h.id}</b> under Review the bet.`;
    else if (exp.status === "draft") msg = `👉 Under Run the test: press <b>Start outreach</b> — creates the real customer list + campaign.`;
    else if (exp.status === "launched") msg = `👉 Under Run the test: press <b>Collect results</b>, then <b>Get the result</b>.`;
    else if (exp.status === "observed") msg = `👉 Press <b>Get the result</b> — test group vs comparison group decides.`;
    else if (["Validated", "Rejected", "Inconclusive"].includes(h.status)) msg = state.screen === "results"
      ? `✅ <b>${h.id}: ${h.status}</b> — click a learning below for the full story.`
      : `✅ <b>${h.id}: ${h.status}</b> — learning saved. Open <b>Results</b> and click it.`;
    else msg = `👉 Under Run the test: continue — start, collect, decide.`;
  } else {
    msg = `👉 Press <b>Find patterns</b> to begin.`;
  }
  $("next").innerHTML = msg;
}

async function showTab(name) {
  if (!SCREENS.includes(name)) name = "data";
  state.screen = name;
  for (const v of SCREENS) $(`view-${v}`).classList.add("hidden");
  $(`view-${name}`).classList.remove("hidden");
  if (window.location.hash !== `#/${name}`) {
    window.location.hash = `#/${name}`;
  }
  try {
    clearError();
    await refreshAll();
  } catch (e) {
    showError(String(e.message || e));
  }
  renderChrome();
  if (name === "data") renderData();
  if (name === "discover") renderDiscover();
  if (name === "hypothesis") renderHypothesis();
  if (name === "test") renderTest();
  if (name === "results") renderResults();
}

function go(name) {
  showTab(name);
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- screen: get data

async function renderData() {
  const el = $("view-data");
  // Session rule: numbers appear only AFTER you fetch in this session.
  // Leftover rows from earlier runs stay invisible until then.
  let statsHtml = `<p class="text-sm text-slate-400 mt-3">No deals loaded yet — press <b>Fetch data</b> for your first batch.</p>`;
  if (state.dataFetched) {
    try {
      const s = (await api("/api/stats")).stats;
      state.stats = s;
      statsHtml = s.n > 0
        ? `<div class="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2">
          ${stat("past deals", s.n)}
          ${stat("won", s.won, "text-emerald-300")}
          ${stat("lost", s.lost)}
          ${stat("win rate", `${(s.win_rate * 100).toFixed(1)}%`)}
        </div>
        <p class="text-xs text-slate-400 mt-2">Fresh mock batch — a new size and a new hidden winner every fetch.</p>`
        : `<p class="text-sm text-slate-400 mt-3">No deals loaded yet — press <b>Fetch data</b> for your first batch.</p>`;
    } catch (e) {
      statsHtml = `<p class="text-sm text-slate-400 mt-3">Stats unavailable — fetch data first.</p>`;
    }
  }
  el.innerHTML = `${screenHead("Get fresh past deals", "every run starts here → then find patterns")}
    <p class="text-sm text-slate-300 mt-2">RevForge learns from <b>past deals</b>. Fetch a brand-new random batch, then move on to finding patterns in it.</p>
    <div class="mt-3 flex gap-2">
      <button id="fetch" class="px-5 py-2 rounded-lg bg-emerald-600 font-bold hover:bg-emerald-500">Fetch data</button>
    </div>
    <div id="ds-stats">${statsHtml}</div>${screenFoot("")}`;
  $("fetch").addEventListener("click", async (ev) => {
    const btn = ev.target;
    btn.disabled = true;
    btn.textContent = "Fetching…";
    try {
      clearError();
      await api("/api/seed", { method: "POST" });
      state.selectedId = null;
      state.selectedKnowledge = null;
      state.hypotheses = [];
      state.experiments = [];
      state.knowledge = [];
      state.dataFetched = true;
      await refreshAll();
      renderChrome();
      renderData();
    } catch (e) {
      showError(String(e.message || e));
    } finally {
      btn.disabled = false;
      btn.textContent = "Fetch data";
    }
  });
}

// ---------------------------------------------------------------- screen: discover

async function loadStats() {
  const el = $("stats");
  if (!el) return;  // discover screen not rendered yet
  try {
    const s = (await api("/api/stats")).stats;
    el.textContent =
      `${s.n} past deals · ${s.won} won · ${s.lost} lost · ${(s.win_rate * 100).toFixed(1)}% win rate`;
  } catch (e) {
    el.textContent = "stats unavailable";
    showError(String(e.message || e));
  }
}

function card(h) {
  const e = h.evidence || {};
  return `<button data-id="${h.id}" class="w-full text-left p-4 rounded-xl bg-slate-800 border-l-4 ${h.id === state.selectedId ? "border-emerald-400" : "border-slate-600"} border border-slate-700 hover:border-emerald-500">
    <p class="text-xs text-slate-400">${h.id} · ${statusBadge(h.status)} <span class="ml-1 text-amber-300 font-semibold">★ rank ${h.priority.toFixed(3)}</span></p>
    <p class="font-semibold mt-1">${h.title}</p>
    <p class="text-sm mt-1"><span class="text-emerald-300 font-bold">${(e.lift || 0).toFixed(2)}x more replies</span>
      <span class="text-slate-300"> · ${h.novelty === "High" ? "brand-new idea" : h.novelty === "Medium" ? "fairly new idea" : "known idea"} · ${h.testability === "High" ? "easy to test" : "testable"}</span></p>
    <p class="text-xs text-slate-400 mt-1">${e.wins} wins out of ${e.support} · replies ${((e.rate || 0) * 100).toFixed(1)}% vs average ${((e.baseline || 0) * 100).toFixed(1)}%</p>
    <p class="text-xs text-emerald-400 mt-1 font-semibold">See what this means →</p>
  </button>`;
}

function renderDiscover() {
  const el = $("view-discover");
  const cards = state.hypotheses.length
    ? state.hypotheses.map(card).join("")
    : `<p class="text-sm text-slate-400">No customer types found yet — press the button and RevForge studies your past wins.</p>`;
  el.innerHTML = `${screenHead("Discover hidden patterns", "mine past wins → pick a pattern")}
    <p id="stats" class="mt-2 text-sm text-emerald-200">loading…</p>
    <div class="mt-3 flex gap-2">
      <button id="analyze" class="px-5 py-2 rounded-lg bg-emerald-600 font-bold hover:bg-emerald-500">Find patterns</button>
    </div>
    <div id="cards" class="mt-4 grid gap-3">${cards}</div>${screenFoot("")}`;
  $("analyze").addEventListener("click", (ev) => runDiscover(ev.target));
  el.querySelectorAll("[data-id]").forEach((b) =>
    b.addEventListener("click", () => { state.selectedId = b.dataset.id; go("hypothesis"); }));
  loadStats();
}

async function runDiscover(btn) {
  btn.disabled = true;
  btn.textContent = "Analyzing past wins…";
  try {
    clearError();
    const j = await api("/api/discover", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "seed", top_k: 3 }),
    });
    state.hypotheses = j.hypotheses || [];
    if (state.hypotheses.length) state.selectedId = state.hypotheses[0].id;
    go("hypothesis");
  } catch (e) {
    showError(String(e.message || e));
  } finally {
    btn.disabled = false;
    btn.textContent = "Find patterns";
  }
}

// ---------------------------------------------------------------- screen: hypothesis

function breakdownBars(bd) {
  return Object.entries(bd || {}).map(([k, v]) => {
    const pct = Math.round(v * 100);
    return `<div><div class="flex justify-between text-xs text-slate-400"><span>${k}</span><span>${v.toFixed(2)}</span></div>
      <div class="h-1.5 rounded bg-slate-800"><div class="h-1.5 rounded bg-gradient-to-r from-emerald-500 to-sky-500" style="width:${pct}%"></div></div></div>`;
  }).join("");
}

async function renderHypothesis() {
  const el = $("view-hypothesis");
  const h = activeHypothesis();
  if (!h) {
    el.innerHTML = `${screenHead("Hypothesis", "review one pattern → approve or reject by testing")}
      <p class="text-sm text-slate-400 mt-3">Nothing discovered yet. <button id="backd" class="text-emerald-300 underline">Go to Discover →</button></p>${screenFoot("")}`;
    $("backd").addEventListener("click", () => go("discover"));
    return;
  }
  let fresh = h;
  try {
    fresh = (await api(`/api/hypotheses/${h.id}`)).hypothesis;
    state.hypotheses = state.hypotheses.map((x) => (x.id === h.id ? fresh : x));
  } catch (e) {
    showError(String(e.message || e));
  }
  const e = fresh.evidence || {};
  const plain = patternPlain(fresh.pattern || {});
  const chips = plain
    .map((t) => `<span class="px-2 py-1 rounded-full bg-emerald-900 border border-emerald-600 text-xs">✓ ${t}</span>`)
    .join(" ");
  const canApprove = fresh.status === "Candidate";
  const canTest = fresh.status === "Prioritized";
  el.innerHTML = `${screenHead(`Sales bet ${fresh.id}: ${fresh.title}`, "review the bet → approve the test")}
    <p class="mt-2">${statusBadge(fresh.status)} <span class="text-xs text-slate-400 ml-1">Our guess: customers like this buy more. The test will prove it right or wrong — approving sends nothing.</span></p>
    <p class="text-xs text-slate-400 mt-2 font-semibold">WHO THIS MEANS</p>
    <div class="mt-1 flex flex-wrap gap-1">${chips}</div>
    <p class="text-xs text-slate-400 mt-3 font-semibold">WHAT HAPPENED IN THE PAST</p>
    <div class="mt-1 grid grid-cols-2 md:grid-cols-4 gap-2">
      ${stat("past wins", `${e.wins}/${e.support}`)}
      ${stat("their reply rate", `${((e.rate || 0) * 100).toFixed(1)}%`)}
      ${stat("average rate", `${((e.baseline || 0) * 100).toFixed(1)}%`)}
      ${stat("edge", `${e.lift}x`, "text-emerald-300")}
    </div>
    <p class="text-sm text-slate-300 mt-3">How new is this: <b>${fresh.novelty === "High" ? "Mostly new — overlaps your usual customers only on company size" : fresh.novelty === "Medium" ? "Partly new — shares some traits with your usual customers" : "Close to your usual customer profile"}</b></p>
    ${fresh.explanation ? `<p class="text-xs text-slate-400 mt-1">${fresh.explanation}</p>` : ""}
    <p class="text-xs text-slate-400 mt-3 mb-1 font-semibold">RANK ${fresh.priority.toFixed(3)} — WHY IT RANKS HERE
      <button id="rescore" class="ml-2 px-2 py-0.5 rounded bg-slate-700 text-slate-200">Re-score</button></p>
    <div class="grid md:grid-cols-2 gap-x-4">${breakdownBars(fresh.priority_breakdown)}</div>
    <p class="text-xs text-slate-400 mt-4 mb-1 font-semibold">RUN THE TEST — HOW MANY CUSTOMERS PER GROUP?</p>
    <div class="mt-1 flex gap-2 items-center flex-wrap">
      ${canApprove ? `<button id="approve" class="px-5 py-2 rounded-lg bg-emerald-600 font-bold hover:bg-emerald-500">Test this bet →</button>` : ""}
      ${canTest ? `<input id="tn" type="number" value="50" min="1" max="200" class="w-20 px-2 py-2 rounded-lg bg-slate-800 border border-slate-600" title="test group size" />
      <input id="cn" type="number" value="50" min="1" max="200" class="w-20 px-2 py-2 rounded-lg bg-slate-800 border border-slate-600" title="comparison group size" />
      <button id="build" class="px-5 py-2 rounded-lg bg-sky-600 font-bold hover:bg-sky-500">Find test customers →</button>` : ""}
    </div>
    <p class="text-xs text-slate-500 mt-1">30+ per group needed for a decisive result · live lookups cost ~1 credit each</p>
    <div id="cohort" class="mt-3"></div>${screenFoot("")}`;
  const ap = $("approve");
  if (ap) ap.addEventListener("click", () => approveHypothesis(fresh.id));
  $("rescore").addEventListener("click", () => rescoreHypothesis(fresh.id));
  const bd = $("build");
  if (bd) bd.addEventListener("click", () => buildCohorts(fresh.id));
}

async function approveHypothesis(id) {
  const btn = $("approve");
  if (btn) btn.disabled = true;
  try {
    clearError();
    await api(`/api/hypotheses/${id}/approve`, { method: "POST" });
    await refreshAll();
    renderChrome();
    renderHypothesis();
  } catch (e) {
    showError(String(e.message || e));
  }
}

async function rescoreHypothesis(id) {
  try {
    clearError();
    await api(`/api/hypotheses/${id}/prioritize`, { method: "POST" });
    await refreshAll();
    renderChrome();
    renderHypothesis();
  } catch (e) {
    showError(String(e.message || e));
  }
}

async function buildCohorts(id) {
  const btn = $("build");
  if (btn) btn.disabled = true;
  const tn = parseInt($("tn").value, 10) || 50;
  const cn = parseInt($("cn").value, 10) || 50;
  $("cohort").innerHTML = `<p class="text-sm text-slate-400">Finding ${tn} test-group + ${cn} comparison-group customers…</p>`;
  try {
    clearError();
    const j = await api(`/api/hypotheses/${id}/test`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ treatment_n: tn, control_n: cn }),
    });
    go("test");
  } catch (e) {
    $("cohort").innerHTML = "";
    showError(String(e.message || e));
  }
}

// ---------------------------------------------------------------- screen: test

function timelineStep(done, label, sub) {
  return `<div class="flex gap-2 items-start">
    <span class="mt-0.5 w-5 h-5 rounded-full text-xs flex items-center justify-center font-bold ${done ? "bg-emerald-600" : "bg-slate-700 text-slate-400"}">${done ? "✓" : "·"}</span>
    <div><p class="text-sm font-medium">${label}</p>${sub ? `<p class="text-xs text-slate-400">${sub}</p>` : ""}</div></div>`;
}

function cohortHtml(cohort, expId) {
  const t = cohort.treatment, c = cohort.control;
  return `<div class="p-4 rounded-xl bg-slate-800 border border-slate-600 text-sm">
    <p class="text-slate-400 text-xs">TEST ${expId || ""} · TEST GROUP vs COMPARISON GROUP</p>
    <div class="mt-2 grid gap-2">
      ${timelineStep(true, `${t.companies_searched} matching companies found`, "customers that look like the bet")}
      ${timelineStep(true, `${t.buyers_found} sales leaders found → ${t.enriched} with contact details`, "the people we will reach out to")}
      ${timelineStep(true, `${t.signals_checked} buying clues checked`, `why now: ${(cohort.live_signals || []).join(", ") || "—"}`)}
      ${timelineStep(true, `Groups ready: ${t.n} test vs ${c.n} comparison`, `comparison group from ${c.companies_searched} ordinary companies`)}
    </div></div>`;
}

function groupPlain(g) {
  return g === "treatment" ? "Test group (fits the bet)" : "Comparison group (ordinary customers)";
}

function resultsHtml(results) {
  if (!results.length) return `<p class="text-xs text-slate-400">No replies counted yet — start outreach, then collect results.</p>`;
  return results.map((x) => `<div class="p-2 mt-1 rounded-lg bg-slate-800 border border-slate-600 text-sm">
      ${srcBadge(x.source)}
      <span class="ml-2"><b>${groupPlain(x.group)}</b>: ${x.positive} replies out of ${x.sent} contacted (${(x.rate * 100).toFixed(1)}%) · ${x.meetings} meetings booked</span>
    </div>`).join("");
}

async function renderTest() {
  const el = $("view-test");
  const h = activeHypothesis();
  const list = h ? state.experiments.filter((e) => e.hypothesis_id === h.id) : [];
  const exp = list.length ? list[list.length - 1] : null;
  if (!exp) {
    el.innerHTML = `${screenHead("Test the hypothesis", "cohorts → launch → outcomes")}
      <p class="text-sm text-slate-400 mt-3">No experiment for ${h ? h.id : "any hypothesis"} yet.
      <button id="backh" class="text-emerald-300 underline">Go back to Review the bet →</button></p>${screenFoot("")}`;
    const b = $("backh");
    if (b) b.addEventListener("click", () => go("hypothesis"));
    return;
  }
  let html = `${screenHead(`Test on ${exp.hypothesis_id}`, `live customer outreach, tracked here`)}
    <p class="mt-2">${statusBadge(exp.status)}</p>
    <div class="mt-3">${exp.cohort ? cohortHtml(exp.cohort, exp.id) : ""}</div>`;
  if (exp.status === "draft") html += `<button id="launch" class="mt-3 px-5 py-2 rounded-lg bg-amber-600 font-bold hover:bg-amber-500">Start outreach →</button>
    <p class="text-xs text-slate-400 mt-1">Creates the graph8 list + campaign. Live mode writes to your real workspace.</p>`;
  if (exp.status !== "draft") html += `<p class="text-xs text-emerald-300 mt-2">✓ Outreach started</p>`;
  if (exp.status === "launched") html += `<button id="sync" class="mt-2 px-5 py-2 rounded-lg bg-sky-600 font-bold hover:bg-sky-500">Collect results →</button>
    <p class="text-xs text-slate-400 mt-1">Demo path: SEEDED fixtures. Live path: graph8 webhooks feed real engagement.</p>`;
  if (exp.status === "observed") html += `<button id="eval" class="mt-2 px-5 py-2 rounded-lg bg-emerald-600 font-bold hover:bg-emerald-500">Get the result →</button>
    <p class="text-xs text-slate-400 mt-1">Compares treatment vs control and writes the verdict + knowledge.</p>`;
  html += `<div id="tresults" class="mt-2"></div>${screenFoot("")}`;
  el.innerHTML = html;
  const l = $("launch"), s = $("sync"), ev = $("eval");
  if (l) l.addEventListener("click", () => launchExperiment(exp.id));
  if (s) s.addEventListener("click", () => syncOutcomes(exp.id));
  if (ev) ev.addEventListener("click", () => evaluateExperiment(exp.id));
  if (exp.status !== "draft") {
    try {
      const rows = (await api(`/api/experiments/${exp.id}/results`)).results || [];
      $("tresults").innerHTML = resultsHtml(rows);
    } catch (e) {
      showError(String(e.message || e));
    }
  }
}

async function launchExperiment(expId) {
  const btn = $("launch");
  if (btn) btn.disabled = true;
  try {
    clearError();
    const j = await api(`/api/experiments/${expId}/launch`, { method: "POST" });
    await refreshAll();
    renderChrome();
    renderTest();
  } catch (e) {
    showError(String(e.message || e));
  }
}

async function syncOutcomes(expId) {
  const btn = $("sync");
  if (btn) btn.disabled = true;
  try {
    clearError();
    await api(`/api/experiments/${expId}/sync-outcomes`, { method: "POST" });
    await refreshAll();
    renderChrome();
    renderTest();
  } catch (e) {
    showError(String(e.message || e));
  }
}

async function evaluateExperiment(expId) {
  const btn = $("eval");
  if (btn) btn.disabled = true;
  try {
    clearError();
    const j = await api(`/api/experiments/${expId}/evaluate`, { method: "POST" });
    await refreshAll();
    renderChrome();
    go("results");
  } catch (e) {
    showError(String(e.message || e));
  }
}

// ---------------------------------------------------------------- screen: results

function verdictHtml(v, results, hypId) {
  const color = v.verdict === "Validated" ? "border-emerald-500 text-emerald-300"
    : v.verdict === "Rejected" ? "border-red-500 text-red-300" : "border-amber-500 text-amber-300";
  const t = results.find((x) => x.group === "treatment") || {};
  const c = results.find((x) => x.group === "control") || {};
  const icon = v.verdict === "Validated" ? "✓" : v.verdict === "Rejected" ? "✗" : "?";
  const headline = v.verdict === "Validated" ? "IT WORKS — bet proven" : v.verdict === "Rejected" ? "IT FAILED — bet disproven" : "UNCLEAR — test again";
  const score = v.verdict === "Inconclusive"
    ? `Treatment ${((t.rate || 0) * 100).toFixed(1)}% vs comparison ${((c.rate || 0) * 100).toFixed(1)}% — too close or too few people to call it (${v.reason}).`
    : `Treatment ${((t.rate || 0) * 100).toFixed(1)}% vs comparison ${((c.rate || 0) * 100).toFixed(1)}% — that's <b>${v.lift}x</b>.`;
  return `<div class="p-4 mt-3 rounded-xl bg-slate-800 border-2 ${color}">
    <p class="font-bold text-lg">${icon} ${headline}</p>
    <p class="text-sm mt-1">${score}</p>
    <p class="text-sm mt-1">${meaningSentence(v.verdict, v.lift, t.rate || 0, c.rate || 0)}</p>
    <p class="text-xs text-slate-400 mt-1">Based on ${v.n_total} people contacted.${hypId ? ` Full story: <button data-k="${hypId}" class="text-emerald-300 underline">open the learning →</button>` : ""}</p>
  </div>`;
}

async function loadKnowledge() {
  renderResults();
}

async function renderResults() {
  const el = $("view-results");
  const h = activeHypothesis();
  const list = h ? state.experiments.filter((e) => e.hypothesis_id === h.id) : [];
  const exp = list.length ? list[list.length - 1] : null;
  let verdict = "";
  if (exp && exp.status === "evaluated") {
    try {
      const rows = (await api(`/api/experiments/${exp.id}/results`)).results || [];
      const t = rows.find((x) => x.group === "treatment") || {};
      if (t.verdict) {
        verdict = verdictHtml(
          { verdict: t.verdict, lift: t.lift || 0, reason: "stored verdict",
            n_total: rows.reduce((a, x) => a + (x.sent || 0), 0) }, rows);
      }
    } catch (e) {
      showError(String(e.message || e));
    }
  }
  const kn = state.knowledge;
  el.innerHTML = `${screenHead("Results: what won, what to do next", "click any learning for the full story in plain words")}
    ${verdict || `<p class="text-sm text-slate-400 mt-3">No result yet — finish the test under Run the test and it lands here with the full story.</p>`}
    <p class="text-xs text-slate-400 mt-4 mb-1 font-semibold">WHAT WE LEARNED (${kn.length}) — click any card for the full story</p>
    ${kn.length ? `<div class="grid gap-2">${kn.map((k) => {
      const icon = k.verdict === "Validated" ? "✓" : k.verdict === "Rejected" ? "✗" : "?";
      const edge = k.verdict === "Validated" ? "border-emerald-600" : k.verdict === "Rejected" ? "border-red-600" : "border-amber-600";
      const plain = k.verdict === "Validated" ? "chase these customers" : k.verdict === "Rejected" ? "skip these customers" : "test again first";
      return `<button data-k="${k.hypothesis_id}" class="w-full text-left p-3 rounded-lg bg-slate-800 border ${edge} hover:border-emerald-400">
        <p class="font-semibold">${icon} ${k.hypothesis_id} — ${statusBadge(k.verdict)} </p>
        <p class="text-sm text-slate-200 mt-1">Bottom line: <b>${plain}</b></p>
        <p class="text-xs text-emerald-400 mt-1 font-semibold">Why? Click for the full story →</p>
      </button>`;
    }).join("")}</div>
    <div id="kdetail" class="mt-3"></div>
    <p class="text-sm text-slate-300 mt-3">${kn.some((k) => k.verdict === "Validated") ? "Sales next step: contact 500 more customers shaped like each proven winner." : "No proven winners yet — validate a bet first, then scale it."}</p>`
    : `<p class="text-sm text-slate-400">Empty — every finished test lands here, wins and losses.</p>`}
    ${screenFoot("")}`;
  el.querySelectorAll("[data-k]").forEach((b) =>
    b.addEventListener("click", () => {
      const k = state.knowledge.find((x) => x.hypothesis_id === b.dataset.k);
      if (k) {
        state.selectedKnowledge = b.dataset.k;
        $("kdetail").innerHTML = knowledgeDetail(k);
        $("kdetail").scrollIntoView({ block: "nearest" });
      }
    }));
}

function knowledgeDetail(k) {
  const traits = patternPlain(k.pattern || {});
  const icon = k.verdict === "Validated" ? "✓" : k.verdict === "Rejected" ? "✗" : "?";
  const title = k.verdict === "Validated" ? "Winner worth chasing" : k.verdict === "Rejected" ? "Dead end — skip it" : "Unclear — needs a bigger test";
  const why = k.verdict === "Validated"
    ? `Customers shaped like this replied about twice as often as ordinary ones in a head-to-head test. Put your salespeople on lookalikes first.`
    : k.verdict === "Rejected"
    ? `Looked promising in old data, but the live test flopped. Save your team wasted calls.`
    : `The test couldn't tell. Run it again with more people before betting on it.`;
  return `<div class="p-4 rounded-xl bg-slate-800 border-2 border-violet-600">
    <p class="font-bold">${icon} ${k.hypothesis_id}: ${title}</p>
    <p class="text-xs text-slate-400 mt-2 font-semibold">THE CUSTOMER TYPE</p>
    <ul class="mt-1">${traits.map((t) => `<li class="text-sm text-slate-200">✓ ${t}</li>`).join("")}</ul>
    <p class="text-xs text-slate-400 mt-2 font-semibold">WHAT IT MEANS FOR SALES</p>
    <p class="text-sm text-slate-200">${why}</p>
    <p class="text-xs text-slate-400 mt-2">${statusBadge(k.verdict)}</p>
  </div>`;
}

// ---------------------------------------------------------------- wiring

window.addEventListener("hashchange", () => {
  const name = (window.location.hash || "#/discover").replace("#/", "");
  if (name !== state.screen) showTab(name);
});

document.querySelectorAll("#tabs a").forEach((x) => {
  x.addEventListener("click", (e) => {
    if (x.dataset.locked) {
      e.preventDefault();
      showError("That step is locked — finish the earlier steps first (follow the green banner).");
    }
  });
});

$("reset").addEventListener("click", async () => {
  try {
    clearError();
    await api("/api/seed", { method: "POST" });
    // Clear ALL local state first: otherwise the stepper, banner, and
    // hidden screens keep showing the previous run after reset.
    state.selectedId = null;
    state.selectedKnowledge = null;
    state.hypotheses = [];
    state.experiments = [];
    state.knowledge = [];
    state.dataFetched = true;
    for (const v of SCREENS) $(`view-${v}`).innerHTML = "";
    renderChrome();
    go("data");
  } catch (e) {
    showError(String(e.message || e));
  }
});

(async function init() {
  const start = (window.location.hash || "#/data").replace("#/", "");
  await showTab(SCREENS.includes(start) ? start : "data");
})();
