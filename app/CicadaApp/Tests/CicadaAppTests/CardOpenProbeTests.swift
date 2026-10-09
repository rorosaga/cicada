import XCTest
import SwiftUI
import AppKit
@testable import CicadaApp

/// Opens the real `EntityDetailCard` in an offscreen window against a scratch backend and measures what the main thread
/// does until the card has settled: when each read lands, how long the main thread was blocked at a stretch, and the
/// total time it spent in stretches over a frame. Instruments-free: a background thread pings the main queue every 2 ms
/// and records how late each ping ran.
///
/// Opt-in, and never the person's backend: it runs only with `CICADA_CARD_PROBE=1` and a `CICADA_PORT` other than
/// 8000 (the app's `APIClient` reads that port), and the caller sets `HOME`, `CICADA_HOME` and the backend's
/// `CICADA_MEMORY_PATH` to scratch folders. `CICADA_CARD_PROBE_ID` names the page (default `owner-example`).
final class CardOpenProbeTests: XCTestCase {
    private final class MainPinger: @unchecked Sendable {
        private let lock = NSLock()
        private var running = true
        private(set) var stalls: [(at: Double, ms: Double)] = []
        let start = DispatchTime.now().uptimeNanoseconds

        func now() -> Double { Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000 }

        func run() {
            Thread.detachNewThread { [self] in
                while lock.withLock({ running }) {
                    let sent = now()
                    let done = DispatchSemaphore(value: 0)
                    DispatchQueue.main.async { done.signal() }
                    done.wait()
                    let late = now() - sent
                    if late > 16 { lock.withLock { stalls.append((sent, late)) } }
                    usleep(2_000)
                }
            }
        }

        func stop() -> [(at: Double, ms: Double)] { lock.withLock { running = false; return stalls } }
    }

    @MainActor
    func testProbeOpeningACard() throws {
        let env = ProcessInfo.processInfo.environment
        guard env["CICADA_CARD_PROBE"] == "1", let port = env["CICADA_PORT"], port != "8000", !port.isEmpty else {
            throw XCTSkip("set CICADA_CARD_PROBE=1 and a scratch CICADA_PORT (never 8000) to probe a card open")
        }
        let id = env["CICADA_CARD_PROBE_ID"] ?? "owner-example"
        let seconds = Double(env["CICADA_CARD_PROBE_SECONDS"] ?? "") ?? 6
        // Every section open (each remembered per viewer, DR-39): what a card costs when everything has been asked for.
        for key in [CardSections.beliefsKey, CardSections.provenanceKey, CardSections.connectionsKey,
                    CardSections.sourcesKey] {
            UserDefaults.standard.set(env["CICADA_CARD_PROBE_OPEN_ALL"] == "1", forKey: key)
        }

        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: APIClient.shared)
        var refreshed = false
        Task { await store.refresh([.graph]); refreshed = true }
        while !refreshed { RunLoop.main.run(until: Date().addingTimeInterval(0.01)) }
        let graph = GraphViewModel(store: store)
        XCTAssertNotNil(graph.nodes.first { $0.id == id }, "the scratch bank has the page")

        CicadaTheme.mode = env["CICADA_CARD_PROBE_LIGHT"] == "1" ? .light : .dark
        defer { CicadaTheme.mode = .dark }
        let root = GraphProbeHost(width: Double(env["CICADA_CARD_PROBE_WIDTH"] ?? "") ?? 560)
            .environment(store)
            .environment(graph)
            .environment(AppRouter())
            .environment(ProvenanceRouter())
            .environment(ProvenanceCache())
            .environment(ProjectsCache())
        _ = NSApplication.shared
        let hosting = NSHostingView(rootView: root)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1100, height: 900), styleMask: [.titled],
                              backing: .buffered, defer: false)
        window.contentView = hosting
        window.orderFrontRegardless()
        RunLoop.main.run(until: Date().addingTimeInterval(0.3))

        let pinger = MainPinger()
        pinger.run()
        RunLoop.main.run(until: Date().addingTimeInterval(0.1))
        // `CICADA_CARD_PROBE_HIDE` (a page file in the scratch bank): moved aside once the graph is read, so the
        // full-page read fails and the card's failure state shows; put back when the probe ends.
        let hidden = env["CICADA_CARD_PROBE_HIDE"]
        if let hidden { try FileManager.default.moveItem(atPath: hidden, toPath: hidden + ".hidden") }
        defer { if let hidden { try? FileManager.default.moveItem(atPath: hidden + ".hidden", toPath: hidden) } }
        let opened = pinger.now()
        graph.selectEntity(id: id)
        var marks: [String: Double] = [:]
        func mark(_ name: String, _ reached: Bool) { if reached, marks[name] == nil { marks[name] = pinger.now() - opened } }
        var displays: [Double] = []
        // Graph pushes while the card is open (Sleep's batches arrive as SSE deltas): from 3 s, one every 300 ms.
        let pushes = Int(env["CICADA_CARD_PROBE_PUSHES"] ?? "") ?? 0
        let base = store.graph.value
        var pushed = 0
        while pinger.now() - opened < seconds * 1000 {
            if pushed < pushes, pinger.now() - opened > 3_000 + Double(pushed) * 300, let base {
                let nodes = pushed % 2 == 0 ? Array(base.nodes.dropLast()) : base.nodes
                store.graph.value = GraphResponse(nodes: nodes, links: base.links)
                store.graph.loadedAt = Date()
                pushed += 1
            }
            RunLoop.main.run(until: Date().addingTimeInterval(0.004))
            let t0 = pinger.now()
            hosting.layoutSubtreeIfNeeded()
            window.displayIfNeeded()
            displays.append(pinger.now() - t0)
            mark("full page in hand", graph.selectedEntity.map { !$0.rawMarkdown.isEmpty } ?? false)
        }
        let stalls = pinger.stop().filter { $0.at >= opened }.map { ($0.at - opened, $0.ms) }
        if let dir = env["CICADA_CARD_PROBE_PNG"], let rep = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds) {
            let t0 = pinger.now()
            hosting.cacheDisplay(in: hosting.bounds, to: rep)
            print(String(format: "PROBE forced draw %.0f ms", pinger.now() - t0))
            try rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: dir))
        }
        window.orderOut(nil)

        print("PROBE page", id, "width", env["CICADA_CARD_PROBE_WIDTH"] ?? "560", "sections open", env["CICADA_CARD_PROBE_OPEN_ALL"] ?? "0")
        for (name, at) in marks.sorted(by: { $0.value < $1.value }) {
            print(String(format: "PROBE mark %-22@ %8.0f ms", name as NSString, at))
        }
        let late = stalls.filter { $0.0 >= 3_000 }
        print(String(format: "PROBE after 3 s (%d pushes): stalls %d · longest %.0f ms · total %.0f ms", pushes,
                     late.count, late.map(\.1).max() ?? 0, late.map(\.1).reduce(0, +)))
        let longest = stalls.map(\.1).max() ?? 0
        let total = stalls.map(\.1).reduce(0, +)
        print(String(format: "PROBE stalls>16ms %d · longest %.0f ms · total %.0f ms", stalls.count, longest, total))
        for (at, ms) in stalls.sorted(by: { $0.1 > $1.1 }).prefix(8) {
            print(String(format: "PROBE stall at %6.0f ms lasted %6.0f ms", at, ms))
        }
        print(String(format: "PROBE longest display pass %.0f ms", displays.max() ?? 0))
    }
}

/// The Graph page's column, alone: the selected entity's card at the column's width.
private struct GraphProbeHost: View {
    let width: Double
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        HStack(spacing: 0) {
            Color.clear
            if let entity = graphVM.selectedEntity {
                EntityDetailCard(entity: entity, style: .column).id(entity.id).frame(width: width)
            }
        }
        .frame(width: 1100, height: 900)
        .environment(\.colorScheme, CicadaTheme.mode == .light ? .light : .dark)
    }
}
