import XCTest
import WebKit
@testable import CicadaApp

/// Item 6 — what the Graph costs in real WebKit at the owner's size (2,000 nodes), not in node: the bundled graph.js
/// and d3 in an offscreen `WKWebView` inside this test process (never the app). Prints `BENCH` lines; opt-in with
/// `CICADA_APP_BENCH=1`. `draw()` is timed in the page, so it is the JavaScript cost of one frame's canvas calls;
/// compositing happens after it and is not in the number.
final class GraphWebKitBenchTests: XCTestCase {
    private static let script = #"""
    function ownerShaped() {
        let seed = 11;
        const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
        const types = ["person", "project", "company", "concept", "tool", "skill", "location", "media"];
        const nodes = [{ id: "owner", name: "Owner Example", type: "person", status: "active", confidence: 1, isOwner: true }];
        const links = [];
        for (let h = 0; h < 24; h++) nodes.push({ id: "h" + h, name: "Hub " + h, type: "hub", isHub: true, status: "active", confidence: 0.9 });
        const core = 2000 - 1 - 24 - 400;
        for (let i = 0; i < core; i++) {
            const member = rnd() < 0.4;
            const hub = "h" + (i % 24);
            nodes.push({ id: "c" + i, name: "Page example " + i, type: types[i % types.length], status: "active",
                         confidence: 0.3 + rnd() * 0.7, degree: 2, ...(member ? { hubId: hub } : {}) });
            if (member) links.push({ source: hub, target: "c" + i, label: "member of" });
            if (i > 0) links.push({ source: "c" + i, target: "c" + Math.floor(rnd() * i), label: "relates to" });
            if (rnd() < 0.5 && i > 0) links.push({ source: "c" + i, target: "c" + Math.floor(rnd() * i), label: "uses" });
            if (i % 3 === 0) links.push({ source: "owner", target: "c" + i, label: "works on" });
        }
        for (let i = 0; i < 400; i++) nodes.push({ id: "i" + i, name: "Isolate " + i, type: types[i % types.length], status: "active", confidence: 0.5 });
        return { nodes, links };
    }
    const out = {};
    const graph = ownerShaped();
    let t = performance.now();
    updateGraph(JSON.stringify(graph));
    out.updateGraphMs = performance.now() - t;
    simulation.stop();
    out.nodes = visibleNodes.length; out.links = visibleLinks.length;
    t = performance.now();
    let ticks = 0;
    while (simulation.alpha() >= simulation.alphaMin() && ticks < 1000) { simulation.tick(); ticks++; }
    out.coldTicks = ticks;
    out.coldSettleMs = performance.now() - t;
    out.msPerTick = out.coldSettleMs / ticks;
    fitGraph && typeof fitGraph === "function" && fitGraph();
    const frames = [];
    for (let i = 0; i < 30; i++) { const s = performance.now(); draw(); frames.push(performance.now() - s); }
    frames.sort((a, b) => a - b);
    out.drawMedianMs = frames[15]; out.drawP90Ms = frames[27];
    // A live push of 20 new pages onto the settled layout (item 6): only they move.
    const before = new Map(visibleNodes.map((n) => [n.id, [n.x, n.y]]));
    const added = [], extra = [];
    for (let i = 0; i < 20; i++) {
        added.push({ id: "new" + i, name: "New page " + i, type: "concept", status: "active", confidence: 0.6 });
        extra.push({ source: "new" + i, target: "c" + (i * 37), label: "relates to" });
    }
    t = performance.now();
    updateGraphDelta(JSON.stringify({ added, updated: [], removed: [], links: [...graph.links, ...extra] }));
    out.deltaIngestMs = performance.now() - t;
    simulation.stop();
    t = performance.now();
    ticks = 0;
    while (simulation.alpha() >= simulation.alphaMin() && ticks < 1000) { simulation.tick(); ticks++; }
    out.deltaTicks = ticks; out.deltaSettleMs = performance.now() - t;
    const end = simulation.on("end"); if (end) end();
    let moved = 0;
    for (const n of visibleNodes) { const b = before.get(n.id); if (b && Math.hypot(n.x - b[0], n.y - b[1]) > 0) moved++; }
    out.settledNodesMoved = moved;
    return JSON.stringify(out);
    """#

    @MainActor
    func testPrintTheGraphsCostAtTwoThousandNodes() async throws {
        guard ProcessInfo.processInfo.environment["CICADA_APP_BENCH"] == "1" else {
            throw XCTSkip("set CICADA_APP_BENCH=1 to print the WebKit numbers")
        }
        let page = try XCTUnwrap(Bundle.cicadaResources.url(forResource: "graph/index", withExtension: "html"))
        let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1200, height: 800))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1200, height: 800), styleMask: [.borderless],
                              backing: .buffered, defer: false)
        window.contentView = web
        web.loadFileURL(page, allowingReadAccessTo: page.deletingLastPathComponent())
        for _ in 0..<100 {
            if (try? await web.evaluateJavaScript("typeof updateGraph === 'function' && !!ctx")) as? Bool == true { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        let result = try await web.callAsyncJavaScript(Self.script, contentWorld: .page)
        let json = try XCTUnwrap(result as? String)
        print("BENCH webkit \(json)")
        let numbers = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any])
        XCTAssertEqual(numbers["settledNodesMoved"] as? Int, 0)
    }
}
