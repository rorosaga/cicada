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
                     processed: Bool = false, link: String? = nil, change: String? = "new") throws -> EpisodeQueueItem {
            var json: [String: Any] = ["id": id, "timestamp": stamp(hoursAgo), "source": origin, "origin": origin,
                                       "title": title, "preview": preview, "processed": processed]
            if let change, !processed { json["change"] = change }
            if let link { json["copyKind"] = "link"; json["copyValue"] = link }
            return try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: json))
        }
        let episodes = [
            try episode("ep_1", origin: "claude-code", title: "Planning the alpha-project release",
                        preview: "Went through what is left before the release: the installer, the signing key and the notes for the testers.",
                        hoursAgo: 3),
            try episode("ep_2", origin: "claude-code", title: "Why the beta-tool tests flake",
                        preview: "The tests share a temporary folder; two runs at once step on each other's files.",
                        hoursAgo: 30, change: "updated"),
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

    /// The kept-for-lookup card, opened, with one source opened (owner 2026-11-23).
    func test_writeTheKeptCard() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_SLEEP_CARDS_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_SLEEP_CARDS_SNAPSHOTS=<dir> to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        CicadaTheme.uiScale = 1
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let vm = SleepViewModel(store: store, putSchedule: { $0 })
        func saved(_ id: String, _ title: String, _ link: String, daysAgo: Double) throws -> EpisodeQueueItem {
            try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: [
                "id": id, "timestamp": ISO8601DateFormatter().string(from: Date().addingTimeInterval(-daysAgo * 86_400)),
                "source": "bookmark", "origin": "chrome-bookmark", "title": title, "preview": "# " + title,
                "processed": true, "copyKind": "link", "copyValue": link,
            ]))
        }
        let items = [try saved("ep_1", "A guide to continuous corners", "https://example.com/design/corners", daysAgo: 1),
                     try saved("ep_2", "How tide tables are computed", "https://example.org/tides", daysAgo: 4),
                     try saved("ep_3", "CRDTs for local-first apps", "https://example.net/crdts", daysAgo: 9)]
        let sources: [SleepKept.Source] = [.init(origin: "chrome-bookmark", count: 412), .init(origin: "safari-bookmark", count: 96),
                                           .init(origin: "chrome-tab-group", count: 14)]
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let view = KeptForLookupCard(kept: 522, load: { origin, _ in
                SleepKept(total: 522, sources: sources, items: origin == nil ? [] : items)
            }, initiallyOpen: true, initiallyOpenSources: ["chrome-bookmark"])
                .padding(CicadaTheme.spacingLG)
            try snapshot(view, size: CGSize(width: 720, height: 640), mode: mode, store: store, vm: vm,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("kept-\(mode == .dark ? "dark" : "light").png"))
        }
    }

    /// The Reader's sentence and wash for a source that changed since Sleep read it (owner 2026-11-23).
    func test_writeTheChangedWash() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_SLEEP_CARDS_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_SLEEP_CARDS_SNAPSHOTS=<dir> to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        CicadaTheme.uiScale = 1
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let vm = SleepViewModel(store: store, putSchedule: { $0 })
        let segments: [CitedSpan.Segment] = [
            .init(text: "Trip to the coast\n\nLeave on Friday after lunch.\n", mark: .plain),
            .init(text: "Take the ferry, not the bridge: the bridge is closed for repairs.", mark: .changed),
            .init(text: "\nBook the cabin by the lighthouse.\n", mark: .plain),
            .init(text: "Bring the big tent as a backup.", mark: .changed),
        ]
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let view = VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                ReaderBannerView(banner: .updated(parts: 2, removed: ["Take the bridge; it is faster."]))
                CitedPassage(segments: segments, font: CicadaTheme.detailBodyFont)
                ReaderBannerView(banner: .deletedAtSource)
            }
            .padding(CicadaTheme.spacingXL)
            try snapshot(view, size: CGSize(width: 520, height: 330), mode: mode, store: store, vm: vm,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("reader-changed-\(mode == .dark ? "dark" : "light").png"))
        }
    }

    /// Past reads as cards with the sources' marks (owner 2026-11-23), one open with a page's change shown.
    func test_writeThePastReadsCards() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_SLEEP_CARDS_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_SLEEP_CARDS_SNAPSHOTS=<dir> to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        CicadaTheme.uiScale = 1
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let vm = SleepViewModel(store: store, putSchedule: { $0 })
        func cycle(_ commit: String, _ date: String, episodes: Int, created: Int, updated: Int) throws -> SleepHistoryEntry {
            try JSONDecoder().decode(SleepHistoryEntry.self, from: Data("""
            {"commitHash": "\(commit)", "date": "\(date)", "message": "Sleep cycle", "filesChanged": [],
             "engine": "claude-cli", "kind": "sleep", "entitiesCreated": \(created), "entitiesUpdated": \(updated),
             "episodes": \(episodes), "sessions": \(episodes), "authors": ["claude-haiku-5-5"], "durationMs": 1274000,
             "usageSummary": {"basis": "list", "connection": "claude-plan", "costUsd": null, "engine": "claude-cli",
                              "equivCostUsd": 0.03, "plan": null, "planShare": []}}
            """.utf8))
        }
        let entries = [try cycle("aaa1111", "2026-11-23T03:00:00+00:00", episodes: 9, created: 1, updated: 18),
                       try cycle("bbb2222", "2026-11-22T03:00:00+00:00", episodes: 12, created: 0, updated: 4),
                       try cycle("ccc3333", "2026-11-21T03:00:00+00:00", episodes: 1, created: 0, updated: 5)]
        func conv(_ id: String, _ origin: String, _ title: String) -> SleepConsolidated.Conversation {
            .init(id: id, title: title, origin: origin, timestamp: "2026-11-22T18:00:00+00:00")
        }
        let first = SleepConsolidated(
            commits: ["aaa1111"],
            conversations: [conv("ep_1", "claude-code", "Planning the alpha-project release"),
                            conv("ep_2", "claude-code", "Why the beta-tool tests flake"),
                            conv("ep_3", "chatgpt", "A reading list for the week"),
                            conv("ep_4", "telegram", "Dinner on Friday")],
            created: [.init(id: "gamma-idea", name: "gamma-idea", commits: ["aaa1111"])],
            updated: [.init(id: "alpha-project", name: "alpha-project", commits: ["aaa1111"]),
                      .init(id: "bob-example", name: "bob-example", commits: ["aaa1111"]),
                      .init(id: "beta-tool", name: "beta-tool", commits: ["aaa1111"]),
                      .init(id: "delta-place", name: "delta-place", commits: ["aaa1111"])],
            questionsRaised: [.init(id: "inbox-1", title: "Is beta-tool the same as beta-runner?")],
            counts: ["conversations": 9, "created": 1, "updated": 18, "questions_raised": 3, "questions_settled": 0])
        let second = SleepConsolidated(
            commits: ["bbb2222"], conversations: [conv("ep_5", "chrome-bookmark", "A guide to continuous corners")],
            updated: [.init(id: "alpha-project", name: "alpha-project"), .init(id: "beta-tool", name: "beta-tool")],
            counts: ["conversations": 12, "created": 0, "updated": 4])
        let items: [SleepConsolidatedKey: SleepConsolidated] = [.commit("aaa1111"): first, .commit("bbb2222"): second]
        let diff = EntityDiff(added: "", removed: "", lines: [
            .init(kind: "hunk", text: "@@ -12,4 +12,5 @@"),
            .init(kind: "context", oldLine: 12, newLine: 12, text: "## Where it stands"),
            .init(kind: "remove", oldLine: 13, text: "The release waits on the installer."),
            .init(kind: "add", newLine: 13, text: "The installer is done; the release waits on the signing key."),
            .init(kind: "add", newLine: 14, text: "Testers get the notes the same day."),
            .init(kind: "context", oldLine: 14, newLine: 15, text: ""),
        ])

        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let name = mode == .dark ? "dark" : "light"
            let list = ConsolidationHistoryCard(entries: entries, details: [:], expanded: nil, items: items,
                                                onToggle: { _ in })
                .padding(CicadaTheme.spacingLG)
            try snapshot(list, size: CGSize(width: 760, height: 430), mode: mode, store: store, vm: vm,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("past-reads-\(name).png"))
            let open = ConsolidationHistoryCard(entries: Array(entries.prefix(1)), details: [:], expanded: "aaa1111",
                                                items: items, onToggle: { _ in })
                .padding(CicadaTheme.spacingLG)
            try snapshot(open, size: CGSize(width: 760, height: 760), mode: mode, store: store, vm: vm,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("past-reads-open-\(name).png"))
            let row = RunPageRow(page: .init(id: "alpha-project", name: "alpha-project"), isNew: false,
                                 commits: ["aaa1111"], initiallyOpen: true, loadDiff: { _, _, _ in diff })
                .padding(CicadaTheme.spacingLG)
                .background(CicadaTheme.bgFocus)
            try snapshot(row, size: CGSize(width: 640, height: 220), mode: mode, store: store, vm: vm,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("past-reads-change-\(name).png"))
        }
    }

    private func snapshot<V: View>(_ view: V, size: CGSize, mode: AppColorScheme, store: Store, vm: SleepViewModel,
                                   to url: URL) throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(store)
            .environment(vm)
            .environment(AppRouter())
            .environment(ProvenanceRouter())
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
