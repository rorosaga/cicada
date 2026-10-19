import XCTest
@testable import CicadaApp

/// Fakes a day read for the cache's test; lists nothing.
final class FakeWatchedDayAPI: ChannelItemsAPI, @unchecked Sendable {
    var day: WatchedDay?
    var fail = false
    private(set) var etags: [String?] = []

    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        throw APIError.serverUnreachable
    }

    func fetchWatchedDay(episode: String, etag: String?) async throws -> Conditional<WatchedDay> {
        etags.append(etag)
        if fail { throw APIError.serverUnreachable }
        guard let day else { return Conditional(value: nil, etag: etag, notModified: true) }
        return Conditional(value: day, etag: "\"d1\"", notModified: false)
    }
}

/// Sources v4 (owner 2026-10-19): "remove the graph and just put what the source is. Avoid repetition" — one header,
/// a "Consolidate now · N waiting" control only when something waits, faces on the root rows, Messages by chat, a
/// watched day that opens to its videos, and conversations whose find lives in the list header. Pure where it can be,
/// pinned at the source where it cannot.
@MainActor
final class SourcesV4Tests: XCTestCase {
    private let us = Locale(identifier: "en_US")
    private let utc = TimeZone(identifier: "UTC")!

    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    // MARK: The wire

    func testTheOverviewDecodesWaitingAndFacesAndAnOlderBackendReadsAsNone() throws {
        let json = #"""
        {"id":"imessage","kind":"messaging","waiting":2,"facesMore":4,
         "faces":[{"kind":"chat","id":"aaaaaaaaaaaaaaaa","label":"Alice Example","photo":"0123456789ab"},
                  {"kind":"site","id":"media-1","label":"example.com","site":"example.com"}]}
        """#
        let row = try JSONDecoder().decode(SourceOverview.self, from: Data(json.utf8))
        XCTAssertEqual(row.waiting, 2)
        XCTAssertEqual(row.facesMore, 4)
        XCTAssertEqual(row.faces.map(\.kind), [.chat, .site])
        XCTAssertEqual(row.faces[0].photo, "0123456789ab")
        XCTAssertEqual(row.faces[1].site, "example.com")
        let old = try JSONDecoder().decode(SourceOverview.self, from: Data(#"{"id":"rss","kind":"feed"}"#.utf8))
        XCTAssertEqual(old.waiting, 0)
        XCTAssertTrue(old.faces.isEmpty)
        // The Store hydrates from disk: the fields survive their own round trip.
        let back = try JSONDecoder().decode(SourceOverview.self, from: JSONEncoder().encode(row))
        XCTAssertEqual(back.faces, row.faces)
        XCTAssertEqual(back.waiting, 2)
    }

    func testAMessagesRowCarriesItsChatAndAWatchedDayItsVideoCount() throws {
        let json = #"""
        [{"kind":"episode","id":"ep_1","title":"Alice Example","day":"2026-10-19",
          "chat":{"id":"aaaaaaaaaaaaaaaa","label":"Alice Example","photo":null}},
         {"kind":"episode","id":"ep_2","title":"Watched on YouTube","day":"2026-10-19","videos":12}]
        """#
        let items = try JSONDecoder().decode([ChannelItem].self, from: Data(json.utf8))
        XCTAssertEqual(items[0].chat?.label, "Alice Example")
        XCTAssertNil(items[0].videos)
        XCTAssertEqual(items[1].videos, 12)
        XCTAssertNil(items[1].chat)
    }

    func testAWatchedDayDecodesItsVideos() throws {
        let json = #"""
        {"episode":"ep_2","day":"2026-10-19","platform":"youtube","videos":[
          {"url":"https://www.youtube.com/watch?v=abcDEF12345","title":"One","channel":"A channel",
           "times":["2026-10-19T08:04:00+00:00"],"videoId":"abcDEF12345","mediaEntityId":null},
          {"url":"https://www.youtube.com/watch?v=zyx-_987654","title":"Two","videoId":"zyx-_987654",
           "mediaEntityId":"media-two"}]}
        """#
        let day = try JSONDecoder().decode(WatchedDay.self, from: Data(json.utf8))
        XCTAssertEqual(day.videos.count, 2)
        XCTAssertEqual(WatchedVideoRoute.of(day.videos[0]), .browser("https://www.youtube.com/watch?v=abcDEF12345"))
        XCTAssertEqual(WatchedVideoRoute.of(day.videos[1]), .saved("media-two"), "a video also saved opens in Saved")
    }

    // MARK: The header

    func testTheStateLineSaysEachFactOnce() {
        let now = Date(timeIntervalSince1970: 1_760_000_000)
        let watching = SourceLiveness(state: .watching, detail: nil)
        let synced = SourceDetailText.state(liveness: watching, status: .synced(now.addingTimeInterval(-5 * 3600)),
                                            fullError: nil, now: now, locale: us)
        XCTAssertEqual(synced.text, "Watching · Last synced 5 hours ago")
        XCTAssertFalse(synced.isAlarm)
        let syncing = SourceDetailText.state(liveness: SourceLiveness(state: .syncing, detail: nil),
                                             status: .syncing(detail: nil, fraction: nil, cancellable: true),
                                             fullError: nil, now: now, locale: us)
        XCTAssertEqual(syncing.text, Copy.syncingNow, "never \"Syncing… · Syncing now\"")
        let hook = SourceDetailText.state(liveness: SourceLiveness(state: .captured, detail: nil), status: .idle,
                                          fullError: nil, now: now, locale: us)
        XCTAssertEqual(hook.text, "Captured by hook")
        let long = "Can't read the file. Grant Full Disk Access in System Settings, then sync again."
        let failed = SourceDetailText.state(liveness: SourceLiveness(state: .failed, detail: "Can't read the file"),
                                            status: .idle, fullError: long, now: now, locale: us)
        XCTAssertTrue(failed.isAlarm)
        XCTAssertTrue(failed.text.contains(long), "the header has the room for the whole error")
        let problem = SourceDetailText.state(liveness: watching, status: .problem("Chrome isn't installed"),
                                             fullError: nil, now: now, locale: us)
        XCTAssertEqual(problem.text, "Chrome isn't installed")
        XCTAssertTrue(problem.isAlarm)
    }

    func testOneHeaderReplacesTheCardTheStripAndTheSyncRow() throws {
        let detail = try source("Views/Sources/SourceDetailView.swift")
        for gone in ["SourceHeaderCard", "SourceQueueStrip", "sparkline", "Consolidated so far"] {
            XCTAssertFalse(detail.contains(gone), "\(gone) repeated the source (owner 2026-10-19)")
        }
        let channel = try source("Views/Sources/ChannelSourceView.swift")
        XCTAssertFalse(channel.contains("stateCard"), "the sync row is the header's state line now")
        let head = try source("Views/Sources/SourceDetailHead.swift")
        XCTAssertTrue(head.contains("SourceDetailText.consolidate(waiting: source.waiting"),
                      "the waiting count is the backend's, per source")
        XCTAssertFalse(head.contains("PrimaryActionButton"), "Consolidate here is neutral; Sleep owns the primary one")
        XCTAssertTrue(head.contains("SourceBlurb.text(for: source)"), "what the source is, in one line")
    }

    func testNoEmptyFolderHeading() {
        XCTAssertFalse(SourceItemsGrouping.showsFolders([]), "the owner's Messages page showed an empty \"By folder\"")
        XCTAssertFalse(SourceItemsGrouping.showsFolders([(folder: SourceItemsGrouping.noFolder, count: 3)]))
        XCTAssertTrue(SourceItemsGrouping.showsFolders([(folder: "Research", count: 3)]))
        XCTAssertTrue(SourceItemsGrouping.showsFolders([(folder: "A", count: 1), (folder: "B", count: 1)]))
    }

    func testEverySourceTheOwnerOpenedSaysWhatItIs() {
        for (id, kind) in [("imessage", SourceKind.messaging), ("harness:unknown", .harness),
                           ("calendar-local", .feed)] {
            let row = SourceOverview(id: id, label: id, kind: kind)
            XCTAssertFalse(SourceBlurb.text(for: row).contains(id), "\(id) has its own sentence, not the fallback")
        }
    }

    // MARK: Faces

    func testThreeFacesThenTheRestAsOneCount() {
        let faces = (1...5).map { SourceFace(kind: .chat, id: String(repeating: "\($0)", count: 16), label: "P\($0)") }
        let plan = SourceFaceStack.plan(faces, more: 7)
        XCTAssertEqual(plan.shown.map(\.label), ["P1", "P2", "P3"])
        XCTAssertEqual(plan.more, 9, "the server's \"more\" plus any face past three")
        XCTAssertEqual(SourceFaceStack.plan(Array(faces.prefix(2)), more: 0).more, 0)
        XCTAssertEqual(Copy.facesMore(4, locale: us), "+4")
        XCTAssertEqual(Copy.facesSpoken(["A", "B"], more: 3), "A, B and 3 more")
    }

    func testPicturesAreAskedOfCicadasOwnApiByIdsThatCannotReshapeThePath() {
        XCTAssertEqual(SourcePictures.chatPhotoPath(("aaaaaaaaaaaaaaaa", "0123456789ab")),
                       "/sources/messages/chats/aaaaaaaaaaaaaaaa/photo?v=0123456789ab")
        XCTAssertNil(SourcePictures.chatPhotoPath(("aaaaaaaaaaaaaaaa", nil)), "no photo stored, no request")
        XCTAssertNil(SourcePictures.chatPhotoPath(("../etc", "0123")))
        XCTAssertEqual(SourcePictures.stillPath(videoId: "abcDEF12345"),
                       "/sources/watch-history/videos/abcDEF12345/thumbnail")
        XCTAssertNil(SourcePictures.stillPath(videoId: "a/b?c=1"))
        XCTAssertNil(SourcePictures.stillPath(videoId: nil))
    }

    func testTheRootRowDrawsFacesOnlyWhereTheSourceHasThem() throws {
        let columns = try source("Views/Sources/SourcesColumns.swift")
        XCTAssertTrue(columns.contains("if style == .wide && !source.faces.isEmpty {"))
    }

    // MARK: Watched days

    func testAWatchedDaySaysItsDayOnceAndItsVideosTimesOnThisMacsClock() throws {
        let today = try XCTUnwrap(ISODay("2026-10-19"))
        let item = ChannelItem(kind: .episode, id: "ep", title: "Watched on YouTube", day: "2026-10-19", videos: 12)
        XCTAssertEqual(WatchedDayText.day(item, today: today, locale: us).text, "Today")
        XCTAssertEqual(Copy.watchedVideos(12, locale: us), "12 videos")
        XCTAssertEqual(Copy.watchedVideos(1, locale: us), "1 video")
        let video = WatchedVideo(url: "https://www.youtube.com/watch?v=abcDEF12345", title: "One", channel: "A channel",
                                 times: ["2026-10-19T08:04:00+00:00", "2026-10-19T21:10:00Z"])
        // Foundation spaces the clock with a narrow no-break space; the words are what is pinned.
        XCTAssertEqual(WatchedDayText.line(video, locale: us, timeZone: utc)?.replacingOccurrences(of: "\u{202F}", with: " "),
                       "A channel · 8:04 AM, 9:10 PM")
        XCTAssertNil(WatchedDayText.line(WatchedVideo(url: "u", title: "t"), locale: us, timeZone: utc))
    }

    func testADayIsReadOnlyWhenItOpensAndKeptWhenTheNextReadFails() async {
        let api = FakeWatchedDayAPI()
        api.day = WatchedDay(episode: "ep", day: "2026-10-19", videos: [WatchedVideo(url: "u", title: "One")])
        let cache = ChannelItemsCache(api: api)
        XCTAssertNil(cache.day("ep"))
        await cache.refreshDay("ep")
        XCTAssertEqual(cache.day("ep")?.videos.count, 1)
        api.fail = true
        await cache.refreshDay("ep")
        XCTAssertEqual(cache.day("ep")?.videos.count, 1, "never blank (DR-43)")
        XCTAssertFalse(cache.dayFailed("ep"), "a failure with a day held is not shown as one")
        XCTAssertEqual(api.etags, [nil, "\"d1\""], "the second read revalidates")
        cache.reset()
        XCTAssertNil(cache.day("ep"), "a bank switch forgets every day")
    }

    // MARK: Conversations

    func testConversationsSayNeitherTheHarnessNorOneEpisodeAndFindLivesInTheListHeader() throws {
        let list = try source("Views/Sources/HarnessConversationsView.swift")
        XCTAssertFalse(list.contains("prompt: \"Filter by title\""), "no always-open field under the header")
        XCTAssertTrue(list.contains("PageFindButton(isOpen: $findOpen)"), "the list header's magnifier (DR-46)")
        XCTAssertTrue(list.contains("inSourceList: true"))
        let row = try source("Views/Sources/ConversationRow.swift")
        XCTAssertTrue(row.contains("if !inSourceList { badge(harnessLabel) }"))
        XCTAssertTrue(row.contains("if !inSourceList || conversation.episodeCount > 1 {"))
    }
}
