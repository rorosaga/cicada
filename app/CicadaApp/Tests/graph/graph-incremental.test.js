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

// ---- Review r1 #2: a push never cancels a layout that has not finished ----

check("a rename before a cold layout's first tick lets the layout finish", () => {
    const t = loadGraph();
    t.call("updateGraph", synthetic(SIZES.small));
    t.get("simulation").stop();
    const before = positions(t);
    t.call("updateGraphDelta", { added: [], updated: [{ id: "c1", name: "Renamed" }], removed: [] });
    assert.ok(t.get("simulation").alpha() > 0.9, `the cold layout keeps its heat (${t.get("simulation").alpha()})`);
    run(t);
    assert.ok(maxMove(before, t) > 50, "the nodes were laid out");
});

check("a newcomer pushed while hidden, then a rename, still finds its place on return", () => {
    const t = settled();
    t.call("setGraphActive", false);
    const graph = synthetic(SIZES.small);
    const add = newcomers(1, ["c1"]);
    t.call("updateGraphDelta", { added: add.nodes, updated: [], removed: [], links: [...graph.links, ...add.links] });
    const before = positions(t);
    const seeded = before.get("new0");
    t.call("updateGraphDelta", { added: [], updated: [{ id: "c1", name: "Renamed" }], removed: [] });
    t.call("setGraphActive", true);
    run(t);
    const n = t.get("visibleNodes").find((x) => x.id === "new0");
    assert.ok(Math.hypot(n.x - seeded[0], n.y - seeded[1]) > 1, "the newcomer moved into its layout");
    before.delete("new0");
    assert.strictEqual(maxMove(before, t), 0, "settled nodes still held");
});

check("a second push of newcomers keeps the first ones moving", () => {
    const t = settled();
    const graph = synthetic(SIZES.small);
    const first = newcomers(1, ["c2"]);
    t.call("updateGraphDelta", { added: first.nodes, updated: [], removed: [], links: [...graph.links, ...first.links] });
    const seeded = positions(t).get("new0");
    const second = { nodes: [{ id: "later0", name: "Later", type: "concept", status: "active", confidence: 0.6 }],
                     links: [{ source: "later0", target: "c3" }] };
    t.call("updateGraphDelta", { added: second.nodes, updated: [], removed: [],
                                  links: [...graph.links, ...first.links, ...second.links] });
    const n = t.get("visibleNodes").find((x) => x.id === "new0");
    assert.ok(n.fx == null, "the first newcomer is not held by the second layout");
    run(t);
    assert.ok(Math.hypot(n.x - seeded[0], n.y - seeded[1]) > 1, "and it settled");
});

// ---- Review r1 #3: a full push during a drag ----

check("a full push during a drag leaves no pin once the drag ends", () => {
    const t = settled();
    t.get("draggingNode = nodes.find(n => n.id === 'c1'); draggingNode.fx = draggingNode.x; draggingNode.fy = draggingNode.y; pressStart = { moved: true };");
    const data = synthetic(SIZES.small);
    data.nodes.push({ id: "new-example", name: "New Example", type: "concept" });
    data.links.push({ source: "new-example", target: "c1" });
    t.call("updateGraph", data);
    run(t);
    const live = t.get("nodes.find(n => n.id === 'c1')");
    assert.strictEqual(t.get("draggingNode"), live, "the drag follows the live node");
    t.call("onMouseUp", {});
    t.get("simulation").stop();
    assert.strictEqual(t.get("draggingNode"), null);
    assert.ok(live.fx == null && live.fy == null, `no orphan pin (fx ${live.fx})`);
    assert.strictEqual(t.get("layoutHolds.size"), 0);
});

if (failures) { console.log(`${failures} failure(s)`); process.exit(1); }
console.log("graph-incremental: all passed");
