import XCTest
@testable import CicadaApp

/// A `ChannelItemsAPI` that knows the search door and records the query each call carried.
@MainActor
private final class SearchingFakeAPI: ChannelItemsAPI {
    var pages: [String: ChannelItemsPage] = [:]
    private(set) var queries: [String] = []

    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        queries.append("")
        return Conditional(value: pages[""], etag: "e0", notModified: false)
    }

    func fetchChannelItems(channel: String, offset: Int, limit: Int, query: String, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        queries.append(query)
        return Conditional(value: pages[query], etag: "e-\(query)", notModified: false)
    }
}

/// source-page-v3 (owner 2026-10-29) — one source page for every source: the status, the one search, the list's rules.
@MainActor
final class SourcePageV3Tests: XCTestCase {
    private let us = Locale(identifier: "en_US")
    private let today = ISODay(year: 2026, month: 10, day: 29)

    // MARK: The status

    func testConnectedSaysTheDayTheLastItemCameIn() {
        let status = SourcePageStatus.of(row: .connected, run: .synced(.now), latest: "2026-10-29")
        XCTAssertEqual(status, .connected(lastItem: "2026-10-29"))
        XCTAssertEqual(status.line(today: today, locale: us), "Connected · last item today")
        XCTAssertEqual(SourcePageStatus.connected(lastItem: "2026-10-28").line(today: today, locale: us),
                       "Connected · last item yesterday")
        XCTAssertEqual(SourcePageStatus.connected(lastItem: "2026-06-03").line(today: today, locale: us),
                       "Connected · last item Jun 3")
        XCTAssertEqual(SourcePageStatus.connected(lastItem: nil).line(today: today, locale: us),
                       "Connected · nothing in yet")
    }

    func testWestOfUTCInTheEveningTheLastItemIsTodayNeverTomorrow() {
        // 2026-10-29 20:30 at UTC−5 is 2026-10-30 01:30 UTC: the backend dates the item the 30th (its UTC day).
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: -5 * 3600)!
        let instant = ISO8601DateFormatter().date(from: "2026-10-30T01:30:00Z")!
        let localToday = ISODay.today(now: instant, calendar: calendar)
        XCTAssertEqual(localToday, ISODay(year: 2026, month: 10, day: 29))
        let status = SourcePageStatus.connected(lastItem: "2026-10-30")
        XCTAssertEqual(status.line(today: localToday, locale: us), "Connected · last item today")
        XCTAssertEqual(SourcePageStatus.off(lastItem: "2026-10-30").line(today: localToday, locale: us),
                       "Off · last item today")
        XCTAssertEqual(SourcePageStatus.connected(lastItem: "2026-10-28").line(today: localToday, locale: us),
                       "Connected · last item yesterday", "a past day is untouched")
    }

    func testARunningReadIsSyncingWithTheReadersOwnWords() {
        let status = SourcePageStatus.of(row: .connected, run: .syncing(detail: "12 of 40", fraction: 0.3,
                                                                         cancellable: true), latest: nil)
        XCTAssertEqual(status.line(today: today, locale: us), "Syncing · 12 of 40")
        XCTAssertEqual(status.tone, .on)
    }

    func testNeedsYouNamesOneAction() {
        XCTAssertEqual(SourcePageStatus.of(row: .needsSignIn, run: .idle, latest: nil).line(today: today),
                       "Needs you · sign in again")
        XCTAssertEqual(SourcePageStatus.of(row: .waitingForAgent, run: .idle, latest: nil).line(today: today),
                       "Needs you · connect an agent on this Mac")
        XCTAssertEqual(SourcePageStatus.of(row: .connected, run: .problem(Copy.sourceNeedsAccess), latest: nil)
                        .line(today: today), "Needs you · allow Full Disk Access")
        XCTAssertEqual(SourcePageStatus.of(row: .connected, run: .problem("Couldn't read the file"), latest: nil)
                        .tone, .attention)
    }

    func testOffSaysOnlyWhatItStillHolds() {
        XCTAssertEqual(SourcePageStatus.of(row: .off, run: .idle, latest: nil).line(today: today), "Off")
        XCTAssertEqual(SourcePageStatus.of(row: .off, run: .idle, latest: "2026-10-29").line(today: today, locale: us),
                       "Off · last item today")
    }

    // MARK: The search

    func testTheSearchRidesQEncodedAndCut() {
        XCTAssertEqual(APIClient.channelItemsPath("notes", offset: 0, limit: 20, query: "  "),
                       "/sources/channels/notes/items?offset=0&limit=20")
        XCTAssertEqual(APIClient.channelItemsPath("notes", offset: 0, limit: 20, query: " a&b=c d#e+f "),
                       "/sources/channels/notes/items?offset=0&limit=20&q=a%26b%3Dc%20d%23e%2Bf")
        let long = String(repeating: "x", count: 300)
        XCTAssertTrue(APIClient.channelItemsPath("notes", offset: 0, limit: 20, query: long)
                        .hasSuffix("&q=" + String(repeating: "x", count: SourceSearch.maxLength)))
    }

    func testTheSearchIsCutByCodePointsLikeTheBackendNeverMidCharacter() {
        let family = "👨‍👩‍👧‍👦"   // one character, seven code points
        let long = String(repeating: family, count: 40)   // 40 characters, 280 code points
        let cut = SourceSearch.normalized(long)
        XCTAssertLessThanOrEqual(cut.unicodeScalars.count, SourceSearch.maxLength, "the backend counts code points")
        XCTAssertEqual(cut, String(repeating: family, count: 28), "whole characters only")
        XCTAssertEqual(SourceSearch.normalized("  short  "), "short")
    }

    func testASearchIsHeldBesideTheChannelsOwnList() async {
        let api = SearchingFakeAPI()
        api.pages[""] = ChannelItemsPage(channel: "notes", total: 2, items: [
            ChannelItem(kind: .episode, id: "a", title: "Garden"), ChannelItem(kind: .episode, id: "b", title: "Rice")],
            all: 2, latest: "2026-10-29")
        api.pages["garden"] = ChannelItemsPage(channel: "notes", total: 1,
                                               items: [ChannelItem(kind: .episode, id: "a", title: "Garden")],
                                               all: 2, latest: "2026-10-29")
        let cache = ChannelItemsCache(api: api)
        await cache.refresh("notes")
        await cache.refresh("notes", query: " garden ")
        XCTAssertEqual(api.queries, ["", "garden"])
        XCTAssertEqual(cache.list("notes")?.items.count, 2, "the unsearched list stays as it was")
        XCTAssertEqual(cache.list("notes", query: "garden")?.items.map(\.id), ["a"])
        XCTAssertEqual(cache.list("notes", query: "garden")?.all, 2)
        XCTAssertEqual(cache.list("notes")?.latest, "2026-10-29")
    }

    func testAFakeWithoutTheSearchDoorAnswersWithItsPage() async {
        let api = FakeChannelItemsAPI()
        api.replies = [.success(Conditional(value: ChannelItemsPage(channel: "notes", total: 0, items: []),
                                            etag: "x", notModified: false))]
        let cache = ChannelItemsCache(api: api)
        await cache.refresh("notes", query: "anything")
        XCTAssertEqual(api.calls.count, 1)
        XCTAssertNotNil(cache.list("notes", query: "anything"))
    }

    func testThePageDecodesAllAndLatest() throws {
        let json = #"{"channel":"imessage","total":1,"all":4,"latest":"2026-10-29","offset":0,"items":[]}"#
        let page = try JSONDecoder().decode(ChannelItemsPage.self, from: Data(json.utf8))
        XCTAssertEqual(page.all, 4)
        XCTAssertEqual(page.latest, "2026-10-29")
        let old = try JSONDecoder().decode(ChannelItemsPage.self, from: Data(#"{"channel":"x","total":0,"items":[]}"#.utf8))
        XCTAssertNil(old.all)
        XCTAssertNil(old.latest)
    }

    // MARK: The list's rules

    func testAChatAndAWatchedDayAreGroupsThatOpenInTheColumn() {
        var chat = ChannelItem(kind: .chat, id: "c", title: "Person A")
        chat.sittings = 3
        XCTAssertTrue(SourceItemsRules.isGroup(chat))
        XCTAssertEqual(SourceItemsRules.groupCount(chat), "3 conversations")
        let day = ChannelItem(kind: .episode, id: "d", title: "Watched", videos: 2)
        XCTAssertTrue(SourceItemsRules.isGroup(day))
        XCTAssertEqual(SourceItemsRules.groupCount(day), Copy.watchedVideos(2))
        XCTAssertFalse(SourceItemsRules.isGroup(ChannelItem(kind: .episode, id: "n", title: "A note")))
    }

    func testAChatRowFromAnyChatSourceCountsItsMessagesAndSaysGroup() throws {
        // #559's chat row (WhatsApp, Telegram): `messages` and `group` beside `sittings`.
        let json = #"{"kind":"chat","id":"abc","title":"Climbing group","day":"2026-10-28","sittings":2,"messages":6,"group":true,"chat":{"id":"abc","label":"Climbing group"}}"#
        let item = try JSONDecoder().decode(ChannelItem.self, from: Data(json.utf8))
        XCTAssertEqual(item.messages, 6)
        XCTAssertEqual(item.group, true)
        XCTAssertEqual(SourceItemsRules.groupCount(item), "6 messages")
        let old = try JSONDecoder().decode(ChannelItem.self,
                                           from: Data(#"{"kind":"chat","id":"x","title":"A","sittings":3}"#.utf8))
        XCTAssertNil(old.group)
        XCTAssertEqual(SourceItemsRules.groupCount(old), "3 conversations", "no message count kept: the sittings")
    }

    func testThePromptNamesWhatTheListHolds() {
        XCTAssertEqual(Copy.SourcePage.searchPrompt(total: 6, noun: ("chat", "chats")), "Search 6 chats")
        XCTAssertEqual(Copy.SourcePage.searchPrompt(total: 1, noun: ("chat", "chats")), "Search 1 chat")
        XCTAssertEqual(Copy.SourcePage.searchPrompt(total: nil, noun: ("chat", "chats")), "Search")
    }
}
