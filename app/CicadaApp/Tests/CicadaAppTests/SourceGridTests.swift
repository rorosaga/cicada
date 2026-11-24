import SwiftUI
import XCTest
@testable import CicadaApp

/// ROR-7 (G217, G161), carried into G245 — what a source's row says (sections, one line, the words it is also found by),
/// a find that needs no network and no model, a company's apps found one by one and never folded together. The cards,
/// their order and the keys are `SourcesRootTests`; this file pins the catalogue's own sections the narrow rows still
/// read, and the page's rails.
final class SourceGridTests: XCTestCase {
    private let chrome = BrowserInventory.catalog.first { $0.id == "chrome" }!
    private let safari = BrowserInventory.catalog.first { $0.id == "safari" }!

    private func rows(channels: [SourceChannel] = [], localReaders: [String: Bool] = [:],
                      savedLists: Set<String> = [], waitingOn: [String: String] = [:], suggested: Set<String> = [],
                      notInstalled: Set<String> = [], browsers: [BrowserSpec]? = nil,
                      watch: @escaping (String) -> BrowserWatchState? = { _ in nil }) -> [SourceCatalogRow] {
        let entries = SourceCatalog.entries(browsers: browsers ?? [chrome, safari], wisprPresent: false, hexPresent: true,
                                            overview: [], channels: channels)
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

    /// What the root's find shows for these words: the cards of the whole catalogue, ranked by the one matcher.
    private func found(_ query: String, in rows: [SourceCatalogRow]? = nil) -> [String] {
        let cards = SourcesRoot.cards(rows: rows ?? self.rows(), streams: ResolvedStreams())
        return SourcesRoot.visible(cards, tab: nil, query: query).map(\.id)
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
        XCTAssertEqual(sections.first, .needsYou)
        XCTAssertEqual(Array(sections.dropFirst()), SourceShelf.allCases.map(SourceGridSection.shelf))
        XCTAssertEqual(section("github", in: all), .needsYou, "a lapsed sign-in")
        XCTAssertEqual(section("calendar-local", in: all), .needsYou, "a permission taken away")
        XCTAssertEqual(section("reddit", in: all), .shelf(.saved), "by what it is, never by who makes it")
        XCTAssertEqual(section(WhatsAppWatcher.channel, in: all), .shelf(.conversations))
        XCTAssertEqual(section("instagram", in: all), .shelf(.saved))
    }

    func testAListWaitingForAnAgentIsWaitingOnThePersonAndNotCounted() {
        let all = rows(savedLists: ["x"])
        XCTAssertEqual(all.first { $0.id == "x" }?.status, .waitingForAgent)
        XCTAssertEqual(section("x", in: all), .needsYou)
        XCTAssertEqual(SourceCatalog.connectedCount(all), 0)
        XCTAssertEqual(SourceCatalog.onCount(all), 1, "but it is on: the header says so, the card says it waits")
        XCTAssertEqual(Copy.Catalog.eyebrow(SourceCatalog.onCount(all)), "1 on")
    }

    /// Seen live (2026-11-24): the notch's Yes turned X on, its card read "On · waits for your agent" and the header
    /// read "0 connected". One list on, nothing read: the header counts it.
    func testTheHeaderCountsASourceTheMomentItIsTurnedOn() {
        let off = rows()
        XCTAssertEqual(SourceCatalog.onCount(off), 0)
        let waiting = rows(savedLists: ["x"])
        XCTAssertEqual(SourceCatalog.onCount(waiting), 1)
        XCTAssertEqual(waiting.first { $0.id == "x" }?.word, Copy.Catalog.waitingForAgent, "its own card says it waits")
    }

    /// #619 — the Connected section and the eyebrow can never disagree, however many rows read one reader.
    func testTheConnectedSectionHoldsExactlyWhatTheEyebrowCounts() {
        let all = rows(channels: [channel(WatchHistoryWatcher.channel), channel("reddit")],
                       localReaders: [WatchHistoryWatcher.channel: true])
        let connected = SourceShelves.shelves(all).flatMap(\.connected).map(\.id)
        XCTAssertEqual(connected.count, SourceCatalog.connectedCount(all))
        XCTAssertTrue(connected.contains(SourceCatalog.browserPrefix + "chrome"), "the reader's own page")
        XCTAssertFalse(connected.contains("youtube"), "it only borrows Chrome's reader")
        XCTAssertEqual(section("youtube", in: all), .shelf(.media))
        XCTAssertEqual(all.first { $0.id == "youtube" }?.status, .connected, "and keeps its green dot there")
        let line = SourceGrid.line(all.first { $0.id == "youtube" }!, now: Date())
        XCTAssertEqual(line?.tone, .on)
    }

    /// ROR-118: a kind's heading no longer says Connected, so a connected card says when it read, or says Connected.
    func testAConnectedCardSaysItIsConnectedWhenItHasNotReadYet() throws {
        let all = rows(channels: [channel("reddit")])
        let row = try XCTUnwrap(all.first { $0.id == "reddit" })
        XCTAssertEqual(row.section, .shelf(.saved))
        XCTAssertEqual(SourceGrid.line(row, now: Date())?.word, row.status.word)
    }

    func testAMarkBelongsToItsSourceAndNoCompanyWearsAShelf() throws {
        let notion = try XCTUnwrap(rows().first { $0.id == "notion" })
        XCTAssertEqual(OriginIconography.logoName(for: notion.entry.origin), "notion")
        let exports = try XCTUnwrap(rows().first { $0.id == "chat-exports" })
        XCTAssertNil(OriginIconography.logoName(for: exports.entry.origin), "it takes every assistant's export")
    }

    /// Seen in the app: Return commits the field's own words first, which sent ⏎ to the best result, not the arrowed card.
    func testReturnKeepsTheCardTheArrowsMovedTo() {
        var state = SourcesRoot.State(text: "google", cursor: "calendar")
        state.typed("google")
        XCTAssertEqual(state.cursor, "calendar")
        state.typed("googl")
        XCTAssertNil(state.cursor, "new words start at the best result")
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
        XCTAssertEqual(SourceCatalog.onCount(all), 1, "though the person has it on")
        let page = SourcePageStatus.of(row: row.status, run: .problem(Copy.sourceNeedsAccess), latest: nil)
        XCTAssertEqual(page, .needsYou(Copy.SourcePage.allowAccess))
    }

    func testAPermissionTakenAwayReadsTheSameOnThePage() {
        let off = SourcePageStatus.of(row: .off, run: .idle, latest: nil, waitingOn: Copy.sourceNeedsAccess)
        XCTAssertEqual(off, .needsYou(Copy.SourcePage.allowAccess))
        XCTAssertEqual(SourcePageStatus.of(row: .off, run: .idle, latest: nil), .off(lastItem: nil))
    }

    func testAConnectedReaderMacOSRefusedReadsTheSameOnTheTileAndThePage() {
        let id = AppleBooksReader.channel
        let row = rows(localReaders: [id: true], waitingOn: [id: Copy.sourceNeedsAccess]).first { $0.id == id }!
        XCTAssertEqual(row.status, .connected, "the switch stays on while macOS refuses the read")
        XCTAssertEqual(row.word, Copy.Catalog.needsAccess)
        let page = SourcePageStatus.of(row: row.status, run: .idle, latest: "Oct 28", waitingOn: row.waitingOn)
        XCTAssertEqual(page, .needsYou(Copy.SourcePage.allowAccess))
        XCTAssertEqual(SourcePageStatus.of(row: .connected, run: .idle, latest: "Oct 28", waitingOn: "Sign in again"),
                       .needsYou("Sign in again"), "any reason, in its own words")
        XCTAssertEqual(SourcePageStatus.of(row: .connected, run: .idle, latest: "Oct 28"),
                       .connected(lastItem: "Oct 28"), "nothing waiting: still Connected")
    }

    func testAnAppThatIsGoneNeverWaitsOnThePerson() {
        let id = WhatsAppWatcher.channel
        let all = rows(waitingOn: [id: Copy.sourceNeedsAccess], suggested: [id], notInstalled: [id])
        let row = all.first { $0.id == id }!
        XCTAssertEqual(row.section, .shelf(.conversations), "not waiting, and not suggested either")
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

    // MARK: Search

    func testAWordFiltersAsItIsTypedNameFirst() {
        XCTAssertEqual(found("whats").first, WhatsAppWatcher.channel)
        XCTAssertEqual(found("x").first, "x", "one letter, its own whole name first")
        XCTAssertEqual(found("YOUTUBE"), ["youtube"], "case never matters")
        XCTAssertTrue(found("zzz-nothing").isEmpty)
    }

    func testACompanysAppsAreFoundOneByOneWhereverTheySit() {
        let google = found("google")
        // Chat exports are not offered until they hold something (plan 3.1), so they are not among the cards found here.
        XCTAssertEqual(Set(google), Set(["youtube", SourceCatalog.browserPrefix + "chrome", "calendar",
                                         GoogleBooksKeyModel.id]))
        XCTAssertEqual(Set(SourceGrid.sections(rows()).flatMap(\.rows).filter { google.contains($0.id) }
            .map(\.entry.category)).count, 4, "Google is four kinds of thing, which is why it is no group")
        XCTAssertTrue(found("meta").contains("instagram"))
        XCTAssertTrue(found("meta").contains(WhatsAppWatcher.channel))
        XCTAssertTrue(found("apple").contains("notes"))
        XCTAssertTrue(found("twitter").contains("x"), "an old name")
        let held = rows(channels: [SourceChannel(id: "chat-export:claude", label: "Claude", connected: true, count: 4,
                                                 lastSync: nil, lastError: nil)])
        XCTAssertTrue(found("chatgpt", in: held).contains("chat-exports"), "once it holds something")
        XCTAssertFalse(found("chatgpt").contains("chat-exports"), "and never offered before")
        XCTAssertTrue(found("obsidian").contains("folders"), "a vault is a folder")
    }

    func testACategoryOrASectionFindsItsWholeGroup() {
        // Owner 2026-11-05: the Telegram bot's tile (a token in a file) shows only for a bot already set up.
        XCTAssertEqual(Set(found("messaging")), Set(["imessage", WhatsAppWatcher.channel, TelegramChats.channel]))
        XCTAssertEqual(Set(found("messaging", in: rows(channels: [channel("telegram")]))),
                       Set(["imessage", WhatsAppWatcher.channel, "telegram", TelegramChats.channel]))
        XCTAssertTrue(found("conversations").contains("imessage"), "a kind is found by its own word")
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
        // The bot's tile shows only once one is set up (ROR-113); its words still find it then.
        for id in SourceGrid.alsoKnownAs.keys where id != "telegram" {
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
        XCTAssertEqual(section("reddit", in: all), .shelf(.saved))
        XCTAssertTrue(all.first { $0.id == "reddit" }!.isConnectedHere)
    }

    // MARK: The hand-offs reach every source, whatever was typed

    func testTheFieldNeverNarrowsTheCatalogueThePageOpensFrom() throws {
        let page = try String(contentsOf: Self.source("Views/Sources/SourcesPageView.swift"), encoding: .utf8)
        // `rootState` reaches the root and is reset on a hand-off; it never filters `catalog`, which the detail column,
        // the side list and every hand-off (`openPendingSource`, `openPendingEntry`) resolve in.
        XCTAssertFalse(page.contains("SourcesRoot.visible"), "only the root's list filters")
        XCTAssertEqual(page.components(separatedBy: " rootState.clearFind()").count - 1, 3,
                       "the sidebar's re-click and the two hand-offs each clear the words")
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
        for file in ["Views/Sources/SourcesRootView.swift", "Views/Sources/SourcesColumns.swift"] {
            let view = try String(contentsOf: Self.source(file), encoding: .utf8)
            XCTAssertFalse(view.contains("withAnimation"), file)
            XCTAssertFalse(view.contains(".animation("), "DR-61: the hover's own ease lives in `softCardRow`: \(file)")
            XCTAssertFalse(view.contains("duration:"), "DR-61: every duration is spelled in CicadaMotion: \(file)")
        }
        let columns = try String(contentsOf: Self.source("Views/Sources/SourcesColumns.swift"), encoding: .utf8)
        XCTAssertTrue(columns.contains("listKeys("), "DR-68: the root's keys are the list pages' keys")
    }

    // MARK: Render

    /// The root's cards at the widths a window can take, in both looks (DR-71): they draw, whatever the width. The
    /// pictures of the states are `SourcesRootRenderTests`.
    @MainActor func testTheCardsDrawInBothLooksAtEveryWidth() throws {
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        let all = rows(channels: [channel("reddit"), channel("github", error: "401 token expired")],
                       savedLists: ["x"], suggested: [WhatsAppWatcher.channel])
        let cards = SourcesRoot.cards(rows: all, streams: ResolvedStreams())
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            for width in [320.0, 700.0, 1200.0] {
                let view = SourcesRootList(cards: cards, state: .constant(SourcesRoot.State()), now: Date(),
                                           open: { _ in }, openByKey: { _ in }, act: { _ in })
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
