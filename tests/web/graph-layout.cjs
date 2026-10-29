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
