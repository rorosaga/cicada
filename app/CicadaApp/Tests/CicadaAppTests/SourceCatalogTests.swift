import XCTest
@testable import CicadaApp

/// G217 (ruling 36 D6) — the Sources page's one catalogue: groups by way in, three status words, Obsidian gone,
/// Instagram present and honest, Contacts kept (ruling 33), chat exports pointing at their agent.
final class SourceCatalogTests: XCTestCase {
    private func rows(channels: [SourceChannel] = [], overview: [SourceOverview] = [],
                      readable: Set<String> = [], browsers: [BrowserSpec] = []) -> [SourceCatalogRow] {
        let entries = SourceCatalog.entries(browsers: browsers, wisprPresent: false, overview: overview)
        return SourceCatalog.rows(entries: entries, channels: channels, overview: overview, readableSites: readable)
    }

    private func row(_ id: String, in rows: [SourceCatalogRow]) -> SourceCatalogRow? { rows.first { $0.id == id } }

    func testGroupsComeInTheirFixedOrderAndEveryEntryHasOne() {
        let groups = SourceCatalog.grouped(rows()).map(\.group)
        XCTAssertEqual(groups, [.accounts, .thisMac, .exports, .feeds])
    }

    func testTheCatalogueHasNoObsidianAndKeepsContactsAndInstagram() {
        let ids = rows().map(\.id)
        XCTAssertFalse(ids.contains { $0.contains("obsidian") })
        XCTAssertTrue(ids.contains("contacts-local"))
        XCTAssertEqual(row("instagram", in: rows())?.entry.verb, .turnOn)
        XCTAssertEqual(row("instagram", in: rows())?.entry.group, .accounts)
    }

    func testStatusIsConnectedNeedsSignInOrOff() {
        let r = rows(channels: [
            SourceChannel(id: "calendar-local", label: "Calendar", connected: true, lastSync: "2026-10-22T10:00:00Z"),
            SourceChannel(id: "reddit", label: "Reddit", connected: true, lastError: "Token expired — reconnect"),
            SourceChannel(id: "rss", label: "RSS", connected: false),
        ])
        XCTAssertEqual(row("calendar-local", in: r)?.status, .connected)
        XCTAssertEqual(row("reddit", in: r)?.status, .needsSignIn)
        XCTAssertEqual(row("rss", in: r)?.status, .off)
        XCTAssertEqual(row("x", in: r)?.status, .off)
    }

    func testInstagramIsConnectedOnlyOnceItsSiteMayBeRead() {
        XCTAssertEqual(row("instagram", in: rows())?.status, .off)
        XCTAssertEqual(row("instagram", in: rows(readable: ["instagram"]))?.status, .connected)
    }

    func testTheLineIsTheLastSyncOnlyWhileOn() {
        let now = ISODate.parse("2026-10-22T12:00:00Z")!
        let r = rows(channels: [SourceChannel(id: "calendar-local", label: "Calendar", connected: true,
                                              lastSync: "2026-10-22T10:00:00Z")])
        XCTAssertNotNil(SourceCatalog.line(row("calendar-local", in: r)!, now: now, locale: Locale(identifier: "en_US")))
        XCTAssertNil(SourceCatalog.line(row("rss", in: r)!, now: now))
    }

    func testAnAgentsConversationsWithNoEntryGetTheirOwnRowAndChatExportsPointAtAgents() {
        let overview = [SourceOverview(id: "harness:cursor", label: "Cursor", kind: .harness, mark: "cursor")]
        let r = rows(overview: overview)
        XCTAssertEqual(row("overview:harness:cursor", in: r)?.entry.group, .conversations)
        XCTAssertEqual(row("overview:harness:cursor", in: r)?.status, .connected)
        XCTAssertEqual(row("chat-exports", in: r)?.entry.verb, .openAgents)
    }

    func testFoldersAreConnectedByAnyFolderChannel() {
        let r = rows(channels: [SourceChannel(id: "folder:abc", label: "Notes", connected: true)])
        XCTAssertEqual(row("folders", in: r)?.status, .connected)
    }

    func testABrowserOnThisMacIsAnEntryWithItsChannels() {
        let chrome = BrowserInventory.spec(id: "chrome")!
        let r = rows(browsers: [chrome])
        let entry = row("browser:chrome", in: r)?.entry
        XCTAssertEqual(entry?.group, .thisMac)
        XCTAssertTrue(entry?.channels.contains("chrome-bookmarks") == true)
        XCTAssertEqual(SourceCatalog.connectedCount(r), 0)
    }

    /// 2026-10-23 — the backend knows a reader synced once, never that it was disconnected on this Mac: a Calendar,
    /// Contacts, tab groups or bookmark watch turned off kept reading Connected while nothing more arrived.
    func testAReaderTurnedOffOnThisMacReadsOffWhateverItSyncedBefore() {
        let synced = [SourceChannel(id: "calendar-local", label: "Calendar", connected: true,
                                    lastSync: "2026-10-22T10:00:00Z"),
                      SourceChannel(id: "notes", label: "Apple Notes", connected: true, lastSync: "2026-10-22T10:00:00Z")]
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, overview: [])
        let off = SourceCatalog.rows(entries: entries, channels: synced, overview: [], readableSites: [],
                                     localReaders: ["calendar-local": false, "notes": false])
        XCTAssertEqual(row("calendar-local", in: off)?.status, .off)
        XCTAssertEqual(row("notes", in: off)?.status, .off)
        XCTAssertNil(SourceCatalog.line(row("calendar-local", in: off)!, now: .now), "no 'last synced' on an Off row")
        let on = SourceCatalog.rows(entries: entries, channels: synced, overview: [], readableSites: [],
                                    localReaders: ["calendar-local": true])
        XCTAssertEqual(row("calendar-local", in: on)?.status, .connected)
        XCTAssertEqual(row("notes", in: on)?.status, .connected, "a reader this page does not know is the backend's word")
    }

    /// A browser's row is Connected while any of its readers is on: bookmarks off, YouTube history on.
    func testABrowserStaysConnectedWhileAnyOfItsReadersIsOn() {
        let chrome = BrowserInventory.spec(id: "chrome")!
        let channels = [SourceChannel(id: "chrome-bookmarks", label: "Chrome", connected: true),
                        SourceChannel(id: WatchHistoryWatcher.channel, label: "YouTube", connected: true)]
        let entries = SourceCatalog.entries(browsers: [chrome], wisprPresent: false, overview: [])
        let rows = SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [],
                                      localReaders: ["chrome-bookmarks": false, WatchHistoryWatcher.channel: true])
        XCTAssertEqual(row("browser:chrome", in: rows)?.status, .connected)
        let none = SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [],
                                      localReaders: ["chrome-bookmarks": false, WatchHistoryWatcher.channel: false])
        XCTAssertEqual(row("browser:chrome", in: none)?.status, .off)
    }

    /// 2026-10-23 — only a connector can need a sign-in: Notes' Automation refusal says "not authorized" and a folder's
    /// failure may say "token", and neither is an account.
    @MainActor func testOnlyAConnectorsFailureReadsAsNeedsSignIn() {
        let r = rows(channels: [
            SourceChannel(id: "notes", label: "Apple Notes", connected: true,
                          lastError: "Not authorized to send Apple events to Notes."),
            SourceChannel(id: "folder:abc", label: "Notes", connected: true, lastError: "token file unreadable"),
            SourceChannel(id: "reddit", label: "Reddit", connected: true, lastError: "401 Unauthorized"),
        ])
        XCTAssertEqual(row("notes", in: r)?.status, .connected)
        XCTAssertEqual(row("folders", in: r)?.status, .connected)
        XCTAssertEqual(row("reddit", in: r)?.status, .needsSignIn)
        XCTAssertEqual(SourceCatalog.signInChannels, ChannelActions.connectorChannels)
    }

    /// 2026-10-23 (live test) — YouTube read Off over a Takeout import of thousands of playlist and watch-history
    /// episodes: the entry named only Chrome's history channel, so it never saw the overview's own rows.
    func testYouTubeIsConnectedByItsImportsAndListsThem() {
        let overview = [SourceOverview(id: "youtube-history", label: "YouTube history", kind: .social, episodes: 2630,
                                       lastActivityAt: "2026-10-22T10:00:00Z"),
                        SourceOverview(id: "youtube", label: "YouTube", kind: .social, episodes: 3156)]
        let r = rows(overview: overview)
        XCTAssertEqual(row("youtube", in: r)?.status, .connected)
        XCTAssertNotNil(row("youtube", in: r)?.lastSync, "its last activity is the line")
        XCTAssertEqual(SourceCatalog.overviewRow(for: row("youtube", in: r)!.entry, in: overview)?.id, "youtube-history")
        XCTAssertEqual(row("youtube", in: rows())?.status, .off, "nothing imported, nothing on: Off")
    }

    /// An import counts only for an account; a browser's own rows carry a channel, so a watch turned off on this Mac
    /// never reads Connected through its episodes.
    func testAnImportCountsForAnAccountButNeverRevivesAReaderTurnedOff() {
        let chrome = BrowserInventory.spec(id: "chrome")!
        let overview = [SourceOverview(id: "chrome-bookmarks", label: "Chrome bookmarks", kind: .browser, episodes: 40,
                                       channelId: "chrome-bookmarks"),
                        SourceOverview(id: "instagram", label: "Instagram", kind: .social, episodes: 3)]
        let channels = [SourceChannel(id: "chrome-bookmarks", label: "Chrome", connected: true)]
        let entries = SourceCatalog.entries(browsers: [chrome], wisprPresent: false, overview: overview)
        let r = SourceCatalog.rows(entries: entries, channels: channels, overview: overview, readableSites: [],
                                   localReaders: ["chrome-bookmarks": false])
        XCTAssertEqual(row("browser:chrome", in: r)?.status, .off)
        XCTAssertEqual(row("instagram", in: r)?.status, .connected)
    }

    /// Review of #448 — `youtube-history` also holds Chrome's watched days, so with Chrome's history switch off it no
    /// longer makes YouTube Connected; a saved playlist import still does.
    func testChromesWatchedDaysNeverKeepYouTubeConnectedOnceItsSwitchIsOff() {
        let history = SourceOverview(id: "youtube-history", label: "YouTube history", kind: .social, episodes: 12)
        let playlists = SourceOverview(id: "youtube", label: "YouTube", kind: .social, episodes: 4)
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, overview: [])
        let off = [WatchHistoryWatcher.channel: false]
        XCTAssertEqual(row("youtube", in: SourceCatalog.rows(entries: entries, channels: [], overview: [history],
                                                             readableSites: [], localReaders: off))?.status, .off)
        XCTAssertEqual(row("youtube", in: SourceCatalog.rows(entries: entries, channels: [],
                                                             overview: [history, playlists], readableSites: [],
                                                             localReaders: off))?.status, .connected)
        XCTAssertEqual(row("youtube", in: SourceCatalog.rows(entries: entries, channels: [], overview: [history],
                                                             readableSites: []))?.status, .connected,
                       "with no reader on this Mac switched off, a Takeout history import counts")
    }

    /// G206 (#426) — a saved list the person's agent keeps current is a connection; the copy no longer says "coming".
    func testASavedListOnIsConnectedAndTheInstagramCopySaysWhatExists() {
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, overview: [])
        let r = SourceCatalog.rows(entries: entries, channels: [], overview: [], readableSites: [],
                                   savedListsOn: ["instagram", "x"])
        XCTAssertEqual(row("instagram", in: r)?.status, .connected)
        XCTAssertEqual(row("x", in: r)?.status, .connected)
        XCTAssertEqual(row("linkedin", in: r)?.status, .off)
        XCTAssertFalse(Copy.Catalog.instagramHonest.lowercased().contains("coming"))
        XCTAssertEqual(SourceCatalog.savedListSites, ["x", "instagram", "linkedin"])
    }

    func testReadingSettingsDecodeTheSavedListsAndAnOlderBackendHasNone() throws {
        let on = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(
            #"{"agentEnabled": true, "savedLists": {"x": false, "instagram": true, "linkedin": false}}"#.utf8))
        XCTAssertEqual(on.savedLists["instagram"], true)
        let old = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(#"{"agentEnabled": true}"#.utf8))
        XCTAssertEqual(old.savedLists, [:])
    }

    func testSignInWordsAreReadFromTheFailure() {
        XCTAssertTrue(SourceCatalog.readsAsSignIn("401 Unauthorized"))
        XCTAssertFalse(SourceCatalog.readsAsSignIn("Timed out"))
        XCTAssertFalse(SourceCatalog.readsAsSignIn(nil))
    }
}
