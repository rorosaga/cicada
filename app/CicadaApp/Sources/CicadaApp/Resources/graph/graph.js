// Cicada graph view — HTML5 canvas renderer backed by d3-force.
//
// History: this used to be an SVG renderer that ran the d3-force simulation
// directly against <circle> and <text> elements. That works fine for a few
// hundred nodes but at 1500+ nodes the per-tick DOM mutation cost dominates,
// the Gaussian blur filter on every node turns the GPU into a space heater,
// and the default alpha decay never lets the simulation settle. This file
// replaces all of that with a canvas pipeline following the same pattern as
// Bostock's canonical @d3/force-directed-graph-canvas Observable and
// vasturiano/force-graph. d3-force stays in place as the layout engine —
// it does not care what you render with.

const typeColors = {
    person:   "#4A9EFF",
    project:  "#A855F7",
    company:  "#F97316",
    concept:  "#22C55E",
    tool:     "#14B8A6",
    deadline: "#EF4444",
    skill:    "#EAB308",
    location: "#9CA3AF",
};

// Soft per-type cluster anchors. These are only used by the xType/yType
// forces at low strength, so the layout still obeys link and charge forces
// — the anchors just nudge same-type nodes toward each other. Obsidian-like
// grouping without a Louvain pass.
const typeClusterPositions = {
    person:   [   0, -300],
    project:  [ 280, -100],
    company:  [ 180,  240],
    concept:  [-180,  240],
    tool:     [-280, -100],
    deadline: [   0,  300],
    skill:    [ 300,  100],
    location: [-300,  100],
};

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 6.0;
const LABEL_ZOOM_THRESHOLD = 1.4;   // show labels when zoomed past this
const LABEL_MIN_SCREEN_RADIUS = 6;  // and only for nodes whose on-screen radius clears this
const DRAG_CLICK_THRESHOLD = 4;     // pixels of movement before a mousedown becomes a drag

// ---------- Module-level state ----------

let canvas, ctx;
let width = 0;
let height = 0;
let dpr = 1;

let simulation;
let nodes = [];
let links = [];
let visibleNodes = [];
let visibleLinks = [];
let neighborsById = new Map();  // id -> Set<id> for hover highlighting

let currentMinDegree = 1;       // default drops only fully isolated nodes
let enabledTypes = null;        // null = all types enabled; otherwise a Set<string>

let transform = d3.zoomIdentity;
let currentZoom;

let hoveredNode = null;
let draggingNode = null;
let pressStart = null;          // { x, y } screen coords of mousedown for click-vs-drag

let needsRedraw = false;
let rafHandle = null;

// ---------- Init ----------

function init() {
    canvas = document.getElementById("graph");
    ctx = canvas.getContext("2d");

    resizeCanvas();
    window.addEventListener("resize", () => {
        resizeCanvas();
        scheduleRedraw();
    });

    // Zoom/pan. We drive d3.zoom on the canvas element and store the result
    // in a local transform object; draw() applies that transform manually
    // in world space via ctx.translate/scale. We do NOT set a DOM transform
    // attribute anymore — there is no DOM tree under the canvas to move.
    currentZoom = d3.zoom()
        .scaleExtent([MIN_ZOOM, MAX_ZOOM])
        .on("zoom", (event) => {
            transform = event.transform;
            scheduleRedraw();
        });
    d3.select(canvas).call(currentZoom);

    // Initial centering transform — put origin in the middle of the canvas
    // at a slightly-zoomed-out starting scale so the whole graph is visible.
    d3.select(canvas).call(
        currentZoom.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(0.6),
    );

    // Suppress d3's default double-click zoom so we can map it to reset.
    d3.select(canvas).on("dblclick.zoom", null);
    d3.select(canvas).on("dblclick", () => { zoomReset(); });

    wireMouseEvents();

    // Signal ready. The Swift side is waiting on this before pushing data.
    try {
        window.webkit.messageHandlers.cicada.postMessage(
            JSON.stringify({ type: "graphReady" })
        );
    } catch (e) {
        console.log("graphReady (no handler):", e);
    }
}

function resizeCanvas() {
    dpr = window.devicePixelRatio || 1;
    width = canvas.clientWidth || window.innerWidth;
    height = canvas.clientHeight || window.innerHeight;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    // Reset the transform stack and apply the HiDPI scale once. draw()
    // applies the pan/zoom transform on top of this on every frame.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

// ---------- Zoom actions (called from Swift) ----------

function zoomIn() {
    d3.select(canvas).transition().duration(250).call(currentZoom.scaleBy, 1.4);
}

function zoomOut() {
    d3.select(canvas).transition().duration(250).call(currentZoom.scaleBy, 0.7);
}

function zoomReset() {
    d3.select(canvas).transition().duration(400).call(
        currentZoom.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(0.6),
    );
}

// ---------- Data ingest ----------

function updateGraph(dataStr) {
    const data = typeof dataStr === "string" ? JSON.parse(dataStr) : dataStr;
    nodes = data.nodes || [];
    links = data.links || [];

    // Degree from links. This has to run BEFORE d3.forceLink mutates the
    // link objects (it replaces the string id endpoints with node refs).
    const degreeMap = new Map();
    links.forEach(l => {
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        degreeMap.set(sid, (degreeMap.get(sid) || 0) + 1);
        degreeMap.set(tid, (degreeMap.get(tid) || 0) + 1);
    });
    nodes.forEach(n => { n.degree = degreeMap.get(n.id) || 0; });

    rebuildVisible();
    rebuildNeighborsIndex();
    startSimulation();
    scheduleRedraw();
}

function rebuildVisible() {
    visibleNodes = nodes.filter(n => n.degree >= currentMinDegree);
    const visibleIds = new Set(visibleNodes.map(n => n.id));
    visibleLinks = links.filter(l => {
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        return visibleIds.has(sid) && visibleIds.has(tid);
    });
}

function rebuildNeighborsIndex() {
    neighborsById = new Map();
    visibleLinks.forEach(l => {
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        if (!neighborsById.has(sid)) neighborsById.set(sid, new Set());
        if (!neighborsById.has(tid)) neighborsById.set(tid, new Set());
        neighborsById.get(sid).add(tid);
        neighborsById.get(tid).add(sid);
    });
}

function startSimulation() {
    if (simulation) simulation.stop();

    simulation = d3.forceSimulation(visibleNodes)
        // Alpha/velocity tuning for dense graphs. Defaults are fine for a
        // hundred nodes; at 1500 they keep the sim bouncing indefinitely.
        .alphaDecay(0.05)
        .velocityDecay(0.55)
        .alphaMin(0.05)
        .force("link", d3.forceLink(visibleLinks)
            .id(d => d.id)
            .distance(60)
            .strength(0.5))
        .force("charge", d3.forceManyBody()
            .strength(-40)
            .distanceMax(400)
            .theta(0.9))
        .force("center", d3.forceCenter(0, 0).strength(0.05))
        .force("collision", d3.forceCollide()
            .radius(d => nodeRadius(d) + 2)
            .strength(0.8))
        // Soft per-type anchoring for Obsidian-style grouping.
        .force("xType", d3.forceX(d => typeClusterPositions[d.type]?.[0] ?? 0).strength(0.04))
        .force("yType", d3.forceY(d => typeClusterPositions[d.type]?.[1] ?? 0).strength(0.04))
        .on("tick", scheduleRedraw)
        .on("end", () => { simulation.stop(); });
}

function nodeRadius(d) {
    // Degree is the dominant signal; sqrt dampens runaway hubs while still
    // making them clearly bigger than leaves. Confidence contributes a
    // secondary bump so a high-confidence leaf is still visually distinct
    // from a low-confidence leaf.
    const degreeTerm = Math.sqrt(d.degree || 0) * 3;
    const confidenceTerm = (d.confidence || 0) * 4;
    return 4 + degreeTerm + confidenceTerm;
}

// ---------- Render loop ----------

function scheduleRedraw() {
    if (needsRedraw) return;
    needsRedraw = true;
    rafHandle = requestAnimationFrame(() => {
        needsRedraw = false;
        draw();
        // Keep redrawing while the sim is still producing movement. Once
        // alpha drops below alphaMin the sim stops on its own and we stop
        // scheduling frames, so idle CPU/GPU usage goes to zero.
        if (simulation && simulation.alpha() > simulation.alphaMin()) {
            scheduleRedraw();
        }
    });
}

function draw() {
    if (!ctx) return;

    // Start from the HiDPI-scaled identity so the next transform we push
    // is in CSS pixels from the canvas's top-left.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    ctx.save();
    ctx.translate(transform.x, transform.y);
    ctx.scale(transform.k, transform.k);

    const hoverActive = hoveredNode !== null;
    const neighbors = hoverActive
        ? (neighborsById.get(hoveredNode.id) || new Set())
        : null;

    const typeFilterActive = enabledTypes !== null;

    // ---- Links ----
    // Single stroke path per link. We don't batch paths because each link
    // can have its own alpha depending on hover and type filter state, and
    // beginPath/stroke per link is cheap at 1500-edge scale.
    for (const l of visibleLinks) {
        const src = l.source;
        const tgt = l.target;
        if (typeof src !== "object" || typeof tgt !== "object") continue;

        let alpha = 0.35;
        if (typeFilterActive) {
            const srcOk = enabledTypes.has(src.type);
            const tgtOk = enabledTypes.has(tgt.type);
            if (!srcOk || !tgtOk) alpha = 0.04;
        }
        if (hoverActive) {
            const touchesHover =
                src.id === hoveredNode.id ||
                tgt.id === hoveredNode.id;
            if (!touchesHover) alpha = Math.min(alpha, 0.08);
            else alpha = 0.8;
        }

        ctx.globalAlpha = alpha;
        ctx.strokeStyle = "#666";
        ctx.lineWidth = 1 / transform.k;
        ctx.beginPath();
        ctx.moveTo(src.x, src.y);
        ctx.lineTo(tgt.x, tgt.y);
        ctx.stroke();
    }

    // ---- Nodes ----
    for (const n of visibleNodes) {
        const r = nodeRadius(n);
        const color = typeColors[n.type] || "#999";

        let alpha = n.status === "decaying" ? 0.55 : 0.92;
        if (typeFilterActive && !enabledTypes.has(n.type)) alpha = 0.06;
        if (hoverActive) {
            const isHover = n.id === hoveredNode.id;
            const isNeighbor = neighbors.has(n.id);
            if (!isHover && !isNeighbor) alpha = Math.min(alpha, 0.15);
            else alpha = 1;
        }

        ctx.globalAlpha = alpha;

        // Decaying nodes get a dashed stroke so the viewer can tell they
        // are on their way out. Canvas doesn't have a per-shape dash cache
        // so we set the line dash inline — cheap at this scale.
        if (n.status === "decaying") {
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.5 / transform.k;
            ctx.setLineDash([4 / transform.k, 3 / transform.k]);
        }

        // Glow only for the hovered node. The original implementation put
        // an SVG feGaussianBlur on every circle and that was the single
        // biggest perf cost in the SVG version.
        if (hoverActive && n.id === hoveredNode.id) {
            ctx.shadowColor = color;
            ctx.shadowBlur = 12;
        } else {
            ctx.shadowBlur = 0;
        }

        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fill();

        if (n.status === "decaying") {
            ctx.stroke();
            ctx.setLineDash([]);
        }

        ctx.shadowBlur = 0;
    }

    ctx.globalAlpha = 1;

    // ---- Labels ----
    // At zoomed-out scales the graph is a clean constellation, no labels.
    // Past LABEL_ZOOM_THRESHOLD we show labels for nodes whose on-screen
    // radius is big enough to warrant one. Font size is divided by zoom k
    // so labels stay a constant screen size as you zoom.
    const labelsVisible = transform.k > LABEL_ZOOM_THRESHOLD;
    if (labelsVisible) {
        const fontSize = 11 / transform.k;
        ctx.font = `${fontSize}px -apple-system, 'SF Pro Text', system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.shadowColor = "rgba(0,0,0,0.85)";
        ctx.shadowBlur = 3 / transform.k;
        for (const n of visibleNodes) {
            const r = nodeRadius(n);
            if (r * transform.k < LABEL_MIN_SCREEN_RADIUS) continue;

            let alpha = 0.95;
            if (typeFilterActive && !enabledTypes.has(n.type)) alpha = 0.06;
            if (hoverActive) {
                const isHover = n.id === hoveredNode.id;
                const isNeighbor = neighbors.has(n.id);
                if (!isHover && !isNeighbor) alpha = Math.min(alpha, 0.15);
            }
            ctx.globalAlpha = alpha;
            ctx.fillStyle = "#F5F5F5";
            ctx.fillText(n.name, n.x, n.y + r + (4 / transform.k));
        }
        ctx.shadowBlur = 0;
        ctx.globalAlpha = 1;
    }

    // Hover label override — always show the hovered node's name with a
    // small background plate, regardless of zoom level. This is the
    // "I want to read just this one label without zooming" affordance.
    if (hoverActive) {
        const n = hoveredNode;
        const r = nodeRadius(n);
        const fontSize = 12 / transform.k;
        ctx.font = `${fontSize}px -apple-system, 'SF Pro Text', system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const text = n.name;
        const metrics = ctx.measureText(text);
        const padX = 6 / transform.k;
        const padY = 4 / transform.k;
        const boxW = metrics.width + padX * 2;
        const boxH = fontSize + padY * 2;
        const boxX = n.x - boxW / 2;
        const boxY = n.y + r + (6 / transform.k);
        ctx.globalAlpha = 0.92;
        ctx.fillStyle = "rgba(18, 18, 22, 0.92)";
        ctx.fillRect(boxX, boxY, boxW, boxH);
        ctx.fillStyle = "#F5F5F5";
        ctx.fillText(text, n.x, boxY + boxH / 2);
        ctx.globalAlpha = 1;
    }

    ctx.restore();
}

// ---------- Mouse / interaction ----------

function wireMouseEvents() {
    canvas.addEventListener("mousedown", onMouseDown);
    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mouseup", onMouseUp);
    canvas.addEventListener("mouseleave", onMouseLeave);
}

function screenToWorld(sx, sy) {
    // Invert the zoom transform to map a client-space (CSS pixel) point
    // back into the simulation's world coordinates.
    return [(sx - transform.x) / transform.k, (sy - transform.y) / transform.k];
}

function eventScreenXY(event) {
    const rect = canvas.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
}

function pickNode(sx, sy) {
    if (!simulation) return null;
    const [wx, wy] = screenToWorld(sx, sy);
    // simulation.find uses a quadtree so this is cheap even at 1500 nodes.
    // The search radius is in world units; we scale it by 1/k so the
    // pick target stays roughly constant in screen space.
    const pickRadius = 24 / transform.k;
    const n = simulation.find(wx, wy, pickRadius);
    return n || null;
}

function onMouseDown(event) {
    const [sx, sy] = eventScreenXY(event);
    pressStart = { x: sx, y: sy, moved: false };
    const picked = pickNode(sx, sy);
    if (picked) {
        draggingNode = picked;
        picked.fx = picked.x;
        picked.fy = picked.y;
        if (simulation) simulation.alphaTarget(0.3).restart();
        canvas.classList.add("dragging");
        // Swallow the event so d3.zoom's drag-pan doesn't also fire.
        event.stopPropagation();
    }
}

function onMouseMove(event) {
    const [sx, sy] = eventScreenXY(event);

    // Apply the click-vs-drag threshold uniformly regardless of whether
    // we're currently holding a node. macOS fires mousemove events on
    // sub-pixel trembles, so flipping pressStart.moved on the very first
    // move (which the drag branch used to do unconditionally) causes
    // every click to be misread as a drag and swallows nodeClicked.
    if (pressStart) {
        const dx = sx - pressStart.x;
        const dy = sy - pressStart.y;
        if (Math.hypot(dx, dy) > DRAG_CLICK_THRESHOLD) {
            pressStart.moved = true;
        }
    }

    if (draggingNode) {
        // Only actually move the node once the user has crossed the
        // threshold. Below that we still treat the gesture as a pending
        // click, which means mouseup will dispatch nodeClicked.
        if (pressStart?.moved) {
            const [wx, wy] = screenToWorld(sx, sy);
            draggingNode.fx = wx;
            draggingNode.fy = wy;
            scheduleRedraw();
        }
        return;
    }

    // Hover pick. Only swap hoveredNode if it actually changed so we don't
    // spam redraws on every pixel of mouse movement.
    const picked = pickNode(sx, sy);
    if (picked !== hoveredNode) {
        hoveredNode = picked;
        canvas.style.cursor = picked ? "pointer" : "";
        scheduleRedraw();
    }
}

function onMouseUp(event) {
    const [sx, sy] = eventScreenXY(event);

    if (draggingNode) {
        const wasClick = pressStart && !pressStart.moved;
        const clickedId = draggingNode.id;
        draggingNode.fx = null;
        draggingNode.fy = null;
        draggingNode = null;
        if (simulation) simulation.alphaTarget(0);
        canvas.classList.remove("dragging");

        if (wasClick) {
            try {
                window.webkit.messageHandlers.cicada.postMessage(
                    JSON.stringify({ type: "nodeClicked", id: clickedId })
                );
            } catch (e) { console.log("click:", clickedId); }
        }
    }

    pressStart = null;
}

function onMouseLeave() {
    if (hoveredNode !== null) {
        hoveredNode = null;
        scheduleRedraw();
    }
}

// ---------- Swift-facing controls ----------

function filterTypes(enabledTypesStr) {
    const arr = JSON.parse(enabledTypesStr);
    enabledTypes = arr.length === Object.keys(typeColors).length
        ? null
        : new Set(arr);
    scheduleRedraw();
}

function setMinDegree(k) {
    const value = Number(k) || 0;
    if (value === currentMinDegree) return;
    currentMinDegree = value;
    if (nodes.length === 0) return;
    rebuildVisible();
    rebuildNeighborsIndex();
    startSimulation();
    scheduleRedraw();
}

// ---------- Boot ----------

document.addEventListener("DOMContentLoaded", init);
