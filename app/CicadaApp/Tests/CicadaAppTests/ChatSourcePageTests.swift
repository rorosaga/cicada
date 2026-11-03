import XCTest
@testable import CicadaApp

/// 2026-11-03 — the owner's Sources feedback: the page actions only where they apply, connected sources first, a chat
/// source's list (recency as the apps say it, the sync line, pins on the wire, the panel's sittings), a chat's face
/// from the page it stands for, and the picker's far-future dates. Every chat, number and name here is synthetic.
final class ChatSourcePageTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!
    private let gb = Locale(identifier: "en_GB")
    /// Monday 2026-11-02 15:00 UTC.
    private let now = ISO8601DateFormatter().date(from: "2026-11-02T15:00:00Z")!

    // MARK: 3 — page actions only where they apply

    private func entry(_ id: String, site: String? = nil) -> SourceCatalogEntry {
        SourceCatalogEntry(id: id, group: .accounts, title: id, origin: id, channels: [], site: site)
    }

    func testReadingInTheBrowserShowsOnlyOnTheSourcesItActsOn() {
        XCTAssertEqual(SourcePageActions.of(entry("x", site: "x"), exploreGone: false), [.readingInBrowser])
        XCTAssertEqual(SourcePageActions.of(entry("youtube"), exploreGone: false), [.readingInBrowser])
        XCTAssertEqual(SourcePageActions.of(entry(WhatsAppWatcher.channel), exploreGone: false), [])
        XCTAssertEqual(SourcePageActions.of(entry(TelegramChats.channel), exploreGone: false), [])
        XCTAssertEqual(SourcePageActions.of(entry(MessagesWatcher.channel), exploreGone: false), [])
    }

    func testExploreSavedSitesShowsOnABrowsersPageUnlessTheRouteIsGone() {
        let browser = entry(SourceCatalog.browserPrefix + "safari")
        XCTAssertEqual(SourcePageActions.of(browser, exploreGone: false), [.exploreSavedSites])
        XCTAssertEqual(SourcePageActions.of(browser, exploreGone: true), [])
    }

    // MARK: 6 — connected first inside each section

    func testASectionListsWhatIsSetUpFirstAndKeepsTheCataloguesOrderInEachPart() {
        let entries = [entry("a"), entry("b"), entry("c"), entry("d")]
        let status: [String: SourceCatalogStatus] = ["a": .off, "b": .connected, "c": .off, "d": .needsSignIn]
        let rows = entries.map { SourceCatalogRow(entry: $0, status: status[$0.id]!, lastSync: nil) }
        let section = SourceCatalog.grouped(rows).first { $0.group == .accounts }
        XCTAssertEqual(section?.rows.map(\.id), ["b", "d", "a", "c"])
        XCTAssertEqual(SourceCatalog.drawnOrder(rows).map(\.id), ["b", "d", "a", "c"], "the keys walk what is drawn")
    }

    // MARK: 7 — a date thousands of years ahead is a sort key, not a date

    func testWhatsAppsLastActivityIsTheNewestMessageNotTheSessionsSortKey() {
        let real = now.addingTimeInterval(-3600).timeIntervalSinceReferenceDate
        // The owner's rows: day and month right, the year 7,000 ahead.
        let sortKey = Calendar(identifier: .gregorian).date(byAdding: .year, value: 7000, to: now)!
            .timeIntervalSinceReferenceDate
        XCTAssertEqual(ChatDates.whatsAppLastActivity(session: sortKey, newest: real, now: now)?
            .timeIntervalSinceReferenceDate, real)
        XCTAssertNil(ChatDates.whatsAppLastActivity(session: sortKey, newest: nil, now: now))
        XCTAssertEqual(ChatDates.whatsAppLastActivity(session: real, newest: nil, now: now)?
            .timeIntervalSinceReferenceDate, real)
    }

    func testEveryPickersLastActivityDropsADateAhead() {
        let far = Calendar(identifier: .gregorian).date(byAdding: .year, value: 6000, to: now)!
        XCTAssertNil(MessagesRowText.lastActivity(far, now: now))
        XCTAssertNotNil(MessagesRowText.lastActivity(now.addingTimeInterval(3600), now: now), "an hour of clock skew")
        XCTAssertNotNil(MessagesRowText.lastActivity(now.addingTimeInterval(-86_400 * 3), now: now))
    }

    func testTheReaderListsAChatByItsNewestMessageWhenTheSessionDateIsFarAhead() throws {
        ContactsTrap.install()
        let store = try SyntheticWhatsAppStore()
        defer { store.close() }
        let readNow = Date(timeIntervalSinceReferenceDate: 800_000_000)
        let pinnedLike = store.session("15550000002@s.whatsapp.net", name: "Bob Example",
                                       last: 800_000_000 + 7000 * 365.2425 * 86_400)
        store.message(pinnedLike, "s1", at: 799_990_000, text: "placeholder")
        let other = store.session("15550000003@s.whatsapp.net", name: "Carol Example", last: 799_995_000)
        store.message(other, "s2", at: 799_995_000, text: "placeholder")
        var reader = WhatsAppReader(store: store.url)
        reader.now = { readNow }
        let chats = try reader.chats()
        XCTAssertEqual(chats.map(\.partnerName), ["Carol Example", "Bob Example"], "the apps' order, by real dates")
        XCTAssertEqual(chats.last?.lastActivity?.timeIntervalSinceReferenceDate, 799_990_000)
    }

    // MARK: 5 — a chat source's rows

    private func chat(lastAt: String? = nil, day: String? = nil, ticked: Bool? = nil, syncedAt: String? = nil)
        -> ChannelItem {
        var item = ChannelItem(kind: .chat, id: String(repeating: "a", count: 32), title: "Person A", day: day)
        item.lastAt = lastAt
        item.ticked = ticked
        item.syncedAt = syncedAt
        return item
    }

    func testRecencyReadsAsTheAppsSayIt() {
        func text(_ at: String) -> String? {
            ChatSourcePage.recency(chat(lastAt: at), now: now, locale: gb, timeZone: utc)?.text
        }
        XCTAssertEqual(text("2026-11-02T09:05:00Z"), "09:05")
        XCTAssertEqual(text("2026-11-01T22:00:00Z"), "Yesterday")
        XCTAssertEqual(text("2026-10-29T10:00:00Z"), "Thursday")
        XCTAssertEqual(text("2026-10-03T10:00:00Z"), "3 Oct")
        XCTAssertEqual(text("2025-12-24T10:00:00Z"), "24 Dec 2025")
        XCTAssertNil(text("9026-10-29T10:00:00Z"), "a date ahead says nothing")
        XCTAssertEqual(ChatSourcePage.recency(chat(day: "2026-11-02"), now: now, locale: gb, timeZone: utc)?.text,
                       "Today", "a day with no time says the day")
    }

    func testATickedChatIsSyncedAndSaysWhenAnyOtherIsNotSyncing() {
        let synced = ChatSourcePage.syncLine(chat(ticked: true, syncedAt: "2026-11-02T14:00:00Z"), check: nil, now: now,
                                             locale: Locale(identifier: "en_US"))
        XCTAssertTrue(synced.synced)
        XCTAssertTrue(synced.text.hasPrefix("Last synced 1 hr"), synced.text)
        let checked = ChatSourcePage.syncLine(chat(ticked: true, syncedAt: "2026-10-30T14:00:00Z"),
                                              check: now.addingTimeInterval(-10), now: now)
        XCTAssertEqual(checked.text, "Last synced just now", "a reader's later check is the later sync")
        let off = ChatSourcePage.syncLine(chat(ticked: false, syncedAt: "2026-11-02T14:00:00Z"), check: now, now: now)
        XCTAssertEqual(off.text, Copy.ChatPage.notSyncing)
        XCTAssertFalse(off.synced)
    }

    func testAChatRowDecodesItsTickPinTimesAndPicture() throws {
        let json = #"""
        {"kind": "chat", "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "title": "Notes to yourself", "day": "2026-11-02",
         "ticked": true, "pinned": true, "last_at": "2026-11-02T09:05:00Z", "synced_at": "2026-11-02T09:06:00Z",
         "chat": {"id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "label": "Notes to yourself",
                  "picture": "/entities/verify-person/picture?v=0123456789ab"}}
        """#
        let item = try JSONDecoder().decode(ChannelItem.self, from: Data(json.utf8))
        XCTAssertEqual(item.ticked, true)
        XCTAssertEqual(item.pinned, true)
        XCTAssertEqual(item.lastAt, "2026-11-02T09:05:00Z")
        XCTAssertEqual(item.syncedAt, "2026-11-02T09:06:00Z")
        XCTAssertEqual(item.chat?.picture, "/entities/verify-person/picture?v=0123456789ab")
    }

    func testThePanelShowsTheNewestSittingsOldestFirstAndOffersEarlierOnes() {
        let sittings = (1...7).map { ChatSitting(id: "ep_\($0)") }   // newest first, as the route sends them
        XCTAssertEqual(ChatSourcePage.shownSittings(sittings, pages: 1).map(\.id), ["ep_3", "ep_2", "ep_1"])
        XCTAssertTrue(ChatSourcePage.hasEarlier(sittings, pages: 1))
        XCTAssertEqual(ChatSourcePage.shownSittings(sittings, pages: 3).count, 7)
        XCTAssertFalse(ChatSourcePage.hasEarlier(sittings, pages: 3))
    }

    func testAPinIsWrittenThroughEachChatSourcesOwnSettingsRoute() {
        XCTAssertEqual(ChatSourcePage.settingsSource[WhatsAppWatcher.channel], "whatsapp")
        XCTAssertEqual(ChatSourcePage.settingsSource[TelegramChats.channel], "telegram")
        XCTAssertEqual(ChatSourcePage.settingsSource[MessagesWatcher.channel], "messages")
        XCTAssertFalse(ChatSourcePage.isChatSource("chat-export:claude"))
    }

    // MARK: 2 — the face is the page the chat stands for

    func testAChatsFaceAsksThePagesPictureFirstThenItsOwnPhoto() {
        let id = String(repeating: "a", count: 32)
        XCTAssertEqual(SourcePictures.chatFacePaths(id: id, photo: "0123456789ab",
                                                    picture: "/entities/verify-person/picture?v=0123456789ab"),
                       ["/entities/verify-person/picture?v=0123456789ab",
                        "/sources/messages/chats/\(id)/photo?v=0123456789ab"])
        XCTAssertEqual(SourcePictures.chatFacePaths(id: id, photo: nil, picture: "/entities/verify-person/photo?k=abc"),
                       ["/entities/verify-person/photo?k=abc"])
        XCTAssertEqual(SourcePictures.chatFacePaths(id: id, photo: nil, picture: nil), [])
    }

    func testOnlyAPathThePrecedenceBuildsIsAsked() {
        XCTAssertNil(SourcePictures.pagePicturePath("https://example.com/entities/a/picture"))
        XCTAssertNil(SourcePictures.pagePicturePath("/entities/../api_token/picture"))
        XCTAssertNil(SourcePictures.pagePicturePath("/entities/a/logo"))
        XCTAssertNil(SourcePictures.pagePicturePath("/sources/x/picture"))
        XCTAssertNotNil(SourcePictures.pagePicturePath("/entities/a/picture?v=0123456789ab"))
    }

    // MARK: 5 — the panel never shows an unticked chat's words

    func testTheSittingsSayWhetherTheChatIsTicked() throws {
        let unticked = try JSONDecoder().decode(ChatSittings.self, from: Data(
            #"{"conversation":"aa","ticked":false,"sittings":[]}"#.utf8))
        XCTAssertEqual(unticked.ticked, false)
        XCTAssertTrue(unticked.sittings.isEmpty)
        let older = try JSONDecoder().decode(ChatSittings.self, from: Data(
            #"{"conversation":"aa","sittings":[{"id":"ep_2026-10-01_001","day":"2026-10-01"}]}"#.utf8))
        XCTAssertNil(older.ticked, "an older backend says nothing; the row's own tick decides")
        XCTAssertEqual(older.sittings.map(\.id), ["ep_2026-10-01_001"])
    }
}
