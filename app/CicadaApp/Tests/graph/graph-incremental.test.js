// Item 6 (2026-10-08): the owner saw every node fly around each time he came back to the Graph page. A data push —
// every Sleep batch, every picture or source change — reheated the WHOLE simulation at 0.3, held while the page was
// hidden and replayed on return (a no-op delta alone moved the settled core 80 wu mean, 573 max on the dense bench).
// A push now relaxes only the nodes it brings; every settled node holds still, and a push that brings none starts no
// layout at all. Real graph.js under the real bundled d3 (graph-physics-harness), ticked by hand.
"use strict";
const assert = require("assert");
const { loadGraph, synthetic, SIZES } = require("./graph-physics-harness");

function settled(size = SIZES.small) {
    const t = loadGraph();
    t.call("updateGraph", synthetic(size));
    const sim = t.get("simulation");
    sim.stop();
    for (let i = 0; i < 400; i++) sim.tick();
    sim.alpha(0);
    return t;
}

const positions = (t) => new Map(t.get("visibleNodes").map((n) => [n.id, [n.x, n.y]]));

function maxMove(before, t, ids = null) {
    let worst = 0;
    for (const n of t.get("visibleNodes")) {
        const b = before.get(n.id);
        if (!b || (ids && !ids.has(n.id))) continue;
        worst = Math.max(worst, Math.hypot(n.x - b[0], n.y - b[1]));
    }
    return worst;
}

/// Tick the current simulation the way d3's timer would, to its end, then fire its "end" listener.
function run(t, max = 600) {
    const sim = t.get("simulation");
    sim.stop();
    let ticks = 0;
    while (sim.alpha() >= sim.alphaMin() && ticks < max) { sim.tick(); ticks += 1; }
    const end = sim.on("end");
    if (end) end();
    return ticks;
}

function newcomers(count, anchorIds) {
    const nodes = [], links = [];
    for (let i = 0; i < count; i++) {
        nodes.push({ id: "new" + i, name: "New " + i, type: "concept", status: "active", confidence: 0.6 });
        links.push({ source: "new" + i, target: anchorIds[i % anchorIds.length] });
    }
    return { nodes, links };
}

let failures = 0;
function check(label, fn) {
    try { fn(); console.log("PASS " + label); } catch (e) { failures++; console.log("FAIL " + label + "\n  " + e.message); }
}

check("a push that changes no node's place starts no layout and moves nothing", () => {
    const t = settled();
    const before = positions(t);
    const node = t.get("visibleNodes").find((n) => n.id === "c3");
    t.call("updateGraphDelta", { added: [], updated: [{ ...node, name: "Renamed", x: undefined, y: undefined }], removed: [] });
    const sim = t.get("simulation");
    assert.ok(sim.alpha() < sim.alphaMin(), `no reheat (alpha ${sim.alpha()})`);
    run(t);
    assert.strictEqual(maxMove(before, t), 0);
    assert.strictEqual(t.get("visibleNodes").find((n) => n.id === "c3").name, "Renamed");
});

check("a removal moves nothing that stays", () => {
    const t = settled();
    const before = positions(t);
    t.call("updateGraphDelta", { added: [], updated: [], removed: ["c7", "i3"] });
    run(t);
    assert.strictEqual(maxMove(before, t), 0);
    assert.ok(!t.get("visibleNodes").some((n) => n.id === "c7"));
});

check("new nodes find their place while every settled node holds still", () => {
    const t = settled();
    const before = positions(t);
    const graph = synthetic(SIZES.small);
    const add = newcomers(12, ["c1", "c2", "c3"]);
    t.call("updateGraphDelta", { added: add.nodes, updated: [], removed: [], links: [...graph.links, ...add.links] });
    const ticks = run(t);
    assert.ok(ticks > 0, "the newcomers were laid out");
    assert.strictEqual(maxMove(before, t), 0, "no settled node moved");
    const fresh = t.get("visibleNodes").filter((n) => n.id.startsWith("new"));
    assert.strictEqual(fresh.length, 12);
    for (const n of fresh) assert.ok(Number.isFinite(n.x) && Number.isFinite(n.y), n.id);
    // The hold is the layout's own and ends with it: nothing it pinned stays pinned.
    assert.ok(t.get("visibleNodes").every((n) => n.fx == null && n.fy == null), "every hold released at the end");
});

check("a push while the page is hidden moves nothing settled when the page comes back", () => {
    const t = settled();
    t.call("setGraphActive", false);
    const before = positions(t);
    const graph = synthetic(SIZES.small);
    const add = newcomers(5, ["c4"]);
    t.call("updateGraphDelta", { added: add.nodes, updated: [], removed: [], links: [...graph.links, ...add.links] });
    t.call("setGraphActive", true);
    run(t);
    assert.strictEqual(maxMove(before, t), 0);
});

check("a full push of a graph already on the canvas moves nothing; only its newcomers move", () => {
    const t = settled();
    const before = positions(t);
    const graph = synthetic(SIZES.small);
    t.call("updateGraph", graph);
    let sim = t.get("simulation");
    assert.ok(sim.alpha() < sim.alphaMin(), "a re-push of the same nodes starts no layout");
    run(t);
    assert.strictEqual(maxMove(before, t), 0);
    const add = newcomers(4, ["c9"]);
    t.call("updateGraph", { nodes: [...graph.nodes, ...add.nodes], links: [...graph.links, ...add.links] });
    run(t);
    assert.strictEqual(maxMove(before, t), 0);
});

check("a focus mode's pins outlive a layout's own hold", () => {
    const t = settled();
    // setFocus's own pins, without its zoom animation (d3 transitions need a real DOM).
    t.get("focusNodeId = 'c1'; focusHops = 1");
    t.call("computeFocusSet");
    t.call("applyFocusPinning");
    const outside = t.get("visibleNodes").find((n) => n.fx != null);
    assert.ok(outside, "focus pinned the nodes outside it");
    const graph = synthetic(SIZES.small);
    const add = newcomers(3, ["c1"]);
    t.call("updateGraphDelta", { added: add.nodes, updated: [], removed: [], links: [...graph.links, ...add.links] });
    run(t);
    assert.ok(outside.fx != null && outside.fy != null, "still pinned by focus");
});

check("a cold layout still lays out every node", () => {
    const t = loadGraph();
    t.call("updateGraph", synthetic(SIZES.small));
    const sim = t.get("simulation");
    assert.strictEqual(sim.alpha(), 1, "a first layout starts hot");
    assert.ok(t.get("visibleNodes").every((n) => n.fx == null), "nothing held");
    sim.stop();
});

if (failures) { console.log(`${failures} failure(s)`); process.exit(1); }
console.log("graph-incremental: all passed");
