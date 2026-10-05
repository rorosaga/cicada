// A07/A09: real bundled graph.js + d3, a manually drained animation queue.
// This proves application scheduling, not WebKit's hidden-window frame policy
// or actual CPU/GPU cost. The existing canvas harness uses no-op drawing.
"use strict";
const path = require("path");
const { loadGraph, synthetic, SIZES } = require(path.resolve(
    __dirname, "../../../../app/CicadaApp/Tests/graph/graph-physics-harness.js"));

function pulseScenario(pending, hidden) {
    const { sandbox, get, call } = loadGraph();
    const frames = [];
    sandbox.requestAnimationFrame = fn => { frames.push(fn); return frames.length; };
    sandbox.document.hidden = hidden;
    const graph = synthetic(SIZES.small);
    if (pending) graph.nodes[0].hasPending = true;
    call("updateGraph", graph);
    const sim = get("simulation");
    sim.stop(); sim.tick(160); sim.alpha(0);
    let rendered = 0;
    while (frames.length && rendered < 120) {
        frames.shift()(rendered * 1000 / 60);
        rendered++;
    }
    sim.stop();
    return { pending, syntheticDocumentHidden: hidden, rendered,
             queuedAfter120: frames.length, alpha: sim.alpha() };
}
console.log(JSON.stringify({ finding: "A07", scenarios: [
    pulseScenario(false, false), pulseScenario(true, false), pulseScenario(true, true),
] }));

const { sandbox, clock, get, call } = loadGraph();
call("updateGraph", synthetic(SIZES.small));
const sim = get("simulation");
sim.stop(); sim.tick(160); sim.alpha(0);
const node = get("visibleNodes").reduce((a, b) =>
    Math.hypot(b.x, b.y) > Math.hypot(a.x, a.y) ? b : a);
const transform = get("transform");
clock.now = 1000;
sandbox.onMouseDown({ clientX: node.x * transform.k + transform.x,
    clientY: node.y * transform.k + transform.y, stopImmediatePropagation() {} });
sim.stop();
sandbox.onMouseLeave({}); // Deliberately omit mouseup: interrupted gesture.
sim.tick(400);
console.log(JSON.stringify({ finding: "A09", draggingStillActive: Boolean(get("draggingNode")),
    alphaTarget: sim.alphaTarget(), alphaAfter400Ticks: sim.alpha() }));
sim.stop();
