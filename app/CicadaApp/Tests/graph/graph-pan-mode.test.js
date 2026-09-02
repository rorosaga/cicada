// Shift = pan mode: no hover pick, no node drag, the press falls through to
// d3-zoom; releasing Shift re-picks at the last pointer position. Runs the real
// graph.js under the physics harness (real d3, no DOM).
const assert = require("assert");
const { loadGraph, synthetic, SIZES } = require("./graph-physics-harness");

const size = SIZES.small || Object.values(SIZES)[0];
const { sandbox, get, call } = loadGraph();
call("updateGraph", synthetic(size));
const sim = get("simulation");
sim.stop();
for (let t = 0; t < 120; t++) sim.tick();

const nodes = get("visibleNodes");
const node = nodes.reduce((a, b) => (Math.hypot(b.x, b.y) > Math.hypot(a.x, a.y) ? b : a));
const tr = get("transform");
const sx = node.x * tr.k + tr.x, sy = node.y * tr.k + tr.y;
const canvas = get("canvas");

// Plain hover picks the node.
sandbox.onMouseMove({ clientX: sx, clientY: sy });
assert.ok(get("hoveredNode") && get("hoveredNode").id === node.id, "plain hover picks the node under the pointer");

// Shift-hover: nothing highlighted, grab cursor.
sandbox.onMouseMove({ clientX: sx, clientY: sy, shiftKey: true });
assert.strictEqual(get("hoveredNode"), null, "shift-hover never highlights");
assert.strictEqual(get("panModifierHeld"), true);
assert.strictEqual(canvas.style.cursor, "grab");

// Shift-press on a node: no drag, propagation NOT stopped (d3-zoom pans).
let stopped = false;
sandbox.onMouseDown({ clientX: sx, clientY: sy, shiftKey: true, stopImmediatePropagation: () => { stopped = true; } });
assert.strictEqual(get("draggingNode"), null, "shift-press never grabs a node");
assert.strictEqual(stopped, false, "shift-press must fall through to d3-zoom");
assert.strictEqual(node.fx, undefined, "node is not pinned by a shift-press");
sandbox.onMouseUp({});

// Releasing Shift (keyup path) re-picks at the last pointer without a move.
sandbox.setPanMode(false);
assert.strictEqual(get("panModifierHeld"), false);
assert.ok(get("hoveredNode") && get("hoveredNode").id === node.id, "keyup restores the hover pick");
assert.strictEqual(canvas.style.cursor, "pointer");

// A plain move also clears a stale pan mode (no keyup ever delivered).
sandbox.onMouseMove({ clientX: sx, clientY: sy, shiftKey: true });
sandbox.onMouseMove({ clientX: sx, clientY: sy });
assert.strictEqual(get("panModifierHeld"), false, "a move without Shift leaves pan mode");

// Shift pressed mid-drag keeps the drag alive.
sandbox.onMouseDown({ clientX: sx, clientY: sy, stopImmediatePropagation: () => {} });
assert.ok(get("draggingNode"), "plain press grabs the node");
sandbox.onMouseMove({ clientX: sx + 10, clientY: sy + 10, shiftKey: true });
assert.ok(get("draggingNode"), "shift during a drag does not drop the node");
sandbox.onMouseUp({});

console.log("All graph pan-mode checks passed.");
