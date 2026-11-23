// Server data must reach the console as text, never as HTML.
// Run: node tests/web/escape.cjs
//
// Memory titles are file content — any agent with write access sets one
// through brain_remember — and the memories list used to splice them into an
// innerHTML template: a title of `<img src=x onerror=...>` ran script in the
// console the moment the Memories tab opened (loopback is admin there).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const js = fs.readFileSync('src/loci/web/app.js', 'utf8').replace(/\r\n/g, '\n');

// ---------- a minimal DOM that records every innerHTML assignment ----------
function makeEl(tag) {
  const el = {
    tagName: tag, children: [], dataset: {}, style: {}, _text: '', value: '',
    className: '', options: [],
    classList: {
      _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      toggle(c, on) { (on ?? !this._s.has(c)) ? this._s.add(c) : this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    addEventListener() {}, setAttribute() {}, focus() {}, remove() {},
    append(...xs) { this.children.push(...xs); },
    appendChild(...xs) { this.children.push(...xs); },
    replaceChildren(...xs) { this.children = xs; },
    querySelectorAll() { return []; },
    set textContent(v) { this._text = String(v); this.children = []; },
    get textContent() { return this._text + this.children.map(textOf).join(''); },
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return this._html || ''; },
    set(v) { HTML_SINKS.push(String(v)); this._html = String(v); this.children = []; },
  });
  return el;
}
function textOf(n) { return typeof n === 'string' ? n : n.textContent; }
const HTML_SINKS = [];

const TITLE = '<img src=x onerror="window.__xss=1">';
const ctx = {
  console,
  document: {
    createElement: makeEl,
    createTextNode: (s) => String(s),
    querySelector: () => makeEl('div'),
    querySelectorAll: () => [],
  },
  t: (k) => ({ optAll: 'all', optShared: 'shared memory', noHarness: 'none' })[k] ?? k,
  api: async () => ({ memories: [
    { name: 'crafted.md', group: 'shared', harness: '', mtime: '2026-11-23 23:36', size: 83, title: TITLE },
    { name: 'a" onmouseover="x.md', group: 'harness', harness: 'h"><b>', mtime: 't', size: 1, title: '' },
  ] }),
  memSelection: null, isEditor: () => true,
};
vm.createContext(ctx);

// ---------- 1. the memories list renders the title as text ----------
const loadMemories = js.slice(js.indexOf('async function loadMemories()'), js.indexOf('async function openMemory('));
vm.runInContext(loadMemories + '\nthis.run = loadMemories;', ctx);

(async () => {
  const list = makeEl('ul');
  const sel = Object.assign(makeEl('select'), { options: [Object.assign(makeEl('option'), { value: '' })] });
  ctx.$ = (s) => ({ '#mem-filter': sel, '#mem-list': list, '#mem-new': makeEl('button') })[s];
  await ctx.run();

  // every node the list produced must carry the raw title as TEXT
  assert.ok(list.children.length === 2, `expected 2 rows, got ${list.children.length}`);
  const [first, second] = list.children;
  assert.equal(textOf(first.children[0]), TITLE, 'title not rendered verbatim as a text node');
  assert.ok(first.children.every((n) => typeof n === 'string' || String(n.tagName).toUpperCase() === 'SMALL'),
    'title produced an element — it was parsed as HTML');
  assert.equal(second.dataset.name, 'a" onmouseover="x.md', 'name with a quote lost in the attribute');

  // ---------- 2. no untrusted string ever reaches an innerHTML sink ----------
  const leaked = HTML_SINKS.filter((h) => h.includes(TITLE) || h.includes('onmouseover') || h.includes('<b>'));
  assert.deepEqual(leaked, [], 'server data reached innerHTML: ' + JSON.stringify(leaked));
  for (const h of HTML_SINKS) {
    assert.ok(!/<\s*(img|script|svg|iframe|b)\b/i.test(h), `markup from data in innerHTML: ${h.slice(0, 80)}`);
  }

  // ---------- 3. the harness drilldown tree escapes file and folder names ----------
  const escSrc = js.slice(js.indexOf('function esc('), js.indexOf('\n}\n', js.indexOf('function esc(')) + 3);
  assert.ok(escSrc.startsWith('function esc('), 'no esc() helper in app.js');
  vm.runInContext(escSrc + '\nthis.esc = esc;', ctx);
  assert.equal(ctx.esc('<img src=x onerror="a">&\''), '&lt;img src=x onerror=&quot;a&quot;&gt;&amp;&#39;');
  const treeSrc = js.slice(js.indexOf('function renderTree()'), js.indexOf('async function openDrillFile('));
  assert.ok(!/\$\{f\.name\}|\$\{name\}/.test(treeSrc.replace(/ICO\.\w+/g, '')),
    'renderTree still interpolates a file/folder name into an HTML string');
  const cardsStart = js.indexOf('async function loadHarnessCards()');
  const cardsSrc = js.slice(cardsStart, js.indexOf(String.fromCharCode(10) + '/* ---------- ', cardsStart));
  for (const field of ['h.name', 'h.display || h.name', 'h.last_updated || "—"', 'h.summary.status']) {
    const used = new RegExp(`\\$\\{${field.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\}`).test(cardsSrc);
    const escaped = new RegExp(`\\$\\{esc\\(${field.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\)\\}`).test(cardsSrc);
    assert.ok(!used || escaped, `harness card still interpolates ${field} unescaped`);
  }
  assert.ok(/esc\(h\.icon\)/.test(js), 'iconHtml still interpolates h.icon unescaped');

  console.log('escape.cjs: ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
