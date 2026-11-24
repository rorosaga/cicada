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
                     processed: Bool = false, link: String? = nil, change: String? = "new",
                     chat: [String: Any]? = nil) throws -> EpisodeQueueItem {
            var json: [String: Any] = ["id": id, "timestamp": stamp(hoursAgo), "source": origin, "origin": origin,
                                       "title": title, "preview": preview, "processed": processed]
            if let change, !processed { json["change"] = change }
            if let chat { json["chat"] = chat }
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
        let chats = [
            try episode("ep_m1", origin: "imessage", title: "Messages with bob-example · 2026-11-23",
                        preview: "bob-example: are we still on for Friday?", hoursAgo: 2,
                        chat: ["id": "b0b", "name": "bob-example", "messages": 14]),
            try episode("ep_m2", origin: "imessage", title: "Messages with bob-example · 2026-11-22",
                        preview: "You: sending the notes tonight", hoursAgo: 26, change: "updated",
                        chat: ["id": "b0b", "name": "bob-example", "messages": 9]),
            try episode("ep_m3", origin: "imessage", title: "Messages · alpha-project · 2026-11-22",
                        preview: "carol-example: the build is green", hoursAgo: 30,
                        chat: ["id": "a1fa", "name": "alpha-project", "messages": 66, "group": true]),
        ]
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let view = StudyListCard(rows: [StudyRow(origin: "imessage", label: "Messages", count: 3, oldestAge: "1d",
                                                     read: nil, total: nil)],
                                     episodes: chats, queueLoad: .loaded(count: 3), initiallyOpen: ["imessage"])
                .padding(CicadaTheme.spacingLG)
            try snapshot(view, size: CGSize(width: 720, height: 330), mode: mode, store: store, vm: vm,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("chat-cards-\(mode == .dark ? "dark" : "light").png"))
        }
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

    /// A chat's waiting messages as one conversation under the faded snippet of what Sleep read (owner 2026-11-23),
    /// and an updated note with what was already read faded.
    func test_writeTheChatThread() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_SLEEP_CARDS_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_SLEEP_CARDS_SNAPSHOTS=<dir> to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        CicadaTheme.uiScale = 1
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let vm = SleepViewModel(store: store, putSchedule: { $0 })
        typealias Line = ReaderChatTests.Line
        func sitting(_ id: String, _ lines: [Line]) -> EpisodeText {
            ReaderChatTests.conversation(lines, episode: id, title: "Messages with bob-example",
                                         timestamp: lines.first?.ts, origin: "imessage",
                                         conversationId: "imessage:0123456789abcdef:k1", correspondent: "bob-example")
        }
        let read = sitting("s0", [
            Line(marker: "user", text: "did the parcel for alpha-project ship?", ts: "2026-11-20T10:00:00+00:00"),
            Line(marker: "speaker:bob", text: "Yes, it left the depot this morning.", ts: "2026-11-20T10:02:00+00:00"),
            Line(marker: "user", text: "great, thanks", ts: "2026-11-20T10:03:00+00:00"),
            Line(marker: "speaker:bob", text: "I'll tell you when it lands.", ts: "2026-11-20T10:04:00+00:00"),
        ])
        let first = sitting("s1", [
            Line(marker: "user", text: "can you check when it arrives?", ts: "2026-11-22T09:00:00+00:00"),
            Line(marker: "speaker:bob", text: "Thursday, between 11 and 3. It was scanned this morning.",
                 ts: "2026-11-22T09:01:00+00:00"),
        ])
        let second = sitting("s2", [
            Line(marker: "user", text: "and the second one?", ts: "2026-11-22T19:30:00+00:00"),
            Line(marker: "speaker:bob", text: "Still waiting for a date. I'll check again tomorrow.",
                 ts: "2026-11-22T19:31:00+00:00"),
            Line(marker: "user", text: "ok", ts: "2026-11-23T08:10:00+00:00"),
        ])
        let layout = ChatThread.layout([first, second], before: read)
        let note: [CitedSpan.Segment] = [
            .init(text: "Trip to the coast\n\nLeave on Friday after lunch.\nBook the cabin by the lighthouse.\n", mark: .plain),
            .init(text: "Take the ferry, not the bridge: the bridge is closed for repairs.", mark: .changed),
            .init(text: "\nPack the stove and the map.", mark: .plain),
        ]
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let view = VStack(alignment: .leading, spacing: 0) {
                ChatThreadRows(layout: layout)
            }
            .padding(CicadaTheme.scaled(ReaderColumn.inset))
            .background(CicadaTheme.bgPane)
            try snapshot(view, size: CGSize(width: 520, height: 620), mode: mode, store: store, vm: vm,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("chat-thread-\(mode == .dark ? "dark" : "light").png"))
            let updated = VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                ReaderBannerView(banner: .updated(parts: 1, removed: []))
                CitedPassage(segments: note).environment(\.readTextFaded, true)
            }
            .padding(CicadaTheme.spacingXL)
            .background(CicadaTheme.bgPane)
            try snapshot(updated, size: CGSize(width: 520, height: 260), mode: mode, store: store, vm: vm,
                         to: URL(fileURLWithPath: dir).appendingPathComponent("reader-faded-\(mode == .dark ? "dark" : "light").png"))
        }
    }

    /// Past sleeps as the Queue's cards (owner 2026-11-24), from the SHARED fixtures the backend writes: a run closed,
    /// and opened with every case — two sources and a meeting, a conversation from another machine, a saved link's site,
    /// one page of each change kind, a page two conversations fed, and the pages no conversation stands behind — at the
    /// page's 1,040 pt column; the filter on one kind; a page's change open; one machine selected; and an older
    /// backend's items (no attribution).
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
        let fixtures = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("fixtures")
        func fixture<T: Decodable>(_ type: T.Type, _ name: String) throws -> T {
            try JSONDecoder().decode(T.self, from: Data(contentsOf: fixtures.appendingPathComponent(name)))
        }
        // The fixture's run, moved to last night so the head reads "Today, …" like a real card.
        let runJSON = try String(contentsOf: fixtures.appendingPathComponent("sleep-history-run.json"), encoding: .utf8)
            .replacingOccurrences(of: "2026-09-30T10:14:00+00:00", with: "2026-11-24T02:10:00+00:00")
            .replacingOccurrences(of: "2026-09-30T17:05:00+00:00", with: "2026-11-24T04:25:00+00:00")
        let run = try JSONDecoder().decode(SleepHistoryEntry.self, from: Data(runJSON.utf8))
        func cycle(_ commit: String, _ date: String, episodes: Int, created: Int, updated: Int) throws -> SleepHistoryEntry {
            try JSONDecoder().decode(SleepHistoryEntry.self, from: Data("""
            {"commitHash": "\(commit)", "date": "\(date)", "message": "Sleep cycle", "filesChanged": [],
             "engine": "claude-cli", "kind": "sleep", "entitiesCreated": \(created), "entitiesUpdated": \(updated),
             "episodes": \(episodes), "sessions": \(episodes), "authors": ["claude-haiku-5-5"], "durationMs": 1274000,
             "usageSummary": {"basis": "list", "connection": "claude-plan", "costUsd": null, "engine": "claude-cli",
                              "equivCostUsd": 0.03, "plan": null, "planShare": []}}
            """.utf8))
        }
        // An older backend's items: conversations and pages with no attribution at all.
        func conv(_ id: String, _ origin: String, _ title: String) -> SleepConsolidated.Conversation {
            .init(id: id, title: title, origin: origin, timestamp: "2026-11-22T18:00:00+00:00")
        }
        let older = SleepConsolidated(
            commits: ["bbb2222"],
            conversations: [conv("ep_1", "claude-code", "Planning the alpha-project release"),
                            conv("ep_2", "claude-code", "Why the beta-tool tests flake"),
                            conv("ep_3", "chatgpt", "A reading list for the week")],
            created: [.init(id: "gamma-idea", name: "gamma-idea", commits: ["bbb2222"])],
            updated: [.init(id: "alpha-project", name: "alpha-project", commits: ["bbb2222"]),
                      .init(id: "beta-tool", name: "beta-tool", commits: ["bbb2222"])],
            counts: ["conversations": 3, "created": 1, "updated": 2])
        let entries = [run, try cycle("bbb2222", "2026-11-22T03:00:00+00:00", episodes: 3, created: 1, updated: 2),
                       try cycle("ccc3333", "2026-11-21T03:00:00+00:00", episodes: 1, created: 0, updated: 5)]
        let fresh = try fixture(SleepConsolidated.self, "sleep-run-items.json")
        let items: [SleepConsolidatedKey: SleepConsolidated] = [.run("sleep_leg1"): fresh, .commit("bbb2222"): older]
        let machines = [MachineStatus(deviceId: nil, name: "saga-01", role: "server", connected: true, how: "local",
                                      queue: 0, current: true, home: true),
                        MachineStatus(deviceId: "device-a", name: "device-a", connected: true, how: "tailscale", queue: 0)]
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
            func write<V: View>(_ view: V, _ height: CGFloat, _ file: String) throws {
                let framed = view
                    .padding(.horizontal, CicadaTheme.spacingXL)
                    .environment(\.runPageDiffLoader, { _, _, _ in diff })
                try snapshot(framed, size: CGSize(width: 1_040 + 2 * 24, height: height), mode: mode, store: store, vm: vm,
                             to: URL(fileURLWithPath: dir).appendingPathComponent("\(file)-\(name).png"))
            }
            func history(expandedRun: String? = nil, expanded: String? = nil, machineId: String? = nil, filter: SleepConsolidated.Change? = nil,
                         page: String? = nil, only: Int = 3) -> some View {
                ConsolidationHistoryCard(entries: Array(entries.prefix(only)), details: [:], expanded: expanded,
                                         expandedRun: expandedRun, items: items, onToggle: { _ in },
                                         machineId: machineId, machineName: machineId.map { _ in "device-a" },
                                         machines: machines, initialFilter: filter, initiallyOpenPage: page)
                    .padding(.vertical, CicadaTheme.spacingLG)
            }
            try write(history(), 430, "past-sleeps")
            try write(history(expandedRun: "sleep_leg1", only: 1), 1_560, "past-sleeps-open")
            try write(history(expandedRun: "sleep_leg1", filter: .archived, only: 1), 760, "past-sleeps-open-archived")
            try write(history(expandedRun: "sleep_leg1", page: "ep_2026-10-01_001|upd-one", only: 1), 1_560,
                      "past-sleeps-open-change")
            try write(history(expandedRun: "sleep_leg1", machineId: "device-a", only: 1), 620, "past-sleeps-machine")
            try write(history(expanded: "bbb2222", only: 2), 900, "past-sleeps-older-backend")
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
