// DS-3a (R-DG9, R-DG11, R-DG25) — the canvas's three new bridges, under the REAL graph.js and the
// REAL bundled d3 (the physics harness): a click on empty canvas, Esc, and the open entity's node.
// G109: none of them may touch the simulation — the ring and the keep-in-view pan move only the zoom
// transform, and never its scale.
"use strict";
const assert = require("assert");
const { loadGraph, synthetic, SIZES } = require("./graph-physics-harness");

const { sandbox, get, call } = loadGraph();
const posted = [];
sandbox.window.webkit.messageHandlers.cicada.postMessage = (s) => posted.push(JSON.parse(s));
call("updateGraph", synthetic(SIZES.small));
const sim = get("simulation");
sim.stop();
for (let t = 0; t < 120; t++) sim.tick();

const noop = () => {};
const screenOf = (n) => { const tr = get("transform"); return [n.x * tr.k + tr.x, n.y * tr.k + tr.y]; };
function emptyPoint() {
    for (let x = 20; x < 1180; x += 13) {
        for (let y = 20; y < 780; y += 13) {
            if (!sandbox.pickNode(x, y)) return [x, y];
        }
    }
    throw new Error("no empty canvas point found");
}

// 1. A click on empty canvas posts backgroundClicked, once — the window listener's second
//    mouseup is a no-op.
const [ex, ey] = emptyPoint();
sandbox.onMouseDown({ clientX: ex, clientY: ey, stopImmediatePropagation: noop });
sandbox.onMouseUp({});
sandbox.onMouseUp({});
assert.deepStrictEqual(posted.map((m) => m.type), ["backgroundClicked"], "one click on empty canvas, one message");

// 2. A drag on empty canvas is a pan (d3-zoom's), never a close (R-DG8).
posted.length = 0;
sandbox.onMouseDown({ clientX: ex, clientY: ey, stopImmediatePropagation: noop });
sandbox.onMouseMove({ clientX: ex + 30, clientY: ey + 30 });
sandbox.onMouseUp({});
assert.deepStrictEqual(posted, [], "a pan is not a click");

// 3. In pan mode every press is a pan.
sandbox.setPanToggle(true);
sandbox.onMouseDown({ clientX: ex, clientY: ey, stopImmediatePropagation: noop });
sandbox.onMouseUp({});
sandbox.setPanToggle(false);
assert.deepStrictEqual(posted, [], "pan mode never closes the column");

// 4. A click on a node is still nodeClicked, never backgroundClicked. The node farthest from the
//    origin is the least likely to overlap another under the pointer (graph-pan-mode.test.js).
const node = get("visibleNodes").reduce((a, b) => (Math.hypot(b.x, b.y) > Math.hypot(a.x, a.y) ? b : a));
const [nx, ny] = screenOf(node);
sandbox.onMouseDown({ clientX: nx, clientY: ny, stopImmediatePropagation: noop });
sandbox.onMouseUp({});
assert.deepStrictEqual(posted.map((m) => m.type), ["nodeClicked"]);
console.log("All graph background-click checks passed.");

// 5. Esc: an ego focus is graph.js's own and goes first; with none, Esc goes to Swift and WebKit
//    never also forwards it (R-DG11 — no double close).
posted.length = 0;
let prevented = 0;
const esc = () => ({ key: "Escape", preventDefault: () => { prevented += 1; } });
get(`focusNodeId = ${JSON.stringify(node.id)}`);
sandbox.onKeyDown(esc());
sim.stop();
assert.strictEqual(get("focusNodeId"), null, "Esc leaves ego focus first");
assert.deepStrictEqual(posted.map((m) => m.type), ["focusCleared"], "…and says so, as it always has");
posted.length = 0;
sandbox.onKeyDown(esc());
assert.deepStrictEqual(posted.map((m) => m.type), ["escape"], "with no focus, Esc is the page's");
assert.strictEqual(prevented, 2, "graph.js keeps every Esc it answers");
sandbox.onKeyDown({ key: "a", preventDefault: () => { prevented += 1; } });
assert.strictEqual(prevented, 2, "other keys pass through untouched");
console.log("All graph escape checks passed.");

// 6. setSelectedNode: the state behind the ring, the keep-in-view pan after a resize, and G109.
const canvas = get("canvas");
const alphaBefore = sim.alpha();
const kBefore = get("transform").k;
const rightmost = get("visibleNodes").reduce((a, b) => (screenOf(b)[0] > screenOf(a)[0] ? b : a));
assert.strictEqual(sandbox.setSelectedNode(rightmost.id), true);
assert.strictEqual(get("selectedNodeId"), rightmost.id);
canvas.clientWidth = 500;              // the column opens: the canvas narrows
sandbox.onResize();
const [rx, ry] = screenOf(rightmost);
assert.ok(rx >= 79.5 && rx <= 420.5, `the open node stays ≥ 80 px inside the narrowed canvas (x = ${rx})`);
assert.ok(ry >= 79.5 && ry <= 720.5, `…vertically too (y = ${ry})`);
assert.strictEqual(get("transform").k, kBefore, "keep-in-view pans, never zooms");
assert.strictEqual(sim.alpha(), alphaBefore, "G109: selecting and resizing never touch the simulation");
assert.strictEqual(sandbox.setSelectedNode("no-such-node"), false, "an unknown id is not an error");
assert.strictEqual(sandbox.setSelectedNode(null), false);
assert.strictEqual(get("selectedNodeId"), null);
console.log("All graph selected-node checks passed.");

// 7. A G123 reveal owns the transform until it lands (R-DG9): `revealEntity` selects AND reveals in one
//    update, and d3 transitions of one name are exclusive, so a keep-in-view pan started beside the reveal
//    would cancel its zoom. Headless, `revealNode` sets the transform directly, so the hold is set by hand.
get("revealing = true");
get("transform = d3.zoomIdentity.translate(-100000, 0)");   // every node far off-screen
assert.strictEqual(sandbox.setSelectedNode(rightmost.id), true, "the node exists");
assert.strictEqual(get("transform.x"), -100000, "no pan while a reveal is in flight");
sandbox.onResize();
assert.strictEqual(get("transform.x"), -100000, "…nor on a resize mid-reveal");
get("revealing = false");
sandbox.setSelectedNode(null);
canvas.clientWidth = 1200;
sandbox.onResize();
console.log("All graph reveal-hold checks passed.");
