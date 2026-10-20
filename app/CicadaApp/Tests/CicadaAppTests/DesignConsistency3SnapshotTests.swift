import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The consistency pass, round 3 (2026-10-20): the palette's rows and Ask states and the export walkthrough's vendor
/// tabs, light and dark, offscreen. Env-gated: `CICADA_CONSISTENCY3_SNAPSHOTS=<dir>`. Built through inits that exist
/// before and after the change, so the same file renders origin/dev and the branch.
@MainActor
final class DesignConsistency3SnapshotTests: XCTestCase {
    func test_writeRoundThreeSurfacesForComparison() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_CONSISTENCY3_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_CONSISTENCY3_SNAPSHOTS=<dir> to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        CicadaTheme.uiScale = 1
        let out = URL(fileURLWithPath: dir)
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let graph = GraphViewModel(store: store)

        let rows: [FindRow] = [
            FindRow(key: FindRowKey(kind: .entity, id: "project-alpha"), group: .entities, title: "alpha-project", detail: "A project",
                    badge: "Project", mark: .symbol("folder"), trailing: "Oct 18", destination: .entity(id: "project-alpha")),
            FindRow(key: FindRowKey(kind: .entity, id: "person-bob"), group: .entities, title: "bob-example", detail: "Reviews the work",
                    badge: "Person", mark: .symbol("person"), trailing: "Oct 11", destination: .entity(id: "person-bob")),
            FindRow(key: FindRowKey(kind: .entity, id: "tool-beta"), group: .entities, title: "beta-tool", detail: "Runs the tests",
                    badge: "Tool", mark: .symbol("wrench.and.screwdriver"), destination: .entity(id: "tool-beta")),
        ]

        let asking = AskViewModel(store: store)
        asking.question = "What does alpha-project use?"
        asking.isAsking = true
        let recent = AskViewModel(store: store)
        recent.history = [
            AskHistoryEntry(question: "What does alpha-project use?", askedAt: Date(timeIntervalSince1970: 1_790_000_000), answer: nil),
            AskHistoryEntry(question: "Who reviews beta-tool?", askedAt: Date(timeIntervalSince1970: 1_789_000_000), answer: nil),
        ]

        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let name = mode == .dark ? "dark" : "light"

            let list = VStack(alignment: .leading, spacing: 2) {
                FindRowView(row: rows[0], selected: true)
                FindRowView(row: rows[1], selected: false)
                FindRowView(row: rows[2], selected: false)
            }
            .padding(CicadaTheme.spacingSM)
            .background(CicadaTheme.surface)
            try snapshot(list, size: CGSize(width: 640, height: 190), mode: mode, store: store, graph: graph,
                         to: out.appendingPathComponent("palette-rows-\(name).png"))

            try snapshot(AskPanel(onSelectEntity: { _ in }, hostedViewModel: asking)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                            .background(CicadaTheme.surface),   // as the palette hosts it
                         size: CGSize(width: 640, height: 260), mode: mode, store: store, graph: graph,
                         to: out.appendingPathComponent("palette-ask-asking-\(name).png"))
            try snapshot(AskPanel(onSelectEntity: { _ in }, hostedViewModel: recent)
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                            .background(CicadaTheme.surface),   // as the palette hosts it
                         size: CGSize(width: 640, height: 200), mode: mode, store: store, graph: graph,
                         to: out.appendingPathComponent("palette-ask-recent-\(name).png"))

            try snapshot(ExportWalkthroughSheet(vendor: .chatgpt, onClose: {}),
                         size: CGSize(width: 860, height: 700), mode: mode, store: store, graph: graph,
                         to: out.appendingPathComponent("export-walkthrough-\(name).png"))
        }
    }

    private func snapshot<V: View>(_ view: V, size: CGSize, mode: AppColorScheme, store: Store, graph: GraphViewModel,
                                   to url: URL) throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(store)
            .environment(graph)
            .environment(ProvenanceRouter())
            .environment(AppRouter())
            .environment(ExportWaitStore(defaults: UserDefaults(suiteName: "snapshot-\(UUID().uuidString)")!,
                                         scheduler: FakeReminders(grant: true)))
            .environment(\.colorScheme, mode == .dark ? .dark : .light)
        let host = NSHostingView(rootView: root)
        host.frame = NSRect(origin: .zero, size: size)
        let window = NSWindow(contentRect: host.frame.offsetBy(dx: -20_000, dy: -20_000), styleMask: [.borderless],
                              backing: .buffered, defer: false)
        window.appearance = NSAppearance(named: mode == .dark ? .darkAqua : .aqua)
        window.contentView = host
        window.orderFrontRegardless()
        defer { window.orderOut(nil) }
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.3))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}
