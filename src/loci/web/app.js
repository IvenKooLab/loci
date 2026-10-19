/* loci web console — vanilla JS, no build step. Token lives in localStorage;
   every data call sends Bearer; 401 pops the login overlay. */
const $ = (s) => document.querySelector(s);
const TOKEN_KEY = "loci.token";
let token = localStorage.getItem(TOKEN_KEY) || "";
let me = null;                       // {label, role}
let memSelection = null;             // {name, isNew}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) { showLogin("session expired — sign in again"); throw new Error("401"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function showLogin(msg = "") {
  $("#login-err").textContent = msg;
  $("#login").classList.remove("hidden");
}
async function trySignIn() {
  token = $("#token").value.trim();
  try {
    await api("/health");
    localStorage.setItem(TOKEN_KEY, token);
    $("#login").classList.add("hidden");
    await boot();
  } catch (e) {
    showLogin(e.message === "401" ? "token rejected" : e.message);
  }
}

const isAdmin = () => me && me.role === "admin";
const isEditor = () => me && ["editor", "admin"].includes(me.role);

/* ---------- tabs ---------- */
document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    document.querySelectorAll("main section").forEach((s) => s.classList.add("hidden"));
    $(`#tab-${b.dataset.tab}`).classList.remove("hidden");
    if (b.dataset.tab === "mem") loadMemories();
    if (b.dataset.tab === "stats") loadStats();
    if (b.dataset.tab === "audit") loadAudit();
  })
);

/* ---------- overview ---------- */
function iconHtml(h) {
  return /\.(png|svg|jpe?g|gif|webp)$/i.test(h.icon)
    ? `<img src="/icons/${encodeURIComponent(h.icon)}" alt="">`
    : `<span class="icon">${h.icon}</span>`;
}

async function loadDash() {
  const { harness } = await api("/harness");
  const cards = $("#cards");
  cards.innerHTML = harness.map((h) => `
    <div class="card" data-name="${h.name}">
      <div class="head">${iconHtml(h)}
        <span class="name">${h.name}</span>
        <span class="badge ${h.summary.status}">${h.summary.status}</span>
      </div>
      <div class="meta">${h.files} files · ${h.chunks} chunks<br>updated ${h.last_updated || "—"}</div>
    </div>`).join("") || `<p class="muted">No [[harness]] entries configured.</p>`;
  cards.querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => openMemory(`harness/${c.dataset.name}.md`)));
}

async function runQuery() {
  const q = $("#q").value.trim(), ask = $("#ask").value.trim();
  const out = $("#answer");
  out.classList.remove("hidden");
  out.textContent = "…";
  try {
    out.textContent = ask
      ? (await api("/ask", { method: "POST", body: JSON.stringify({ question: ask }) })).result
      : (await api("/search", { method: "POST", body: JSON.stringify({ query: q || ask }) })).result;
  } catch (e) { out.textContent = `error: ${e.message}`; }
}

/* ---------- memories ---------- */
async function loadMemories() {
  const { memories } = await api("/memories");
  const filter = $("#mem-filter").value;
  const list = $("#mem-list");
  list.innerHTML = memories
    .filter((m) => !filter || m.group === filter)
    .map((m) => `<li data-name="${m.name}" class="${memSelection?.name === m.name ? "on" : ""}">
      ${m.title || m.name}<small>${m.group} · ${m.mtime} · ${m.size}B</small></li>`)
    .join("");
  list.querySelectorAll("li").forEach((li) =>
    li.addEventListener("click", () => openMemory(li.dataset.name)));
  $("#mem-new").style.display = isEditor() ? "" : "none";
}

async function openMemory(name) {
  const { text } = await api(`/memory?name=${encodeURIComponent(name)}`);
  memSelection = { name, isNew: false };
  $("#mem-title").textContent = name;
  $("#mem-text").value = text;
  $("#mem-text").removeAttribute("readonly");
  $("#mem-save").classList.toggle("hidden", !isEditor());
  $("#mem-del").classList.toggle("hidden", !(isEditor() && !name.startsWith("harness/")));
  highlightMem(name);
}

function highlightMem(name) {
  document.querySelectorAll("#mem-list li").forEach((li) =>
    li.classList.toggle("on", li.dataset.name === name));
}

function newMemory() {
  memSelection = { isNew: true };
  $("#mem-title").textContent = "new memory";
  $("#mem-text").value = "";
  $("#mem-save").classList.remove("hidden");
  $("#mem-del").classList.add("hidden");
}

async function saveMemory() {
  const text = $("#mem-text").value;
  try {
    if (memSelection?.isNew) {
      const first = text.split("\n").find((l) => l.trim()) || "memory";
      const title = first.replace(/^#*\s*/, "").slice(0, 60);
      await api("/memory", { method: "POST",
        body: JSON.stringify({ title, text }) });
    } else {
      await api("/memory", { method: "POST",
        body: JSON.stringify({ name: memSelection.name, text }) });
    }
    memSelection = null;
    await loadMemories();
  } catch (e) { alert(e.message); }
}

async function deleteMemory() {
  if (!memSelection?.name) return;
  if (!confirm(`Move ${memSelection.name} to .trash?`)) return;
  await api(`/memory?name=${encodeURIComponent(memSelection.name)}`,
    { method: "DELETE" });
  memSelection = null;
  $("#mem-title").textContent = "select a memory";
  $("#mem-text").value = "";
  $("#mem-save").classList.add("hidden");
  $("#mem-del").classList.add("hidden");
  await loadMemories();
}

/* ---------- index / audit ---------- */
async function loadStats() {
  const { stats, harness } = await api("/stats");
  let text = stats;
  if (harness?.length) {
    text += "\nharnesses:\n" + harness.map((h) =>
      `  ${h.name}  ${h.files} files / ${h.chunks} chunks  summary: ${h.summary.status}`).join("\n");
  }
  $("#stats-out").textContent = text;
  $("#ingest-btn").style.display = isAdmin() ? "" : "none";
  $("#summarize-btn").style.display = isAdmin() ? "" : "none";
}

async function loadAudit() {
  if (!isAdmin()) {
    $("#audit-table").nextElementSibling?.remove();
    $("#audit-table").outerHTML = "<p class='muted'>admin role required.</p>";
    return;
  }
  const { audit } = await api("/audit");
  $("#audit-table tbody").innerHTML = audit.map((a) =>
    `<tr><td>${a.ts}</td><td>${a.label}</td><td>${a.role}</td><td>${a.action}</td><td>${a.detail}</td></tr>`
  ).join("") || "<tr><td colspan=5 class='muted'>no events yet</td></tr>";
}

async function runIngest() {
  $("#busy").textContent = "indexing…";
  try {
    const { result } = await api("/ingest", { method: "POST", body: "{}" });
    $("#busy").textContent = "";
    await loadStats();
    $("#stats-out").textContent += "\n\n" + result;
  } catch (e) { $("#busy").textContent = e.message; }
}

async function runSummarize() {
  $("#busy").textContent = "summarizing…";
  try {
    const { result } = await api("/harness",
      { method: "POST", body: JSON.stringify({ action: "summarize" }) });
    $("#busy").textContent = "";
    await loadStats();
    $("#stats-out").textContent += "\n\n" + result;
  } catch (e) { $("#busy").textContent = e.message; }
}

/* ---------- boot ---------- */
$("#login-btn").addEventListener("click", trySignIn);
$("#token").addEventListener("keydown", (e) => e.key === "Enter" && trySignIn());
$("#qbtn").addEventListener("click", runQuery);
$("#askbtn").addEventListener("click", runQuery);
$("#mem-new").addEventListener("click", newMemory);
$("#mem-save").addEventListener("click", saveMemory);
$("#mem-del").addEventListener("click", deleteMemory);
$("#mem-filter").addEventListener("change", loadMemories);
$("#ingest-btn").addEventListener("click", runIngest);
$("#summarize-btn").addEventListener("click", runSummarize);

async function boot() {
  try {
    me = (await api("/health")).me || null;
    // /health returns role info so the console can show/hide controls
    $("#who").textContent = me ? `${me.label} · ${me.role}` : "";
    await loadDash();
  } catch (e) { /* login overlay already shown */ }
}

if (token) boot(); else showLogin();
