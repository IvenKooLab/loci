/* loci web console — vanilla JS, no build step.
   Anonymous from localhost: the server trusts loopback as admin, no login.
   Remote / strict mode: 401 pops the login overlay. UI language: 中/EN. */
const $ = (s) => document.querySelector(s);
const TOKEN_KEY = "loci.token";
const LANG_KEY = "loci.lang";
let token = localStorage.getItem(TOKEN_KEY) || "";
let me = null;                       // {label, role}
let memSelection = null;             // {name, isNew}

/* ---------- i18n ---------- */
const I18N = {
  en: {
    title: "loci console",
    navDash: "Overview", navMem: "Memories", navStats: "Index", navAudit: "Audit",
    phSearch: "Search the knowledge base…", phAsk: "Ask a question…",
    btnSearch: "Search", btnAsk: "Ask",
    hHarnesses: "Harnesses",
    optAll: "all", optShared: "shared", optHarness: "harness",
    btnNew: "＋ New memory", pickNote: "select a memory",
    btnSave: "Save", btnDelete: "Delete",
    phEditor: "pick a note on the left, or create a new one",
    btnIngest: "Re-index (ingest)", btnSummarize: "Re-summarize harnesses",
    auditNote: "Write & admin events since the service last restarted (full history in the service log).",
    adminRequired: "admin role required.",
    thTime: "time", thWho: "who", thRole: "role", thAction: "action", thDetail: "detail",
    noEvents: "no events yet",
    loginTitle: "loci console",
    loginHint: "This instance requires a token. Paste one from [[auth.tokens]] in config.toml.",
    phToken: "Bearer token", btnSignin: "Sign in",
    expired: "session expired — sign in again", rejected: "token rejected",
    noHarness: "No [[harness]] entries configured.",
    files: "files", chunks: "chunks", updated: "updated",
    fresh: "fresh", stale: "stale", missing: "missing",
    indexing: "indexing…", summarizing: "summarizing…",
    confirmDelete: (n) => `Move ${n} to .trash?`,
    errorPrefix: "error: ",
  },
  zh: {
    title: "loci 管理台",
    navDash: "总览", navMem: "记忆", navStats: "索引", navAudit: "审计",
    phSearch: "搜索知识库…", phAsk: "输入问题…",
    btnSearch: "搜索", btnAsk: "提问",
    hHarnesses: "工具（Harness）",
    optAll: "全部", optShared: "共享记忆", optHarness: "工具记忆",
    btnNew: "＋ 新建记忆", pickNote: "选择左侧记忆",
    btnSave: "保存", btnDelete: "删除",
    phEditor: "在左侧选择一条记忆，或新建一条",
    btnIngest: "重建索引（ingest）", btnSummarize: "重新生成 harness 摘要",
    auditNote: "自服务上次重启以来的写入与管理事件（完整历史见服务日志）。",
    adminRequired: "需要 admin 角色。",
    thTime: "时间", thWho: "操作者", thRole: "角色", thAction: "动作", thDetail: "详情",
    noEvents: "暂无事件",
    loginTitle: "loci 管理台",
    loginHint: "本实例要求鉴权。请粘贴 config.toml 中 [[auth.tokens]] 里的 token。",
    phToken: "Bearer token", btnSignin: "登录",
    expired: "会话过期——请重新登录", rejected: "token 被拒绝",
    noHarness: "尚未配置 [[harness]] 条目。",
    files: "个文件", chunks: "块", updated: "更新于",
    fresh: "最新", stale: "待更新", missing: "未生成",
    indexing: "索引中…", summarizing: "总结中…",
    confirmDelete: (n) => `把 ${n} 移入 .trash？`,
    errorPrefix: "错误：",
  },
};
let lang = localStorage.getItem(LANG_KEY)
  || ((navigator.language || "en").toLowerCase().startsWith("zh") ? "zh" : "en");
const t = (k, ...a) => {
  const v = (I18N[lang] ?? I18N.en)[k] ?? I18N.en[k] ?? k;
  return typeof v === "function" ? v(...a) : v;
};
function applyI18n() {
  document.documentElement.lang = lang;
  document.title = t("title");
  document.querySelectorAll("[data-i18n]").forEach((el) => el.textContent = t(el.dataset.i18n));
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => el.placeholder = t(el.dataset.i18nPh));
  $("#lang-btn").textContent = lang === "zh" ? "EN" : "中文";
}
$("#lang-btn").addEventListener("click", () => {
  lang = lang === "zh" ? "en" : "zh";
  localStorage.setItem(LANG_KEY, lang);
  applyI18n();
  refreshActiveTab();
});

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) { showLogin(t("expired")); throw new Error("401"); }
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
    showLogin(e.message === "401" ? t("rejected") : e.message);
  }
}

const isAdmin = () => !!me && me.role === "admin";
const isEditor = () => !!me && ["editor", "admin"].includes(me.role);

/* ---------- tabs ---------- */
function refreshActiveTab() {
  const on = document.querySelector("nav button.on");
  const tab = on ? on.dataset.tab : "dash";
  if (tab === "mem") loadMemories();
  if (tab === "stats") loadStats();
  if (tab === "audit") loadAudit();
  if (tab === "dash") loadDash();
}
document.querySelectorAll("nav button[data-tab]").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("nav button[data-tab]").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    document.querySelectorAll("main section").forEach((s) => s.classList.add("hidden"));
    $(`#tab-${b.dataset.tab}`).classList.remove("hidden");
    refreshActiveTab();
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
        <span class="name">${h.display || h.name}</span>
        <span class="badge ${h.summary.status}">${t(h.summary.status)}</span>
      </div>
      <div class="meta">${h.files} ${t("files")} · ${h.chunks} ${t("chunks")}<br>${t("updated")} ${h.last_updated || "—"}</div>
    </div>`).join("")
    || `<p class="muted">${t("noHarness")}</p>`;
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
  } catch (e) { out.textContent = t("errorPrefix") + e.message; }
}

/* ---------- memories ---------- */
async function loadMemories() {
  const { memories } = await api("/memories");
  const filter = $("#mem-filter").value;
  const list = $("#mem-list");
  list.innerHTML = memories
    .filter((m) => !filter || m.group === filter)
    .map((m) => `<li data-name="${m.name}" class="${memSelection?.name === m.name ? "on" : ""}">
      ${m.title || m.name}<small>${m.group === "shared" ? t("optShared") : t("optHarness")} · ${m.mtime} · ${m.size}B</small></li>`)
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
  $("#mem-title").textContent = t("btnNew");
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
    $("#mem-title").textContent = t("pickNote");
    await loadMemories();
  } catch (e) { alert(e.message); }
}

async function deleteMemory() {
  if (!memSelection?.name) return;
  if (!confirm(t("confirmDelete", memSelection.name))) return;
  await api(`/memory?name=${encodeURIComponent(memSelection.name)}`,
    { method: "DELETE" });
  memSelection = null;
  $("#mem-title").textContent = t("pickNote");
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
    text += "\n" + t("hHarnesses") + ":\n" + harness.map((h) =>
      `  ${h.name}  ${h.files} ${t("files")} / ${h.chunks} ${t("chunks")}  ${t("updated")}: ${h.summary.status}`).join("\n");
  }
  $("#stats-out").textContent = text;
  $("#ingest-btn").style.display = isAdmin() ? "" : "none";
  $("#summarize-btn").style.display = isAdmin() ? "" : "none";
}

async function loadAudit() {
  const admin = isAdmin();
  $("#audit-hint").classList.toggle("hidden", admin);
  $("#audit-table").classList.toggle("hidden", !admin);
  if (!admin) { $("#audit-hint").textContent = t("adminRequired"); return; }
  const { audit } = await api("/audit");
  $("#audit-table tbody").innerHTML = audit.map((a) =>
    `<tr><td>${a.ts}</td><td>${a.label}</td><td>${a.role}</td><td>${a.action}</td><td>${a.detail}</td></tr>`
  ).join("") || `<tr><td colspan=5 class="muted">${t("noEvents")}</td></tr>`;
}

async function runIngest() {
  $("#busy").textContent = t("indexing");
  try {
    const { result } = await api("/ingest", { method: "POST", body: "{}" });
    $("#busy").textContent = "";
    await loadStats();
    $("#stats-out").textContent += "\n\n" + result;
  } catch (e) { $("#busy").textContent = e.message; }
}

async function runSummarize() {
  $("#busy").textContent = t("summarizing");
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
  applyI18n();
  try {
    const h = await api("/health");
    me = h.me || null;
    $("#who").textContent = me ? `${me.label} · ${me.role}` : "";
    await loadDash();
  } catch (e) { /* login overlay shown on 401; other errors surface inline */ }
}

applyI18n();
boot();
