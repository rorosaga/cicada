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

// Toolbar toggle: sticky pan mode without Shift; keyup/blur do not clear it.
sandbox.setPanToggle(true);
assert.strictEqual(get("panModifierHeld"), true, "toggle turns pan mode on");
sandbox.onMouseMove({ clientX: sx, clientY: sy });
assert.strictEqual(get("hoveredNode"), null, "toggled pan mode never highlights, even without Shift");
stopped = false;
sandbox.onMouseDown({ clientX: sx, clientY: sy, stopImmediatePropagation: () => { stopped = true; } });
assert.strictEqual(get("draggingNode"), null, "toggled pan mode never grabs a node");
assert.strictEqual(stopped, false, "toggled pan mode falls through to d3-zoom");
sandbox.onMouseUp({});
sandbox.setPanToggle(false);
assert.strictEqual(get("panModifierHeld"), false, "toggle off restores normal mode");
assert.ok(get("hoveredNode") && get("hoveredNode").id === node.id, "toggle off re-picks the hover");
console.log("All graph pan-toggle checks passed.");

// Entity card open: hover is suppressed, clicks still select.
sandbox.setHoverSuppressed(true);
sandbox.onMouseMove({ clientX: sx, clientY: sy });
assert.strictEqual(get("hoveredNode"), null, "no hover highlight while the entity card is open");
stopped = false;
sandbox.onMouseDown({ clientX: sx, clientY: sy, stopImmediatePropagation: () => { stopped = true; } });
assert.ok(get("draggingNode"), "a press still grabs/selects a node while the card is open");
assert.strictEqual(stopped, true);
sandbox.onMouseUp({});
sandbox.setHoverSuppressed(false);
sandbox.onMouseMove({ clientX: sx, clientY: sy });
assert.ok(get("hoveredNode") && get("hoveredNode").id === node.id, "hover returns once the card closes");
console.log("All graph hover-suppression checks passed.");

// G123 revealNode: zooms to a visible node (readable scale, node centred); unknown id → false.
const before = get("transform");
assert.strictEqual(sandbox.revealNode("no-such-node"), false);
assert.strictEqual(sandbox.revealNode(node.id), true);
const tr2 = get("transform");
assert.ok(tr2.k >= 1.0 && tr2.k <= 6.0, "reveal lands at a readable scale");
const cx = node.x * tr2.k + tr2.x, cy = node.y * tr2.k + tr2.y;
assert.ok(Math.abs(cx - 600) < 2 && Math.abs(cy - 400) < 2, "the node sits at the viewport centre");
console.log("All graph reveal checks passed.");
