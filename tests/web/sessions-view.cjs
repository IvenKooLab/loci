// Session-style query history. No browser, no network — pure source checks.
// Run: node tests/web/sessions-view.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const js = fs.readFileSync('src/loci/web/app.js', 'utf8');
const html = fs.readFileSync('src/loci/web/index.html', 'utf8');
const css = fs.readFileSync('src/loci/web/style.css', 'utf8');

// ---------- 1. structure: new view added, old table kept ----------
for (const id of ['q-sessions', 'q-agents', 'q-agent-pick', 'q-filter',
                  'q-select', 'q-export', 'q-table-view', 'queries-table']) {
  assert.ok(html.includes(`id="${id}"`), `missing element #${id}`);
}
for (const view of ['sessions', 'table']) {
  assert.ok(html.includes(`data-qview="${view}"`), `missing view switch ${view}`);
}
assert.ok(css.includes('.q-tree'), 'session view CSS not loaded');
assert.ok(css.includes('.q-row:hover .q-act'), 'no hover-revealed actions');
assert.ok(html.includes('rel="icon"') && html.includes('data:image/svg+xml'),
          'inline favicon missing — every page load logs a 404');

// ---------- 2. i18n: every new key in both languages ----------
const i18nSrc = js.slice(js.indexOf('const I18N = {'), js.indexOf('\n};', js.indexOf('const I18N = {')) + 3);
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(i18nSrc + '\nthis.I18N = I18N;', sandbox);
const keys = Object.keys(sandbox.I18N.en).filter((k) => k.startsWith('q'));
assert.ok(keys.length >= 18, `only ${keys.length} session keys in English`);
for (const k of keys) {
  assert.ok(k in sandbox.I18N.zh, `session key missing in zh: ${k}`);
}

// ---------- 3. pure helpers ----------
function helpers() {
  const src = js.slice(js.indexOf('const Q_PAGE = 50;'), js.indexOf('function drawSessions()'));
  const el = () => ({
    className: '', textContent: '', title: '', type: '', value: '',
    dataset: {}, classList: { add() {}, toggle() {}, remove() {} },
    style: {}, children: [],
    append(...xs) { this.children.push(...xs); },
    setAttribute() {}, addEventListener() {}, focus() {}, remove() {},
  });
  const ctx = {
    t: (k, ...a) => {
      const map = {
        qNoSource: 'no result', qRoot: 'root', qLive: 'live', qSlow: 'slow',
        qSelect: 'Select', qRetry: 'Run this query again', qCopy: 'Copy query text',
        qSelected: (n) => `${n} selected`, qExport: 'Export JSONL',
        ms: 'ms', thTime: 'time', thWho: 'who', thRole: 'role', thKind: 'kind',
        thHits: 'hits', thMs: 'took', thTop: 'top result',
      };
      const v = map[k];
      return typeof v === 'function' ? v(...a) : (v || k);
    },
    document: { createElement: el, querySelector: () => el() },
    navigator: { clipboard: { writeText: async () => {} } },
    URL: { createObjectURL: () => 'blob:x', revokeObjectURL() {} },
    Blob: function () {},
    $: () => el(),
    setTimeout, clearTimeout, console, Date, Math, Number, String, Set, Map,
    JSON, Object, Array,
  };
  ctx.queryRows = []; ctx.qAgent = ''; ctx.qNeedle = ''; ctx.qDetail = '';
  ctx.qOpen = new Set(); ctx.qPicked = new Set(); ctx.qSelecting = false;
  ctx.qDrawn = new Map();
  vm.createContext(ctx);
  vm.runInContext(src + '\nthis.api = { qGroupOf, qFiltered, qAgo, qRow, qDetailOf };', ctx);
  // `let` bindings are lexical inside a vm context, not context properties.
  // Set them through the context's own scope so the functions see them.
  ctx.set = (rows, agent = '', needle = '') => vm.runInContext(
    `queryRows = ${JSON.stringify(rows)}; qAgent = ${JSON.stringify(agent)};` +
    ` qNeedle = ${JSON.stringify(needle)};`, ctx);
  return ctx;
}
const h = helpers();

// grouping follows the citation path, on both separator styles
assert.equal(h.api.qGroupOf({ top: 'notes/hr/policy.md > 报销 > chunk' }), 'notes/hr');
assert.equal(h.api.qGroupOf({ top: 'policy.md > 报销' }), 'root');
assert.equal(h.api.qGroupOf({ top: '' }), 'no result');
assert.equal(h.api.qGroupOf({ top: 'C:\\work\\docs\\a.md > §1' }), 'C:\\work\\docs');

// agent + text filter (search covers the question AND the result location)
const fixture = [
  { query: '住宿上限', top: 'notes/hr/policy.md > 报销', label: 'codex', kind: 'ask' },
  { query: '年假天数', top: 'notes/hr/leave.md > 年假', label: 'claude', kind: 'search' },
  { query: '限额', top: 'notes/fin/budget.md > 预算', label: 'codex', kind: 'ask' },
];
h.set(fixture, 'codex');
assert.equal(h.api.qFiltered().length, 2);
h.set(fixture, 'codex', 'budget');
assert.equal(h.api.qFiltered().length, 1, 'search must match the result path');
h.set(fixture, '', '年假');
assert.equal(h.api.qFiltered().length, 1);
h.set(fixture);

// ---------- 4. query text is never interpreted as HTML ----------
const evil = '<img src=x onerror=alert(1)>';
const evilRow = { _i: 0, query: evil, top: 'a.md', ts: new Date().toISOString(),
                  label: 'x', kind: 'ask', hits: 1, ms: 12 };
h.set([evilRow]);
const row = h.api.qRow(evilRow);
const flat = JSON.stringify(row);
assert.ok(flat.includes(evil), 'query text must appear verbatim as textContent');
assert.ok(!flat.includes('innerHTML'), 'query text must never touch innerHTML');

// details show every recorded field
const detail = h.api.qDetailOf({ ts: 't', label: 'l', role: 'r', kind: 'ask',
                                 hits: 3, ms: 4.7, top: 'file > section' });
assert.equal(detail.children[1].children.length, 14, '7 dt + 7 dd after the summary line');

console.log('sessions-view: structure, i18n, grouping, filtering and escaping OK');

// ---------- 5. desktop shell: default-deny CSP ----------
const conf = JSON.parse(fs.readFileSync('native/desktop/src-tauri/tauri.conf.json', 'utf8'));
const csp = conf.app.security.csp;
assert.ok(csp && csp !== null, 'Tauri CSP must not be disabled');
for (const directive of ["default-src 'self'", "script-src 'self'", "object-src 'none'",
                         "base-uri 'none'", "frame-ancestors 'none'"]) {
  assert.ok(csp.includes(directive), `CSP missing: ${directive}`);
}
assert.ok(csp.includes('data:'), 'inline SVG favicon needs data: images');

// ---------- 6. desktop shell: no port TOCTOU, no cwd-dependent root ----------
const mainRs = fs.readFileSync('native/desktop/src-tauri/src/main.rs', 'utf8');
assert.ok(mainRs.includes('serve_bound'), 'desktop shell must hand over a bound listener');
assert.ok(!mainRs.includes('drop(listener)'),
          'dropping the listener before serve rebinds is a TOCTOU race');
assert.ok(mainRs.includes('current_exe()'),
          'demo notes must be anchored to the executable, not the launch cwd');

// ---------- 7. no blocking alert() on the harness drilldown path ----------
const drillSrc = js.slice(js.indexOf('async function openDrilldown'), js.indexOf('function buildTree'));
// strip comments before checking — the fix explains why alert() was removed
const drillCode = drillSrc.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
assert.ok(!drillCode.includes('alert('), 'harness drilldown must not use a blocking alert');
assert.ok(drillSrc.includes('harnessUnavailable'), 'inline fallback message missing');
assert.ok(js.includes('harnessUnavailable:') && js.includes('此版本不支持查看'),
          'harness fallback must be translated');
