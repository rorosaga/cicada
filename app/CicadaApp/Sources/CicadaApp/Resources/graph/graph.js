const typeColors = {
    person:   "#4A9EFF",
    project:  "#A855F7",
    company:  "#F97316",
    concept:  "#22C55E",
    tool:     "#14B8A6",
    deadline: "#EF4444",
    skill:    "#EAB308",
    location: "#9CA3AF"
};

let simulation, svg, g, linkGroup, nodeGroup, labelGroup;
let width, height;
let currentZoom;
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 3.0;

function init() {
    svg = d3.select("#graph");
    width = window.innerWidth;
    height = window.innerHeight;

    // Glow filter
    const defs = svg.append("defs");
    const filter = defs.append("filter").attr("id", "glow");
    filter.append("feGaussianBlur").attr("stdDeviation", "4").attr("result", "blur");
    const merge = filter.append("feMerge");
    merge.append("feMergeNode").attr("in", "blur");
    merge.append("feMergeNode").attr("in", "SourceGraphic");

    g = svg.append("g");
    linkGroup = g.append("g").attr("class", "links");
    nodeGroup = g.append("g").attr("class", "nodes");
    labelGroup = g.append("g").attr("class", "labels");

    // Zoom with limits
    currentZoom = d3.zoom()
        .scaleExtent([MIN_ZOOM, MAX_ZOOM])
        .translateExtent([[-5000, -5000], [5000, 5000]])
        .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(currentZoom);

    // Initial center
    svg.call(currentZoom.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(0.9));

    // Double-click on background resets zoom
    svg.on("dblclick.zoom", null); // remove d3's default double-click zoom
    svg.on("dblclick", () => {
        zoomReset();
    });

    // Signal ready
    try {
        window.webkit.messageHandlers.cicada.postMessage(JSON.stringify({ type: "graphReady" }));
    } catch(e) {
        console.log("graphReady (no handler):", e);
    }
}

// Called from Swift for zoom buttons
function zoomIn() {
    svg.transition().duration(300).call(currentZoom.scaleBy, 1.3);
}

function zoomOut() {
    svg.transition().duration(300).call(currentZoom.scaleBy, 0.7);
}

function zoomReset() {
    svg.transition().duration(500).call(
        currentZoom.transform,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(0.9)
    );
}

function updateGraph(dataStr) {
    const data = typeof dataStr === "string" ? JSON.parse(dataStr) : dataStr;
    const nodes = data.nodes;
    const links = data.links;

    // Compute a radius that scales with the number of nodes so larger graphs fit
    const radius = Math.max(400, Math.min(1800, Math.sqrt(nodes.length) * 140));

    // Force simulation with bounded area
    simulation = d3.forceSimulation(nodes)
        .force("link", d3.forceLink(links).id(d => d.id).distance(120).strength(0.8))
        .force("charge", d3.forceManyBody().strength(-180).distanceMax(600))
        .force("center", d3.forceCenter(0, 0).strength(0.08))
        .force("collision", d3.forceCollide().radius(d => nodeRadius(d) + 10))
        .force("x", d3.forceX(0).strength(0.05))
        .force("y", d3.forceY(0).strength(0.05))
        .force("radial", d3.forceRadial(d => 0, 0, 0).strength(0.005));

    // Bound nodes to a circle area on each tick so nothing escapes to infinity
    function boundNodes() {
        nodes.forEach(d => {
            const dist = Math.sqrt(d.x * d.x + d.y * d.y);
            if (dist > radius) {
                const factor = radius / dist;
                d.x *= factor;
                d.y *= factor;
            }
        });
    }

    // Links
    const link = linkGroup.selectAll("line")
        .data(links)
        .join("line")
        .attr("class", "link")
        .attr("stroke-width", 1);

    // Link labels
    const linkLabel = linkGroup.selectAll("text")
        .data(links)
        .join("text")
        .attr("class", "link-label")
        .text(d => d.label);

    // Nodes
    const node = nodeGroup.selectAll("circle")
        .data(nodes)
        .join("circle")
        .attr("r", d => nodeRadius(d))
        .attr("fill", d => typeColors[d.type] || "#999")
        .attr("stroke", d => d.status === "decaying" ? typeColors[d.type] : "transparent")
        .attr("stroke-width", d => d.status === "decaying" ? 2 : 0)
        .attr("stroke-dasharray", d => d.status === "decaying" ? "4 3" : "none")
        .attr("opacity", d => d.status === "decaying" ? 0.5 : 0.9)
        .attr("filter", "url(#glow)")
        .attr("cursor", "pointer")
        .on("click", (event, d) => {
            event.stopPropagation();
            try {
                window.webkit.messageHandlers.cicada.postMessage(
                    JSON.stringify({ type: "nodeClicked", id: d.id })
                );
            } catch(e) { console.log("click:", d.id); }
        })
        .on("mouseenter", function(event, d) {
            d3.select(this)
                .transition().duration(150)
                .attr("r", nodeRadius(d) * 1.2)
                .attr("opacity", 1);
        })
        .on("mouseleave", function(event, d) {
            d3.select(this)
                .transition().duration(150)
                .attr("r", nodeRadius(d))
                .attr("opacity", d.status === "decaying" ? 0.5 : 0.9);
        })
        .call(d3.drag()
            .on("start", dragStarted)
            .on("drag", dragged)
            .on("end", dragEnded));

    // Labels
    const label = labelGroup.selectAll("text")
        .data(nodes)
        .join("text")
        .attr("class", "node-label")
        .attr("dy", d => nodeRadius(d) + 14)
        .text(d => d.name);

    // Tick
    simulation.on("tick", () => {
        boundNodes();

        link
            .attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y);

        linkLabel
            .attr("x", d => (d.source.x + d.target.x) / 2)
            .attr("y", d => (d.source.y + d.target.y) / 2);

        node
            .attr("cx", d => d.x)
            .attr("cy", d => d.y);

        label
            .attr("x", d => d.x)
            .attr("y", d => d.y);
    });
}

function nodeRadius(d) {
    return d.confidence * 18 + 8;
}

function dragStarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;
}

function dragged(event, d) {
    d.fx = event.x;
    d.fy = event.y;
}

function dragEnded(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;
}

function filterTypes(enabledTypesStr) {
    const enabledTypes = JSON.parse(enabledTypesStr);
    const enabledSet = new Set(enabledTypes);

    nodeGroup.selectAll("circle")
        .transition().duration(300)
        .attr("opacity", d => enabledSet.has(d.type) ? (d.status === "decaying" ? 0.5 : 0.9) : 0.06)
        .attr("filter", d => enabledSet.has(d.type) ? "url(#glow)" : "none");

    labelGroup.selectAll("text")
        .transition().duration(300)
        .attr("opacity", d => enabledSet.has(d.type) ? 1 : 0.06);

    linkGroup.selectAll("line")
        .transition().duration(300)
        .attr("stroke-opacity", d => {
            const srcType = typeof d.source === "object" ? d.source.type : null;
            const tgtType = typeof d.target === "object" ? d.target.type : null;
            return (srcType && enabledSet.has(srcType)) && (tgtType && enabledSet.has(tgtType)) ? 0.4 : 0.03;
        });

    linkGroup.selectAll("text")
        .transition().duration(300)
        .attr("opacity", d => {
            const srcType = typeof d.source === "object" ? d.source.type : null;
            const tgtType = typeof d.target === "object" ? d.target.type : null;
            return (srcType && enabledSet.has(srcType)) && (tgtType && enabledSet.has(tgtType)) ? 1 : 0.03;
        });
}

window.addEventListener("resize", () => {
    width = window.innerWidth;
    height = window.innerHeight;
});

document.addEventListener("DOMContentLoaded", init);
