import SwiftUI
import XCTest
@testable import CicadaApp

/// ROR-7 (G217, G161) — the Sources root as a grid of apps: three questions at a glance, a search that needs no network
/// and no model, a company's apps found one by one and never folded together.
final class SourceGridTests: XCTestCase {
    private let chrome = BrowserInventory.catalog.first { $0.id == "chrome" }!
    private let safari = BrowserInventory.catalog.first { $0.id == "safari" }!

    private func rows(channels: [SourceChannel] = [], localReaders: [String: Bool] = [:],
                      savedLists: Set<String> = [], waitingOn: [String: String] = [:], suggested: Set<String> = [],
                      notInstalled: Set<String> = [], browsers: [BrowserSpec]? = nil,
                      watch: @escaping (String) -> BrowserWatchState? = { _ in nil }) -> [SourceCatalogRow] {
        let entries = SourceCatalog.entries(browsers: browsers ?? [chrome, safari], wisprPresent: false, hexPresent: true,
                                            overview: [])
        return SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [],
                                  localReaders: localReaders, savedListsOn: savedLists, notInstalled: notInstalled,
                                  waitingOn: waitingOn, suggested: suggested, watch: watch)
    }

    private func channel(_ id: String, error: String? = nil, lastSync: String? = nil) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: true, lastSync: lastSync, lastError: error)
    }

    private func section(_ id: String, in rows: [SourceCatalogRow]) -> SourceGridSection? {
        rows.first { $0.id == id }?.section
    }

    private func found(_ query: String, in rows: [SourceCatalogRow]? = nil) -> [String] {
        SourceGrid.results(rows ?? self.rows(), query: query).map(\.id)
    }

    // MARK: The three questions

    func testASourceSitsInExactlyOneSectionAndEverySourceIsDrawn() {
        let all = rows(channels: [channel("reddit")], savedLists: ["x"], waitingOn: ["calendar-local": Copy.sourceNeedsAccess],
                       suggested: [WhatsAppWatcher.channel])
        let drawn = SourceGrid.drawnOrder(all).map(\.id)
        XCTAssertEqual(drawn.count, Set(drawn).count, "a tile twice would be walked twice by the arrow keys")
        XCTAssertEqual(Set(drawn), Set(all.map(\.id)), "nothing the catalogue holds may fall off the page")
    }

    func testWhatsWaitingThenWhatsConnectedThenWhatCouldBeAdded() {
        let all = rows(channels: [channel("reddit"), channel("github", error: "401 token expired")],
                       waitingOn: ["calendar-local": Copy.sourceNeedsAccess], suggested: [WhatsAppWatcher.channel])
        let sections = SourceGrid.sections(all).map(\.section)
        XCTAssertEqual(Array(sections.prefix(3)), [.needsYou, .connected, .suggested])
        XCTAssertEqual(section("github", in: all), .needsYou, "a lapsed sign-in")
        XCTAssertEqual(section("calendar-local", in: all), .needsYou, "a permission taken away")
        XCTAssertEqual(section("reddit", in: all), .connected)
        XCTAssertEqual(section(WhatsAppWatcher.channel, in: all), .suggested)
        XCTAssertEqual(section("instagram", in: all), .category(.social), "the rest by what it is")
    }

    func testAListWaitingForAnAgentIsWaitingOnThePersonAndNotCounted() {
        let all = rows(savedLists: ["x"])
        XCTAssertEqual(all.first { $0.id == "x" }?.status, .waitingForAgent)
        XCTAssertEqual(section("x", in: all), .needsYou)
        XCTAssertEqual(SourceCatalog.connectedCount(all), 0)
    }

    /// #619 — the Connected section and the eyebrow can never disagree, however many rows read one reader.
    func testTheConnectedSectionHoldsExactlyWhatTheEyebrowCounts() {
        let all = rows(channels: [channel(WatchHistoryWatcher.channel), channel("reddit")],
                       localReaders: [WatchHistoryWatcher.channel: true])
        let connected = SourceGrid.sections(all).first { $0.section == .connected }?.rows.map(\.id) ?? []
        XCTAssertEqual(connected.count, SourceCatalog.connectedCount(all))
        XCTAssertTrue(connected.contains(SourceCatalog.browserPrefix + "chrome"), "the reader's own page")
        XCTAssertFalse(connected.contains("youtube"), "it only borrows Chrome's reader")
        XCTAssertEqual(section("youtube", in: all), .category(.media))
        XCTAssertEqual(all.first { $0.id == "youtube" }?.status, .connected, "and keeps its green dot there")
        let line = SourceGrid.line(all.first { $0.id == "youtube" }!, now: Date())
        XCTAssertEqual(line?.tone, .on)
    }

    func testAReaderThatCannotReadWaitsOnThePersonAndTheTileAndThePageAgree() {
        let blocked = SourceCatalog.browserPrefix + "chrome"
        let bookmarks = chrome.bookmarksChannel!
        let all = rows(channels: [channel(bookmarks)], localReaders: [bookmarks: true],
                       watch: { $0 == bookmarks ? .blocked : nil })
        let row = all.first { $0.id == blocked }!
        XCTAssertEqual(row.section, .needsYou)
        XCTAssertEqual(row.word, Copy.Catalog.needsAccess)
        XCTAssertEqual(row.tone, .attention)
        XCTAssertEqual(row.help, Copy.sourceNeedsAccess)
        XCTAssertEqual(SourceCatalog.connectedCount(all), 0, "a blocked reader reads nothing")
        let page = SourcePageStatus.of(row: row.status, run: .problem(Copy.sourceNeedsAccess), latest: nil)
        XCTAssertEqual(page, .needsYou(Copy.SourcePage.allowAccess))
    }

    func testAPermissionTakenAwayReadsTheSameOnThePage() {
        let off = SourcePageStatus.of(row: .off, run: .idle, latest: nil, waitingOn: Copy.sourceNeedsAccess)
        XCTAssertEqual(off, .needsYou(Copy.SourcePage.allowAccess))
        XCTAssertEqual(SourcePageStatus.of(row: .off, run: .idle, latest: nil), .off(lastItem: nil))
    }

    func testAnAppThatIsGoneNeverWaitsOnThePerson() {
        let id = WhatsAppWatcher.channel
        let all = rows(waitingOn: [id: Copy.sourceNeedsAccess], suggested: [id], notInstalled: [id])
        let row = all.first { $0.id == id }!
        XCTAssertEqual(row.section, .category(.messaging), "not waiting, and not suggested either")
        XCTAssertEqual(SourceGrid.line(row, now: Date())?.word, Copy.SourcePage.notInstalledRow)
    }

    // MARK: A tile says one line, only when it says something

    func testAnOffTileSaysNothingAndAConnectedOneSaysWhenItLastRead() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let last = ISO8601DateFormatter().string(from: now.addingTimeInterval(-7_200))
        let all = rows(channels: [channel("reddit", lastSync: last), channel("github")])
        XCTAssertNil(SourceGrid.line(all.first { $0.id == "instagram" }!, now: now), "no dot is the word")
        let line = SourceGrid.line(all.first { $0.id == "reddit" }!, now: now, locale: Locale(identifier: "en_US"))
        XCTAssertEqual(line?.tone, .on)
        XCTAssertTrue(line?.word.contains("2") ?? false, "the age, not the section's word again: \(line?.word ?? "nil")")
        XCTAssertEqual(SourceGrid.line(all.first { $0.id == "github" }!, now: now)?.word, Copy.Catalog.connected,
                       "nothing read yet: the word, never a blank")
    }

    func testEveryWaitingWordFitsATile() {
        let longest = [Copy.Catalog.waitsForAgent, Copy.Catalog.needsAccess, Copy.Catalog.needsSignIn,
                       Copy.SourcePage.needsYou, Copy.SourcePage.notInstalledRow].map(\.count).max() ?? 0
        XCTAssertLessThanOrEqual(longest, 20, "\(SourceGrid.tileMinWidth) units hold 20 characters beside the mark")
    }

    // MARK: Search

    func testAWordFiltersAsItIsTypedNameFirst() {
        XCTAssertEqual(found("whats").first, WhatsAppWatcher.channel)
        XCTAssertEqual(found("x").first, "x", "one letter, its own whole name first")
        XCTAssertEqual(found("YOUTUBE"), ["youtube"], "case never matters")
        XCTAssertTrue(found("zzz-nothing").isEmpty)
    }

    func testACompanysAppsAreFoundOneByOneWhereverTheySit() {
        let google = found("google")
        XCTAssertEqual(Set(google), Set(["youtube", SourceCatalog.browserPrefix + "chrome", "chat-exports", "calendar"]))
        XCTAssertEqual(Set(SourceGrid.sections(rows()).flatMap(\.rows).filter { google.contains($0.id) }
            .map(\.entry.category)).count, 4, "Google is four kinds of thing, which is why it is no group")
        XCTAssertTrue(found("meta").contains("instagram"))
        XCTAssertTrue(found("meta").contains(WhatsAppWatcher.channel))
        XCTAssertTrue(found("apple").contains("notes"))
        XCTAssertTrue(found("twitter").contains("x"), "an old name")
        XCTAssertTrue(found("chatgpt").contains("chat-exports"))
        XCTAssertTrue(found("obsidian").contains("folders"), "a vault is a folder")
    }

    func testACategoryOrASectionFindsItsWholeGroup() {
        XCTAssertEqual(Set(found("messaging")), Set(["imessage", WhatsAppWatcher.channel, "telegram", TelegramChats.channel]))
        XCTAssertEqual(found("connected", in: rows(channels: [channel("reddit")])), ["reddit"])
    }

    func testSearchNeverLeavesTheApp() throws {
        let model = try String(contentsOf: Self.source("Models/SourceGrid.swift"), encoding: .utf8)
        for word in ["URLSession", "APIClient", "api.", "LLM", "fetch("] {
            XCTAssertFalse(model.contains(word), "search is words on this Mac: \(word)")
        }
    }

    func testEveryWordListNamesARealSource() {
        let every = SourceCatalog.entries(browsers: BrowserInventory.catalog, wisprPresent: true, hexPresent: true,
                                          overview: []).map(\.id)
        for id in SourceGrid.alsoKnownAs.keys {
            XCTAssertTrue(every.contains(id), "\(id) is on no tile")
        }
    }

    func testEveryWordsNeedNoRepeatOfTheName() {
        for row in rows(browsers: BrowserInventory.catalog) {
            for word in SourceGrid.alsoKnownAs[row.id] ?? [] {
                XCTAssertNotEqual(word.lowercased(), row.entry.title.lowercased(), row.id)
            }
        }
    }

    func testOnlySpacesAreNoSearch() {
        XCTAssertFalse(SourceGrid.isSearching("   "))
        XCTAssertFalse(SourceGrid.isSearching(""))
        XCTAssertTrue(SourceGrid.isSearching(" x "))
    }

    func testTheKeysWalkTheResultsAndStopAtEitherEnd() {
        let results = SourceGrid.results(rows(), query: "messaging")
        let ids = results.map(\.id)
        XCTAssertEqual(SourceGrid.highlighted(results, cursor: nil), ids[0], "⏎ opens the best result at once")
        XCTAssertEqual(SourceGrid.highlighted(results, cursor: "reddit"), ids[0], "a cursor the words dropped")
        XCTAssertEqual(SourceGrid.moved(1, in: results, cursor: nil), ids[1])
        XCTAssertEqual(SourceGrid.moved(-1, in: results, cursor: ids[0]), ids[0])
        XCTAssertEqual(SourceGrid.moved(1, in: results, cursor: ids.last), ids.last)
        XCTAssertNil(SourceGrid.moved(1, in: [], cursor: nil))
    }

    // MARK: Suggested

    func testOnlyAnAppThePersonChoseToInstallIsSuggestedAndNoIsNeverAgain() {
        let here: Set<String> = ["net.whatsapp.WhatsApp", "notion.id", "com.google.Chrome", "com.apple.Notes",
                                 "com.apple.Safari"]
        let suggested = SourceGrid.suggested(installed: { here.contains($0) }, declined: ["notion"])
        XCTAssertTrue(suggested.contains(WhatsAppWatcher.channel))
        XCTAssertTrue(suggested.contains(SourceCatalog.browserPrefix + "chrome"))
        XCTAssertFalse(suggested.contains("notion"), "the person said No on the notch")
        XCTAssertFalse(suggested.contains("notes"), "every Mac has it: no signal")
        XCTAssertFalse(suggested.contains(SourceCatalog.browserPrefix + "safari"))
    }

    func testWhatIsSuggestedIsWhatTheCatalogueCanOpen() {
        let every = SourceCatalog.entries(browsers: BrowserInventory.catalog.filter(\.supported), wisprPresent: true,
                                          hexPresent: true, overview: []).map(\.id)
        for id in SourceGrid.suggestableApps().values { XCTAssertTrue(every.contains(id), id) }
    }

    func testWisprIsNotSuggestedWhileItIsOffTheOffer() {
        XCTAssertFalse(SourceGrid.suggestableApps().values.contains(SourceCatalog.wisprChannel))
    }

    func testAConnectedSourceIsNeverSuggested() {
        let all = rows(channels: [channel("reddit")], suggested: ["reddit"])
        XCTAssertEqual(section("reddit", in: all), .connected)
    }

    // MARK: The hand-offs reach every source, whatever was typed

    func testTheFieldNeverNarrowsTheCatalogueThePageOpensFrom() throws {
        let page = try String(contentsOf: Self.source("Views/Sources/SourcesPageView.swift"), encoding: .utf8)
        // `gridSearch` reaches the grid and is reset on a hand-off; it never filters `catalog`, which the detail column,
        // the side list and every hand-off (`openPendingSource`, `openPendingEntry`, `consumeAddSource`) resolve in.
        XCTAssertFalse(page.contains("SourceGrid.results"), "only the grid filters")
        XCTAssertEqual(page.components(separatedBy: " gridSearch = SourceGridSearch()").count - 2, 4,
                       "the sidebar's re-click and the three hand-offs each clear the words")
    }

    @MainActor func testAPaletteHandOffStillStagesItsSource() {
        let router = AppRouter()
        router.routeToSourceDetail("imessage")
        XCTAssertEqual(router.pendingTab, .sources)
        XCTAssertEqual(router.consumeSourceDetail(), "imessage")
    }

    // MARK: Keyboard never animates; durations stay in CicadaMotion

    func testTheKeysPathNeverAnimatesAndTheViewSpellsNoDuration() throws {
        let page = try String(contentsOf: Self.source("Views/Sources/SourcesPageView.swift"), encoding: .utf8)
        let byKey = try XCTUnwrap(page.range(of: "private func openByKey"))
        let body = page[byKey.lowerBound...].prefix(240)
        XCTAssertTrue(body.contains("Instant.run"), "DR-60")
        XCTAssertFalse(body.contains("withAnimation"), "DR-60")
        let view = try String(contentsOf: Self.source("Views/Sources/SourceGridView.swift"), encoding: .utf8)
        XCTAssertFalse(view.contains("withAnimation"))
        XCTAssertFalse(view.contains(".animation("), "DR-61: the hover's own ease lives in `rowHover`")
    }

    // MARK: Render

    /// The tiles at the widths a window can take: nothing but the column count changes, in both looks (DR-71).
    @MainActor func testTheGridDrawsInBothLooksAtEveryWidth() throws {
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let now = Date()
        let all = rows(channels: [channel("reddit"), channel("github", error: "401 token expired")],
                       savedLists: ["x"], suggested: [WhatsAppWatcher.channel])
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            for width in [320.0, 700.0, 1200.0] {
                let view = VStack(alignment: .leading, spacing: 0) {
                    SourceGridView(rows: all, search: SourceGridSearch(), open: { _ in }, importFiles: {})
                    SourceAppTile(row: all[0], highlighted: true, now: now, open: {})
                }
                .frame(width: width)
                .background(CicadaTheme.bgBase)
                .environment(store)
                let renderer = ImageRenderer(content: view)
                XCTAssertNotNil(renderer.nsImage, "\(mode) at \(width)")
            }
        }
    }

    private static func source(_ path: String) -> URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp").appendingPathComponent(path)
    }
}
