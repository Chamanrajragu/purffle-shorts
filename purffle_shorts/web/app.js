/* PurffleShorts Studio — no framework, no build step. Talks to the local JSON API in studio.py. */
"use strict";

const TOKEN = document.querySelector('meta[name="studio-token"]').content;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const I = {
  check: '<svg viewBox="0 0 24 24"><path d="M5 12.5 10 17 19 7"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>',
  info: '<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M12 10.5V16M12 7.6v.1"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M8 5.5v13l10-6.5z" fill="currentColor"/></svg>',
  pen: '<svg viewBox="0 0 24 24"><path d="M4 20h4.5L19 9.5 14.5 5 4 15.5z"/><path d="M12.5 7l4.5 4.5"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="M6.5 14.5 12 9l5.5 5.5"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="M6.5 9.5 12 15l5.5-5.5"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10.5 11v5.5M13.5 11v5.5"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  upload: '<svg viewBox="0 0 24 24"><path d="M12 15.5V4M7.5 8.5 12 4l4.5 4.5M4.5 15v4.5h15V15"/></svg>',
  dl: '<svg viewBox="0 0 24 24"><path d="M12 4v11.5M7.5 11l4.5 4.5 4.5-4.5M4.5 15v4.5h15V15"/></svg>',
  yt: '<svg viewBox="0 0 24 24"><rect x="3" y="5.5" width="18" height="13" rx="3.5"/><path d="M10.5 9.5v5l4-2.5z" fill="currentColor"/></svg>',
  spark: '<svg viewBox="0 0 24 24"><path d="M4 18l6.5-6.5M14 4v3M14 11v3M10 7.5h3M15 7.5h3M17.5 14.5l2 2"/><circle cx="14" cy="7.5" r="1.2" fill="currentColor"/></svg>',
  film: '<svg viewBox="0 0 24 24"><rect x="6" y="3.5" width="12" height="17" rx="1.5"/><path d="M6 7.5H3.5M6 12H3.5M6 16.5H3.5M18 7.5h2.5M18 12h2.5M18 16.5h2.5"/></svg>',
  doc: '<svg viewBox="0 0 24 24"><path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5M9 12.5h6.5M9 16h4.5"/></svg>',
  bulb: '<svg viewBox="0 0 24 24"><rect x="5" y="3.5" width="14" height="17" rx="1.2"/><path d="M8.5 8h7M8.5 11.5h7M8.5 15h4"/></svg>',
  scissors: '<svg viewBox="0 0 24 24"><circle cx="6.5" cy="6.5" r="2.8"/><circle cx="6.5" cy="17.5" r="2.8"/><path d="M8.7 8.2 20 17.5M8.7 15.8 20 6.5"/></svg>',
  chart: '<svg viewBox="0 0 24 24"><path d="M4 20h16M6.5 20v-6M11 20V8M15.5 20v-9M20 20V5"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/></svg>',
  copy: '<svg viewBox="0 0 24 24"><rect x="8.5" y="8.5" width="11" height="11" rx="1.2"/><path d="M15.5 8.5v-4h-11v11h4"/></svg>',
  arrow: '<svg viewBox="0 0 24 24"><path d="M5 12h13M13.5 7.5 18 12l-4.5 4.5"/></svg>',
};
// One line drawing per format, so the choice reads at a glance.
const G = {
  auto: '<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><circle cx="8.5" cy="8.5" r="1.3" fill="currentColor"/><circle cx="15.5" cy="15.5" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/></svg>',
  facts: '<svg viewBox="0 0 24 24"><path d="M9 6.5h11M9 12h8M9 17.5h10"/><circle cx="4.8" cy="6.5" r="1.2" fill="currentColor"/><circle cx="4.8" cy="12" r="1.2" fill="currentColor"/><circle cx="4.8" cy="17.5" r="1.2" fill="currentColor"/></svg>',
  story: '<svg viewBox="0 0 24 24"><path d="M3.5 17c3-6 5.5-6 8.5 0s5.5 0 8.5-9"/><circle cx="3.5" cy="17" r="1.5" fill="currentColor"/><path d="M20.5 8V4l-3 1.5"/></svg>',
  listicle: '<svg viewBox="0 0 24 24"><path d="M3.5 20.5h17M9 20.5V9.5h6v11M3.5 20.5v-6.5H9M15 20.5V12.5h5.5v8"/></svg>',
  myth: '<svg viewBox="0 0 24 24"><path d="M3.5 12.5l3 3 5-6"/><path d="M14.5 9l6 6M20.5 9l-6 6"/></svg>',
  quiz: '<svg viewBox="0 0 24 24"><path d="M4 5.5h16v10H11l-4.5 4v-4H4z"/><path d="M10.2 8.7a1.9 1.9 0 1 1 2.6 1.8c-.6.3-.8.6-.8 1.2M12 13.3v.1"/></svg>',
  explainer: '<svg viewBox="0 0 24 24"><circle cx="6.5" cy="12" r="3"/><circle cx="17.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/><path d="M9.2 10.7 15.2 7.6M9.2 13.3l6 3.1"/></svg>',
  motivational: '<svg viewBox="0 0 24 24"><path d="M3.5 19.5h4v-4h4v-4h4v-4h5"/><path d="M17 4.5h3.5V8"/></svg>',
  news: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="13" height="14" rx="1"/><path d="M16.5 9h4v8.5a1.5 1.5 0 0 1-3 0M6.5 9h7M6.5 12.5h7M6.5 16h4"/></svg>',
  dialogue: '<svg viewBox="0 0 24 24"><path d="M3.5 4.5h10v7H8l-3 2.5v-2.5H3.5z"/><path d="M16.5 9.5h4v7H19v2.5l-3-2.5h-5.5v-3"/></svg>',
  chat: '<svg viewBox="0 0 24 24"><rect x="6" y="2.5" width="12" height="19" rx="2"/><path d="M8.5 7h5M10.5 10.5h5M8.5 14h4"/><path d="M11 18.5h2"/></svg>',
  reddit: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="1.5"/><path d="M7.5 10.5 9.5 8l2 2.5M9.5 8v6M13.5 9h3.5M13.5 12h3.5M7.5 16.5h9.5"/></svg>',
};

const FORMATS = [
  ["auto", "Auto", "The AI picks the best format"],
  ["facts", "Facts", "Rapid-fire surprising facts"],
  ["story", "Story", "A true story with a twist"],
  ["listicle", "Top 3", "Countdown to number one"],
  ["myth", "Myth vs fact", "Bust a common belief"],
  ["quiz", "Quiz", "Question, suspense, answer"],
  ["explainer", "Explainer", "One idea, one analogy"],
  ["motivational", "Motivation", "A story and a takeaway"],
  ["news", "News", "What happened and why"],
  ["dialogue", "Dialogue", "Two voices, back and forth", true],
  ["chat", "Text story", "Animated text messages", true],
  ["reddit", "Reddit story", "Post card, then the story", true],
];
const MULTI = new Set(["dialogue", "chat"]);
const STAGES = [["topic", "Topic"], ["script", "Script"], ["review", "Review"], ["voice", "Voice"], ["footage", "Footage"],
  ["captions", "Captions"], ["render", "Render"], ["check", "Check"], ["upload", "Upload"]];
const STATUS_CHIP = { uploaded: "ok", scheduled: "blue", rendered: "accent", queued: "", failed: "bad" };
const VIEW_NO = { create: "01", library: "02", queue: "03", ideas: "04", clip: "05", channel: "06", system: "07" };
// The page heading: a numbered eyebrow, the title and one line of what the page is for.
function head(view, title, text, aside = "") {
  return `<div class="page-head"><div><p class="eyebrow"><b>${VIEW_NO[view] || "00"}</b>Studio</p><h1>${title}</h1>${text ? `<p>${text}</p>` : ""}</div>${aside}</div>`;
}
// A sheet's heading: its number in the brief, the title, and anything that sits on the right.
const sh = (n, title, aside = "") => `<header class="sheet-h"><span class="n">${n}</span><h2>${title}</h2>${aside ? `<span class="aside">${aside}</span>` : ""}</header>`;
const empty = (k, title, text) => `<div class="empty" data-k="${k}"><b>${title}</b>${text}</div>`;
const KIND_ICON = { make: I.film, draft: I.pen, clip: I.scissors, plan: I.bulb, upload: I.upload, stats: I.chart };

const store = {
  get(k, d) { try { const v = localStorage.getItem("purffle." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("purffle." + k, JSON.stringify(v)); } catch { /* private mode: fine */ } },
};

async function get(url) {
  const r = await fetch(url);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Studio-Token": TOKEN }, body: JSON.stringify(body || {}) });
  const data = await r.json().catch(() => ({}));
  if (r.status === 403 && data.error === "bad token") {  // the server restarted with a new session token
    throw new Error("The Studio was restarted. Reload this page to continue (your form and draft are kept).");
  }
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

const S = {
  info: null, options: null, jobs: [], view: "create",
  form: store.get("form", {}), draft: store.get("draft", null), createJob: store.get("createJob", null),
  lib: { status: "", q: "" }, seen: new Map(), voices: {}, live: false,
};

// ------------------------------------------------------------------ helpers
function toast(html, kind = "info", ms = 5200) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `${kind === "ok" ? I.check : kind === "bad" ? I.x : I.info}<div>${html}</div>`;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}
function paint(root = document) {  // CSP forbids inline styles: sizes are applied from data attributes
  $$("[data-w]", root).forEach(el => { el.style.width = Math.max(0, Math.min(100, +el.dataset.w)) + "%"; });
  $$("[data-p]", root).forEach(el => { el.style.setProperty("--p", el.dataset.p); el.style.setProperty("--c", scoreColor(+el.dataset.p)); });
}
const scoreColor = p => p >= 75 ? "var(--ok)" : p >= 55 ? "var(--accent)" : "var(--bad)";
const fmtSec = s => s == null ? "" : s >= 60 ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : `${Math.round(s)}s`;
const fmtNum = n => n == null ? "–" : Number(n).toLocaleString();
function ago(ts) {
  if (!ts) return "";
  const t = typeof ts === "number" ? ts * 1000 : Date.parse(ts);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
function seg(name, opts, cur) {
  return `<div class="seg" role="group">${opts.map(([v, label]) =>
    `<button type="button" data-seg="${name}" data-v="${esc(v)}" aria-pressed="${String(v) === String(cur)}">${label}</button>`).join("")}</div>`;
}
function sel(name, opts, cur) {
  return `<select data-f="${name}">${opts.map(([v, label]) => `<option value="${esc(v)}"${String(v) === String(cur) ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
}
const shortTitle = t => (t || "").replace(/\s*#shorts$/i, "");
const words = t => (t || "").trim().split(/\s+/).filter(Boolean).length;
const saveForm = () => store.set("form", S.form);
const saveDraft = () => store.set("draft", S.draft);

// ------------------------------------------------------------------ theme (light, dark, or the system's)
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
  $$("[data-theme-set]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.themeSet === (t || "auto"))));
  const dark = t === "dark" || (t !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  const meta = $('meta[name="theme-color"]');
  if (meta) meta.content = dark ? "#11100e" : "#f2eee5";
}
applyTheme(store.get("theme", "auto"));
document.addEventListener("click", e => {
  const b = e.target.closest("[data-theme-set]");
  if (b) { store.set("theme", b.dataset.themeSet); applyTheme(b.dataset.themeSet); }
});

// ------------------------------------------------------------------ boot & routing
async function boot() {
  try {
    [S.info, S.options] = await Promise.all([get("/api/info"), get("/api/options")]);
  } catch (e) {
    $("#main").innerHTML = empty("NO SIGNAL", "Can't reach the Studio server", esc(e.message));
    return;
  }
  const i = S.info;
  S.form = Object.assign({
    mode: "topic", topic: "", url: "", style: i.style || "auto", language: i.language, duration: i.duration,
    aspect: ["9:16", "16:9", "1:1", "4:5"].includes(i.aspect) ? i.aspect : "9:16", caption_style: i.caption_style,
    caption_position: i.caption_position, grade: i.grade, transition: i.transition, review: i.review, tts: i.tts,
    voice: "", voice_b: "", provider: "", model: "", also_langs: (i.also_languages || []).join(", "), music: true,
    upload: false, offline: !i.llm_ok, visuals: i.visuals, background: "", layout: "full", sfx: true, emphasis: true,
    emoji: true,
  }, S.form);
  if (!i.llm_ok) S.form.offline = true;
  status();
  window.addEventListener("hashchange", route);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeDrawer();
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && S.view === "create") startMake();
  });
  $("#drawer").addEventListener("click", e => { if (e.target.closest("[data-close]")) closeDrawer(); });
  route();
  tick();
  connectEvents();
  setInterval(() => { if (!S.live) tick(); }, 1500);  // polling only while the live stream is down
  setInterval(async () => { try { S.info = await get("/api/info"); status(); } catch { /* server restarting */ } }, 15000);
}

function status() {
  const i = S.info;
  $("#status").innerHTML = [
    ["Model", i.llm_ok ? i.llm : "demo only", !i.llm_ok], ["Voice", i.tts], ["Publish", i.upload ? `${Math.max(0, i.quota_left)} of ${i.daily_limit} today` : "off", !i.upload],
  ].map(([k, v, off]) => `<dt>${k}</dt><dd class="${off ? "off" : ""}" title="${esc(v)}">${esc(v)}</dd>`).join("");
  const ib = $("#ibadge");
  ib.hidden = !i.ideas;
  ib.textContent = i.ideas;
}

const VIEWS = { create: viewCreate, library: viewLibrary, queue: viewQueue, ideas: viewIdeas, clip: viewClip, channel: viewChannel, system: viewSystem };
function route() {
  const v = (location.hash || "#create").slice(1).split("/")[0];
  S.view = VIEWS[v] ? v : "create";
  $$("#nav a").forEach(a => a.classList.toggle("active", a.dataset.view === S.view));
  $("#main").innerHTML = "";
  VIEWS[S.view]();
  $("#main").focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------------ jobs: live stream, polling as fallback
// While the server is unreachable (stopped, restarting), retry less and less often, up to every 30 s.
const backoff = n => Math.min(30000, 1500 * 2 ** Math.min(n, 5));

function connectEvents() {
  if (!window.EventSource) return;
  const es = new EventSource("/api/events");
  es.addEventListener("jobs", e => {
    S.live = true;
    S.esFails = 0;
    let jobs;
    try { jobs = JSON.parse(e.data); } catch { return; }
    applyJobs(jobs);
  });
  es.onerror = () => {  // polling covers the gap; reconnect ourselves so a dead server isn't hammered
    S.live = false;
    es.close();
    S.esFails = (S.esFails || 0) + 1;
    setTimeout(connectEvents, backoff(S.esFails));
  };
}

async function tick() {
  if (Date.now() < (S.retryAt || 0)) return;
  let jobs;
  try {
    jobs = await get("/api/jobs");
    S.fails = 0;
    S.retryAt = 0;
  } catch {
    S.fails = (S.fails || 0) + 1;
    S.retryAt = Date.now() + backoff(S.fails);
    return;
  }
  applyJobs(jobs);
}

function applyJobs(jobs) {
  S.jobs = jobs;
  const active = jobs.filter(j => j.status === "running" || j.status === "queued").length;
  const qb = $("#qbadge");
  qb.hidden = !active;
  qb.textContent = active;
  for (const j of jobs) {
    const before = S.seen.get(j.id);
    S.seen.set(j.id, j.status);
    if (before && before !== j.status && ["done", "failed"].includes(j.status)) finished(j);
  }
  // A draft that finished while this page was closed or reloading still belongs in the editor.
  const cj = currentCreateJob();
  if (cj && cj.kind === "draft" && cj.status === "done" && !S.createJob.loaded) finished(cj);
  if (S.view === "queue") drawJobs();
  if (S.view === "create") drawLive();
}

function finished(j) {
  const r = j.result || {};
  if (j.kind === "draft" && j.status === "done" && currentCreateJob() === j) {
    if (S.createJob.loaded) return;
    S.createJob.loaded = true;
    store.set("createJob", S.createJob);
    S.draft = r.script;
    saveDraft();
    toast("Script ready — read it, edit anything, then render.", "ok");
    if (S.view === "create") drawSide();
    return;
  }
  if (j.status === "failed") {
    toast(`<b>${esc(j.label)}</b><br>${esc((r.error || j.message || "failed").slice(0, 220))}`, "bad", 9000);
  } else if (j.kind === "make" || j.kind === "clip") {
    const id = r.id || (r.clips && r.clips.find(c => c.ok) || {}).id;
    toast(`<b>${esc(r.title || j.label)}</b> is ready. ${id ? `<a href="#library" data-open="${id}">Watch it</a>` : ""}`, "ok", 9000);
  } else if (j.kind === "plan") {
    toast(`${r.ideas} new idea(s) in the queue.`, "ok");
    if (S.view === "ideas") viewIdeas();
  } else if (j.kind === "upload") {
    toast(`Upload: ${esc(r.status)}`, r.status === "failed" ? "bad" : "ok");
  } else if (j.kind === "stats") {
    toast(`Stats refreshed for ${r.updated} video(s).`, "ok");
    if (S.view === "channel") viewChannel();
  }
  get("/api/info").then(i => { S.info = i; status(); }).catch(() => {});
  if (S.view === "library") drawLibrary();
  if (S.view === "create") drawSide();
}

document.addEventListener("click", e => {
  const o = e.target.closest("[data-open]");
  if (o) { e.preventDefault(); if (S.view !== "library") location.hash = "#library"; openVideo(+o.dataset.open); }
});

// ------------------------------------------------------------------ CREATE
function payload(extra = {}) {
  const f = S.form;
  const p = {
    style: f.style === "auto" ? "" : f.style, language: f.language, duration: f.duration, aspect: f.aspect,
    caption_style: f.caption_style, caption_position: f.caption_position, grade: f.grade, transition: f.transition,
    tts: f.tts, voice: f.voice, voice_b: f.voice_b, provider: f.provider, model: f.model, review: f.review,
    also_langs: f.also_langs, music: f.music, upload: f.upload && S.info.upload && !f.offline, offline: f.offline,
    visuals: f.visuals, background: f.background || "", layout: f.layout, sfx: f.sfx !== false,
    emphasis: f.emphasis !== false, emoji: f.emoji !== false,
  };
  if (f.mode === "topic") p.topic = f.topic.trim();
  if (f.mode === "url") p.url = f.url.trim();
  if (f.mode === "queue") p.source = "queue";
  return Object.assign(p, extra);
}

async function startMake(extra = {}) {
  const f = S.form;
  if (f.mode === "url" && !f.url.trim() && !extra.script) return toast("Paste the address of a web page first.", "bad");
  try {
    const { job } = await post("/api/make", payload(extra));
    S.createJob = { id: job, kind: "make", session: TOKEN };
    store.set("createJob", S.createJob);
    S.seen.set(job, "queued");
    toast(extra.script ? "Rendering your script…" : "Making your video…", "info", 3000);
    drawSide();
    tick();
  } catch (e) { toast(esc(e.message), "bad"); }
}
async function startDraft() {
  const f = S.form;
  if (f.offline) return toast("Drafting needs an AI model. Turn off demo mode (and add a key in .env).", "bad");
  if (f.mode === "url" && !f.url.trim()) return toast("Paste the address of a web page first.", "bad");
  try {
    const { job } = await post("/api/draft", payload());
    S.createJob = { id: job, kind: "draft", session: TOKEN };
    store.set("createJob", S.createJob);
    S.seen.set(job, "queued");
    drawSide();
    tick();
  } catch (e) { toast(esc(e.message), "bad"); }
}

function viewCreate() {
  const i = S.info, f = S.form;
  $("#main").innerHTML = `
  ${head("create", "New Short", "Write the brief, then draft the script to read and edit it, or go straight to the render.")}
  ${i.llm_ok ? "" : `<div class="banner">${I.info}<p><b>No AI model is set up yet.</b> Demo mode renders a sample video with no keys. Add one API key (or run Ollama) in <span class="mono">.env</span> to write real scripts. <a href="#system">Check the setup</a></p></div>`}
  <div class="create"><div id="form"></div><div class="sticky" id="side"></div></div>`;
  drawForm();
  drawSide();
}

function drawForm() {
  const f = S.form, o = S.options;
  const langs = Object.entries(o.languages);
  const provs = [["", "Default (.env)"], ...o.providers.map(p => [p.name, `${p.label}${p.ready ? "" : " — no key"}`])];
  const multi = MULTI.has(f.style);
  $("#form").innerHTML = `
  <section class="card">
    ${sh("01", "What is it about?")}
    <div class="src-tabs">${seg("mode", [["topic", "Topic"], ["url", "Web page"], ["queue", "Idea queue"], ["auto", "Surprise me"]], f.mode)}</div>
    ${f.mode === "topic" ? `<div class="field big"><input type="text" data-f="topic" value="${esc(f.topic)}" placeholder="Why octopuses have three hearts" aria-label="Topic"><p class="hint">Broad or specific: the AI finds the surprising angle, using what people actually search for.</p></div>`
    : f.mode === "url" ? `<div class="field big"><input type="url" data-f="url" value="${esc(f.url)}" placeholder="https://… an article, a blog post or a Reddit post" aria-label="Web page"><p class="hint">The page's text becomes the script's source material.</p></div>`
    : f.mode === "queue" ? `<p class="hint">Uses the oldest idea in your queue (${i_ideas()} waiting). Plan more on the <a href="#ideas">Ideas</a> page.</p>`
    : `<p class="hint">Picks a fresh topic from your niches and topic sources in .env.</p>`}
  </section>

  <section class="card">
    ${sh("02", "Format", `${FORMATS.length} kinds`)}
    <div class="formats">${FORMATS.map(([k, name, blurb, isNew]) =>
      `<button type="button" class="fmt" data-seg="style" data-v="${k}" aria-pressed="${f.style === k}"><span class="g">${G[k] || G.auto}</span><b>${name}${isNew ? '<span class="new">new</span>' : ""}</b><span>${blurb}</span></button>`).join("")}</div>
  </section>

  <section class="card">
    ${sh("03", "Shape and voice")}
    <div class="grid2">
      <div class="field"><label>Language</label>${sel("language", langs.map(([c, n]) => [c, `${n} (${c})`]), f.language)}</div>
      <div class="field"><label>Length</label><div class="range-row"><input type="range" min="15" max="120" step="5" data-f="duration" value="${f.duration}" aria-label="Length in seconds"><output id="dur-out">${f.duration}s</output></div></div>
    </div>
    <div class="field"><label>Aspect</label>${seg("aspect", [["9:16", '<i class="shape s916"></i>9:16 Short'], ["16:9", '<i class="shape s169"></i>16:9 YouTube'], ["1:1", '<i class="shape s11"></i>1:1 Square'], ["4:5", '<i class="shape s45"></i>4:5 Feed']], f.aspect)}</div>
    <div class="grid2">
      <div class="field"><label>Voice engine</label>${sel("tts", o.tts.map(t => [t, { edge: "Microsoft neural (free)", openai: "OpenAI", elevenlabs: "ElevenLabs", kokoro: "Kokoro (local)", coqui: "Coqui (local)", system: "System voice" }[t] || t]), f.tts)}</div>
      <div class="field"><label>${multi ? "Voice A" : "Voice"}</label><input type="text" data-f="voice" list="voices" value="${esc(f.voice)}" placeholder="automatic for the language"></div>
    </div>
    ${multi ? `<div class="field"><label>Voice B (second speaker)</label><input type="text" data-f="voice_b" list="voices" value="${esc(f.voice_b)}" placeholder="automatic contrasting voice"></div>` : ""}
    <datalist id="voices"></datalist>
  </section>

  <section class="card">
    ${sh("04", "Look and sound")}
    <div class="swatches">${o.caption_styles.map(c => `<button type="button" class="sw" data-seg="caption_style" data-v="${c}" aria-pressed="${f.caption_style === c}">${capSample(c)}<small>${c}</small></button>`).join("")}</div>
    <div class="field"><label>Caption position</label>${seg("caption_position", [["upper", "Top"], ["center", "Middle"], ["lower", "Lower third"]], f.caption_position)}</div>
    <div class="grid2">
      <div class="field"><label>Colour grade</label>${sel("grade", o.grades.map(g => [g, g]), f.grade)}</div>
      <div class="field"><label>Transitions</label>${sel("transition", o.transitions.map(t => [t, t]), f.transition)}</div>
    </div>
    <div class="field"><label>Footage & images</label><div class="checks-inline">${o.visuals.map(v => `<label><input type="checkbox" data-visual="${v}"${(f.visuals || []).includes(v) ? " checked" : ""}>${{ pexels: "Pexels", pixabay: "Pixabay", local: "My media folder", pollinations: "AI images (Pollinations, key advised)", "openai-images": "OpenAI images" }[v] || v}</label>`).join("")}</div></div>
    <div class="field"><label>Background video</label>${(o.backgrounds || []).length
      ? sel("background", [["", "None: footage for every scene"], ...o.backgrounds.map(b => [b.path, b.name])], f.background)
      : `<p class="hint">Put gameplay or other videos you may reuse in <span class="mono">media/backgrounds/</span> (or set BACKGROUND_VIDEO) to play one under stories.</p>`}</div>
    ${f.background ? `<div class="field"><label>Layout</label>${seg("layout", [["full", "Full screen"], ["split", "Split: footage on top"]], f.layout)}</div>` : ""}
    <div class="grid2">
      <label class="switch"><input type="checkbox" data-f="music"${f.music ? " checked" : ""}><span>Background music<small>From your music folder, ducked under the voice</small></span></label>
      <label class="switch"><input type="checkbox" data-f="sfx"${f.sfx !== false ? " checked" : ""}><span>Sound effects<small>Whoosh on scene changes, pop per message</small></span></label>
    </div>
    <div class="grid2">
      <label class="switch"><input type="checkbox" data-f="emphasis"${f.emphasis !== false ? " checked" : ""}><span>Highlight key words<small>Numbers and the words that matter, in colour</small></span></label>
      <label class="switch"><input type="checkbox" data-f="emoji"${f.emoji !== false ? " checked" : ""}><span>Emoji<small>One per scene pops up above the captions</small></span></label>
    </div>
  </section>

  <section class="card">
    ${sh("05", "Model and publishing")}
    <div class="grid2">
      <div class="field"><label>AI model provider</label>${sel("provider", provs, f.provider)}</div>
      <div class="field"><label>Model</label><input type="text" data-f="model" value="${esc(f.model)}" placeholder="provider default"></div>
    </div>
    <div class="field"><label>Script Doctor</label>${seg("review", [["off", "Off"], ["score", "Score only"], ["rewrite", "Score & rewrite"]], f.review)}<p class="hint">A second AI pass grades the hook and pacing, then rewrites weak lines.</p></div>
    <div class="field"><label>Also make it in</label><input type="text" data-f="also_langs" value="${esc(f.also_langs)}" placeholder="e.g. es, hi, pt — translated copies, same footage"></div>
    <div class="grid2">
      <label class="switch"><input type="checkbox" data-f="upload"${f.upload ? " checked" : ""}${S.info.upload ? "" : " disabled"}><span>Publish when done<small>${S.info.upload ? publishTo() : "disabled in .env (UPLOAD=false)"}</small></span></label>
      <label class="switch"><input type="checkbox" data-f="offline"${f.offline ? " checked" : ""}><span>Demo mode<small>No keys: sample script, generated backgrounds</small></span></label>
    </div>
  </section>

  <div class="go-row">
    <button class="btn" id="draft-btn" type="button">${I.pen}Draft the script first</button>
    <button class="btn rec" id="make-btn" type="button"><span class="dot"></span>Create video<kbd>${/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"} ↵</kbd></button>
  </div>`;
  bindForm();
  loadVoices();
}
const i_ideas = () => S.info.ideas || 0;

function capSample(style, position = "") {
  const at = position === "upper" ? " at-upper" : position === "lower" ? " at-lower" : "";
  if (style === "karaoke") return `<span class="cap karaoke${at}"><u>THREE</u> <i>HEARTS</i></span>`;
  return `<span class="cap ${style}${at}">THREE <i>HEARTS</i></span>`;
}

function bindForm() {
  const root = $("#form");
  root.addEventListener("click", e => {
    const b = e.target.closest("[data-seg]");
    if (!b) return;
    const k = b.dataset.seg, v = b.dataset.v;
    const multiBefore = MULTI.has(S.form.style);
    S.form[k] = v;
    saveForm();
    if (k === "mode" || (k === "style" && MULTI.has(v) !== multiBefore)) return drawForm();
    $$(`[data-seg="${k}"]`, root).forEach(x => x.setAttribute("aria-pressed", String(x.dataset.v === v)));
    if (k === "caption_style" || k === "aspect" || k === "caption_position") drawSide();
  });
  root.addEventListener("input", e => {
    const el = e.target;
    if (el.dataset.visual) {
      S.form.visuals = $$("[data-visual]", root).filter(x => x.checked).map(x => x.dataset.visual);
    } else if (el.dataset.f) {
      S.form[el.dataset.f] = el.type === "checkbox" ? el.checked : el.type === "range" ? +el.value : el.value;
      if (el.dataset.f === "duration") $("#dur-out").textContent = el.value + "s";
      if (el.dataset.f === "language" || el.dataset.f === "tts") loadVoices();
      if (el.dataset.f === "background") { saveForm(); return drawForm(); }
    }
    saveForm();
  });
  $("#make-btn").onclick = () => startMake();
  $("#draft-btn").onclick = startDraft;
}

async function loadVoices() {
  const f = S.form, dl = $("#voices");
  if (!dl || f.tts !== "edge") { if (dl) dl.innerHTML = ""; return; }
  const lang = f.language;
  if (!S.voices[lang]) {
    try { S.voices[lang] = await get("/api/voices?lang=" + encodeURIComponent(lang)); } catch { S.voices[lang] = []; }
  }
  if (S.form.language === lang && $("#voices")) {
    $("#voices").innerHTML = S.voices[lang].map(v => `<option value="${esc(v.name)}">${esc(v.gender)} · ${esc(v.locale)}</option>`).join("");
  }
}

function currentCreateJob() {
  // Job ids restart with the server, so a job remembered from an earlier session is not this one.
  if (!S.createJob || S.createJob.session !== TOKEN) return null;
  return S.jobs.find(j => j.id === S.createJob.id) || null;
}

function drawSide() {
  const side = $("#side");
  if (!side) return;
  side.innerHTML = `<div id="live"></div><div id="editor"></div>`;
  drawLive();
  drawEditor();
}

function drawLive() {
  const box = $("#live");
  if (!box) return;
  const j = currentCreateJob();
  if (!j || (j.status === "done" && j.kind === "draft") || j.status === "cancelled") { box.innerHTML = ""; return; }
  const r = j.result || {};
  const idx = STAGES.findIndex(([k]) => k === j.stage);
  const running = j.status === "running" || j.status === "queued";
  const name = j.status === "queued" ? "Waiting for the previous job" : j.status === "failed" ? "Failed"
    : j.status === "done" ? "Finished" : (STAGES[idx] || [0, "Starting"])[1];
  const sig = `${j.id}:${j.status}:${j.stage}`;
  if (box.dataset.sig === sig && j.status === "running" && $("#live-pct", box)) {  // just the moving parts
    $("#live-pct", box).textContent = progressText(j);
    $("#live-msg", box).textContent = j.message || "";
    $("#live-bar", box).style.width = Math.min(100, j.pct) + "%";
    $("#live-log", box).textContent = j.log.slice(-8).join("\n");
    return;
  }
  box.dataset.sig = sig;
  box.innerHTML = `<section class="card live ${j.status}">
    <div class="lhead"><span class="status-pill ${j.status}">${j.kind === "draft" ? "Drafting" : "Making"} · ${j.status}</span>
      <span class="actions push">${running ? `<button class="btn ghost sm" data-cancel="${j.id}" type="button">Cancel</button>` : ""}
      ${!running ? `<button class="btn ghost sm" id="live-close" type="button" aria-label="Dismiss">${I.x}</button>` : ""}</span></div>
    <h3>${esc(r.title || j.label)}</h3>
    ${running ? `<div class="timeline" data-n="${STAGES.length}">${STAGES.map(([k, label], n) => `<span class="${n < idx ? "done" : n === idx ? "now" : ""}" title="${label}">${label}</span>`).join("")}</div>
      <div class="stage-name"><b>${esc(name)}</b><span id="live-pct">${esc(progressText(j))}</span></div>
      <div class="pbar"><i id="live-bar" data-w="${j.pct}"></i></div>
      <p class="hint" id="live-msg">${esc(j.message || "")}</p>` : ""}
    ${j.status === "done" && r.id ? `<div class="actions"><button class="btn primary sm" type="button" data-open="${r.id}">${I.play}Watch</button>
      ${r.score != null ? `<span class="chip ${r.score >= 75 ? "ok" : r.score >= 55 ? "accent" : "bad"}">Retention score ${r.score}</span>` : ""}
      <span class="chip">${esc(r.status)}</span>${(r.variants || []).map(v => `<span class="chip ${v.ok ? "ok" : "bad"}">${esc(v.language)} ${v.ok ? "✓" : "✗"}</span>`).join("")}</div>` : ""}
    ${j.status === "failed" ? `<div class="err">${esc(r.error || j.message)}</div>` : ""}
    ${running ? `<pre class="log" id="live-log">${esc(j.log.slice(-8).join("\n"))}</pre>` : ""}
  </section>`;
  paint(box);
  const c = $("#live-close");
  if (c) c.onclick = () => { S.createJob = null; store.set("createJob", null); drawSide(); };
  const x = $("[data-cancel]", box);
  if (x) x.onclick = () => post(`/api/jobs/${x.dataset.cancel}/cancel`).then(() => toast("Stopping…", "info", 2500)).catch(e => toast(esc(e.message), "bad"));
}

function progressText(j) {
  if (j.status !== "running") return j.message || "";
  return `${j.pct}%` + (j.eta != null ? ` · about ${fmtSec(Math.max(1, j.eta))} left` : "");
}

const RUBRIC = [["hook", "Hook"], ["curiosity", "Curiosity"], ["pacing", "Pacing"], ["specificity", "Specifics"], ["payoff", "Payoff"], ["accuracy", "Accuracy"]];
function rubricHtml(r) {
  if (!r || !RUBRIC.some(([k]) => r[k] != null)) return "";
  return `<div class="rubric">${RUBRIC.filter(([k]) => r[k] != null).map(([k, label]) =>
    `<div><span>${label}</span><span class="bar"><i data-w="${r[k] * 10}"></i></span><b>${r[k]}</b></div>`).join("")}</div>`;
}

function drawEditor() {
  const box = $("#editor");
  if (!box) return;
  const d = S.draft, f = S.form;
  const j = currentCreateJob();
  if (!d) {
    if (j && (j.status === "running" || j.status === "queued")) { box.innerHTML = ""; return; }
    const shape = { "9:16": "s916", "16:9": "s169", "1:1": "s11", "4:5": "s45" }[f.aspect] || "s916";
    const res = { "9:16": "1080×1920", "16:9": "1920×1080", "1:1": "1080×1080", "4:5": "1080×1350" }[f.aspect] || "";
    box.innerHTML = `<div class="monitor" aria-label="Preview">
      <div class="mhead"><span>Program monitor</span><span class="rec">Preview</span></div>
      <div class="frame ${shape}"><div class="bar"></div><div class="wm">${esc(S.info.channel || "")}</div><div class="ph-hook">This animal has 3 hearts</div>${capSample(f.caption_style, f.caption_position)}<span class="tc">00:00:02:14</span></div>
      <div class="spec"><span><b>${esc(res)}</b></span><span>${esc(f.aspect)}</span><span>${esc(f.caption_style)}</span><span>${esc(f.language)}</span></div>
    </div>
    <section class="card"><ol class="steps">
      <li><div><b>Draft the script</b><small>The AI writes it, the Script Doctor grades and tightens it, and you can change any line before rendering.</small></div></li>
      <li><div><b>Create the video</b><small>Voice, footage, word-synced captions, sound and the render in one go, usually about a minute.</small></div></li>
      <li><div><b>Publish</b><small>To YouTube, TikTok and Instagram from the Library, or switch on publishing here.</small></div></li>
    </ol></section>`;
    return;
  }
  const multi = MULTI.has(d.style) || d.scenes.some(s => s.speaker === "B");
  const total = d.scenes.reduce((n, s) => n + words(s.narration), 0);
  const target = Math.round((f.duration || 40) * 2.6);
  box.innerHTML = `<section class="card">
    ${sh("SC", "Script", `<span class="chip">${esc(d.style)}</span><span class="chip">${esc(d.language)}</span><span class="wc" id="wc">${total} words · ~${Math.round(total / 2.6)}s</span><button class="btn ghost sm" id="discard" type="button">${I.trash}Discard</button>`)}
    ${d.score != null ? `<div class="score"><div class="ring" data-p="${d.score}"><b>${d.score}</b></div><div class="grow"><b>Retention score</b>${rubricHtml(d.rubric)}${d.review && d.review.length ? `<ul>${d.review.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="hint">No issues found.</p>`}</div></div>` : ""}
    <div class="field"><label>Title</label><input type="text" data-k="title" value="${esc(d.title)}" maxlength="90"></div>
    <div class="field"><label>On-screen hook</label><input type="text" data-k="hook_text" value="${esc(d.hook_text)}" maxlength="48"></div>
    ${multi ? `<div class="grid2"><div class="field"><label>Speaker A</label><input type="text" data-cast="0" value="${esc((d.cast || [])[0] || "")}"></div>
      <div class="field"><label>Speaker B</label><input type="text" data-cast="1" value="${esc((d.cast || [])[1] || "")}"></div></div>` : ""}
    <div class="field"><label>Scenes <span class="hint">· target about ${target} words</span></label>
    <div class="scenes">${d.scenes.map((s, n) => `
      <div class="scene ${s.speaker === "B" ? "b" : "a"}${multi ? " multi" : ""}">
        <span class="num">${multi ? esc(s.speaker || "A") : String(n + 1).padStart(2, "0")}</span>
        <div class="field">
          <textarea data-i="${n}" data-s="narration" aria-label="Scene ${n + 1} narration">${esc(s.narration)}</textarea>
          <div class="row">
            ${multi ? `<button class="btn ghost sm" type="button" data-act="speaker" data-i="${n}" title="Switch speaker">A/B</button>` : ""}
            <input type="text" data-i="${n}" data-s="search_query" value="${esc(s.search_query)}" placeholder="footage search" aria-label="Footage search">
            <span class="tools">
              <button class="btn ghost sm" type="button" data-act="up" data-i="${n}" aria-label="Move up">${I.up}</button>
              <button class="btn ghost sm" type="button" data-act="down" data-i="${n}" aria-label="Move down">${I.down}</button>
              <button class="btn ghost sm" type="button" data-act="del" data-i="${n}" aria-label="Delete scene">${I.trash}</button>
            </span>
          </div>
        </div>
      </div>`).join("")}</div>
    <div class="actions"><button class="btn ghost sm" type="button" data-act="add">${I.plus}Add scene</button></div></div>
    <div class="field"><label>Description</label><textarea data-k="description">${esc(d.description)}</textarea></div>
    <div class="field"><label>Hashtags</label><input type="text" data-tags value="${esc((d.hashtags || []).join(" "))}"></div>
    <div class="go-row"><span></span><button class="btn rec" id="render-btn" type="button"><span class="dot"></span>Render this script</button></div>
  </section>`;
  paint(box);
  box.oninput = e => {
    const el = e.target;
    if (el.dataset.k) d[el.dataset.k] = el.value;
    else if (el.dataset.s) d.scenes[+el.dataset.i][el.dataset.s] = el.value;
    else if (el.dataset.cast) { d.cast = d.cast || ["", ""]; d.cast[+el.dataset.cast] = el.value; }
    else if (el.hasAttribute("data-tags")) d.hashtags = el.value.split(/\s+/).filter(Boolean);
    const t = d.scenes.reduce((n, s) => n + words(s.narration), 0);
    $("#wc").textContent = `${t} words · ~${Math.round(t / 2.6)}s`;
    saveDraft();
  };
  box.onclick = e => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const n = +b.dataset.i, sc = d.scenes;
    if (b.dataset.act === "del" && sc.length > 1) sc.splice(n, 1);
    if (b.dataset.act === "up" && n > 0) [sc[n - 1], sc[n]] = [sc[n], sc[n - 1]];
    if (b.dataset.act === "down" && n < sc.length - 1) [sc[n + 1], sc[n]] = [sc[n], sc[n + 1]];
    if (b.dataset.act === "speaker") sc[n].speaker = sc[n].speaker === "B" ? "A" : "B";
    if (b.dataset.act === "add") sc.push({ narration: "", search_query: "", image_prompt: "", speaker: sc.length && sc[sc.length - 1].speaker === "A" && multi ? "B" : "A" });
    saveDraft();
    drawEditor();
  };
  $("#discard").onclick = () => { if (confirm("Discard this script?")) { S.draft = null; saveDraft(); drawEditor(); } };
  $("#render-btn").onclick = () => {
    const clean = Object.assign({}, d, { scenes: d.scenes.filter(s => s.narration.trim()) });
    if (!clean.scenes.length) return toast("The script has no narration.", "bad");
    startMake({ script: clean, topic: "", url: "", source: "" });
  };
}

// ------------------------------------------------------------------ LIBRARY
function viewLibrary() {
  $("#main").innerHTML = `
  ${head("library", "Library", "Everything you have made. Open a video to watch it, edit and re-render it, publish it or delete it.")}
  <div class="toolbar">${seg("lib", [["", "All"], ["rendered", "Ready"], ["scheduled", "Scheduled"], ["uploaded", "Uploaded"], ["queued", "Queued"], ["failed", "Failed"]], S.lib.status)}
    <input type="search" id="lib-q" placeholder="Search titles" value="${esc(S.lib.q)}" aria-label="Search"></div>
  <div class="lib" id="lib"></div>`;
  $(".toolbar").addEventListener("click", e => {
    const b = e.target.closest("[data-seg]");
    if (!b) return;
    S.lib.status = b.dataset.v;
    $$("[data-seg=lib]").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.v === S.lib.status)));
    drawLibrary();
  });
  let t;
  $("#lib-q").oninput = e => { clearTimeout(t); t = setTimeout(() => { S.lib.q = e.target.value; drawLibrary(); }, 200); };
  drawLibrary();
  const deep = +(location.hash.split("/")[1] || 0);  // #library/12 opens video 12: a link to one video
  if (deep) openVideo(deep);
}

async function drawLibrary() {
  const box = $("#lib");
  if (!box) return;
  let vs;
  try { vs = await get(`/api/videos?status=${encodeURIComponent(S.lib.status)}&q=${encodeURIComponent(S.lib.q)}`); } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (!vs.length) {
    box.innerHTML = S.lib.status || S.lib.q ? empty("NO MATCH", "Nothing matches", "Try another filter or search.")
      : empty("EMPTY REEL", "No videos yet", `<a href="#create">Make your first Short</a> and it shows up here.`);
    return;
  }
  box.innerHTML = vs.map(v => `
    <button class="vcard" type="button" data-open="${v.id}">
      <div class="thumb">${v.has_cover ? `<img src="/files/${v.id}/cover.jpg" alt="" loading="lazy">` : `<div class="ph">${v.status === "failed" ? "failed" : "no frame"}</div>`}
        <div class="tl"><span class="chip ${STATUS_CHIP[v.status] || ""}">${esc(v.status)}</span>${v.score != null ? `<span class="chip">${v.score}</span>` : ""}</div>
        ${v.duration ? `<span class="dur">${fmtSec(v.duration)}</span>` : ""}</div>
      <div class="meta"><span class="sub">#${String(v.id).padStart(3, "0")} · ${esc(v.style || "video")}${v.language ? ` · ${esc(v.language)}` : ""}</span>
        <b>${esc(shortTitle(v.title) || "(untitled)")}</b>
        <span class="sub">${ago(v.created)}${v.parent_id ? " · translation" : ""}${v.views != null ? ` · ${fmtNum(v.views)} views` : ""}</span></div>
    </button>`).join("");
}

function publishTo() {
  const name = { youtube: "YouTube", tiktok: "TikTok", instagram: "Instagram", facebook: "Facebook", threads: "Threads", x: "X", linkedin: "LinkedIn", bluesky: "Bluesky", pinterest: "Pinterest" };
  const list = (S.info.publish_to || ["youtube"]).map(p => name[p] || p).join(", ");
  return `${list}${(S.info.publish_to || ["youtube"]).includes("youtube") ? ` · ${S.info.privacy}, or scheduled` : ""}`;
}
// Where a video still has to go: YouTube until it has an id, every other network until it is out.
const POSTED = new Set(["posted", "scheduled", "submitted", "draft"]);
function toPublish(v, m) {
  const done = m.published || {};
  return (S.info.publish_to || ["youtube"]).filter(p => p === "youtube" ? !v.youtube_id : !POSTED.has((done[p] || {}).status));
}
function postsHtml(published) {
  const items = Object.entries(published || {});
  if (!items.length) return "";
  const name = { tiktok: "TikTok", instagram: "Instagram", facebook: "Facebook", threads: "Threads", x: "X", linkedin: "LinkedIn", bluesky: "Bluesky", pinterest: "Pinterest" };
  return `<div class="chips posts">${items.map(([p, r]) => {
    const tone = POSTED.has(r.status) ? "ok" : r.status === "skipped" ? "" : "bad";
    const label = `${esc(name[p] || p)} · ${esc(r.status)}`;
    const tip = r.error ? ` title="${esc(r.error)}"` : "";
    return r.url && /^https:\/\//.test(r.url) ? `<a class="chip ${tone}" href="${esc(r.url)}" target="_blank" rel="noopener"${tip}>${label} ↗</a>` : `<span class="chip ${tone}"${tip}>${label}</span>`;
  }).join("")}</div>`;
}

async function openVideo(id) {
  let v;
  try { v = await get("/api/videos/" + id); } catch (e) { return toast(esc(e.message), "bad"); }
  const m = v.metadata || {}, sc = v.script;
  const panel = $("#drawer-panel");
  const review = m.review || [];
  panel.innerHTML = `
    <button class="btn ghost close" type="button" data-close aria-label="Close">${I.x}</button>
    <div class="player">${v.video ? `<video src="/files/${id}/${esc(v.video)}" controls playsinline preload="metadata"${v.has_cover ? ` poster="/files/${id}/cover.jpg"` : ""}></video>`
      : v.has_cover ? `<img src="/files/${id}/cover.jpg" alt="">` : empty("NO FILE", "The video file is gone", v.youtube_id ? "It lives on YouTube now." : "")}
      <div class="actions">${v.video ? `<a class="btn sm" href="/files/${id}/${esc(v.video)}?download=1">${I.dl}MP4</a>` : ""}${v.has_srt ? `<a class="btn sm" href="/files/${id}/captions.srt?download=1">${I.dl}Captions</a>` : ""}</div>
    </div>
    <div>
      <p class="eyebrow"><b>#${String(id).padStart(3, "0")}</b>Video</p>
      <div class="chips"><span class="chip ${STATUS_CHIP[v.status] || ""}">${esc(v.status)}</span>${v.style ? `<span class="chip">${esc(v.style)}</span>` : ""}${v.language ? `<span class="chip">${esc(v.language)}</span>` : ""}${v.parent_id ? `<span class="chip" data-open="${v.parent_id}">translation of #${v.parent_id}</span>` : ""}</div>
      <h2>${esc(v.title)}</h2>
      ${v.youtube_id ? `<p><a class="btn sm" href="https://youtube.com/shorts/${esc(v.youtube_id)}" target="_blank" rel="noopener">${I.yt}Open on YouTube</a>${v.publish_at ? ` <span class="muted">goes public ${esc(new Date(v.publish_at).toLocaleString())}</span>` : ""}</p>` : ""}
      ${postsHtml(m.published)}
      ${v.error ? `<div class="banner">${I.info}<p>${esc(v.error)}</p></div>` : ""}
      <div class="actions">
        ${v.video && toPublish(v, m).length ? `<button class="btn primary sm" type="button" id="d-up">${I.upload}Publish${toPublish(v, m).length < (S.info.publish_to || []).length ? " the rest" : ""}</button>` : ""}
        ${sc ? `<button class="btn sm" type="button" id="d-edit">${I.pen}Edit & re-render</button>` : ""}
        <button class="btn sm danger" type="button" id="d-del">${I.trash}Delete</button>
      </div>
      ${v.score != null ? `<div class="score"><div class="ring" data-p="${v.score}"><b>${v.score}</b></div><div class="grow"><b>Retention score</b>${rubricHtml(m.rubric)}${review.length ? `<ul>${review.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div></div>` : ""}
      <dl class="kv">
        <dt>Length</dt><dd>${fmtSec(v.duration)}</dd>
        ${m.resolution ? `<dt>Size</dt><dd>${esc(m.resolution)}</dd>` : ""}
        <dt>Voice</dt><dd>${esc(v.voice || m.voice || "")}</dd>
        <dt>Script by</dt><dd>${esc(v.llm || "")}</dd>
        ${v.topic ? `<dt>Topic</dt><dd>${esc(v.topic)}</dd>` : ""}
        ${v.views != null ? `<dt>Views</dt><dd>${fmtNum(v.views)} · ${fmtNum(v.likes)} likes · ${fmtNum(v.comments)} comments</dd>` : ""}
        <dt>Made</dt><dd>${esc(new Date(v.created_at).toLocaleString())}</dd>
        <dt>Folder</dt><dd class="mono" title="${esc(v.folder || "")}">${esc((v.folder || "").split(/[\\/]/).slice(-2).join("/"))}</dd>
      </dl>
      ${v.description ? `<div class="desc">${esc(v.description)}</div>` : ""}
      ${v.tags && v.tags.length ? `<div class="chips">${v.tags.map(t => `<span class="chip">${esc(t)}</span>`).join("")}</div>` : ""}
    </div>`;
  paint(panel);
  $("#drawer").hidden = false;
  document.body.style.overflow = "hidden";
  const up = $("#d-up");
  if (up) up.onclick = async () => { up.disabled = true; try { await post("/api/upload/" + id); toast("Upload queued — follow it in Queue.", "info"); tick(); } catch (e) { toast(esc(e.message), "bad"); } };
  const ed = $("#d-edit");
  if (ed) ed.onclick = () => {
    S.draft = Object.assign({}, sc, { title: (sc.title || "").replace(/\s*#shorts$/i, "") });
    saveDraft();
    if (sc.language) S.form.language = sc.language;
    if (sc.style) S.form.style = sc.style;
    saveForm();
    closeDrawer();
    location.hash = "#create";
    if (S.view === "create") route();
  };
  $("#d-del").onclick = async () => {
    if (!confirm("Delete this video and its folder from your computer? (Nothing is removed from YouTube.)")) return;
    try { await post(`/api/videos/${id}/delete`); closeDrawer(); toast("Deleted.", "ok"); drawLibrary(); } catch (e) { toast(esc(e.message), "bad"); }
  };
}
function closeDrawer() {
  const d = $("#drawer");
  if (d.hidden) return;
  $$("video", d).forEach(v => v.pause());
  d.hidden = true;
  document.body.style.overflow = "";
}

// ------------------------------------------------------------------ QUEUE
const openLogs = new Set();
function viewQueue() {
  $("#main").innerHTML = `${head("queue", "Queue", "Jobs run one at a time, in order. Each shows its live stage, time left and log.")}<div class="jobs" id="jobs"></div>`;
  drawJobs();
}
function drawJobs() {
  const box = $("#jobs");
  if (!box) return;
  if (!S.jobs.length) { box.innerHTML = empty("STANDING BY", "Nothing running", "Jobs you start from Create, Ideas or Clip show up here."); return; }
  const scroll = {};
  $$(".log", box).forEach(l => { scroll[l.dataset.id] = l.scrollHeight - l.scrollTop - l.clientHeight < 30; });
  box.innerHTML = S.jobs.map(j => {
    const r = j.result || {};
    const running = j.status === "running";
    const open = running || openLogs.has(j.id);
    const took = j.started ? Math.round(((j.finished || Date.now() / 1000) - j.started)) : null;
    const stage = (STAGES.find(([k]) => k === j.stage) || [0, j.stage])[1];
    return `<div class="job ${j.status}">
      <div class="job-top"><span class="jid">#${String(j.id).padStart(3, "0")}</span><span class="kind">${KIND_ICON[j.kind] || I.film}</span>
        <div class="t"><b>${esc(r.title || j.label)}</b><small><span class="status-pill ${j.status}">${j.status}</span>${running && stage ? ` · ${esc(stage)}` : ""}${running ? ` · ${esc(progressText(j))}` : ""}${running && j.message ? ` · ${esc(j.message)}` : ""}${took != null ? ` · ${fmtSec(took)}` : ""}</small></div>
        <span class="acts">${j.status === "queued" || running ? `<button class="btn ghost sm" type="button" data-cancel="${j.id}">Cancel</button>` : ""}
        ${j.status === "done" && r.id ? `<button class="btn sm" type="button" data-open="${r.id}">${I.play}Watch</button>` : ""}
        ${j.status === "done" && j.kind === "draft" ? `<a class="btn sm" href="#create">${I.pen}Edit</a>` : ""}
        <button class="btn ghost sm" type="button" data-log="${j.id}">${open ? "Hide log" : "Log"}</button></span>
      </div>
      ${running ? (() => { const idx = STAGES.findIndex(([k]) => k === j.stage);
        return `<div class="timeline">${STAGES.map(([k, label], n) => `<span class="${n < idx ? "done" : n === idx ? "now" : ""}">${label}</span>`).join("")}</div>`; })() : ""}
      ${j.status !== "cancelled" ? `<div class="pbar"><i data-w="${j.status === "failed" ? 100 : j.pct}"></i></div>` : ""}
      ${r.error ? `<div class="err">${esc(r.error)}</div>` : ""}
      ${r.clips ? `<div class="chips">${r.clips.map(c => `<span class="chip ${c.ok ? "ok" : "bad"}"${c.id ? ` data-open="${c.id}"` : ""}${c.reason ? ` title="${esc(c.reason)}"` : ""}>${esc(shortTitle(c.title) || "clip")}${c.score != null ? ` · <b>${c.score}</b>` : ""}</span>`).join("")}</div>` : ""}
      ${open ? `<pre class="log" data-id="${j.id}">${esc(j.log.join("\n")) || "…"}</pre>` : ""}
    </div>`;
  }).join("");
  paint(box);
  $$(".log", box).forEach(l => { if (scroll[l.dataset.id] !== false) l.scrollTop = l.scrollHeight; });
  box.onclick = async e => {
    const lg = e.target.closest("[data-log]");
    if (lg) { const id = +lg.dataset.log; openLogs.has(id) ? openLogs.delete(id) : openLogs.add(id); drawJobs(); }
    const c = e.target.closest("[data-cancel]");
    if (c) { await post(`/api/jobs/${c.dataset.cancel}/cancel`).catch(() => {}); tick(); }
  };
}

// ------------------------------------------------------------------ IDEAS
async function viewIdeas() {
  const main = $("#main");
  if (!main.innerHTML.trim()) main.innerHTML = head("ideas", "Ideas", "") + empty("LOADING", "Reading the idea queue…", "");
  let data;
  try { data = await get("/api/ideas"); } catch (e) { main.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (S.view !== "ideas") return;
  const styles = [["", "Any format"], ...FORMATS.filter(([k]) => k !== "auto").map(([k, n]) => [k, n])];
  main.innerHTML = `
  ${head("ideas", "Ideas", "Plan a week of videos in one go. The autopilot and Create's idea queue always use these first, oldest first.")}
  <div class="grid2">
    <section class="card">${sh("01", "Plan with AI", "uses real YouTube searches")}
      <div class="field"><label>Niche (optional)</label><input type="text" id="plan-niche" placeholder="e.g. space and the universe — blank uses your NICHES"></div>
      <div class="field"><label>How many</label><div class="range-row"><input type="range" id="plan-n" min="3" max="30" value="10"><output id="plan-out">10</output></div></div>
      <div class="actions end"><button class="btn primary" id="plan-go" type="button">${I.spark}Plan ideas</button></div>
    </section>
    <section class="card">${sh("02", "Add your own")}
      <div class="field"><label>Idea</label><input type="text" id="idea-s" placeholder="e.g. The man who survived two atomic bombs"></div>
      <div class="field"><label>Format</label><select id="idea-f">${styles.map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</select></div>
      <div class="actions end"><button class="btn" id="idea-add" type="button">${I.plus}Add to queue</button></div>
    </section>
  </div>
  <section class="card">${sh("03", "In the queue", `${data.pending.length} waiting`)}
    ${data.pending.length ? `<div class="list">${data.pending.map(i => `
      <div class="item"><span class="ix">#${String(i.id).padStart(3, "0")}</span>
        <div class="grow"><b>${esc(i.subject)}</b>${i.notes ? `<small>${esc(i.notes)}</small>` : ""}</div><span class="chip ${i.style ? "accent" : ""}">${esc(i.style || "auto")}</span>
        <button class="btn sm" type="button" data-make="${i.id}">${I.play}Make now</button>
        <button class="btn ghost sm" type="button" data-del="${i.id}" aria-label="Remove">${I.trash}</button></div>`).join("")}</div>`
      : empty("NOTHING PLANNED", "The queue is empty", "Plan some ideas with AI, or add your own.")}
  </section>
  ${data.used.length ? `<section class="card">${sh("04", "Recently made")}<div class="list">${data.used.map(i => `
      <div class="item"><span class="chip">${esc(i.style || "auto")}</span><div class="grow"><b>${esc(i.subject)}</b><small>${ago(i.used_at)}</small></div>
      ${i.video_id ? `<button class="btn ghost sm" type="button" data-open="${i.video_id}">${I.play}Watch</button>` : ""}</div>`).join("")}</div></section>` : ""}`;
  $("#plan-n").oninput = e => { $("#plan-out").textContent = e.target.value; };
  $("#plan-go").onclick = async () => {
    try { await post("/api/plan", { count: +$("#plan-n").value, niche: $("#plan-niche").value }); toast("Planning ideas… (see Queue)", "info"); tick(); }
    catch (e) { toast(esc(e.message), "bad"); }
  };
  $("#idea-add").onclick = async () => {
    const s = $("#idea-s").value.trim();
    if (!s) return;
    try { await post("/api/ideas", { subject: s, style: $("#idea-f").value }); viewIdeas(); refreshInfo(); } catch (e) { toast(esc(e.message), "bad"); }
  };
  main.onclick = async e => {
    const d = e.target.closest("[data-del]"), m = e.target.closest("[data-make]");
    if (d) { await post(`/api/ideas/${d.dataset.del}/delete`).catch(() => {}); viewIdeas(); refreshInfo(); }
    if (m) {
      const idea = data.pending.find(i => i.id === +m.dataset.make);
      await post(`/api/ideas/${idea.id}/delete`).catch(() => {});
      const topic = idea.notes ? `${idea.subject} (angle: ${idea.notes})` : idea.subject;
      try { await post("/api/make", payload({ topic, url: "", source: "", style: idea.style || "" })); toast("Making it now — see Queue.", "info"); tick(); viewIdeas(); refreshInfo(); }
      catch (err) { toast(esc(err.message), "bad"); }
    }
  };
}
async function refreshInfo() { try { S.info = await get("/api/info"); status(); } catch { /* ignore */ } }

// ------------------------------------------------------------------ CLIP
function viewClip() {
  const c = Object.assign({ source: "", count: 3, crop: "center", upload: false, brief: "", jump_cuts: true, zoom: true },
    store.get("clip", {}));
  $("#main").innerHTML = `
  ${head("clip", "Clip a long video", "Turn a podcast, interview, talk or stream into Shorts of its best moments, edited and captioned.")}
  <div class="create">
    <section class="card">${sh("01", "Source and edit")}
      <div class="field"><label>Video file or URL</label><input type="text" id="c-src" value="${esc(c.source)}" placeholder="/Users/me/Videos/podcast.mp4  or  https://…"><p class="hint">Local files work out of the box. URLs need <span class="mono">pip install yt-dlp</span>. Only clip videos you own or may reuse.</p></div>
      <div class="grid2">
        <div class="field"><label>Clips</label><div class="range-row"><input type="range" id="c-n" min="1" max="10" value="${c.count}"><output id="c-out">${c.count}</output></div></div>
        <div class="field"><label>Framing</label>${seg("crop", [["center", "Fill (crop)"], ["face", "Follow face"], ["blur", "Fit + blur"]], c.crop)}</div>
      </div>
      <div class="field"><label>What to look for <span class="muted">(optional)</span></label><input type="text" id="c-brief" value="${esc(c.brief)}" placeholder="e.g. the funniest moments, or every tip about sleep"><p class="hint">The AI only picks moments that fit. Needs an AI model.</p></div>
      <div class="grid2">
        <label class="switch"><input type="checkbox" id="c-cuts"${c.jump_cuts ? " checked" : ""}><span>Cut pauses and ums<small>Tighter pacing, lips stay in sync</small></span></label>
        <label class="switch"><input type="checkbox" id="c-zoom"${c.zoom ? " checked" : ""}><span>Punch-in zoom<small>Changes framing between sentences</small></span></label>
      </div>
      <div class="field"><label class="switch"><input type="checkbox" id="c-up"${c.upload ? " checked" : ""}${S.info.upload ? "" : " disabled"}><span>Upload the clips when done</span></label></div>
      <div class="go-row"><span></span><button class="btn rec" id="c-go" type="button"><span class="dot"></span>Find the best moments</button></div>
    </section>
    <section class="card">${sh("02", "How it works")}<ol class="steps">
      <li><div><b>Transcribe</b><small>Word-level timing with faster-whisper (free, on this computer) or OpenAI.</small></div></li>
      <li><div><b>The AI picks the moments</b><small>Self-contained, 20–58 s, a hook in the first line and a payoff at the end. Each gets a title and a virality score with the reason.</small></div></li>
      <li><div><b>Edited, vertical, captioned</b><small>Pauses and ums cut, punch-in zoom, face-following or blurred-fit 9:16, word-by-word captions, loudness at −14 LUFS.</small></div></li>
    </ol></section>
  </div>`;
  const save = () => store.set("clip", c);
  $("#c-n").oninput = e => { c.count = +e.target.value; $("#c-out").textContent = c.count; save(); };
  $("#c-src").oninput = e => { c.source = e.target.value; save(); };
  $("#c-up").onchange = e => { c.upload = e.target.checked; save(); };
  $("#c-brief").oninput = e => { c.brief = e.target.value; save(); };
  $("#c-cuts").onchange = e => { c.jump_cuts = e.target.checked; save(); };
  $("#c-zoom").onchange = e => { c.zoom = e.target.checked; save(); };
  $("#main").addEventListener("click", e => {
    const b = e.target.closest("[data-seg=crop]");
    if (b) { c.crop = b.dataset.v; $$("[data-seg=crop]").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.v === c.crop))); save(); }
  });
  $("#c-go").onclick = async () => {
    if (!c.source.trim()) return toast("Give a video file path or URL.", "bad");
    try { await post("/api/clip", { source: c.source.trim(), count: c.count, crop: c.crop, upload: c.upload, brief: c.brief.trim(), jump_cuts: c.jump_cuts, zoom: c.zoom }); toast("Clipping… follow it in Queue.", "info"); tick(); }
    catch (e) { toast(esc(e.message), "bad"); }
  };
}

// ------------------------------------------------------------------ CHANNEL
function calibrationCard(c) {
  const rho = c.score_vs_views;
  const tone = rho == null ? "" : rho >= 0.5 ? "ok" : rho >= 0.25 ? "accent" : "bad";
  return `<section class="card">${sh("02", "Do the predictions hold up?")}
    <p>${rho != null ? `<span class="chip ${tone}">ρ = ${rho.toFixed(2)}</span> ` : ""}Retention score vs real views: ${esc(c.verdict)}.
      <span class="muted">Spearman rank correlation over ${c.scored} scored video(s) that have been public for 2+ days.</span></p>
    ${c.hours.length ? `<p class="muted">Best publish hours (your time): ${c.hours.map(h => `<b>${String(h.hour).padStart(2, "0")}:00</b> ${fmtNum(h.median_views)}`).join(" · ")}</p>` : ""}
  </section>`;
}

async function viewChannel() {
  const main = $("#main");
  if (!main.innerHTML.trim()) main.innerHTML = head("channel", "Channel", "") + empty("LOADING", "Reading your channel…", "");
  let ch;
  try { [ch, S.info] = await Promise.all([get("/api/channel"), get("/api/info")]); } catch (e) { main.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (S.view !== "channel") return;
  const i = S.info, cnt = i.counts || {};
  const live = (cnt.uploaded || 0) + (cnt.scheduled || 0);
  const top = Math.max(1, ...ch.by_style.map(s => s.avg_views));
  main.innerHTML = `
  ${head("channel", "Channel", `How your uploads are doing${ch.synced ? `, with stats from ${ago(ch.synced)}` : ""}.`, `<button class="btn" id="sync" type="button">${I.refresh}Refresh stats</button>`)}
  ${i.learn_from_stats ? "" : `<div class="banner">${I.spark}<p>Set <span class="mono">LEARN_FROM_STATS=true</span> in .env and new scripts will learn from what performs best here. Add <span class="mono">YOUTUBE_API_KEY</span> (or run <span class="mono">purffle-shorts auth</span> again) so stats can be read.</p></div>`}
  <div class="kpis">
    <div class="kpi"><small>Videos made</small><b>${fmtNum(i.total)}</b></div>
    <div class="kpi"><small>On YouTube</small><b>${fmtNum(live)}</b></div>
    <div class="kpi"><small>Total views</small><b>${fmtNum(i.views)}</b></div>
    <div class="kpi"><small>Ideas queued</small><b>${fmtNum(i.ideas)}</b></div>
  </div>
  ${ch.calibration && ch.calibration.videos ? calibrationCard(ch.calibration) : ""}
  ${ch.videos.length ? `<div class="grid2">
    <section class="card">${sh("03", "Average views by format")}${ch.by_style.map(s => `<div class="hbar"><span>${esc(s.style)}</span><span class="track"><i data-w="${100 * s.avg_views / top}"></i></span><span class="num">${fmtNum(s.avg_views)}</span></div>`).join("")}</section>
    <section class="card">${sh("04", "Best performer")}${(() => { const v = ch.videos[0]; return `<h3>${esc(v.title)}</h3><p class="muted">${fmtNum(v.views)} views · ${fmtNum(v.likes)} likes · ${esc(v.style || "")}</p><button class="btn sm" type="button" data-open="${v.id}">${I.play}Open</button>`; })()}</section>
  </div>
  <section class="card">${sh("05", "Videos")}<table><thead><tr><th>Title</th><th>Format</th><th class="num">Score</th><th class="num">Views</th><th class="num">Likes</th></tr></thead>
    <tbody>${ch.videos.map(v => `<tr><td><a href="#library" data-open="${v.id}">${esc(v.title)}</a></td><td>${esc(v.style || "")}</td><td class="num">${v.score ?? "–"}</td><td class="num">${fmtNum(v.views)}</td><td class="num">${fmtNum(v.likes)}</td></tr>`).join("")}</tbody></table></section>`
    : empty("NO DATA YET", "No stats yet", "Publish some videos, then refresh. View counts need a day or two to mean something.")}`;
  paint(main);
  $("#sync").onclick = async () => { try { await post("/api/stats"); toast("Refreshing stats…", "info"); tick(); } catch (e) { toast(esc(e.message), "bad"); } };
}

// ------------------------------------------------------------------ SYSTEM
async function viewSystem() {
  const main = $("#main");
  main.innerHTML = `${head("system", "System", "Setup checks, settings and ways to drive PurffleShorts from other tools.")}<div id="sys">${empty("RUNNING CHECKS", "Checking your setup…", "")}</div>`;
  let checks;
  try { checks = await get("/api/doctor"); } catch (e) { $("#sys").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (S.view !== "system") return;
  const bad = checks.filter(c => c.ok === false).length;
  const mcp = JSON.stringify({ mcpServers: { "purffle-shorts": { command: "purffle-shorts", args: ["mcp"], env: { PURFFLE_HOME: "/path/to/your/purffle/folder" } } } }, null, 2);
  $("#sys").innerHTML = `
  <section class="card">${sh("01", "Setup", bad ? `<span class="chip bad">${bad} to fix</span>` : `<span class="chip ok">all good</span>`)}
    <div class="checks">${checks.map(c => `<div class="check"><span class="m ${c.ok === true ? "ok" : c.ok === false ? "bad" : "info"}">${c.ok === true ? "✓" : c.ok === false ? "✕" : "·"}</span><span>${esc(c.label)}</span><span>${esc(c.detail)}</span></div>`).join("")}</div>
    <p class="hint">Settings live in <span class="mono">.env</span> next to where you started the Studio. Restart it after editing.</p></section>
  <div class="grid2">
    <section class="card">${sh("02", "Use it from Claude and other AI apps")}
      <p class="muted">Add this to Claude Desktop, Claude Code, Cursor or any MCP client, then ask: “make a 30-second Short about why cats purr”.</p>
      <pre class="code" id="mcp">${esc(mcp)}</pre><div class="actions end"><button class="btn sm" id="copy" type="button">${I.copy}Copy</button></div></section>
    <section class="card">${sh("03", "Command line")}<pre class="code">purffle-shorts run                 # autopilot
purffle-shorts make --style chat   # one video
purffle-shorts make --url https://…
purffle-shorts clip talk.mp4 --count 3
purffle-shorts plan --count 14
purffle-shorts stats
purffle-shorts doctor</pre></section>
  </div>
  <p class="hint">PurffleShorts ${esc(S.info.version)} · <a href="https://github.com/Chamanrajragu/purffle-shorts" target="_blank" rel="noopener">GitHub</a></p>`;
  $("#copy").onclick = async () => { try { await navigator.clipboard.writeText(mcp); toast("Copied.", "ok", 2000); } catch { toast("Select the text and copy it.", "info"); } };
}

boot();
