// Audit 2026-10-02 A07/A09 — the graph's frame and physics lifecycle, under the REAL graph.js and the REAL
// bundled d3 (the physics harness), with a hand-drained animation-frame queue and a recorded timer queue.
// This proves application scheduling only, not WebKit's own hidden-page throttling or CPU cost.
"use strict";
const assert = require("assert");
const { loadGraph, synthetic, SIZES } = require("./graph-physics-harness");

function setup({ pending = false } = {}) {
    const env = loadGraph();
    const { sandbox, get, call } = env;
    const frames = [];
    const timers = [];
    sandbox.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    sandbox.cancelAnimationFrame = () => { frames.length = 0; };
    sandbox.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
    sandbox.clearTimeout = () => { timers.length = 0; };
    const graph = synthetic(SIZES.small);
    if (pending) graph.nodes[0].hasPending = true;
    call("updateGraph", graph);
    const sim = get("simulation");
    sim.stop(); sim.tick(160); sim.alpha(0);
    frames.length = 0; timers.length = 0; get("needsRedraw = false");
    const drain = (max = 120) => {
        let n = 0;
        while (frames.length && n < max) { frames.shift()(n * 1000 / 60); n++; }
        return n;
    };
    const centerOn = (id) => {
        const n = get("visibleNodes").find((x) => x.id === id);
        get(`transform = d3.zoomIdentity.translate(${600 - n.x}, ${400 - n.y})`);
    };
    const moveAway = () => get("transform = d3.zoomIdentity.translate(100000, 100000)");
    return { ...env, frames, timers, drain, centerOn, moveAway, sim };
}

let failures = 0;
function check(label, fn) {
    try { fn(); console.log("PASS " + label); } catch (e) { failures++; console.log("FAIL " + label + "\n  " + e.message); }
}

// ---- A07: settle, pending, off-screen pending ----

check("a settled graph with no pending item draws once and schedules nothing", () => {
    const t = setup();
    t.call("scheduleRedraw");
    assert.strictEqual(t.drain(), 1);
    assert.strictEqual(t.frames.length, 0);
    assert.strictEqual(t.timers.length, 0);
});

check("an on-screen pending pulse runs on a bounded timer, not every display frame", () => {
    const t = setup({ pending: true });
    t.centerOn("h0");
    t.call("scheduleRedraw");
    assert.strictEqual(t.drain(), 1);
    assert.strictEqual(t.frames.length, 0, "no back-to-back animation frame for a pulse at alpha 0");
    assert.strictEqual(t.timers.length, 1, "one pulse timer");
    assert.ok(t.timers[0].ms >= 1000 / 31, `pulse cadence capped near 30 fps (got ${t.timers[0].ms} ms)`);
    t.timers.shift().fn();
    assert.strictEqual(t.drain(), 1, "the timer asks for exactly one frame");
});

check("the pulse phase follows elapsed time, not the frame count", () => {
    const t = setup({ pending: true });
    t.centerOn("h0");
    t.clock.now = 0;
    t.call("scheduleRedraw"); t.drain();
    const p0 = t.get("pulsePhase");
    t.clock.now = 500;
    t.timers.shift().fn(); t.drain();
    const p1 = t.get("pulsePhase");
    assert.ok(Math.abs((p1 - p0) - 0.48) < 1e-9, `0.5 s advances the ~1 s pulse by ~0.48 (got ${p1 - p0})`);
});

check("a pending node off screen stops the loop after one frame", () => {
    const t = setup({ pending: true });
    t.moveAway();
    t.call("scheduleRedraw");
    assert.strictEqual(t.drain(), 1);
    assert.strictEqual(t.frames.length, 0);
    assert.strictEqual(t.timers.length, 0);
});

// ---- A07: suspend and resume ----

check("an inactive graph cancels queued frames and pulse timers and draws nothing", () => {
    const t = setup({ pending: true });
    t.centerOn("h0");
    t.call("scheduleRedraw");
    t.call("setGraphActive", false);
    assert.strictEqual(t.drain(), 0, "the queued frame was cancelled");
    t.call("scheduleRedraw");
    assert.strictEqual(t.frames.length, 0, "no frame is requested while inactive");
    assert.strictEqual(t.timers.length, 0);
});

check("a data push while inactive leaves the simulation suspended, not running", () => {
    const t = setup();
    t.call("setGraphActive", false);
    // A push with something to lay out (item 6: a push of nodes already on the canvas starts no layout at all).
    const graph = synthetic(SIZES.small);
    graph.nodes.push({ id: "newcomer", name: "Newcomer", type: "concept", status: "active", confidence: 0.6 });
    graph.links.push({ source: "newcomer", target: "c1" });
    t.call("updateGraph", graph);
    assert.strictEqual(t.get("simSuspended"), true);
    assert.strictEqual(t.frames.length, 0);
});

check("resume restarts a suspended simulation at its own alpha (no reheat) and keeps positions and zoom", () => {
    const t = setup();
    t.sim.alpha(0.3);
    t.call("setGraphActive", false);
    assert.strictEqual(t.get("simSuspended"), true);
    const before = t.get("visibleNodes").map((n) => [n.x, n.y]);
    const tr = t.get("transform");
    t.call("setGraphActive", true);
    const sim = t.get("simulation");
    sim.stop();
    assert.strictEqual(sim.alpha(), 0.3, "alpha untouched");
    assert.strictEqual(t.get("simSuspended"), false);
    const after = t.get("visibleNodes").map((n) => [n.x, n.y]);
    assert.deepStrictEqual(after, before, "no node moved on resume");
    assert.strictEqual(t.get("transform"), tr, "zoom untouched");
    assert.strictEqual(t.frames.length, 1, "one redraw on resume");
});

check("resume of a settled graph does not restart the simulation", () => {
    const t = setup();
    t.call("setGraphActive", false);
    assert.strictEqual(t.get("simSuspended"), false);
    t.call("setGraphActive", true);
    assert.strictEqual(t.get("simulation").alpha(), 0);
});

// ---- A09: interrupted drags ----

function press(t) {
    const node = t.get("visibleNodes")[5];
    t.centerOn(node.id);
    t.clock.now = 1000;
    t.sandbox.onMouseDown({ clientX: 600, clientY: 400, stopImmediatePropagation() {} });
    t.get("simulation").stop();
    assert.ok(t.get("draggingNode"), "the press picked a node");
    return node;
}

function assertReleased(t, node) {
    assert.strictEqual(t.get("draggingNode"), null);
    assert.strictEqual(node.fx, null);
    assert.strictEqual(node.fy, null);
    assert.strictEqual(t.get("simulation").alphaTarget(), 0);
}

check("a window blur mid-drag releases the node and the alpha target without a reheat", () => {
    const t = setup();
    const node = press(t);
    const alpha = t.get("simulation").alpha();
    t.sandbox.onWindowBlur();
    assertReleased(t, node);
    assert.strictEqual(t.get("simulation").alpha(), alpha, "no alpha bump");
    const sim = t.get("simulation");
    sim.stop(); sim.tick(400);
    assert.ok(sim.alpha() < sim.alphaMin(), `physics settles (alpha ${sim.alpha()})`);
});

check("a move with no button held mid-drag means the release was lost", () => {
    const t = setup();
    const node = press(t);
    t.sandbox.onMouseMove({ clientX: 650, clientY: 420, buttons: 0, shiftKey: false });
    assertReleased(t, node);
});

check("a move with the button held keeps dragging", () => {
    const t = setup();
    press(t);
    t.sandbox.onMouseMove({ clientX: 650, clientY: 420, buttons: 1, shiftKey: false });
    assert.ok(t.get("draggingNode"));
    assert.strictEqual(t.get("simulation").alphaTarget(), 0.1);
});

check("going inactive mid-drag releases the node", () => {
    const t = setup();
    const node = press(t);
    t.call("setGraphActive", false);
    assertReleased(t, node);
});

check("a pointer cancel mid-drag releases the node", () => {
    const t = setup();
    const node = press(t);
    t.sandbox.cancelInteraction();
    assertReleased(t, node);
});

check("a cancelled drag keeps a node that focus mode froze pinned", () => {
    const t = setup();
    const node = press(t);
    t.get(`focusNodeId = "h0"; focusSet = new Set(["h0"])`);
    node.fx = 12; node.fy = 34;
    t.sandbox.onWindowBlur();
    assert.strictEqual(t.get("draggingNode"), null);
    assert.strictEqual(node.fx, 12);
    assert.strictEqual(node.fy, 34);
});

check("a pan that brings a pending node on screen restarts the pulse", () => {
    const t = setup({ pending: true });
    t.moveAway();
    t.call("scheduleRedraw"); t.drain();
    assert.strictEqual(t.timers.length, 0);
    t.centerOn("h0");
    t.call("scheduleRedraw"); t.drain();   // what the zoom handler does on every pan
    assert.strictEqual(t.timers.length, 1);
});

check("a startSimulation while inactive never leaves the real d3 timer running", () => {
    const t = setup();
    t.call("setGraphActive", false);
    t.call("startSimulation", { reheat: 0.5 });
    assert.strictEqual(t.get("simSuspended"), true);
    assert.strictEqual(t.get("simulation").alpha(), 0.5, "stopped in the same turn, before any tick");
});

// ---- the d3 timer really stops (real time, real d3 timer) ----

(async () => {
    const t = loadGraph();
    t.call("updateGraph", synthetic(SIZES.small));
    t.get("simulation").alpha(0.5);
    t.call("setGraphActive", false);
    const before = t.get("simulation").alpha();
    await new Promise((r) => setTimeout(r, 120));
    const after = t.get("simulation").alpha();
    check("an inactive graph's d3 timer does not tick", () => assert.strictEqual(after, before));
    t.get("simulation").stop();
    if (failures) { console.log(`${failures} failure(s)`); process.exit(1); }
    console.log("graph-lifecycle: all passed");
})();
