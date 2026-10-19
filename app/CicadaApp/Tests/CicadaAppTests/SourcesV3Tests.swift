import XCTest
@testable import CicadaApp

/// Sources v3 (owner 2026-10-19): "in two clicks I click on something, then I click on Chrome, and then I can see all
/// the things that I've saved in Chrome. Instead of putting the Chrome logo maybe put the website's logo … Clicking
/// again on Sources takes me back to the main Sources page." The grouping, the two-click path, the sidebar re-click,
/// a saved row (its why and its mark, with the fallback) and paging — pure where they can be, pinned at the source
/// where they cannot.
@MainActor
final class SourcesV3Tests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func source(_ path: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(path) }, path)
        return try String(contentsOf: file, encoding: .utf8)
    }

    private func row(_ id: String, _ kind: SourceKind, _ intent: SourceIntent, last: String? = nil,
                     items: Int = 0, episodes: Int = 0, conversations: Int = 0, channelId: String? = nil,
                     harness: String? = nil, actions: [String] = [], lastError: String? = nil) -> SourceOverview {
        SourceOverview(id: id, label: id, kind: kind, conversations: conversations, episodes: episodes, items: items,
                       lastActivityAt: last, lastError: lastError, actions: actions, channelId: channelId,
                       harness: harness, intent: intent)
    }

    // MARK: 1 · The grouping — where your stuff came from

    func testSavedComesFirstThenCapturedEachNewestFirst() {
        let groups = SourceIntentGroups.group([
            row("harness:claude-code", .harness, .captured, last: "2026-10-19T09:00:00Z"),
            row("chrome-bookmarks", .browser, .saved, last: "2026-10-18T09:00:00Z"),
            row("youtube", .social, .saved, last: "2026-10-19T08:00:00Z"),
            row("imessage", .messaging, .captured, last: "2026-10-01T09:00:00Z"),
            row("x", .social, .saved),
        ])
        XCTAssertEqual(groups.map(\.intent), [.saved, .captured])
        XCTAssertEqual(groups.map(\.title), ["Saved by you", "Captured for you"])
        XCTAssertEqual(groups[0].rows.map(\.id), ["youtube", "chrome-bookmarks", "x"], "newest first, undated last")
        XCTAssertEqual(groups[1].rows.map(\.id), ["harness:claude-code", "imessage"])
    }

    func testAnEmptyGroupIsNotDrawn() {
        XCTAssertEqual(SourceIntentGroups.group([row("rss", .feed, .captured)]).map(\.intent), [.captured])
        XCTAssertTrue(SourceIntentGroups.group([]).isEmpty)
    }

    func testTheIntentDecodesAndAnOlderBackendReadsAsCaptured() throws {
        let decode = { (json: String) in try JSONDecoder().decode(SourceOverview.self, from: Data(json.utf8)) }
        XCTAssertEqual(try decode(#"{"id":"chrome-bookmarks","kind":"browser","intent":"saved"}"#).intent, .saved)
        XCTAssertEqual(try decode(#"{"id":"rss","kind":"feed"}"#).intent, .captured)
        XCTAssertEqual(try decode(#"{"id":"rss","kind":"feed","intent":"weird"}"#).intent, .captured)
        // The Store hydrates from disk: the field must survive its own round trip.
        let saved = row("x", .social, .saved)
        XCTAssertEqual(try JSONDecoder().decode(SourceOverview.self, from: JSONEncoder().encode(saved)).intent, .saved)
    }

    func testARowSaysWhatCameFromItAndWhatItIsDoingWithNoGraph() {
        let chrome = row("chrome-bookmarks", .browser, .saved, items: 342, channelId: "chrome-bookmarks")
        let watching = SourceLiveness(state: .watching, detail: nil)
        XCTAssertEqual(SourceListText.line(chrome, liveness: watching), "342 saved · Watching")
        let youtube = row("youtube", .social, .saved, items: 12, episodes: 40)
        XCTAssertEqual(SourceListText.count(youtube), "12 saved", "the saved pages its list lists, never its episodes")
        XCTAssertEqual(SourceListText.count(row("youtube", .social, .saved, episodes: 30)), "Nothing saved yet",
                       "review of #347: thirty captured days are not thirty saves")
        XCTAssertEqual(SourceListText.count(row("x", .social, .saved)), "Nothing saved yet")
        let claude = row("harness:claude-code", .harness, .captured, episodes: 300, conversations: 204,
                         harness: "claude-code")
        XCTAssertEqual(SourceListText.line(claude, liveness: SourceLiveness(state: .captured, detail: nil)),
                       "204 conversations · Captured by hook")
        let broken = SourceLiveness(state: .failed, detail: "Can't open the file")
        XCTAssertEqual(SourceListText.line(chrome, liveness: broken), "Sync failed — Can't open the file",
                       "a failing source says its failure, not its count")
    }

    /// Re-review of #347 — a captured history row headlines its days; it never reads "Nothing yet" over thirty of them,
    /// and its detail lists those days under its own id.
    func testAWatchHistoryRowCountsItsDaysAndListsThem() throws {
        let history = SourceOverview(id: "youtube-history", label: "YouTube history", kind: .social, episodes: 30,
                                     origins: ["youtube-history"], intent: .captured)
        XCTAssertTrue(history.isWatchHistory)
        XCTAssertNotEqual(SourceListText.count(history), "Nothing yet")
        XCTAssertEqual(SourceListText.count(history), "30 watched days")
        XCTAssertEqual(history.countLines.first, "30 watched days", "the detail's sentence agrees")
        XCTAssertEqual(history.itemsListId, "youtube-history")
        XCTAssertFalse(row("youtube", .social, .saved).isWatchHistory)
        let channel = try source("Views/Sources/ChannelSourceView.swift")
        XCTAssertTrue(channel.contains("} else if source.isWatchHistory {\n            // Review of #347"))
    }

    func testTheRootHasNoSparklineAndOneQuietStatisticsDisclosure() throws {
        let columns = try source("Views/Sources/SourcesColumns.swift")
        for gone in ["sparklinePath", "weekDots", "SourceDeltaText", "SourceCardGrid", "LazyVGrid"] {
            XCTAssertFalse(columns.contains(gone), "\(gone) is the v2 grid's, retired by the owner")
        }
        XCTAssertTrue(columns.contains("ContributorsStrip"), "who wrote your memory moved under Statistics")
        XCTAssertEqual(columns.components(separatedBy: "usageVM.mode").count - 1, 2,
                       "one disclosure, on the remembered `cicada.usageMode` key (DR-39)")
        XCTAssertEqual(Copy.Lists.advancedStatistics, "Statistics")
    }

    // MARK: 2 · The two-click path — Sources → Chrome → everything saved in Chrome

    func testOpeningASavedSourceListsItsItemsUnderItsChannelOrItsOwnId() {
        XCTAssertEqual(row("chrome-bookmarks", .browser, .saved, channelId: "chrome-bookmarks").itemsListId,
                       "chrome-bookmarks")
        XCTAssertEqual(row("youtube", .social, .saved).itemsListId, "youtube",
                       "a one-shot import with no channel is listed by its row id (the backend accepts it)")
    }

    func testTheSecondClickLandsOnTheSavedListNotOnGraphs() throws {
        let channel = try source("Views/Sources/ChannelSourceView.swift")
        XCTAssertTrue(channel.contains("if source.intent == .saved {"))
        XCTAssertTrue(channel.contains("CapturedItemsList(channel: source.itemsListId, style: .saved)"))
        // Sources v4: no source has a 30-day card or queue strip any more — one header, then the list.
        let detail = try source("Views/Sources/SourceDetailView.swift")
        XCTAssertFalse(detail.contains("headerCard"))
        XCTAssertTrue(detail.contains("SourceDetailHead(source: live"))
    }

    func testTheFirstClickOpensTheSourceAndTheEyebrowSaysWhere() {
        var columns = ListColumns<SourcesSelection>()
        let groups = SourceIntentGroups.group([row("chrome-bookmarks", .browser, .saved),
                                               row("harness:claude-code", .harness, .captured)])
        columns.open(.source("chrome-bookmarks"))
        XCTAssertEqual(columns.openId, .source("chrome-bookmarks"))
        XCTAssertEqual(SourcesModel.eyebrow(groups: groups, open: columns.openId), "Sources · 2 connected",
                       "Sources v4: the eyebrow stays the page's (the list shows where you are)")
    }

    func testASavedRowOpensWhereASavedItemOpensToday() {
        let item = ChannelItem(kind: .media, id: "media-one", title: "One", day: "2026-10-19")
        XCTAssertEqual(CapturedItemRoute.of(item, interactive: true), .feed(mediaEntityId: "media-one"),
                       "Sleep › Saved's detail, the established landing (R-DL16)")
    }

    // MARK: 3 · Clicking Sources again returns to the root

    func testARailCellTappedOnItsOwnPageIsAReselect() {
        XCTAssertTrue(RailReselect.isReselect(current: .sources, tapped: .sources))
        XCTAssertFalse(RailReselect.isReselect(current: .graph, tapped: .sources))
    }

    func testTheRouterCountsReselectsPerPageAndRemembersTheKey() {
        let router = AppRouter()
        XCTAssertEqual(router.reselections(of: .sources), 0)
        router.reselect(.sources)
        XCTAssertFalse(router.lastReselectByKey, "a click")
        router.reselect(.sources, byKey: true)
        XCTAssertTrue(router.lastReselectByKey, "the last one came from ⌘ — it must not animate (DR-60)")
        router.reselect(.graph)
        XCTAssertEqual(router.reselections(of: .sources), 2)
        XCTAssertEqual(router.reselections(of: .graph), 1)
    }

    func testAReselectPopsTheDetailAndTheReaderAndNothingAtTheRoot() {
        XCTAssertTrue(SourcesModel.popsToRoot(detailOpen: true, readerOpen: false))
        XCTAssertTrue(SourcesModel.popsToRoot(detailOpen: true, readerOpen: true))
        XCTAssertTrue(SourcesModel.popsToRoot(detailOpen: false, readerOpen: true))
        XCTAssertFalse(SourcesModel.popsToRoot(detailOpen: false, readerOpen: false))
        var columns = ListColumns<SourcesSelection>()
        columns.open(.source("chrome-bookmarks"))
        columns.close()
        XCTAssertNil(columns.openId, "closing the detail is the root")
    }

    func testThePageAndTheRailAreWiredToTheReselect() throws {
        let page = try source("Views/Sources/SourcesPageView.swift")
        XCTAssertTrue(page.contains(".onRailReselect(.sources, router: router)"))
        XCTAssertTrue(page.contains("router.popToRoot(reduceMotion: reduceMotion, change)"),
                      "the shared path: the ⌘ key never animates (DR-60)")
        let rail = try source("Views/Shell/NavRail.swift")
        XCTAssertTrue(rail.contains("router?.reselect(tab, byKey:"))
    }

    // MARK: 4 · A saved row: the site's mark (with the fallback), the title, the day and the why

    func testASavedRowDecodesItsSiteAndWhyLeniently() throws {
        let json = #"""
        {"kind":"media","id":"m1","title":"A design system","day":"2026-10-19","host":"example.com",
         "site":"example.com","why":{"labels":["The design"],"text":"the type scale"}}
        """#
        let item = try JSONDecoder().decode(ChannelItem.self, from: Data(json.utf8))
        XCTAssertEqual(item.host, "example.com")
        XCTAssertEqual(item.site, "example.com")
        XCTAssertEqual(item.why, ChannelItemWhy(labels: ["The design"], text: "the type scale"))
        let old = try JSONDecoder().decode(ChannelItem.self, from: Data(#"{"kind":"media","id":"m1","title":"T"}"#.utf8))
        XCTAssertNil(old.why); XCTAssertNil(old.site); XCTAssertNil(old.host)
        let bad = try JSONDecoder().decode(ChannelItem.self,
                                           from: Data(#"{"kind":"media","id":"m1","title":"T","why":"nope"}"#.utf8))
        XCTAssertNil(bad.why, "a malformed why drops the field, never the row")
    }

    func testTheWhyLeadsTheSecondLineThenTheReasonsThenTheSite() {
        let item = ChannelItem(kind: .media, id: "m1", title: "T", day: "2026-10-19", host: "example.com",
                               site: "example.com",
                               why: ChannelItemWhy(labels: ["The design", "To read later"], text: "  the type scale "))
        XCTAssertEqual(SavedItemText.line(item), "“the type scale” · The design · To read later · example.com")
        XCTAssertEqual(SavedItemText.whySpoken(item), "the type scale, The design, To read later")
        let plain = ChannelItem(kind: .media, id: "m2", title: "T", host: "example.com")
        XCTAssertEqual(SavedItemText.line(plain), "example.com", "no answer: just where it lives")
        XCTAssertNil(SavedItemText.whySpoken(plain))
        XCTAssertNil(SavedItemText.line(ChannelItem(kind: .media, id: "m3", title: "T")))
    }

    func testTheMarkIsTheSitesNeverTheBrowsersWithAMonogramFallback() {
        let site = ChannelItem(kind: .media, id: "m1", title: "Post", host: "linkedin.com", site: "linkedin")
        XCTAssertEqual(SavedItemText.mark(site), .site(key: "linkedin", label: "linkedin.com"))
        XCTAssertEqual(SiteIconLayout.rung(favicon: false, site: "linkedin", markExists: { _ in true }),
                       .bundled("linkedin"), "a family's own bundled mark")
        XCTAssertEqual(SiteIconLayout.rung(favicon: false, site: "example.com", markExists: { _ in true }), .monogram,
                       "a site whose own icon has not arrived (or does not exist) draws its monogram")
        let noSite = ChannelItem(kind: .media, id: "m2", title: "Zebra notes", host: "zebra.example")
        XCTAssertEqual(SavedItemText.mark(noSite), .monogram("Z"))
        XCTAssertEqual(SavedItemText.mark(ChannelItem(kind: .media, id: "m3", title: "quiet page")), .monogram("Q"))
    }

    func testTheRowsMarkAsksItsOwnSiteThroughTheBackend() throws {
        let row = try source("Views/Sources/CapturedItemsList.swift")
        XCTAssertTrue(row.contains("SiteIcon(site: key, label: label, savedItem: item.kind == .media ? item.id : nil)"))
        let client = try source("Services/APIClient.swift")
        XCTAssertTrue(client.contains("\"/sources/saved/\\(encodedID(mediaEntityId))/site-icon\""))
        XCTAssertFalse(row.contains("OriginMark(origin"), "never the browser's mark on a saved row")
        XCTAssertFalse(row.contains("URL(string"), "the app loads no picture a page names from the web")
    }

    func testTheDayIsComputedWhenReadWithTheFullDateAsHelp() throws {
        let today = try XCTUnwrap(ISODay("2026-10-19"))
        let item = { (day: String) in ChannelItem(kind: .media, id: "m", title: "T", day: day) }
        XCTAssertEqual(SavedItemText.day(item("2026-10-19"), today: today, locale: us)?.text, "Today")
        XCTAssertEqual(SavedItemText.day(item("2026-10-18"), today: today, locale: us)?.text, "Yesterday")
        XCTAssertEqual(SavedItemText.day(item("2026-09-03"), today: today, locale: us)?.text, "Sep 3")
        XCTAssertEqual(SavedItemText.day(item("2026-09-03"), today: today, locale: us)?.help, "Thursday, September 3, 2026")
        XCTAssertNil(SavedItemText.day(ChannelItem(kind: .media, id: "m", title: "T"), today: today))
    }

    func testTheRowIsSpokenWithItsWhy() {
        XCTAssertEqual(Copy.savedRowLabel("A design system", day: "Monday, October 19, 2026", why: "the type scale",
                                          host: "example.com", left: nil),
                       "A design system, saved Monday, October 19, 2026, why: the type scale, example.com")
    }

    /// Owner ruling 2026-10-19 — a saved row asks its own site's icon by its media id, once per site; never the
    /// reading list's icon-service route.
    func testASavedRowAsksItsOwnSiteOncePerSiteAndNeverTheIconService() async {
        let saved = SavedAsks()
        let store = SiteIconStore(fetch: { _ in XCTFail("the icon-service route is never asked for a saved row"); return nil },
                                  fetchForSaved: { id in await saved.add(id); return nil })
        _ = await store.image(site: "paperfold.io", bank: "b1", savedItem: "media-1")
        _ = await store.image(site: "paperfold.io", bank: "b1", savedItem: "media-2")
        _ = await store.image(site: "other.io", bank: "b1", savedItem: "media-3")
        let asked = await saved.ids
        XCTAssertEqual(asked, ["media-1", "media-3"], "a second row of the same site reuses the first answer, a miss too")
    }

    // MARK: 5 · Paging at the owner's scale

    func testASavedListPagesTwentyAtATimeAndKeepsEveryWhy() async {
        let api = FakeChannelItemsAPI()
        func saved(_ n: Int) -> ChannelItem {
            ChannelItem(kind: .media, id: "m\(n)", title: "Saved \(n)", day: "2026-10-01", host: "example.com",
                        site: "example.com", why: ChannelItemWhy(labels: [], text: "why \(n)"))
        }
        api.replies = [.success(Conditional(value: ChannelItemsPage(channel: "chrome-bookmarks", total: 3000,
                                                                     items: (0..<20).map(saved)),
                                            etag: "\"a\"", notModified: false)),
                       .success(Conditional(value: ChannelItemsPage(channel: "chrome-bookmarks", total: 3000, offset: 20,
                                                                     items: (20..<40).map(saved)),
                                            etag: "\"b\"", notModified: false))]
        let cache = ChannelItemsCache(api: api)
        await cache.refresh("chrome-bookmarks")
        XCTAssertEqual(api.calls.first, .init(channel: "chrome-bookmarks", offset: 0, limit: 20, etag: nil),
                       "the first page only — never three thousand rows at once")
        await cache.loadMore("chrome-bookmarks")
        let list = cache.list("chrome-bookmarks")
        XCTAssertEqual(list?.items.count, 40)
        XCTAssertEqual(list?.total, 3000)
        XCTAssertTrue(list?.hasMore ?? false)
        XCTAssertEqual(list?.items.last?.why?.text, "why 39")
    }

    func testTheSavedListIsLazy() throws {
        let list = try source("Views/Sources/CapturedItemsList.swift")
        XCTAssertTrue(list.contains("LazyVStack(spacing: CicadaTheme.scaled(RowMetrics.twoLineGap))"))
    }
}

private actor SavedAsks {
    var ids: [String] = []
    func add(_ id: String) { ids.append(id) }
}
