import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Projects v2's PR screenshots, rendered offscreen (an `NSHostingView` in a never-shown window — never the running
/// app) from the demo scenario's wire (`projects-demo.json`) plus synthetic fading and past rows. Skipped unless
/// `PROJECTS_V2_RENDER_DIR` names a folder; the PNGs land there, light and dark.
@MainActor
final class ProjectsV2RenderTests: XCTestCase {
    private let today = ProjectFixtures.today

    private static let names = ["Reading Lamp Rebuild", "Thesis Draft", "Bike Tune-up", "Recipe Box", "Spanish Practice",
                                "Garage Shelving", "Photo Archive", "Home Network", "Board Game Prototype",
                                "Running Plan", "Synth Kit", "Balcony Garden"]

    private func synthetic(_ objects: [[String: Any]]) throws -> [ProjectRow] {
        let data = try JSONSerialization.data(withJSONObject: ["projects": objects])
        return try JSONDecoder().decode(ProjectsResponse.self, from: data).projects
    }

    /// Three projects quiet past their rhythm, and 120 past ones last heard across two years. Synthetic only.
    private func extraRows() throws -> [ProjectRow] {
        let fading: [[String: Any]] = (0..<3).map { i in
            ["id": "fading-\(i)", "name": Self.names[i], "oneLiner": "A synthetic project that went quiet.",
             "status": "active", "medianGapDays": 4, "lastMomentDay": today.adding(-30 - 9 * i).description]
        }
        let past: [[String: Any]] = (0..<120).map { i in
            ["id": "past-\(i)", "name": "\(Self.names[i % Self.names.count]) \(i / Self.names.count + 1)",
             "oneLiner": "A synthetic past project.", "status": "archived",
             "lastMomentDay": today.adding(-95 - 6 * i).description]
        }
        return try synthetic(fading + past)
    }

    func testRenderRootPastAndADetailInBothAppearances() async throws {
        guard let dir = ProcessInfo.processInfo.environment["PROJECTS_V2_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set PROJECTS_V2_RENDER_DIR to render the Projects v2 screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        let wire = try ProjectFixtures.load()
        let rows = wire.projects.projects + (try extraRows())
        let reads = FakeProjectsAPI()
        for (id, t) in wire.timelines {
            reads.timelineReplies[id] = Array(repeating: .success(Conditional(value: t, etag: "t", notModified: false)),
                                              count: 8)
        }
        let cache = ProjectsCache(api: reads)
        await cache.refreshTimeline("rover-arm-project")
        let backlog = BacklogCache(api: FakeBacklogAPI())
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }

        for dark in [false, true] {
            CicadaTheme.mode = dark ? .dark : .light
            let scheme: ColorScheme = dark ? .dark : .light
            let suffix = dark ? "dark" : "light"
            let options = ProjectsListOptions()

            // STATE 0 — Current: in motion, parts under their parents, Gone quiet under its label (no folds, v3).
            let current = ProjectsModel.entries(rows, tab: .current, query: "", today: today, options: options)
            let root = page(eyebrow: ProjectsModel.eyebrow(partial: false),
                            tab: .current, rows: rows) {
                list(current, tab: .current, style: .wide, openId: nil)
            }
            try await write(root, size: CGSize(width: 1100, height: 600), scheme: scheme, store: store, cache: cache,
                      backlog: backlog, to: base.appendingPathComponent("projects-root-\(suffix).png"))

            // Past: searchable, under year labels, a page at a time.
            let past = ProjectsModel.entries(rows, tab: .past, query: "", today: today)
            let pastPage = page(eyebrow: ProjectsModel.eyebrow(partial: false),
                                tab: .past, rows: rows) {
                list(past, tab: .past, style: .wide, openId: nil)
            }
            try await write(pastPage, size: CGSize(width: 1100, height: 600), scheme: scheme, store: store, cache: cache,
                      backlog: backlog, to: base.appendingPathComponent("projects-past-\(suffix).png"))

            // STATE 1 — a project open: the list narrows, the detail answers first and folds the rest.
            let rover = try XCTUnwrap(rows.first { $0.id == "rover-arm-project" })
            let detail = page(eyebrow: ProjectsModel.eyebrow(partial: false),
                              tab: .current, rows: rows) {
                HStack(alignment: .top, spacing: 0) {
                    list(current, tab: .current, style: .triage, openId: "rover-arm-project")
                        .frame(width: 300, alignment: .topLeading)
                    Rectangle().fill(CicadaTheme.border).frame(width: 1)
                    ProjectDetailColumn(projectId: "rover-arm-project", row: rover, parentName: nil, today: today,
                                        gutter: CicadaTheme.spacingXL, hiddenListCount: nil, openCard: nil,
                                        openBacklogItem: nil, onShowList: {}, onClose: {}, onEscape: {},
                                        openProject: { _ in }, openEntity: { _ in }, openItem: { _ in },
                                        full: .constant(nil))
                }
            }
            try await write(detail, size: CGSize(width: 1240, height: 760), scheme: scheme, store: store, cache: cache,
                      backlog: backlog, to: base.appendingPathComponent("projects-detail-\(suffix).png"))
        }
    }

    private func page<Content: View>(eyebrow: String, tab: ProjectsTab, rows: [ProjectRow],
                                     @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: eyebrow) {
                AdaptiveTextTabs(tabs: ProjectsModel.tabs(ProjectsModel.counts(rows, today: self.today)), selection: .constant(tab),
                                 menuTitle: Copy.Projects.tabMenu)
            }
            content()
        }
    }

    private func list(_ entries: [ProjectsEntry], tab: ProjectsTab, style: ColumnPlan.ListStyle,
                      openId: String?) -> some View {
        ProjectsListColumn(entries: entries, style: style, today: today, state: .list, tab: tab, query: "",
                           findOpen: .constant(false), findText: .constant(""), openId: openId, tap: { _ in },
                           showMore: { }, move: { _ in }, focusDetail: {},
                           escape: {}, retry: {})
    }

    private func write<V: View>(_ view: V, size: CGSize, scheme: ColorScheme, store: Store, cache: ProjectsCache,
                                backlog: BacklogCache, to url: URL) async throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(store)
            .environment(cache)
            .environment(backlog)
            .environment(AppRouter())
            .environment(ProvenanceRouter())
            .environment(\.colorScheme, scheme)
        let host = NSHostingView(rootView: root)
        host.frame = CGRect(origin: .zero, size: size)
        host.appearance = NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = host.appearance
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        // The detail derives its story off the main actor (R-FA2): give it a few turns to land.
        // A nested run loop holds the main actor, so its tasks wait: suspend instead.
        for _ in 0..<6 {
            RunLoop.main.run(until: Date().addingTimeInterval(0.1))
            try await Task.sleep(nanoseconds: 300_000_000)
            host.layoutSubtreeIfNeeded()
        }
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}
