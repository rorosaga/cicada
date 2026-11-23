import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The Sleep page's Waiting list as source cards holding episode cards (owner 2026-11-23), light and dark, offscreen.
/// Env-gated: `CICADA_SLEEP_CARDS_SNAPSHOTS=<dir>`. Synthetic titles only.
@MainActor
final class SleepSourceCardsSnapshotTests: XCTestCase {
    func test_writeTheSourceCards() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_SLEEP_CARDS_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_SLEEP_CARDS_SNAPSHOTS=<dir> to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        CicadaTheme.uiScale = 1
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let vm = SleepViewModel(store: store, putSchedule: { $0 })

        let now = Date()
        func stamp(_ hoursAgo: Double) -> String {
            ISO8601DateFormatter().string(from: now.addingTimeInterval(-hoursAgo * 3600))
        }
        func episode(_ id: String, origin: String, title: String, preview: String, hoursAgo: Double,
                     processed: Bool = false, link: String? = nil) throws -> EpisodeQueueItem {
            var json: [String: Any] = ["id": id, "timestamp": stamp(hoursAgo), "source": origin, "origin": origin,
                                       "title": title, "preview": preview, "processed": processed]
            if let link { json["copyKind"] = "link"; json["copyValue"] = link }
            return try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: json))
        }
        let episodes = [
            try episode("ep_1", origin: "claude-code", title: "Planning the alpha-project release",
                        preview: "Went through what is left before the release: the installer, the signing key and the notes for the testers.",
                        hoursAgo: 3),
            try episode("ep_2", origin: "claude-code", title: "Why the beta-tool tests flake",
                        preview: "The tests share a temporary folder; two runs at once step on each other's files.",
                        hoursAgo: 30),
            try episode("ep_3", origin: "claude-code", title: "Reading list for the week",
                        preview: "Three papers on memory for agents, one on scheduling.", hoursAgo: 80, processed: true),
            try episode("ep_4", origin: "chrome-bookmark", title: "A guide to continuous corners",
                        preview: "How squircles differ from rounded rectangles, with examples.", hoursAgo: 50,
                        link: "https://example.com/design/corners"),
        ]
        let rows = [
            StudyRow(origin: "claude-code", label: "Claude Code", count: 2, oldestAge: "1d", read: nil, total: nil),
            StudyRow(origin: "chrome-bookmark", label: "Chrome bookmarks", count: 1, oldestAge: "2d", read: nil, total: nil),
            StudyRow(origin: "notes", label: "Notes", count: 4, oldestAge: "5d", read: nil, total: nil),
        ]

        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let name = mode == .dark ? "dark" : "light"
            let view = StudyListCard(rows: rows, episodes: episodes, queueLoad: .loaded(count: 7),
                                     initiallyOpen: ["claude-code"])
                .padding(CicadaTheme.spacingLG)
            try snapshot(view, size: CGSize(width: 720, height: 640), mode: mode, store: store, vm: vm,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("sleep-source-cards-\(name).png"))
        }
    }

    private func snapshot<V: View>(_ view: V, size: CGSize, mode: AppColorScheme, store: Store, vm: SleepViewModel,
                                   to url: URL) throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(store)
            .environment(vm)
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
        RunLoop.main.run(until: Date().addingTimeInterval(0.4))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        try XCTUnwrap(rep.representation(using: .png, properties: [:])).write(to: url)
    }
}
