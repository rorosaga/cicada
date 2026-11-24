import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// G245 (track B2) — the views' PR screenshots, rendered offscreen (an `NSHostingView` in a never-shown window, never the
/// running app) from placeholder data: LinkedIn's Connections by month, a person's links wearing their sites' marks, Apple
/// Notes as Notes draws it, Notion's tree.
///
/// Skipped unless `SOURCES_VIEWS_RENDER_DIR` names a folder; the PNGs land there. Run:
///
///     SOURCES_VIEWS_RENDER_DIR=<folder> swift test --filter SourceViewsRenderTests
///
/// Pictures come from Cicada's API, which is offline under XCTest, so a face with no picture draws its monogram.
@MainActor
final class SourceViewsRenderTests: XCTestCase {
    private let now = SourceStreamsFixture.now

    private func renderDir() throws -> URL {
        guard let dir = ProcessInfo.processInfo.environment["SOURCES_VIEWS_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set SOURCES_VIEWS_RENDER_DIR to render the views' screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        CicadaTheme.uiScale = 1.0
        return base
    }

    private func iso(_ ago: TimeInterval) -> String { ISO8601DateFormatter().string(from: now.addingTimeInterval(-ago)) }

    private func day(_ daysAgo: Int) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone(identifier: "UTC")
        return f.string(from: now.addingTimeInterval(-86_400 * Double(daysAgo)))
    }

    // MARK: - LinkedIn: Connections

    /// Placeholder people, newest first, across three months; some matched to a page, two with a week's or a month's
    /// precision, one with no date at all.
    private var connections: [LinkedInConnection] {
        let heads = ["Staff engineer at Alpha Works", "Designer, Beta Studio", "Founder at Gamma Labs",
                     "Product lead at Delta Systems", "Research scientist at Epsilon Institute", "Writer and editor",
                     "Operations at Zeta Co", "Engineering manager at Eta Cloud", "Independent consultant",
                     "Data engineer at Theta Analytics", "Head of design at Iota Apps", "Teacher and maker"]
        let names = ["Alex Example", "Blake Sample", "Casey Placeholder", "Drew Fictional", "Emery Demo", "Finley Test",
                     "Gray Imaginary", "Harper Synthetic", "Indigo Mock", "Jules Notional", "Kai Pretend", "Logan Stand-in"]
        let ago = [1, 2, 2, 4, 6, 9, 12, 20, 33, 41, 55, 70]
        return names.indices.map { i in
            var c = LinkedInConnection(id: "c\(i)", name: names[i], headline: heads[i],
                                       url: "https://www.linkedin.com/in/\(names[i].lowercased().replacingOccurrences(of: " ", with: "-"))",
                                       day: day(ago[i]), precision: i == 5 ? .week : (i == 9 ? .month : .day),
                                       page: [0, 3, 7].contains(i) ? "person-\(i)" : nil)
            if i == 11 { c.day = nil; c.precision = .day }
            return c
        }
    }

    private func connectionsPage(_ rows: [LinkedInConnection], total: Int? = nil) -> LinkedInConnectionsPage {
        LinkedInConnectionsPage(rows: rows, total: total ?? rows.count, offset: 0, next: nil, kept: total ?? rows.count)
    }

    private func streams(_ edit: (inout SourceStreamsResponse) -> Void = { _ in }) throws -> SourceStreamsResponse {
        var response = try SourceStreamsFixture.load()
        edit(&response)
        return response
    }

    private func linkedInStreams(connectionsOn: Bool, savedCount: Int?, connectionsCount: Int?) throws -> SourceStreamsResponse {
        try streams { response in
            guard let at = response.sources.firstIndex(where: { $0.id == "linkedin" }) else { return }
            response.sources[at].streams = [
                SourceStream(id: "linkedin.saved", label: "Saved posts", kind: .saved, state: savedCount == nil ? .off : .on,
                             health: savedCount == nil ? nil : .read, lastReadAt: savedCount == nil ? nil : now.addingTimeInterval(-3_600 * 5),
                             count: savedCount, switchRef: StreamSwitch(setting: "savedLists", key: "linkedin")),
                SourceStream(id: "linkedin.connections", label: "Connections", kind: .connections,
                             state: connectionsOn ? .on : .off, health: connectionsOn ? .read : nil,
                             lastReadAt: connectionsOn ? now.addingTimeInterval(-3_600 * 5) : nil, count: connectionsCount,
                             switchRef: StreamSwitch(setting: "savedLists", key: "linkedin-connections"))]
        }
    }

    private struct PageEnv: ViewModifier {
        let store: Store
        let cache: ChannelItemsCache
        let streams: SourceStreamsResponse
        let fetch: LinkedInConnectionsModel.Fetch

        func body(content: Content) -> some View {
            let model = SourceStreamsModel(fetch: { _ in Conditional(value: streams, etag: nil, notModified: false) })
            model.apply(streams)
            let lights = BrowserWatcher()
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
                .environment(\.linkedInConnectionsFetch, fetch)
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

    private func linkedInRow(_ response: SourceStreamsResponse, items: Int) async throws
        -> (Store, SourceCatalogRow, ResolvedStreams) {
        let channels = [SourceChannel(id: "linkedin", label: "LinkedIn", connected: true, count: items, lastSync: iso(3_600 * 5), lastError: nil)]
        let overview = [try JSONDecoder().decode(SourceOverview.self, from: Data("""
            {"id": "linkedin", "label": "LinkedIn", "kind": "social", "mark": "linkedin", "connected": true,
             "channelId": "linkedin", "intent": "saved", "items": \(items), "actions": ["sync"]}
            """.utf8))]
        let sync = FakeSyncAPI()
        sync.replies[.channels] = .value(channels)
        sync.replies[.sourcesOverview] = .value(overview)
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: sync)
        await store.refresh([.channels, .sourcesOverview])
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, hexPresent: false, overview: overview, channels: channels)
        let rows = SourceCatalog.rows(entries: entries, channels: channels, overview: overview, readableSites: [],
                                      localReaders: [:], savedListsOn: ["linkedin"], localAgent: true, savedListsRead: ["linkedin"])
        let resolved = SourceStreamOverlay.resolve(response, app: StreamAppState(readers: [:]), entries: entries, now: now)
        return (store, try XCTUnwrap(rows.first { $0.id == "linkedin" }), resolved)
    }

    func testRenderLinkedInConnections() async throws {
        let base = try renderDir()
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        var saved = ChannelItem(kind: .media, id: "p1", title: "A post about shipping a small tool", day: day(2), host: "linkedin.com", site: "linkedin")
        saved.lists = ["Saved posts"]
        saved.author = "Alex Example"
        let cache = ChannelItemsCache(api: PagesAPI(["linkedin": ChannelItemsPage(channel: "linkedin", total: 2, items: [saved], latest: day(2))]))
        await cache.refresh("linkedin")
        let everyone = connectionsPage(connections)
        let jobs: [(name: String, response: SourceStreamsResponse, fetch: LinkedInConnectionsModel.Fetch, tab: String?, size: CGSize)] = [
            ("connections", try linkedInStreams(connectionsOn: true, savedCount: 2, connectionsCount: 12),
             { _, _, _ in everyone }, "linkedin.connections", CGSize(width: 760, height: 1_320)),
            ("saved", try linkedInStreams(connectionsOn: true, savedCount: 2, connectionsCount: 12),
             { _, _, _ in everyone }, "lists", CGSize(width: 760, height: 620)),
            ("off", try linkedInStreams(connectionsOn: false, savedCount: nil, connectionsCount: nil),
             { _, _, _ in LinkedInConnectionsPage() }, nil, CGSize(width: 760, height: 520)),
            ("waiting", try linkedInStreams(connectionsOn: true, savedCount: nil, connectionsCount: nil),
             { _, _, _ in LinkedInConnectionsPage() }, nil, CGSize(width: 760, height: 520)),
        ]
        for dark in [true, false] {
            CicadaTheme.mode = dark ? .dark : .light
            for job in jobs where dark || job.name == "connections" {
                let (store, row, resolved) = try await linkedInRow(job.response, items: 2)
                let view = SourceCatalogDetail(row: row, onClose: {}, resolved: resolved, onCheckNow: {}, startTab: job.tab, clock: now)
                    .frame(width: job.size.width, height: job.size.height)
                    .modifier(PageEnv(store: store, cache: cache, streams: job.response, fetch: job.fetch))
                try write(view, size: job.size, scheme: dark ? .dark : .light,
                          to: base.appendingPathComponent("linkedin-\(job.name)-\(dark ? "dark" : "light").png"))
            }
        }
    }

    // MARK: - A person's links

    private func personSources() throws -> PageBlocks.Sources {
        let json = """
        {"total": 8, "tracked": 8, "items": [
          {"ref": "https://www.linkedin.com/in/alex-example", "kind": "url", "label": "Alex Example", "linkKind": "linkedin", "state": "ok", "site": "LinkedIn", "checkedAt": "2026-11-22", "addedBy": "cicada"},
          {"ref": "https://x.com/alex_example", "kind": "url", "label": "x", "linkKind": "x", "state": "ok", "site": "x.com", "checkedAt": "2026-11-23"},
          {"ref": "https://www.instagram.com/alex.example/", "kind": "url", "linkKind": "instagram", "state": "new", "site": "instagram.com"},
          {"ref": "https://github.com/alex-example", "kind": "url", "linkKind": "github", "state": "ok", "site": "github.com", "checkedAt": "2026-11-21"},
          {"ref": "https://www.youtube.com/@alexexample", "kind": "url", "linkKind": "website", "state": "new", "site": "youtube.com"},
          {"ref": "https://t.me/alex_example", "kind": "url", "linkKind": "website", "state": "new", "site": "t.me"},
          {"ref": "https://wa.me/15550100", "kind": "url", "linkKind": "website", "state": "new", "site": "wa.me"},
          {"ref": "https://alex.example.org/about", "kind": "url", "label": "Alex's site", "linkKind": "website", "state": "ok", "site": "alex.example.org", "checkedAt": "2026-11-20"}]}
        """
        return try JSONDecoder().decode(PageBlocks.Sources.self, from: Data(json.utf8))
    }

    func testRenderAPersonsLinks() async throws {
        let base = try renderDir()
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        let sources = try personSources()
        let sync = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: sync)
        for dark in [true, false] {
            CicadaTheme.mode = dark ? .dark : .light
            let box = WhereToCheckBox(entityId: "person-alex", isPerson: true, sources: sources, adding: .constant(false),
                                      today: ISODay(year: 2026, month: 11, day: 24))
                .padding(CicadaTheme.scaled(24))
                .environment(store)
            try write(box, size: CGSize(width: 640, height: 420), scheme: dark ? .dark : .light,
                      to: base.appendingPathComponent("person-where-to-check-\(dark ? "dark" : "light").png"))
        }
    }

    // MARK: - Apple Notes and Notion

    private final class TreeAPI: ChannelItemsAPI, @unchecked Sendable {
        let pages: [String: ChannelItemsPage]
        let trees: [String: ChannelCollections]
        init(pages: [String: ChannelItemsPage], trees: [String: ChannelCollections]) { self.pages = pages; self.trees = trees }
        func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
            -> Conditional<ChannelItemsPage> {
            guard let page = pages[channel] else { throw APIError.httpError(404, "") }
            return Conditional(value: page, etag: nil, notModified: false)
        }
        func fetchChannelCollections(channel: String, etag: String?) async throws -> Conditional<ChannelCollections> {
            guard let tree = trees[channel] else { throw APIError.httpError(404, "") }
            return Conditional(value: tree, etag: nil, notModified: false)
        }
    }

    private func notesTree(pinsRead: Bool?) throws -> ChannelCollections {
        let pins = pinsRead.map { "\"pinsRead\": \($0)," } ?? ""
        let json = """
        {"channel": "notes", \(pins) "locked": 2, "accounts": [
          {"name": "iCloud", "provider": "icloud", "count": 41, "collections": [
            {"id": "nf-notes", "name": "Notes", "count": 5, "total": 5, "path": ["Notes"], "parent": null, "children": [], "depth": 0},
            {"id": "nf-work", "name": "Work", "count": 4, "total": 19, "path": ["Work"], "parent": null, "children": ["nf-projects", "nf-meetings"], "depth": 0},
            {"id": "nf-projects", "name": "Projects", "count": 5, "total": 9, "path": ["Work", "Projects"], "parent": "nf-work", "children": ["nf-archive"], "depth": 1},
            {"id": "nf-archive", "name": "Archive", "count": 4, "total": 4, "path": ["Work", "Projects", "Archive"], "parent": "nf-projects", "children": [], "depth": 2},
            {"id": "nf-meetings", "name": "Meetings", "count": 6, "total": 6, "path": ["Work", "Meetings"], "parent": "nf-work", "children": [], "depth": 1},
            {"id": "nf-ideas", "name": "Ideas", "count": 11, "total": 11, "path": ["Ideas"], "parent": null, "children": [], "depth": 0},
            {"id": "nf-recipes", "name": "Recipes", "count": 6, "total": 6, "path": ["Recipes"], "parent": null, "children": [], "depth": 0}]},
          {"name": "On My Mac", "provider": "local", "count": 3, "collections": [
            {"id": "nf-scratch", "name": "Scratch", "count": 3, "total": 3, "path": ["Scratch"], "parent": null, "children": [], "depth": 0}]}]}
        """
        return try JSONDecoder().decode(ChannelCollections.self, from: Data(json.utf8))
    }

    private func note(_ id: String, _ title: String, snippet: String?, hoursAgo: Double, pinned: Bool = false) -> ChannelItem {
        var item = ChannelItem(kind: .episode, id: id, title: title, day: day(Int(hoursAgo / 24)))
        item.snippet = snippet
        item.modifiedAt = iso(hoursAgo * 3_600)
        item.pinned = pinned ? true : nil
        item.place = "notes"
        return item
    }

    private var noteItems: [ChannelItem] {
        [note("n1", "Alpha plan", snippet: "Three milestones, the first by the end of the month.", hoursAgo: 40, pinned: true),
         note("n2", "Reading list", snippet: "Papers to get through before the review.", hoursAgo: 900, pinned: true),
         note("n3", "Beta checklist", snippet: "Run the migration on a copy first, then the real one.", hoursAgo: 2),
         note("n4", "Gamma sketch", snippet: nil, hoursAgo: 5),
         note("n5", "Meeting notes, Thursday", snippet: "Decisions: ship the small version, revisit the rest in two weeks.", hoursAgo: 26),
         note("n6", "Delta", snippet: "Open questions about the export format.", hoursAgo: 80),
         note("n7", "Groceries", snippet: "Oats, lemons, rice, the good olive oil.", hoursAgo: 200),
         note("n8", "Trip ideas", snippet: "A week somewhere quiet with a lake.", hoursAgo: 520),
         note("n9", "Epsilon draft", snippet: "First pass at the intro, still too long.", hoursAgo: 1_300),
         note("n10", "Old budget", snippet: "Last year's numbers for reference.", hoursAgo: 9_800)]
    }

    private func notesScene(pinsRead: Bool?) async throws -> (Store, ChannelItemsCache) {
        let tree = try notesTree(pinsRead: pinsRead)
        let items = noteItems
        let folderItems = Array(items.prefix(6))
        let cache = ChannelItemsCache(api: TreeAPI(pages: [
            "notes": ChannelItemsPage(channel: "notes", total: 41, items: items, latest: day(0)),
            SourceListKey.make("notes", collection: "nf-work"): ChannelItemsPage(channel: "notes", total: 19, items: folderItems, latest: day(0)),
        ], trees: ["notes": tree]))
        await cache.refreshCollections("notes")
        for key in ["notes", SourceListKey.make("notes", collection: "nf-work")] { await cache.refresh(key) }
        let sync = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: sync)
        return (store, cache)
    }

    func testRenderAppleNotes() async throws {
        let base = try renderDir()
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        let work = try XCTUnwrap(try notesTree(pinsRead: true).accounts[0].collections.first { $0.id == "nf-work" })
        let icloud = try notesTree(pinsRead: true).accounts[0]
        let jobs: [(String, Bool?, [SourceBrowserLevel], CGSize)] = [
            ("root", false, [], CGSize(width: 760, height: 1_500)),
            ("root-pins", true, [], CGSize(width: 760, height: 1_500)),
            ("folder", true, [.collection(work, account: icloud)], CGSize(width: 760, height: 1_000)),
        ]
        for dark in [true, false] {
            CicadaTheme.mode = dark ? .dark : .light
            for job in jobs where dark || job.0 == "root" {
                let (store, cache) = try await notesScene(pinsRead: job.1)
                let view = SourceBrowser(channel: "notes", sourceTitle: "Apple Notes", initialPath: job.2)
                    .padding(CicadaTheme.scaled(24))
                    .environment(store)
                    .environment(cache)
                    .environment(AppRouter())
                    .environment(ProvenanceRouter())
                    .environment(SourcePageBack())
                try write(view, size: job.3, scheme: dark ? .dark : .light,
                          to: base.appendingPathComponent("notes-\(job.0)-\(dark ? "dark" : "light").png"))
            }
        }
    }

    // MARK: - YouTube: the watched days under their own tab

    func testRenderYouTubeHistoryTab() async throws {
        let base = try renderDir()
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        let response = try streams { response in
            guard let at = response.sources.firstIndex(where: { $0.id == "youtube" }) else { return }
            response.sources[at].streams = [
                SourceStream(id: "youtube.watch_later", label: "Watch later", kind: .later, state: .on, health: .read,
                             lastReadAt: now.addingTimeInterval(-3_600 * 9), count: 41,
                             switchRef: StreamSwitch(setting: "youtubeLists", key: "watch_later")),
                SourceStream(id: "youtube.history", label: "History", kind: .history, state: .on, health: .read,
                             lastReadAt: now.addingTimeInterval(-3_600 * 30), count: 30,
                             switchRef: StreamSwitch(setting: "youtubeLists", key: "history"))]
        }
        let saved = SourceOverview(id: "youtube", label: "YouTube", kind: .social, items: 41, connected: true, channelId: "youtube",
                                   intent: .saved)
        let days = SourceOverview(id: "youtube-history", label: "YouTube history", kind: .social, episodes: 30,
                                  origins: ["youtube-history"], intent: .captured)
        var video = ChannelItem(kind: .media, id: "v1", title: "A walk through a small compiler", day: day(3), host: "youtube.com", site: "youtube")
        video.lists = ["Watch later"]
        video.video = true
        func dayRow(_ id: String, _ ago: Int, _ n: Int) -> ChannelItem {
            var item = ChannelItem(kind: .episode, id: id, title: "Watched", day: day(ago))
            item.videos = n
            return item
        }
        let cache = ChannelItemsCache(api: PagesAPI([
            "youtube": ChannelItemsPage(channel: "youtube", total: 41, items: [video], latest: day(3)),
            SourceListKey.make("youtube", stream: "youtube.watch_later"): ChannelItemsPage(channel: "youtube", total: 41, items: [video], latest: day(3)),
            "youtube-history": ChannelItemsPage(channel: "youtube-history", total: 30,
                                                items: [dayRow("d1", 1, 12), dayRow("d2", 2, 4), dayRow("d3", 3, 9), dayRow("d4", 6, 2)], latest: day(1)),
        ]))
        for key in ["youtube", SourceListKey.make("youtube", stream: "youtube.watch_later"), "youtube-history"] { await cache.refresh(key) }
        let channels = [SourceChannel(id: "youtube", label: "YouTube", connected: true, count: 41, lastSync: iso(3_600 * 5), lastError: nil)]
        let overview = [saved, days]
        let sync = FakeSyncAPI()
        sync.replies[.channels] = .value(channels)
        sync.replies[.sourcesOverview] = .value(overview)
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: sync)
        await store.refresh([.channels, .sourcesOverview])
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, hexPresent: false, overview: overview, channels: channels)
        let rows = SourceCatalog.rows(entries: entries, channels: channels, overview: overview, readableSites: [],
                                      localReaders: [:], savedListsOn: ["youtube"], localAgent: true, savedListsRead: ["youtube"])
        let resolved = SourceStreamOverlay.resolve(response, app: StreamAppState(readers: [:]), entries: entries, now: now)
        let row = try XCTUnwrap(rows.first { $0.id == "youtube" })
        for (name, tab) in [("cards", nil), ("history", "youtube.history")] as [(String, String?)] {
            CicadaTheme.mode = .dark
            let view = SourceCatalogDetail(row: row, onClose: {}, resolved: resolved, onCheckNow: {}, startTab: tab, clock: now)
                .frame(width: 760, height: 760)
                .modifier(PageEnv(store: store, cache: cache, streams: response, fetch: { _, _, _ in LinkedInConnectionsPage() }))
            try write(view, size: CGSize(width: 760, height: 760), scheme: .dark,
                      to: base.appendingPathComponent("youtube-\(name)-dark.png"))
        }
    }

    // MARK: - Notion

    func testRenderNotion() async throws {
        let base = try renderDir()
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        let json = """
        {"channel": "notion-api", "accounts": [{"name": null, "provider": null, "count": 23, "collections": [
          {"id": "nn-tasks", "name": "Tasks", "count": 8, "total": 8, "path": ["Tasks"], "parent": null, "children": [], "depth": 0},
          {"id": "nn-wiki", "name": "Team wiki", "count": 3, "total": 12, "path": ["Team wiki"], "parent": null, "children": ["nn-onboarding"], "depth": 0},
          {"id": "nn-onboarding", "name": "Onboarding", "count": 9, "total": 9, "path": ["Team wiki", "Onboarding"], "parent": "nn-wiki", "children": [], "depth": 1},
          {"id": "nn-unfiled", "name": "Unfiled", "count": 3, "total": 3, "path": ["Unfiled"], "parent": null, "children": [], "depth": 0}]}]}
        """
        let tree = try JSONDecoder().decode(ChannelCollections.self, from: Data(json.utf8))
        func page(_ id: String, _ title: String, _ snippet: String?, hours: Double) -> ChannelItem {
            var item = ChannelItem(kind: .episode, id: id, title: title, day: day(Int(hours / 24)))
            item.snippet = snippet
            item.modifiedAt = iso(hours * 3_600)
            return item
        }
        let items = [page("p1", "Q4 planning", "Goals, owners and the two open risks.", hours: 3),
                     page("p2", "Sprint 41 retro", "What went well: the smaller releases.", hours: 30),
                     page("p3", "Onboarding checklist", "Accounts, laptop, first week.", hours: 120),
                     page("p4", "Vendor notes", nil, hours: 700)]
        let cache = ChannelItemsCache(api: TreeAPI(pages: ["notion-api": ChannelItemsPage(channel: "notion-api", total: 23, items: items, latest: day(0))],
                                                  trees: ["notion-api": tree]))
        await cache.refreshCollections("notion-api")
        await cache.refresh("notion-api")
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        CicadaTheme.mode = .dark
        let view = SourceBrowser(channel: "notion-api", sourceTitle: "Notion")
            .padding(CicadaTheme.scaled(24))
            .environment(store).environment(cache).environment(AppRouter()).environment(ProvenanceRouter()).environment(SourcePageBack())
        try write(view, size: CGSize(width: 760, height: 900), scheme: .dark, to: base.appendingPathComponent("notion-dark.png"))
    }

    // MARK: - How deep Cicada went on a saved item (G245 B3)

    /// Four cards, one per depth: kept (says nothing), asked, read, watched. The depth is one quiet word or phrase at the
    /// end of the card's own meta line: no colour, no badge.
    func testRenderTheDepthOfASavedItem() throws {
        let base = try renderDir()
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        func item(_ id: String, _ title: String, _ words: String?, depth: String, posted: Int) -> ChannelItem {
            var item = ChannelItem(kind: .media, id: id, title: title, day: day(posted), host: "x.com", site: "x.com",
                                   why: words.map { ChannelItemWhy(labels: [], text: $0) })
            item.lists = ["Bookmarks"]
            item.depth = depth
            item.posted = day(posted + 1)
            item.author = "Alex Example"
            return item
        }
        let items = [item("d1", "A thread on keeping small tools small", nil, depth: "kept", posted: 1),
                     item("d2", "Notes from a talk on durable software", "Talked about it for the storage doc.", depth: "asked", posted: 2),
                     item("d3", "The case for plain files as the interface", "Reread when writing the storage doc.", depth: "read", posted: 4),
                     item("d4", "A walkthrough of building a static site", "Watched with the sync notes open.", depth: "watched", posted: 6)]
        let today = ISODay.today()
        for dark in [true, false] {
            CicadaTheme.mode = dark ? .dark : .light
            let column = VStack(alignment: .leading, spacing: CicadaTheme.cardGap) {
                ForEach(items, id: \.self) { card in
                    SourceItemCard(item: card, omittingList: "Bookmarks", today: today, route: nil, open: { _ in })
                }
            }
            .padding(CicadaTheme.scaled(24))
            try write(column, size: CGSize(width: 640, height: 400), scheme: dark ? .dark : .light,
                      to: base.appendingPathComponent("item-depth-\(dark ? "dark" : "light").png"))
        }
    }

    // MARK: - Writing a PNG

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
        for _ in 0..<8 { RunLoop.main.run(until: Date().addingTimeInterval(0.1)) }
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}
