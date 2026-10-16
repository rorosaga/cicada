// QA 2026-10-16 — "the Graph is not fitted on first show": the first-load fit could run while the canvas still had a
// size it was about to lose, leaving the graph in the corner of the view it finally got. Until something else moves
// the view, a resize fits again; once the person (or a reveal, or a focus) has moved it, a resize leaves it alone.
// Run: node Tests/graph/graph-fit-resize.test.js
"use strict";
const assert = require("assert");
const { loadGraph, synthetic, SIZES } = require("./graph-physics-harness");

let failures = 0;
function check(label, fn) {
    try { fn(); console.log("PASS " + label); } catch (e) { failures++; console.log("FAIL " + label + "\n  " + e.message); }
}

function laidOut() {
    const env = loadGraph();
    env.call("updateGraph", synthetic(SIZES.small));
    env.runUntilStop(600);
    return env;
}

check("a resize after the first fit fits again, centred in the new size", () => {
    const { get } = laidOut();
    // The first fit ran at 1200 × 800; the view is still that fit.
    get("autoFit = transformForNodes(visibleNodes, FIT_PAD); transform = autoFit");
    const before = get("autoFit");
    get("canvas.clientWidth = 1700; canvas.clientHeight = 900");
    get("onResize()");
    const after = get("autoFit");
    assert.notDeepStrictEqual([after.x, after.y, after.k], [before.x, before.y, before.k], "the fit follows the resize");
    // The fitted box's centre lands on the new canvas centre.
    const box = get(`(() => { let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
        for (const n of visibleNodes) { a = Math.min(a, n.x); b = Math.min(b, n.y); c = Math.max(c, n.x); d = Math.max(d, n.y); }
        return { cx: (a + c) / 2, cy: (b + d) / 2 }; })()`);
    assert.ok(Math.abs(after.x + after.k * box.cx - 850) < 30, `x centre ${after.x + after.k * box.cx}`);
    assert.ok(Math.abs(after.y + after.k * box.cy - 450) < 30, `y centre ${after.y + after.k * box.cy}`);
});

check("once the view is moved, a resize keeps it", () => {
    const { get } = laidOut();
    get("autoFit = transformForNodes(visibleNodes, FIT_PAD); transform = autoFit.translate(40, 0)");
    assert.strictEqual(get("viewIsStillTheFit()"), false);
    assert.strictEqual(get("refitForResize()"), null);
});

check("a fit the person asked for is theirs (no follow), and an open node is never refitted away", () => {
    const { get } = laidOut();
    get("autoFit = null; transform = transformForNodes(visibleNodes, FIT_PAD)");
    assert.strictEqual(get("refitForResize()"), null);
    get("autoFit = transform; selectedNodeId = visibleNodes[0].id");
    assert.strictEqual(get("refitForResize()"), null);
});

if (failures) { console.log(`${failures} failed`); process.exit(1); }
console.log("all passed");
