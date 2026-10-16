import SQLite3
import XCTest
@testable import CicadaApp

/// G71 (2026-10-16) — a synthetic Chrome `History` database (the schema `api/tests/fixtures/chrome_history_tables.sql`
/// the backend's test builds too), placeholder titles only. Never the person's own Chrome profile.
final class SyntheticChromeHistory {
    let dir: URL
    var url: URL { dir.appendingPathComponent("History") }
    private var db: OpaquePointer?
    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    static var schemaURL: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("api/tests/fixtures/chrome_history_tables.sql")
    }

    init() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("SyntheticChromeHistory-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        XCTAssertEqual(sqlite3_open(url.path, &db), SQLITE_OK)
        let schema = try String(contentsOf: Self.schemaURL, encoding: .utf8)
        XCTAssertEqual(sqlite3_exec(db, schema, nil, nil, nil), SQLITE_OK)
    }

    func close() {
        sqlite3_close(db)
        db = nil
    }

    func remove() { close(); try? FileManager.default.removeItem(at: dir) }

    /// Chrome's clock: microseconds since 1601-01-01 UTC.
    static func webkit(_ iso: String) -> Int64 {
        let f = ISO8601DateFormatter()
        let date = f.date(from: iso)!
        return Int64((date.timeIntervalSince1970 + 11_644_473_600) * 1_000_000)
    }

    @discardableResult
    func visit(_ url: String, title: String, at iso: String) -> Int64 {
        exec("INSERT INTO urls (url, title) VALUES (?, ?)", [url, title])
        let urlId = sqlite3_last_insert_rowid(db)
        exec("INSERT INTO visits (url, visit_time) VALUES (?, ?)", [urlId, Self.webkit(iso)])
        return sqlite3_last_insert_rowid(db)
    }

    func clearAll() { exec("DELETE FROM visits"); exec("DELETE FROM urls") }

    private func exec(_ sql: String, _ values: [Any] = []) {
        var stmt: OpaquePointer?
        XCTAssertEqual(sqlite3_prepare_v2(db, sql, -1, &stmt, nil), SQLITE_OK)
        defer { sqlite3_finalize(stmt) }
        for (i, value) in values.enumerated() {
            let at = Int32(i + 1)
            switch value {
            case let v as Int64: sqlite3_bind_int64(stmt, at, v)
            case let v as Int: sqlite3_bind_int64(stmt, at, Int64(v))
            case let v as String: sqlite3_bind_text(stmt, at, v, -1, Self.transient)
            default: sqlite3_bind_null(stmt, at)
            }
        }
        XCTAssertEqual(sqlite3_step(stmt), SQLITE_DONE)
    }
}

final class FakeWatchHistoryAPI: WatchHistorySyncAPI, @unchecked Sendable {
    var posted: [WatchHistoryPayload] = []
    var fail = false

    func syncWatchHistory(_ payload: WatchHistoryPayload) async throws -> WatchHistorySyncResult {
        if fail { throw APIError.serverUnreachable }
        posted.append(payload)
        return WatchHistorySyncResult(received: payload.visits.count, kept: payload.visits.count, added: payload.visits.count,
                                      videos: Set(payload.visits.map(\.url)).count)
    }
}

final class ChromeWatchHistoryReaderTests: XCTestCase {
    private var history: SyntheticChromeHistory!
    private var scratch: URL!

    override func setUp() async throws {
        history = try SyntheticChromeHistory()
        scratch = FileManager.default.temporaryDirectory.appendingPathComponent("wh-scratch-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
    }

    override func tearDown() async throws {
        history.remove()
        try? FileManager.default.removeItem(at: scratch)
    }

    private func reader(batch: Int = 2000) -> ChromeWatchHistoryReader {
        ChromeWatchHistoryReader(historyFile: history.url, batchLimit: batch, scratchRoot: scratch)
    }

    func testOnlyYouTubeVideoPagesLeaveTheReaderWithTheirTitleAndTime() throws {
        history.visit("https://www.youtube.com/watch?v=aaaaaaaaaaa&t=30", title: "Bridge design - YouTube",
                      at: "2026-10-14T09:14:03Z")
        history.visit("https://example.com/a-private-page", title: "A private page", at: "2026-10-14T09:15:00Z")
        history.visit("https://www.youtube.com/results?search_query=private", title: "private - YouTube",
                      at: "2026-10-14T09:16:00Z")
        history.visit("https://youtu.be/bbbbbbbbbbb", title: "Knots - YouTube", at: "2026-10-14T09:17:00Z")
        history.visit("https://www.youtube.com/shorts/ccccccccccc", title: "A short - YouTube", at: "2026-10-14T09:18:00Z")
        history.visit("https://www.youtube.com.evil.example/watch?v=aaaaaaaaaaa", title: "Not YouTube",
                      at: "2026-10-14T09:19:00Z")
        history.close()
        let pass = try reader().read(after: 0)
        XCTAssertEqual(pass.visits.map(\.url), ["https://www.youtube.com/watch?v=aaaaaaaaaaa&t=30",
                                                "https://youtu.be/bbbbbbbbbbb",
                                                "https://www.youtube.com/shorts/ccccccccccc"])
        XCTAssertEqual(pass.visits.first?.title, "Bridge design - YouTube")
        XCTAssertEqual(pass.visits.first?.visitedAt, "2026-10-14T09:14:03Z")
        XCTAssertEqual(pass.lastVisitId, 5, "the cursor passes every row the query looked at")
        XCTAssertFalse(pass.hasMore)
    }

    func testTheLiveFileIsCopiedNeverChangedAndTheCopyIsGone() throws {
        history.visit("https://www.youtube.com/watch?v=aaaaaaaaaaa", title: "Bridge design", at: "2026-10-14T09:14:03Z")
        history.close()
        let before = try Data(contentsOf: history.url)
        let attrs = try FileManager.default.attributesOfItem(atPath: history.url.path)
        _ = try reader().read(after: 0)
        XCTAssertEqual(try Data(contentsOf: history.url), before)
        XCTAssertEqual(try FileManager.default.attributesOfItem(atPath: history.url.path)[.modificationDate] as? Date,
                       attrs[.modificationDate] as? Date)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: scratch.path), [], "the private copy is deleted")
    }

    func testAnUnreadableCopyIsDeletedToo() throws {
        history.close()
        try Data("not a database".utf8).write(to: history.url)
        XCTAssertThrowsError(try reader().read(after: 0)) { error in
            XCTAssertEqual(error as? WatchHistoryReadError, .unreadable)
        }
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: scratch.path), [],
                       "the private copy is deleted on the error path as well")
    }

    func testPassesResumePastTheCursorAndAClearedHistoryStartsAgain() throws {
        for i in 1...3 {
            history.visit("https://www.youtube.com/watch?v=video000000\(i)", title: "Video \(i)",
                          at: "2026-10-14T0\(i):00:00Z")
        }
        let first = try reader(batch: 2).read(after: 0)
        XCTAssertEqual(first.visits.count, 2)
        XCTAssertTrue(first.hasMore)
        let second = try reader(batch: 2).read(after: first.lastVisitId)
        XCTAssertEqual(second.visits.map(\.title), ["Video 3"])
        XCTAssertFalse(second.hasMore)
        history.clearAll()
        history.visit("https://www.youtube.com/watch?v=video0000009", title: "After clearing", at: "2026-10-15T01:00:00Z")
        history.close()
        let afterClear = try reader().read(after: 999)
        XCTAssertEqual(afterClear.visits.map(\.title), ["After clearing"], "a cursor past the file's ids starts again")
    }

    func testAMissingHistoryIsNamedAsMissing() {
        let r = ChromeWatchHistoryReader(historyFile: scratch.appendingPathComponent("nope/History"), scratchRoot: scratch)
        XCTAssertThrowsError(try r.read(after: 0)) { error in
            guard case BrowserFileError.missing(.chromeHistory, _) = error else { return XCTFail("\(error)") }
        }
    }

    func testWhatIsAVideoPage() {
        for yes in ["https://www.youtube.com/watch?v=abc", "https://m.youtube.com/watch?v=abc&list=WL",
                    "https://music.youtube.com/watch?v=abc", "https://youtu.be/abc", "https://youtube.com/shorts/abc"] {
            XCTAssertTrue(ChromeWatchHistoryReader.isWatchURL(yes), yes)
        }
        for no in ["https://www.youtube.com/", "https://www.youtube.com/watch", "https://www.youtube.com/@alice-example",
                   "http://www.youtube.com/watch?v=abc", "https://example.com/watch?v=abc", "https://youtu.be/",
                   "https://notyoutube.com/watch?v=abc"] {
            XCTAssertFalse(ChromeWatchHistoryReader.isWatchURL(no), no)
        }
    }
}

@MainActor
final class WatchHistoryWatcherTests: XCTestCase {
    private var history: SyntheticChromeHistory!
    private var defaults: UserDefaults!

    override func setUp() async throws {
        history = try SyntheticChromeHistory()
        history.visit("https://www.youtube.com/watch?v=aaaaaaaaaaa", title: "Bridge design - YouTube",
                      at: "2026-10-14T09:14:03Z")
        history.visit("https://example.com/a-private-page", title: "A private page", at: "2026-10-14T09:15:00Z")
        defaults = UserDefaults(suiteName: "WatchHistory-\(UUID().uuidString)")!
    }

    override func tearDown() async throws { history.remove() }

    private func watcher(_ api: FakeWatchHistoryAPI) -> WatchHistoryWatcher {
        WatchHistoryWatcher(api: api, reader: ChromeWatchHistoryReader(historyFile: history.url),
                            defaults: defaults, checkInterval: .seconds(3600), bank: { "alpha" })
    }

    func testOffByDefaultReadsNothingUntilTurnedOn() async {
        let api = FakeWatchHistoryAPI()
        let w = watcher(api)
        XCTAssertFalse(w.enabled)
        w.start()
        XCTAssertEqual(w.status, .off)
        await w.run(force: true)
        XCTAssertTrue(api.posted.isEmpty, "nothing is read before the switch")
        do {
            _ = try await w.syncNow()
            XCTFail("Sync now must refuse while off")
        } catch {}
    }

    func testTurningOnPostsOnlyYouTubeVisitsAndAdvancesTheCursorPerBank() async {
        let api = FakeWatchHistoryAPI()
        let w = watcher(api)
        await w.enable()
        XCTAssertTrue(defaults.bool(forKey: WatchHistoryWatcher.enabledKey))
        XCTAssertEqual(api.posted.count, 1)
        XCTAssertEqual(api.posted[0].browser, "chrome")
        XCTAssertEqual(api.posted[0].visits.map(\.url), ["https://www.youtube.com/watch?v=aaaaaaaaaaa"])
        XCTAssertEqual(w.cursor(bank: "alpha"), 1, "the last YouTube visit read; the other site was never read")
        XCTAssertEqual(w.status, .watching)
        XCTAssertEqual(w.videos, 1)
        await w.run(force: false)   // the file did not move: a stat, nothing read or posted
        XCTAssertEqual(api.posted.count, 1)
        w.disable()
        XCTAssertFalse(defaults.bool(forKey: WatchHistoryWatcher.enabledKey))
        XCTAssertEqual(w.status, .off)
    }

    func testAFailedPostKeepsTheCursorSoTheVisitsAreReadAgain() async {
        let api = FakeWatchHistoryAPI()
        api.fail = true
        let w = watcher(api)
        await w.enable()
        XCTAssertEqual(w.cursor(bank: "alpha"), 0)
        guard case .failed = w.status else { return XCTFail("\(w.status)") }
        api.fail = false
        _ = try? await w.syncNow()
        XCTAssertEqual(api.posted.count, 1)
        XCTAssertEqual(w.cursor(bank: "alpha"), 1, "the last YouTube visit read; the other site was never read")
    }

    func testTheRowSaysWhatItReadsBeforeItIsOn() {
        let off = WatchHistoryRows.model(enabled: false, status: .off, videos: nil, channel: nil, run: nil)
        XCTAssertEqual(off.line, Copy.watchHistoryOffLine)
        XCTAssertTrue(off.line?.contains("Only YouTube video pages") ?? false)
        let on = WatchHistoryRows.model(enabled: true, status: .watching, videos: 12, channel: nil, run: nil)
        XCTAssertEqual(on.line, "12 videos watched, one entry per day")
        XCTAssertEqual(on.origin, "youtube-history")
    }
}

/// The agent door's settings (G71): the two YouTube lists, off by default, words for each state.
@MainActor
final class YouTubeListSettingsTests: XCTestCase {
    func testTheSettingsDecodeTheListsAndAnOlderBackendReadsAsOff() throws {
        let body = """
        {"agentEnabled": true, "allowedSites": {}, "ackCurrent": true, "exploreSignedIn": true, "neverExplore": {},
         "youtubeLists": {"watchLater": true, "history": false},
         "youtube": {"pausedUntil": null, "lists": {"watch_later": {"lastReadAt": "2026-10-15T08:00:00+00:00",
                     "lastOutcome": "read", "videos": 4}, "history": {"lastReadAt": null}}}}
        """
        let s = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(body.utf8))
        XCTAssertTrue(s.youtubeLists.isOn(.watchLater))
        XCTAssertFalse(s.youtubeLists.isOn(.history))
        XCTAssertEqual(s.youtube?.lists["watch_later"]?.videos, 4)
        let old = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(#"{"agentEnabled": true}"#.utf8))
        XCTAssertEqual(old.youtubeLists, YouTubeListSwitches())
    }

    func testEachListSaysWhatItIsDoing() {
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(YouTubeListWords.detail(.watchLater, on: false, status: nil), Copy.Reading.youtubeWatchLaterOff)
        XCTAssertEqual(YouTubeListWords.detail(.history, on: true, status: nil), Copy.Reading.youtubeWaiting)
        let read = YouTubeListsStatus(lists: ["history": .init(lastReadAt: "2026-10-15T08:00:00+00:00")])
        XCTAssertEqual(YouTubeListWords.detail(.history, on: true, status: read, locale: en),
                       Copy.Reading.youtubeLastRead("Oct 15"))
        let paused = YouTubeListsStatus(pausedUntil: "2026-10-22T08:00:00+00:00")
        XCTAssertTrue(YouTubeListWords.detail(.watchLater, on: true, status: paused, locale: en)
            .contains("wasn't signed in"))
    }

    func testTurningAListOnSendsOnePatchAndKeepsTheAnswer() async {
        var sent: [[String: Bool]] = []
        var deps = ReadingAgentModel.Deps(
            fetch: { ReadingSettingsResponse(agentEnabled: true, ackCurrent: true) },
            write: { _, _, _ in ReadingSettingsResponse() },
            prompt: { "" },
            fetchSites: { ReadingSitesResponse() },
            fetchMethods: { throw APIError.serverUnreachable },
            setMethod: { _, _ in throw APIError.serverUnreachable },
            addPage: { _ in throw APIError.serverUnreachable })
        deps.writeYouTube = { patch in
            sent.append(patch)
            return ReadingSettingsResponse(agentEnabled: true, ackCurrent: true,
                                           youtubeLists: YouTubeListSwitches(watchLater: true))
        }
        let model = ReadingAgentModel(deps: deps)
        let ok = await model.setYouTubeList(.watchLater, true)
        XCTAssertTrue(ok)
        XCTAssertEqual(sent, [["watch_later": true]])
        XCTAssertTrue(model.settings?.youtubeLists.watchLater ?? false)
    }
}
