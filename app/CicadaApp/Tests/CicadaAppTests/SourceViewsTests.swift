import XCTest
@testable import CicadaApp

/// G245 (track B2) — the views' pure rules: LinkedIn's Connections by month, a notes page laid out as Notes lays it, the
/// folder tree, a person's links wearing their sites' marks, the tabs of a page with a history or with people, and the
/// root card's check word. Placeholder names only.
final class SourceViewsTests: XCTestCase {
    private let today = ISODay(year: 2026, month: 11, day: 24)
    private let en = Locale(identifier: "en_US")
    private var utc: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }

    // MARK: LinkedIn Connections

    private func connection(_ id: String, day: String?, precision: LinkedInConnection.Precision = .day) -> LinkedInConnection {
        LinkedInConnection(id: id, name: "Person \(id)", day: day, precision: precision)
    }

    func testTheListDecodesLeniently() throws {
        let json = """
        {"rows": [{"id": "a", "name": "Alex Example", "headline": "Maker", "url": "https://www.linkedin.com/in/alex-example",
                   "day": "2026-11-20", "precision": "week", "page": "alex-example"},
                  {"id": "b", "name": "Blake Sample", "precision": "century", "extra": 1}],
         "total": 2, "offset": 0, "next": null, "kept": 7}
        """
        let page = try JSONDecoder().decode(LinkedInConnectionsPage.self, from: Data(json.utf8))
        XCTAssertEqual(page.rows.map(\.id), ["a", "b"])
        XCTAssertEqual(page.rows[0].precision, .week)
        XCTAssertEqual(page.rows[0].page, "alex-example")
        XCTAssertEqual(page.rows[1].precision, .day, "a precision this build does not know reads as a day")
        XCTAssertEqual(page.rows[1].headline, "")
        XCTAssertEqual(page.kept, 7)
        XCTAssertNil(page.next)
    }

    func testMonthsGroupNewestFirstAndCountOnlyAWholeMonth() {
        let rows = [connection("1", day: "2026-11-23"), connection("2", day: "2026-11-02"), connection("3", day: "2026-10-30"),
                    connection("4", day: "2026-10-01"), connection("5", day: nil)]
        let partial = LinkedInConnectionsText.months(rows, complete: false, locale: en)
        XCTAssertEqual(partial.map(\.title), ["November 2026", "October 2026", "No date"])
        XCTAssertEqual(partial.map(\.heading), ["November 2026 · 2", "October 2026 · 2", "No date"],
                       "the last group may continue on a page not read yet, so it says no count")
        let whole = LinkedInConnectionsText.months(rows, complete: true, locale: en)
        XCTAssertEqual(whole.map(\.heading), ["November 2026 · 2", "October 2026 · 2", "No date · 1"])
        XCTAssertEqual(whole[0].rows.map(\.id), ["1", "2"], "the order sent is kept inside a month")
    }

    func testADayIsSaidWithAroundWhenOnlyAWeekOrAMonthIsKnown() throws {
        let exact = try XCTUnwrap(LinkedInConnectionsText.day(connection("1", day: "2026-11-14"), today: today, locale: en))
        XCTAssertEqual(exact.text, "Nov 14")
        let week = try XCTUnwrap(LinkedInConnectionsText.day(connection("2", day: "2026-11-12", precision: .week), today: today, locale: en))
        XCTAssertEqual(week.text, "around Nov 12")
        let month = try XCTUnwrap(LinkedInConnectionsText.day(connection("3", day: "2026-10-01", precision: .month), today: today, locale: en))
        XCTAssertEqual(month.text, "around Oct", "a month's precision never names the first of it")
        let older = try XCTUnwrap(LinkedInConnectionsText.day(connection("4", day: "2025-03-01", precision: .month), today: today, locale: en))
        XCTAssertEqual(older.text, "around Mar 2025")
        XCTAssertNil(LinkedInConnectionsText.day(connection("5", day: nil), today: today, locale: en))
    }

    func testOnlyAnHttpLinkWithAHostIsAProfile() {
        func url(_ raw: String?) -> URL? {
            LinkedInConnectionsText.profile(LinkedInConnection(id: "x", name: "Person", url: raw))
        }
        XCTAssertNotNil(url("https://www.linkedin.com/in/alex-example"))
        XCTAssertNil(url("javascript:alert(1)"))
        XCTAssertNil(url("file:///etc/hosts"))
        XCTAssertNil(url("linkedin.com/in/alex"))
        XCTAssertNil(url(nil))
    }

    func testTheEmptyStatesSayOffWaitingOrNoMatch() {
        XCTAssertEqual(LinkedInConnectionsText.empty(streamOn: false, searching: false), .off)
        XCTAssertEqual(LinkedInConnectionsText.empty(streamOn: true, searching: false), .waiting)
        XCTAssertEqual(LinkedInConnectionsText.empty(streamOn: true, searching: true), .noMatch)
    }

    @MainActor
    func testTheModelPagesAndKeepsRowsWhileASearchIsRead() async {
        let all = (1...5).map { LinkedInConnection(id: "c\($0)", name: "Person \($0)", day: "2026-11-0\($0)") }
        var asked: [(String, Int, Int)] = []
        let fetch: LinkedInConnectionsModel.Fetch = { query, offset, limit in
            asked.append((query, offset, limit))
            let pool = query.isEmpty ? all : Array(all.prefix(1))
            let slice = Array(pool.dropFirst(offset).prefix(2))
            let next = offset + slice.count < pool.count ? offset + slice.count : nil
            return LinkedInConnectionsPage(rows: slice, total: pool.count, offset: offset, next: next, kept: 5)
        }
        let model = LinkedInConnectionsModel()
        XCTAssertEqual(model.phase, .idle)
        await model.load(query: "  ", using: fetch)
        XCTAssertEqual(model.rows.map(\.id), ["c1", "c2"])
        XCTAssertTrue(model.hasMore)
        await model.more(using: fetch)
        XCTAssertEqual(model.rows.map(\.id), ["c1", "c2", "c3", "c4"])
        await model.more(using: fetch)
        await model.more(using: fetch)
        XCTAssertEqual(model.rows.count, 5)
        XCTAssertFalse(model.hasMore, "no next page, no button")
        await model.load(query: "alex", using: fetch)
        XCTAssertEqual(model.rows.map(\.id), ["c1"])
        XCTAssertEqual(model.kept, 5)
        XCTAssertEqual(asked.first?.0, "", "the words are trimmed before they leave")
        XCTAssertEqual(asked.last?.0, "alex")
    }

    @MainActor
    func testAFailedFirstReadSaysSoAndAFailedLaterReadKeepsTheRows() async {
        let model = LinkedInConnectionsModel()
        await model.load(query: "", using: { _, _, _ in throw APIError.serverUnreachable })
        XCTAssertEqual(model.phase, .failed(Copy.Streams.connectionsFailed))
        await model.load(query: "", using: { _, _, _ in LinkedInConnectionsPage(rows: [LinkedInConnection(id: "a", name: "Person")], total: 1) })
        XCTAssertEqual(model.phase, .loaded)
        await model.load(query: "x", using: { _, _, _ in throw APIError.serverUnreachable })
        XCTAssertEqual(model.rows.map(\.id), ["a"], "never blank (DR-43)")
        XCTAssertEqual(model.phase, .loaded)
    }

    /// "Forget kept connections": the page then says nothing is kept, and the names are gone from the screen at once, even
    /// when the refetch that follows fails (a failed read used to keep the old rows until the tab was left).
    @MainActor
    func testForgottenConnectionsAreGoneFromTheScreenEvenWhenTheRefetchFails() async {
        let model = LinkedInConnectionsModel()
        await model.load(query: "", kept: 2, using: { _, _, _ in
            LinkedInConnectionsPage(rows: [LinkedInConnection(id: "a", name: "Person"), LinkedInConnection(id: "b", name: "Other")],
                                    total: 2, kept: 2)
        })
        XCTAssertEqual(model.rows.count, 2)
        await model.load(query: "", kept: 0, using: { _, _, _ in throw APIError.serverUnreachable })
        XCTAssertTrue(model.rows.isEmpty, "forgotten means gone from the screen")
        XCTAssertEqual(model.kept, 0)
        XCTAssertEqual(model.total, 0)
        XCTAssertFalse(model.hasMore)
        XCTAssertEqual(model.phase, .loaded, "an empty list, not an error about names that are gone")
        // A read that does fail with names still kept leaves them.
        await model.load(query: "", kept: 1, using: { _, _, _ in LinkedInConnectionsPage(rows: [LinkedInConnection(id: "c", name: "Third")], total: 1, kept: 1) })
        await model.load(query: "", kept: 1, using: { _, _, _ in throw APIError.serverUnreachable })
        XCTAssertEqual(model.rows.map(\.id), ["c"])
    }

    func testTheConnectionsTabsAndTheirDefault() {
        func stream(_ id: String, _ label: String, _ kind: StreamKind, count: Int?, on: Bool = true) -> ResolvedStream {
            ResolvedStream(source: "linkedin", stream: SourceStream(id: id, label: label, kind: kind, state: on ? .on : .off, count: count),
                           word: on ? .read : .off, fix: nil, reader: nil)
        }
        let both = [stream("linkedin.saved", "Saved posts", .saved, count: 2), stream("linkedin.connections", "Connections", .connections, count: 12)]
        XCTAssertEqual(SourceStreamItems.peopleTabs(both).map(\.label), ["Saved posts", "Connections"], "the stream's own label, not the export's")
        XCTAssertEqual(SourceStreamItems.peopleSelection(nil, streams: both), "linkedin.connections", "what the person came for")
        XCTAssertEqual(SourceStreamItems.peopleSelection(SourceStreamItems.listsTab, streams: both), SourceStreamItems.listsTab)
        XCTAssertEqual(SourceStreamItems.peopleSelection("linkedin.saved", streams: both), SourceStreamItems.listsTab)
        let only = [stream("linkedin.saved", "Saved posts", .saved, count: nil), stream("linkedin.connections", "Connections", .connections, count: nil)]
        XCTAssertEqual(SourceStreamItems.peopleTabs(only).map(\.label), ["Connections"], "a list with nothing in it has no tab")
        XCTAssertNil(SourceStreamItems.peopleSelection(nil, streams: [stream("x.bookmarks", "Bookmarks", .saved, count: 3)]))
    }

    // MARK: Apple Notes and Notion

    private func note(_ id: String, hoursAgo: Double? = nil, day: String? = nil, pinned: Bool = false) -> ChannelItem {
        var item = ChannelItem(kind: .episode, id: id, title: "Note \(id)", day: day)
        if let hoursAgo {
            let instant = Date(timeIntervalSince1970: 1_795_521_600).addingTimeInterval(-hoursAgo * 3_600)   // 2026-11-24 12:00 UTC
            item.modifiedAt = ISO8601DateFormatter().string(from: instant)
        }
        item.pinned = pinned ? true : nil
        return item
    }

    func testNotesAreGroupedAsNotesGroupsThem() {
        let items = [note("p", hoursAgo: 900, pinned: true), note("t", hoursAgo: 1), note("y", hoursAgo: 26), note("w", hoursAgo: 100),
                     note("m", hoursAgo: 400), note("oct", hoursAgo: 900), note("old", hoursAgo: 10_000), note("none")]
        let groups = NoteGroups.groups(items, today: today, calendar: utc, locale: en)
        XCTAssertEqual(groups.map(\.title), ["Pinned", "Today", "Yesterday", "Previous 7 Days", "Previous 30 Days", "October",
                                             "2025", "Earlier"])
        XCTAssertEqual(groups.map { $0.items.map(\.id) }, [["p"], ["t"], ["y"], ["w"], ["m"], ["oct"], ["old"], ["none"]])
        XCTAssertEqual(NoteGroups.groups([], today: today, calendar: utc, locale: en), [], "a group with nothing in it is not drawn")
    }

    func testAPinnedNoteIsOnlyUnderPinned() {
        let groups = NoteGroups.groups([note("p", hoursAgo: 1, pinned: true), note("t", hoursAgo: 2)], today: today, calendar: utc, locale: en)
        XCTAssertEqual(groups.map(\.title), ["Pinned", "Today"])
        XCTAssertEqual(groups[1].items.map(\.id), ["t"])
    }

    func testANotesTimeIsWordedAsNotesWordsIt() throws {
        // macOS words a time with a narrow no-break space before AM/PM: compare as plain spaces.
        func time(_ item: ChannelItem) -> String? {
            NoteGroups.time(item, today: today, calendar: utc, locale: en)?.text.replacingOccurrences(of: "\u{202F}", with: " ")
        }
        XCTAssertEqual(time(note("a", hoursAgo: 2)), "10:00 AM")
        XCTAssertEqual(time(note("b", hoursAgo: 26)), "10:00 AM", "yesterday's group already says Yesterday")
        XCTAssertEqual(time(note("c", hoursAgo: 100)), "Friday")
        XCTAssertEqual(time(note("d", hoursAgo: 400)), "Nov 7")
        XCTAssertEqual(time(note("e", day: "2026-11-24")), "Today", "a day with no instant says only the day")
        XCTAssertNil(time(note("f")))
    }

    func testTheDayACrossesMidnightFollowsTheViewersCalendar() {
        var east = Calendar(identifier: .gregorian)
        east.timeZone = TimeZone(secondsFromGMT: 9 * 3_600)!   // 23:00 UTC is 08:00 the next morning here
        var item = ChannelItem(kind: .episode, id: "n", title: "Late")
        item.modifiedAt = "2026-11-23T23:00:00Z"
        XCTAssertEqual(NoteGroups.day(item, calendar: east), ISODay(year: 2026, month: 11, day: 24))
        XCTAssertEqual(NoteGroups.day(item, calendar: utc), ISODay(year: 2026, month: 11, day: 23))
    }

    func testAFolderOpensToItsOwnSubfoldersInTheAppsOrder() throws {
        let json = """
        {"channel": "notes", "pinsRead": false, "accounts": [{"name": "iCloud", "count": 9, "collections": [
          {"id": "w", "name": "Work", "count": 1, "total": 9, "children": ["m", "p"], "depth": 0},
          {"id": "p", "name": "Projects", "count": 3, "total": 3, "parent": "w", "children": [], "depth": 1},
          {"id": "m", "name": "Meetings", "count": 5, "total": 5, "parent": "w", "children": [], "depth": 1}]}]}
        """
        let tree = try JSONDecoder().decode(ChannelCollections.self, from: Data(json.utf8))
        let account = tree.accounts[0]
        let work = account.collections[0]
        XCTAssertEqual(SourceBrowserTree.subfolders(of: work, in: account).map(\.name), ["Meetings", "Projects"], "Notes' own order, not the name's")
        XCTAssertEqual(SourceBrowserTree.subfolders(of: account.collections[1], in: account), [])
        XCTAssertTrue(SourceBrowserTree.pinsUnread(channel: "notes", tree: tree))
        XCTAssertFalse(SourceBrowserTree.pinsUnread(channel: "notion-api", tree: tree), "Notion has no pins to lose")
        XCTAssertFalse(SourceBrowserTree.pinsUnread(channel: "notes", tree: nil))
        XCTAssertTrue(SourceBrowserTree.isTree("notes") && SourceBrowserTree.isTree("notion-api"))
        XCTAssertFalse(SourceBrowserTree.isTree("calendar-local"), "a calendar keeps its flat browser")
    }

    // MARK: A person's links

    func testAProfileLinkWearsItsSitesBundledMark() {
        let exists: (String) -> Bool = { _ in true }
        for (ref, mark) in [("https://www.linkedin.com/in/alex-example", "linkedin"), ("https://x.com/alex_example", "x"),
                            ("https://twitter.com/alex_example", "x"), ("https://www.instagram.com/alex.example/", "instagram"),
                            ("https://github.com/alex-example", "github"), ("https://www.youtube.com/@alexexample", "youtube"),
                            ("https://t.me/alex_example", "telegram"), ("https://www.whatsapp.com/", "whatsapp")] {
            XCTAssertEqual(PersonSiteLink.mark(ref: ref, exists: exists), mark, ref)
        }
        XCTAssertNil(PersonSiteLink.mark(ref: "https://alex.example.org/about", exists: exists), "any other site keeps its row")
        XCTAssertNil(PersonSiteLink.mark(ref: "https://www.reddit.com/user/alex", exists: exists), "Reddit's mark ships but is not a person's profile family")
        XCTAssertNil(PersonSiteLink.mark(ref: "Ask Alex about the plan", exists: exists), "a note is not a link")
        XCTAssertNil(PersonSiteLink.mark(ref: "https://x.com/alex_example", exists: { _ in false }), "no mark shipped, no chip")
    }

    func testAProfileChipNamesTheAccountNeverABareAddress() {
        XCTAssertEqual(PersonSiteLink.name(ref: "https://x.com/alex_example", label: "x", mark: "x"), "@alex_example")
        XCTAssertEqual(PersonSiteLink.name(ref: "https://github.com/alex-example", label: nil, mark: "github"), "@alex-example")
        XCTAssertEqual(PersonSiteLink.name(ref: "https://www.instagram.com/alex.example/", label: "instagram.com", mark: "instagram"), "@alex.example")
        XCTAssertEqual(PersonSiteLink.name(ref: "https://www.linkedin.com/in/alex-example", label: "Alex Example", mark: "linkedin"), "Alex Example")
        XCTAssertEqual(PersonSiteLink.name(ref: "https://www.linkedin.com/in/alex-example", label: "linkedin.com/in/alex-example", mark: "linkedin"), "LinkedIn")
        XCTAssertEqual(PersonSiteLink.name(ref: "https://www.youtube.com/@alexexample", label: nil, mark: "youtube"), "@alexexample")
        XCTAssertEqual(PersonSiteLink.name(ref: "https://www.youtube.com/watch?v=abc", label: nil, mark: "youtube"), "YouTube")
        XCTAssertEqual(PersonSiteLink.name(ref: "https://wa.me/15550100", label: "", mark: "whatsapp"), "WhatsApp")
    }

    // MARK: The page's tabs, a card's line, a check's word

    private func stream(_ id: String, _ label: String, _ kind: StreamKind, count: Int?, state: StreamState = .on) -> ResolvedStream {
        ResolvedStream(source: "youtube", stream: SourceStream(id: id, label: label, kind: kind, state: state, count: count),
                       word: state == .on ? .read : .off, fix: nil, reader: nil)
    }

    func testAWatchedHistoryHasItsOwnTabBesideTheLists() {
        let streams = [stream("youtube.watch_later", "Watch later", .later, count: 41), stream("youtube.history", "History", .history, count: 30)]
        XCTAssertEqual(SourceStreamItems.tabs(streams).map(\.label), ["Watch later", "History"])
        XCTAssertNil(SourceStreamItems.effective(nil, streams: streams), "the cards stay the first tab")
        XCTAssertEqual(SourceStreamItems.effective("youtube.history", streams: streams), "youtube.history")
        XCTAssertTrue(SourceStreamItems.showsHistory("youtube.history", streams: streams))
        XCTAssertFalse(SourceStreamItems.showsHistory(nil, streams: streams))
        XCTAssertNil(SourceStreamItems.folderStream("youtube.history", streams: streams), "the days have no folder menu")
        let several = streams + [stream("youtube.playlists", "Playlists", .playlists, count: 3)]
        XCTAssertEqual(SourceStreamItems.tabs(several).map(\.label), ["All", "Watch later", "Playlists", "History"])
        let onlyHistory = [stream("youtube.history", "History", .history, count: 30)]
        XCTAssertTrue(SourceStreamItems.tabs(onlyHistory).isEmpty, "one thing holding items is no tabs")
        XCTAssertEqual(SourceStreamItems.historyStream(onlyHistory)?.id, "youtube.history")
        XCTAssertNil(SourceStreamItems.historyStream([stream("youtube.history", "History", .history, count: 0)]))
    }

    func testACardsStreamLineNeverSaysANothingOrAnUnknownCount() {
        let line = SourcesRoot.StreamsLine(ink: .on, parts: [.init(label: "Bookmarks", count: 214), .init(label: "Likes", count: 0),
                                                              .init(label: "History", count: nil)], folders: 3)
        XCTAssertEqual(line.text(locale: en), "Bookmarks 214 · Likes · History · 3 folders")
    }

    @MainActor
    func testARootCardShowsTheWordThatNeedsThePersonFirstAndOnlyWhileItIsFresh() {
        let now = Date(timeIntervalSince1970: 1_795_521_600)
        let a = stream("x.bookmarks", "Bookmarks", .saved, count: 1)
        let b = stream("x.likes", "Likes", .liked, count: 1)
        func result(_ id: String, _ word: StreamWord, ago: TimeInterval) -> SourceStreamCheckModel.Result {
            .init(streamId: id, word: word, at: now.addingTimeInterval(-ago), previous: nil)
        }
        let results = ["x.bookmarks": result("x.bookmarks", .read, ago: 5), "x.likes": result("x.likes", .signedOut, ago: 5)]
        XCTAssertEqual(SourceStreamCheckModel.cardWord(streams: [a, b], results: results, now: now)?.word, .signedOut)
        XCTAssertEqual(SourceStreamCheckModel.cardWord(streams: [a], results: results, now: now)?.word, .read)
        XCTAssertNil(SourceStreamCheckModel.cardWord(streams: [a, b], results: results, now: now.addingTimeInterval(600)),
                     "after a while the card goes back to its own state")
        XCTAssertNil(SourceStreamCheckModel.cardWord(streams: [a], results: [:], now: now))
    }

    func testAnItemCardLeadsWithItsAuthorAndAListUnderItsStreamsName() {
        var item = ChannelItem(kind: .media, id: "m", title: "A post", day: "2026-11-23")
        item.author = "@alex_example"
        item.lists = ["Saved posts"]
        let footer = SourceItemCardText.footer(item, today: today, locale: en)
        XCTAssertEqual(footer.first, "@alex_example")
        XCTAssertTrue(footer.contains("Saved posts"))
        XCTAssertEqual(SourceItemCardText.footer(item, today: today, omitting: "Saved posts", locale: en).contains("Saved posts"), false)
    }
}
