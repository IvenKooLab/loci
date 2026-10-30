// Run with node tests/web/graph-layout.cjs. No browser or network dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync('src/loci/web/app.js', 'utf8');
const draw = js.slice(js.indexOf('function drawGraph(g)'), js.indexOf('\n$("#board-range").addEventListener'));
for (const width of [240, 1168]) {
  for (const count of [0, 1, 5, 40]) {
    const ctx = new Proxy({measureText: s => ({width:s.length*6})}, {get:(o,k)=>o[k] || (()=>{})});
    const canvas = {width, style:{}, parentElement:{getBoundingClientRect:()=>({width})}, getContext:()=>ctx};
    const el = {classList:{add(){},toggle(){}}, style:{}};
    const sandbox = { $: id => id === '#graph-canvas' ? canvas : el,
      document:{documentElement:{}},getComputedStyle:()=>({getPropertyValue:()=>''}),
      graphSim:{}, cancelAnimationFrame(){}, requestAnimationFrame:()=>1, Math};
    vm.createContext(sandbox); vm.runInContext(draw, sandbox);
    sandbox.drawGraph({nodes:Array.from({length:count}, (_,i)=>({path:`note-${i}.md`, chunks:3})),links:[]});
    const nodes = sandbox.graphSim.nodes;
    assert.equal(new Set(nodes.map(n=>`${n.x},${n.y}`)).size, count);
    for (const n of nodes) {
      assert.ok(n.x > 0 && n.x < width && n.y > 0 && n.y < canvas.height);
    }
  }
}
console.log('Graph layout: empty/single/5/40 disconnected notes at narrow/wide widths passed');

// A qualified target resolves correctly; an ambiguous bare name remains unresolved.
{
  const ctx = new Proxy({measureText: s => ({width:s.length*6})}, {get:(o,k)=>o[k] || (()=>{})});
  const canvas = {width:800, style:{}, parentElement:{getBoundingClientRect:()=>({width:800})}, getContext:()=>ctx};
  const el = {classList:{add(){},toggle(){}}, style:{}};
  const sandbox = { $: id => id === '#graph-canvas' ? canvas : el, document:{documentElement:{}},
    getComputedStyle:()=>({getPropertyValue:()=>''}), graphSim:{}, cancelAnimationFrame(){}, requestAnimationFrame:()=>1, Math};
  vm.createContext(sandbox); vm.runInContext(draw, sandbox);
  sandbox.drawGraph({nodes:['source.md','a/note.md','b/note.md'].map(path=>({path})),
    links:[['source.md','a/note'],['source.md','note'],['source.md','note'],
      ['source.md','B/NOTE.MD'],['source.md','a/note.md']]});
  assert.equal(sandbox.graphSim.links[0][1].path, 'a/note.md');
  assert.equal(sandbox.graphSim.links[1][1].ghost, true);
  assert.equal(sandbox.graphSim.links[1][1], sandbox.graphSim.links[2][1]);
  assert.equal(sandbox.graphSim.links[3][1].path, 'b/note.md');
  assert.equal(sandbox.graphSim.links[4][1].path, 'a/note.md');
}
console.log('Graph link resolution: qualified and ambiguous targets passed');
