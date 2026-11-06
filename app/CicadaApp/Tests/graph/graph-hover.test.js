// ROR-135 — the hover card's half of the canvas, under the REAL graph.js and the REAL bundled d3 (the physics
// harness). graph.js tells Swift WHICH node the pointer rests on and where it is on screen, and nothing else: the
// card's picture, name and line are already in the app. This holds the three promises the card makes:
//   1. it posts on a CHANGE only (a still pointer costs a compare per frame);
//   2. a pan, a zoom, a drag or leaving posts `hoverEnded` once and then nothing per frame (no lag in panning);
//   3. none of it touches the simulation (G109).
// It also measures the pointer path at the owner's scale (9,000 pages) and prints the numbers.
"use strict";
const assert = require("assert");
const { loadGraph, synthetic } = require("./graph-physics-harness");

function setup(spec) {
    const env = loadGraph();
    const posted = [];
    env.sandbox.window.webkit.messageHandlers.cicada.postMessage = (s) => posted.push(JSON.parse(s));
    env.call("updateGraph", synthetic(spec));
    const sim = env.get("simulation");
    sim.stop();
    for (let t = 0; t < 40; t++) sim.tick();
    return { ...env, posted, sim };
}
const types = (posted) => posted.map((m) => m.type);

// ---- 1-3 at a small size -------------------------------------------------------------------------------------
{
    const { sandbox, get, posted, sim } = setup({ n: 300, isolates: 100, hubs: 6, facets: 20, extraLinksPerNode: 3 });
    const tr = () => get("transform");
    const nodes = get("visibleNodes");
    const target = nodes.find((n) => !n.isHub && !n.isFacet);
    const screenOf = (n) => [n.x * tr().k + tr().x, n.y * tr().k + tr().y];
    const move = (x, y) => sandbox.onMouseMove({ clientX: x, clientY: y, buttons: 0 });
    const emptyPoint = () => {
        for (let x = 20; x < 1180; x += 11) for (let y = 20; y < 780; y += 11) if (!sandbox.pickNode(x, y)) return [x, y];
        throw new Error("no empty point");
    };

    // the whole sim before: positions and heat, to prove the card never moved a thing
    const before = JSON.stringify(nodes.map((n) => [n.id, n.x, n.y, n.vx, n.vy])) + sim.alpha();

    const [sx, sy] = screenOf(target);
    move(sx, sy);
    sandbox.draw();
    assert.strictEqual(posted.length, 1, "one message for a new hovered node");
    const m = posted[0];
    assert.strictEqual(m.type, "nodeHovered");
    assert.strictEqual(m.id, get("hoveredNode").id, "it names the node the pointer picked");
    assert.ok(Math.abs(m.x - get("hoveredNode").x * tr().k - tr().x) < 1e-6 && Math.abs(m.y - get("hoveredNode").y * tr().k - tr().y) < 1e-6,
        "its centre is in canvas pixels");
    assert.ok(m.r > 0, "and its radius on screen");

    // 1. a still pointer, many frames, nothing more
    for (let i = 0; i < 60; i++) sandbox.draw();
    assert.strictEqual(posted.length, 1, "a still pointer posts nothing per frame");

    // 2. a pan hides the card once; further frames of the pan post nothing
    posted.length = 0;
    for (let i = 1; i <= 40; i++) {
        get(`transform = d3.zoomIdentity.translate(${i * 3}, ${i * 2})`);
        sandbox.draw();
    }
    assert.deepStrictEqual(types(posted), ["hoverEnded"], "a pan hides the card once, never per frame");
    // a zoom the same
    posted.length = 0;
    for (let i = 1; i <= 20; i++) { get(`transform = d3.zoomIdentity.translate(100, 80).scale(${1 + i * 0.05})`); sandbox.draw(); }
    assert.deepStrictEqual(posted, [], "a zoom after the pan hid it posts nothing more");

    // the pointer leaving and returning shows it again at the node's new place
    get("transform = d3.zoomIdentity");
    const [ex, ey] = emptyPoint();
    move(ex, ey); sandbox.draw();
    move(...screenOf(target)); sandbox.draw();
    assert.strictEqual(posted.at(-1).type, "nodeHovered", "back on the node, the card returns");
    assert.strictEqual(posted.at(-1).id, target.id);

    // a drag hides it; letting go does not bring it back by itself
    posted.length = 0;
    get(`draggingNode = visibleNodes.find((n) => n.id === ${JSON.stringify(target.id)})`);
    sandbox.draw();
    assert.deepStrictEqual(types(posted), ["hoverEnded"], "a drag hides the card");
    get("draggingNode = null");

    // the pointer onto empty canvas ends it, once
    posted.length = 0;
    const [gx, gy] = emptyPoint();
    move(gx, gy); sandbox.draw(); sandbox.draw();
    assert.ok(types(posted).filter((t) => t === "hoverEnded").length <= 1, "leaving posts at most one end");
    move(gx, gy); sandbox.draw();

    // suppressed (the entity column is open): no hover, no card
    posted.length = 0;
    sandbox.setHoverSuppressed(true);
    move(...screenOf(target)); sandbox.draw();
    assert.ok(!types(posted).includes("nodeHovered"), "a suppressed hover shows no card");
    sandbox.setHoverSuppressed(false);

    // a node that drifts under a settling layout re-posts its centre, but only past HOVER_MOVE_PX
    posted.length = 0;
    move(...screenOf(target)); sandbox.draw();
    posted.length = 0;
    target.x += 0.5; sandbox.draw();
    assert.deepStrictEqual(posted, [], "half a pixel is no news");
    target.x += 10; sandbox.draw();
    assert.deepStrictEqual(types(posted), ["nodeHovered"], "ten pixels is");
    target.x -= 10.5;

    // 3. the simulation is untouched by any of it
    const after = JSON.stringify(nodes.map((n) => [n.id, n.x, n.y, n.vx, n.vy])) + sim.alpha();
    assert.strictEqual(after, before, "hover reports never touch the forces, positions or heat");
}

// ---- the pointer path at the owner's scale ------------------------------------------------------------------
{
    const spec = { n: 9000, isolates: 3000, hubs: 40, facets: 400, extraLinksPerNode: 3 };
    const { sandbox, get, posted } = setup(spec);
    const nodes = get("visibleNodes");
    const k = get("transform").k;
    const [tx, ty] = [get("transform").x, get("transform").y];
    const pts = nodes.filter((_, i) => i % 3 === 0).slice(0, 1500).map((n) => [n.x * k + tx, n.y * k + ty]);
    const empty = [-50, -50];
    const time = (f) => { const t0 = process.hrtime.bigint(); f(); return Number(process.hrtime.bigint() - t0) / 1e6; };

    // each move: a pick (the quadtree) and a frame's reportHover compare. Two moves in three land on a node.
    const perMove = [];
    for (const [x, y] of pts) {
        perMove.push(time(() => { sandbox.onMouseMove({ clientX: x, clientY: y, buttons: 0 }); sandbox.reportHover(); }));
        sandbox.onMouseMove({ clientX: empty[0], clientY: empty[1], buttons: 0 }); sandbox.reportHover();
    }
    perMove.sort((a, b) => a - b);
    const q = (p) => perMove[Math.min(perMove.length - 1, Math.floor(perMove.length * p))];
    // a pan frame: the compare against the last report, with the card already hidden
    sandbox.onMouseMove({ clientX: pts[0][0], clientY: pts[0][1], buttons: 0 }); sandbox.reportHover();
    get("transform = d3.zoomIdentity.translate(5, 5)");
    const panFrame = time(() => { for (let i = 0; i < 10000; i++) sandbox.reportHover(); }) / 10000;
    console.log(`graph-hover: ${nodes.length} nodes · pick+report per move p50 ${q(0.5).toFixed(4)} ms, p95 ${q(0.95).toFixed(4)} ms, ` +
        `max ${q(1).toFixed(3)} ms · a pan frame's report ${(panFrame * 1000).toFixed(2)} µs · ${posted.length} messages for ${pts.length * 2} moves`);
    assert.ok(q(0.95) < 1, "a pointer move with a card costs under a millisecond at 9,000 nodes");
    assert.ok(posted.length <= pts.length * 2 + 2, "at most one message per change");
}
console.log("graph-hover: ok");
