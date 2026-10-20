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
    tagline: "Shared memory layer for your AI coding tools",
    navDash: "Overview", navMem: "Memories", navStats: "Index", navAudit: "Audit",
    phSearch: "Search the knowledge base…", phAsk: "Ask a question…",
    btnSearch: "Search", btnAsk: "Ask",
    hHarnesses: "Harnesses",
    optAll: "all", optShared: "shared", optHarness: "harness",
    btnNew: "＋ New memory", pickNote: "select a memory",
    btnSave: "Save", btnDelete: "Delete",
    phEditor: "pick a note on the left, or create a new one",
    btnIngest: "Re-index (ingest)", btnSummarize: "Re-summarize harnesses",
    auditIntro: "Audit trail of every write and admin action on this loci instance.",
    auditP1: "<b>What gets logged:</b> memory create / edit / delete, remember, ingest triggers, harness re-summarize.",
    auditP2: "<b>Who it's for:</b> when several people or agents share this instance via [[auth.tokens]], trace exactly who changed what, and when.",
    auditP3: "<b>Retention:</b> newest 500 events in memory (cleared on service restart); the full history goes to the service log.",
    adminRequired: "admin role required.",
    thTime: "time", thWho: "who", thRole: "role", thAction: "action", thDetail: "detail",
    noEvents: "No events yet — create or edit a memory in the Memories tab, then come back and watch it appear here.",
    loginTitle: "loci console",
    loginHint: "This instance requires a token. Paste one from [[auth.tokens]] in config.toml.",
    phToken: "Bearer token", btnSignin: "Sign in",
    expired: "session expired — sign in again", rejected: "token rejected",
    noHarness: "No [[harness]] entries configured.",
    noFiles: "(empty)",
    pickFile: "Pick a memory file on the left.",
    files: "files", chunks: "chunks", updated: "updated",
    fresh: "fresh", stale: "stale", missing: "missing",
    indexing: "indexing…", summarizing: "summarizing…",
    confirmDelete: (n) => `Move ${n} to .trash?`,
    errorPrefix: "error: ",
  },
  zh: {
    title: "loci 管理台",
    tagline: "AI 编码工具的共享记忆层",
    navDash: "总览", navMem: "记忆", navStats: "索引", navAudit: "审计",
    phSearch: "搜索知识库…", phAsk: "输入问题…",
    btnSearch: "搜索", btnAsk: "提问",
    hHarnesses: "工具（Harness）",
    optAll: "全部", optShared: "共享记忆", optHarness: "工具记忆",
    btnNew: "＋ 新建记忆", pickNote: "选择左侧记忆",
    btnSave: "保存", btnDelete: "删除",
    phEditor: "在左侧选择一条记忆，或新建一条",
    btnIngest: "重建索引（ingest）", btnSummarize: "重新生成 harness 摘要",
    auditIntro: "本 loci 实例所有写入与管理操作的审计记录。",
    auditP1: "<b>记录什么：</b>记忆的新建 / 编辑 / 删除、remember、触发 ingest、重新生成 harness 摘要。",
    auditP2: "<b>给谁看：</b>多人或多 agent 通过 [[auth.tokens]] 共用本实例时，精确追溯「谁在什么时候改了什么」。",
    auditP3: "<b>保留多久：</b>内存中最近 500 条（服务重启后清零）；完整历史在服务日志。",
    adminRequired: "需要 admin 角色。",
    thTime: "时间", thWho: "操作者", thRole: "角色", thAction: "动作", thDetail: "详情",
    noEvents: "暂无事件——去「记忆」页新建或编辑一条，然后回来看它出现在这里。",
    loginTitle: "loci 管理台",
    loginHint: "本实例要求鉴权。请粘贴 config.toml 中 [[auth.tokens]] 里的 token。",
    phToken: "Bearer token", btnSignin: "登录",
    expired: "会话过期——请重新登录", rejected: "token 被拒绝",
    noHarness: "尚未配置 [[harness]] 条目。",
    noFiles: "（空）",
    pickFile: "在左侧选择一个记忆文件。",
    files: "个文件", chunks: "块", updated: "更新于",
    fresh: "最新", stale: "待更新", missing: "未生成",
    indexing: "索引中…", summarizing: "总结中…",
    confirmDelete: (n) => `把 ${n} 移入 .trash？`,
    errorPrefix: "错误：",
  },
};
let lang = localStorage.getItem(LANG_KEY)
  || ((navigator.language || "en").toLowerCase().startsWith("zh") ? "zh" : "en");

/* ---------- theme: light (iOS flat white) by default, manual toggle ---------- */
const THEME_KEY = "loci.theme";
let theme = localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light";
function applyTheme() {
  document.documentElement.dataset.theme = theme;
  $("#theme-btn").textContent = theme === "dark" ? "☀️" : "🌙";
}
$("#theme-btn").addEventListener("click", () => {
  theme = theme === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, theme);
  applyTheme();
});
const t = (k, ...a) => {
  const v = (I18N[lang] ?? I18N.en)[k] ?? I18N.en[k] ?? k;
  return typeof v === "function" ? v(...a) : v;
};
function applyI18n() {
  document.documentElement.lang = lang;
  document.title = t("title");
  applyTheme();
  // dictionary strings are static code (no user input), so rich text is safe
  document.querySelectorAll("[data-i18n]").forEach((el) => el.innerHTML = t(el.dataset.i18n));
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
  cards.innerHTML = harness.map((h) => {
    const stale = h.summary.status === "stale" && isAdmin();
    return `
    <div class="card" data-name="${h.name}">
      <div class="head">${iconHtml(h)}
        <span class="name">${h.display || h.name}</span>
        <span class="badge ${h.summary.status}${stale ? " actionable" : ""}"
              ${stale ? `data-h="${h.name}" title="${t("badgeTip")}"` : ""}>${t(h.summary.status)}</span>
      </div>
      <div class="meta">${h.files} ${t("files")} · ${h.chunks} ${t("chunks")}<br>${t("updated")} ${h.last_updated || "—"}</div>
    </div>`;
  }).join("")
    || `<p class="muted">${t("noHarness")}</p>`;
  cards.querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => openDrilldown(c.dataset.name)));
  // "stale" badge is a button: one click regenerates that harness's digest
  cards.querySelectorAll(".badge.actionable").forEach((b) =>
    b.addEventListener("click", async (ev) => {
      ev.stopPropagation();                  // don't open the drilldown too
      if (b.dataset.busy) return;
      b.dataset.busy = "1";
      b.textContent = "…";
      try {
        await api("/harness", { method: "POST",
          body: JSON.stringify({ action: "summarize", name: b.dataset.h }) });
      } catch (e) { alert(e.message); }
      await loadDash();
    }));
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


/* ---------- harness drilldown: left file tree + right preview ----------
   Icons are hand-drawn SF-Symbols-style SVGs (no emoji): a folder glyph and
   a "memory" glyph (document outline with three linked synapse nodes). The
   tree renders fully expanded; folders collapse on click. */
const ICO = {
  chevron: '<svg class="chev" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7"/></svg>',
  dir: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M3 7.2c0-1 .8-1.8 1.8-1.8h3.6c.5 0 1 .2 1.3.6l1.2 1.4h7.3c1 0 1.8.8 1.8 1.8v8.6c0 1-.8 1.8-1.8 1.8H4.8c-1 0-1.8-.8-1.8-1.8V7.2z"/></svg>',
  memory: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"><path d="M6 3.8h8.2L19 8.6v10.6c0 1-.8 1.8-1.8 1.8H6c-1 0-1.8-.8-1.8-1.8V5.6c0-1 .8-1.8 1.8-1.8z"/><path d="M14 3.8v5h5"/><circle cx="8.6" cy="13.2" r="1.15" fill="currentColor" stroke="none"/><circle cx="12.6" cy="16.4" r="1.15" fill="currentColor" stroke="none"/><circle cx="15.6" cy="11.6" r="1.15" fill="currentColor" stroke="none"/><path d="M9.7 13.9l1.8 1.7 2.2-3.4 1 .6" stroke-width="1.3"/></svg>',
};

let drill = null;                       // {name, display, files, tree}

async function openDrilldown(name) {
  try {
    const data = await api(`/harness-files?name=${encodeURIComponent(name)}`);
    drill = { ...data, tree: buildTree(data.files), name };
    $("#drilldown").classList.remove("hidden");
    $("#dd-title").textContent = data.display;
    renderTree();
    // land on the harness digest when one exists, else prompt
    const digest = `harness/${name}.md`;
    const hasDigest = await api("/memories").then(
      (r) => r.memories.some((m) => m.name === digest)).catch(() => false);
    if (hasDigest) {
      const { text } = await api(`/memory?name=${encodeURIComponent(digest)}`);
      $("#dd-view").textContent = text;
    } else {
      $("#dd-view").textContent = t("pickFile");
    }
    $("#drilldown").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) { alert(e.message); }
}

function buildTree(files) {
  const root = { dirs: new Map(), files: [] };
  for (const f of files) {
    const parts = f.rel.split("/");
    let node = root;
    parts.forEach((p, i) => {
      if (i === parts.length - 1) node.files.push({ name: p, ...f });
      else {
        if (!node.dirs.has(p)) node.dirs.set(p, { dirs: new Map(), files: [] });
        node = node.dirs.get(p);
      }
    });
  }
  return root;
}

function renderTree() {
  const tree = $("#dd-tree");
  tree.innerHTML = "";

  const fileLi = (f) => {
    const li = document.createElement("li");
    li.className = "file";
    li.innerHTML = `${ICO.memory}<span class="fname">${f.name}</span>`;
    li.addEventListener("click", () => {
      tree.querySelectorAll("li.file.on").forEach((x) => x.classList.remove("on"));
      li.classList.add("on");
      openDrillFile(f);
    });
    return li;
  };

  const dirUl = (node, depth) => {          // fully expanded by default
    const ul = document.createElement("ul");
    for (const [name, child] of [...node.dirs.entries()].sort((a, b) =>
      a[0].localeCompare(b[0]))) {
      const li = document.createElement("li");
      li.className = "dir";
      const head = document.createElement("div");
      head.className = "dir-head";
      head.innerHTML = `${ICO.chevron}${ICO.dir}<span>${name}</span>`;
      head.addEventListener("click", () => li.classList.toggle("closed"));
      li.appendChild(head);
      li.appendChild(dirUl(child, depth + 1));
      ul.appendChild(li);
    }
    for (const f of node.files.sort((a, b) => a.name.localeCompare(b.name))) {
      ul.appendChild(fileLi(f));
    }
    return ul;
  };

  // top level: root files first, then folders
  tree.appendChild(dirUl(drill.tree, 0));
}

async function openDrillFile(f) {
  const view = $("#dd-view");
  view.textContent = "…";
  try {
    const { text } = await api(`/source-file?path=${encodeURIComponent(f.path)}`);
    view.textContent = `# ${f.rel}\n\n${text}`;
  } catch (e) { view.textContent = t("errorPrefix") + e.message; }
}

$("#drill-close").addEventListener("click", () => {
  drill = null;
  $("#drilldown").classList.add("hidden");
});

/* ---------- memories ---------- */
async function loadMemories() {
  const { memories } = await api("/memories");
  const filter = $("#mem-filter").value;
  const seen = new Set(memories.filter((m) => m.harness).map((m) => m.harness));
  const sel = $("#mem-filter");
  const opts = ["", "shared", ...seen];
  if ([...sel.options].map((o) => o.value).join(",") !== opts.join(",")) {
    sel.innerHTML = opts.map((v) =>
      `<option value="${v}">${v === "" ? t("optAll") : v === "shared" ? t("optShared") : v}</option>`).join("");
    sel.value = filter && opts.includes(filter) ? filter : "";
  }
  const list = $("#mem-list");
  list.innerHTML = memories
    .filter((m) => !filter || m.group === filter || m.harness === filter)
    .map((m) => `<li data-name="${m.name}" class="${memSelection?.name === m.name ? "on" : ""}">
      ${m.title || m.name}<small>${m.harness ? m.harness : t("optShared")} · ${m.mtime} · ${m.size}B</small></li>`)
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
  $("#audit-wrap").classList.toggle("hidden", !admin);
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
