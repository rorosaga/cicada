import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// G245 (ruling 78, plan 3.2) — the source page's PR screenshots, rendered offscreen (an `NSHostingView` in a never-shown
/// window, never the running app) from the stage-1 streams fixture and placeholder items: X (connected, several streams,
/// items on more than one list), YouTube (four streams, two off), Apple Notes (read on this Mac), a chat source (its
/// stream needs the source's own setup), a source not connected, and onboarding's compact mode.
///
/// Skipped unless `SOURCES_PAGE_RENDER_DIR` names a folder; the PNGs land there as `page-*.png`. Run:
///
///     SOURCES_PAGE_RENDER_DIR=<folder> swift test --filter SourcePageStreamsRenderTests
///
/// Pictures come from Cicada's API, which is offline under XCTest, so a mark with no bundled logo draws its glyph.
/// A window that was never shown is not key, and macOS draws every switch of such a window in its inactive grey (an
/// ON switch and an OFF one differ only by the knob's side here, even with an explicit tint, on a window made key off
/// screen too). The running app's switches take the accent while its window is key, as Settings' do.
@MainActor
final class SourcePageStreamsRenderTests: XCTestCase {
    private let now = SourceStreamsFixture.now

    private func iso(_ ago: TimeInterval) -> String { ISO8601DateFormatter().string(from: now.addingTimeInterval(-ago)) }

    private func day(_ daysAgo: Int) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone(identifier: "UTC")
        return f.string(from: now.addingTimeInterval(-86_400 * Double(daysAgo)))
    }

    private func item(_ id: String, _ title: String, host: String, daysAgo: Int, words: String? = nil,
                      lists: [String]? = nil, folders: [String]? = nil, depth: String? = nil, posted: Int? = nil, why: [String] = []) -> ChannelItem {
        var item = ChannelItem(kind: .media, id: id, title: title, day: day(daysAgo), host: host, site: host,
                               why: words == nil && why.isEmpty ? nil : ChannelItemWhy(labels: why, text: words))
        item.lists = lists
        item.folders = folders
        item.depth = depth
        item.posted = posted.map(day)
        return item
    }

    private var xItems: [ChannelItem] {
        [item("m1", "A short thread on how local-first apps sync without a server", host: "x.com", daysAgo: 1,
              words: "For the sync engine: the part about merging edits without a coordinator.",
              lists: ["Bookmarks", "Likes"], depth: "read", posted: 2),
         item("m2", "Notes from a talk on small, durable software", host: "x.com", daysAgo: 2,
              lists: ["Bookmarks"], folders: ["Design"], posted: 3),
         item("m3", "The case for plain files as the interface", host: "x.com", daysAgo: 4,
              words: "Reread when writing the storage doc.", lists: ["Likes"], posted: 6),
         item("m4", "A diagram of how a static site gets built", host: "x.com", daysAgo: 6, lists: ["Bookmarks"], folders: ["Reading"]),
         item("m5", "Why the report was shorter this quarter", host: "x.com", daysAgo: 9,
              lists: ["Bookmarks", "Likes"], depth: "read", posted: 12),
         item("m6", "A map of the trails near the lake", host: "x.com", daysAgo: 12, lists: ["Bookmarks"])]
    }

    private func page(_ channel: String, _ items: [ChannelItem], total: Int) -> ChannelItemsPage {
        ChannelItemsPage(channel: channel, total: total, items: items, latest: day(1))
    }

    /// The streams' own rows, as the fixture says them, with a couple of changes for the states a render needs.
    private func streams(_ edit: (inout SourceStreamsResponse) -> Void = { _ in }) throws -> SourceStreamsResponse {
        var response = try SourceStreamsFixture.load()
        edit(&response)
        return response
    }

    private func scene(extra: [SourceChannel] = [], streams response: SourceStreamsResponse,
                       overview: [SourceOverview] = []) async throws -> (Store, [SourceCatalogRow], ResolvedStreams) {
        let chrome = BrowserInventory.catalog.first { $0.id == "chrome" }!
        let channels = [
            SourceChannel(id: "x", label: "X", connected: true, count: 1_246, lastSync: iso(3_600 * 4), lastError: nil),
            SourceChannel(id: "notes", label: "Apple Notes", connected: true, count: 88, lastSync: iso(60 * 12), lastError: nil),
            SourceChannel(id: "youtube", label: "YouTube", connected: true, count: 41, lastSync: iso(86_400 * 4), lastError: nil),
        ] + extra
        let sync = FakeSyncAPI()
        sync.replies[.channels] = .value(channels)
        sync.replies[.sourcesOverview] = .value(overview)
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: sync)
        await store.refresh([.channels, .sourcesOverview])
        let entries = SourceCatalog.entries(browsers: [chrome], wisprPresent: false, hexPresent: false,
                                            overview: overview, channels: channels)
        let readers = ["notes": true]
        let rows = SourceCatalog.rows(entries: entries, channels: channels, overview: overview, readableSites: [],
                                      localReaders: readers, savedListsOn: ["x", "youtube"], localAgent: true,
                                      savedListsRead: ["x", "youtube"])
        let resolved = SourceStreamOverlay.resolve(response, app: StreamAppState(readers: readers), entries: entries,
                                                   now: now)
        return (store, rows, resolved)
    }

    private func overviewRow(_ id: String, _ label: String, kind: SourceKind = .social) throws -> SourceOverview {
        try JSONDecoder().decode(SourceOverview.self, from: Data("""
            {"id": "\(id)", "label": "\(label)", "kind": "\(kind.rawValue)", "mark": "\(id)", "connected": true,
             "channelId": "\(id)", "intent": "saved", "items": 1246, "actions": ["sync"]}
            """.utf8))
    }

    private func env(_ store: Store, cache: ChannelItemsCache, streams: SourceStreamsResponse) -> some ViewModifier {
        PageEnv(store: store, cache: cache, streams: streams, now: now)
    }

    private struct PageEnv: ViewModifier {
        let store: Store
        let cache: ChannelItemsCache
        let streams: SourceStreamsResponse
        let now: Date

        func body(content: Content) -> some View {
            let model = SourceStreamsModel(fetch: { _ in Conditional(value: streams, etag: nil, notModified: false) })
            model.apply(streams)
            let lights = BrowserWatcher()
            // Notes is connected in these fixtures, so its page draws the connected state (no Connect step under Reads).
            let notesDefaults = TestDefaults.suite("page-render-\(UUID().uuidString)")!
            notesDefaults.set(true, forKey: AppleNotesWatcher.enabledKey)
            return content
                .environment(store)
                .environment(AppRouter())
                .environment(ReadingAgentModel())
                .environment(LocalSourceWatcher(lights: lights))
                .environment(lights)
                .environment(InboxViewModel(store: store))
                .environment(ExploreCache())
                .environment(cache)
                .environment(ProvenanceRouter())
                .environment(model)
                .environment(AppleNotesWatcher(defaults: notesDefaults,
                                               notesRunning: { false }, read: { throw CancellationError() }))
                .environment(SourceStreamCheckModel(deps: .init(runReader: { _ in "" }, askBackend: { _ in streams })))
        }
    }

    private final class PagesAPI: ChannelItemsAPI, @unchecked Sendable {
        let pages: [String: ChannelItemsPage]
        init(_ pages: [String: ChannelItemsPage]) { self.pages = pages }
        func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
            -> Conditional<ChannelItemsPage> {
            guard let page = pages[channel] else { throw APIError.httpError(404, "") }
            return Conditional(value: page, etag: nil, notModified: false)
        }
    }

    func testRenderASourcesPageInTheStatesThatMatter() async throws {
        guard let dir = ProcessInfo.processInfo.environment["SOURCES_PAGE_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set SOURCES_PAGE_RENDER_DIR to render the source page's screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }

        // The chat source: its one stream needs the source's own setup (the chats to tick), so no switch stands in the row.
        let chat = try streams { response in
            response.sources.removeAll { $0.id == "imessage" }
            response.sources.append(SourceStreamsSource(id: "imessage", label: "Messages", streams: [
                SourceStream(id: "imessage.chats", label: "Chats you ticked", kind: .chats, how: .app, owner: .backend,
                             control: .setup, state: .on, health: .read, lastReadAt: now.addingTimeInterval(-60 * 7),
                             count: 312, depth: .read)]))
        }
        let full = try streams()
        // YouTube: four streams, two off (Playlists and Liked videos were never turned on).
        let youtube = try streams { response in
            guard let at = response.sources.firstIndex(where: { $0.id == "youtube" }) else { return }
            response.sources[at].streams = [
                SourceStream(id: "youtube.watch_later", label: "Watch later", kind: .later, state: .on, health: .read,
                             lastReadAt: now.addingTimeInterval(-3_600 * 9), count: 41, depth: .index,
                             switchRef: StreamSwitch(setting: "youtubeLists", key: "watch_later")),
                SourceStream(id: "youtube.history", label: "History", kind: .history, state: .on, health: .read,
                             lastReadAt: now.addingTimeInterval(-3_600 * 30), count: 2_310, depth: .index,
                             switchRef: StreamSwitch(setting: "youtubeLists", key: "history")),
                SourceStream(id: "youtube.playlists", label: "Playlists", kind: .playlists, state: .off,
                             switchRef: StreamSwitch(setting: "youtubeLists", key: "playlists")),
                SourceStream(id: "youtube.liked", label: "Liked videos", kind: .liked, state: .off,
                             switchRef: StreamSwitch(setting: "youtubeLists", key: "liked"))]
        }

        let xRow = try overviewRow("x", "X")
        let ytRow = try overviewRow("youtube", "YouTube", kind: .social)
        let ytItems = [item("v1", "A walk through a small compiler, start to finish", host: "youtube.com", daysAgo: 3,
                            lists: ["Watch later"]),
                       item("v2", "How a mechanical watch keeps time", host: "youtube.com", daysAgo: 8,
                            words: "For the weekend.", lists: ["Watch later"])]
        let cache = ChannelItemsCache(api: PagesAPI([
            "x": page("x", xItems, total: 1_246),
            SourceListKey.make("x", stream: "x.bookmarks"): page("x", xItems.filter { $0.lists?.contains("Bookmarks") ?? false }, total: 214),
            SourceListKey.make("x", stream: "x.likes"): page("x", xItems.filter { $0.lists?.contains("Likes") ?? false }, total: 1_032),
            "youtube": page("youtube", ytItems, total: 41),
            SourceListKey.make("youtube", stream: "youtube.watch_later"): page("youtube", ytItems, total: 41),
        ]))
        for key in ["x", SourceListKey.make("x", stream: "x.bookmarks"), SourceListKey.make("x", stream: "x.likes"),
                    "youtube", SourceListKey.make("youtube", stream: "youtube.watch_later")] {
            await cache.refresh(key)
        }

        let jobs: [(name: String, source: String, response: SourceStreamsResponse, compact: Bool, size: CGSize,
                    tab: String?)] = [
            ("x", "x", full, false, CGSize(width: 760, height: 1_160), nil),
            ("x-bookmarks", "x", full, false, CGSize(width: 760, height: 1_000), "x.bookmarks"),
            ("youtube", "youtube", youtube, false, CGSize(width: 760, height: 880), nil),
            ("notes", "notes", full, false, CGSize(width: 760, height: 520), nil),
            ("chat", "imessage", chat, false, CGSize(width: 760, height: 460), nil),
            ("notconnected", "linkedin", full, false, CGSize(width: 760, height: 520), nil),
            ("onboarding", "x", full, true, CGSize(width: 560, height: 380), nil),
        ]
        for dark in [true, false] {
            CicadaTheme.mode = dark ? .dark : .light
            let scheme: ColorScheme = dark ? .dark : .light
            for job in jobs where dark || ["x", "onboarding"].contains(job.name) {
                let (store, rows, resolved) = try await scene(streams: job.response, overview: [xRow, ytRow])
                var catalog = rows
                if job.source == "linkedin" || job.source == "imessage" {
                    let channels = job.source == "imessage"
                        ? [SourceChannel(id: MessagesWatcher.channel, label: "Messages", connected: true, count: 312,
                                         lastSync: iso(60 * 7), lastError: nil)] : []
                    let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, hexPresent: false, overview: [],
                                                        channels: channels)
                    catalog = SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [],
                                                 localReaders: [:], savedListsOn: [], localAgent: true)
                }
                let row = try XCTUnwrap(catalog.first { $0.id == job.source }, job.source)
                let view = SourceCatalogDetail(row: row, onClose: {}, resolved: resolved, compact: job.compact,
                                               onCheckNow: job.compact ? nil : {}, startTab: job.tab, clock: now)
                    .frame(width: job.size.width, height: job.size.height)
                    .modifier(env(store, cache: cache, streams: job.response))
                let suffix = dark ? "dark" : "light"
                try write(view, size: job.size, scheme: scheme, to: base.appendingPathComponent("page-\(job.name)-\(suffix).png"))
            }
        }
    }

    private func write<V: View>(_ view: V, size: CGSize, scheme: ColorScheme, to url: URL) throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(\.colorScheme, scheme)
        let host = NSHostingView(rootView: root)
        host.frame = CGRect(origin: .zero, size: size)
        host.appearance = NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = host.appearance
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        for _ in 0..<6 { RunLoop.main.run(until: Date().addingTimeInterval(0.1)) }
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}
