import XCTest
@testable import CicadaApp

/// ROR-118 — the Sources page's six kinds, its add overlay's groups and the website-reading card's scene, all pure.
final class SourceShelfTests: XCTestCase {
    private func rows(channels: [SourceChannel] = [], savedLists: Set<String> = []) -> [SourceCatalogRow] {
        let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, overview: [])
        return SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [],
                                  savedListsOn: savedLists, localAgent: true)
    }

    private func channel(_ id: String) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: true, lastSync: nil, lastError: nil)
    }

    func testEveryCatalogueEntryHasOneKindAndNoVendorMakesAKind() {
        let all = rows()
        XCTAssertEqual(Set(all.map(\.entry.shelf)), Set(SourceShelf.allCases), "all six kinds hold something")
        XCTAssertEqual(SourceShelf.of(all.first { $0.id == "notes" }!.entry), .documents)
        XCTAssertEqual(SourceShelf.of(all.first { $0.id == "notion" }!.entry), .documents, "Notes and Notion together")
        XCTAssertEqual(SourceShelf.of(all.first { $0.id == "calendar-local" }!.entry), .events)
        XCTAssertEqual(SourceShelf.of(all.first { $0.id == "calendar" }!.entry), .events, "Apple's and Google's together")
        XCTAssertEqual(SourceShelf.of(all.first { $0.id == "github" }!.entry), .work)
        XCTAssertEqual(SourceShelf.of(all.first { $0.id == "x" }!.entry), .saved)
        XCTAssertEqual(SourceShelf.of(all.first { $0.id == "youtube" }!.entry), .media)
        XCTAssertEqual(SourceShelf.of(all.first { $0.id == "imessage" }!.entry), .conversations)
    }

    func testAShelfListsWhatIsConnectedAndWhatCouldStillBeAdded() {
        let all = rows(channels: [channel("reddit")])
        let saved = SourceShelves.shelves(all).first { $0.shelf == .saved }!
        XCTAssertEqual(saved.connected.map(\.id), ["reddit"])
        XCTAssertFalse(saved.addable.contains { $0.id == "reddit" }, "added already")
        XCTAssertTrue(saved.addable.contains { $0.id == "instagram" })
        XCTAssertEqual(SourceShelves.yours(all).map(\.id), ["reddit"])
    }

    func testTheOverlayNarrowsByKindAndByWordsAndNeverRepeatsYours() {
        let all = rows(channels: [channel("reddit")])
        let everything = SourceShelves.addGroups(all, shelf: nil, query: "")
        XCTAssertEqual(everything.map(\.shelf), SourceShelf.allCases)
        XCTAssertFalse(everything.flatMap(\.addable).contains { $0.id == "reddit" })
        XCTAssertEqual(SourceShelves.addGroups(all, shelf: .work, query: "").map(\.shelf), [.work])
        let found = SourceShelves.addGroups(all, shelf: nil, query: "notion").flatMap(\.addable).map(\.id)
        XCTAssertEqual(found.first, "notion")
    }

    func testEveryKindHoldsOnePlaceAndAnEmptyOneStillShowsWhatItTakes() {
        let all = rows(channels: [channel("reddit"), channel("github")])
        let shown = SourceShelfLayout.shown(SourceShelves.shelves(all))
        XCTAssertEqual(shown.map(\.shelf), SourceShelf.allCases, "one fixed order: a kind never moves when a source joins it")
        let documents = shown.first { $0.shelf == .documents }!
        XCTAssertTrue(documents.connected.isEmpty)
        XCTAssertTrue(documents.addable.contains { $0.id == "notes" }, "Apple Notes is findable by name")
        let events = shown.first { $0.shelf == .events }!
        XCTAssertTrue(events.addable.contains { $0.id == "calendar-local" }, "so is the Mac's Calendar")
        XCTAssertEqual(Copy.Shelf.calendarNote, "Includes Google")
    }

    func testTheCountInTheTitleIsTheYoursStripAndTheRowsOnThePage() {
        let all = rows(channels: [channel("reddit"), channel("github")])
        let onPage = SourceShelves.shelves(all).flatMap(\.connected).map(\.id)
        XCTAssertEqual(SourceCatalog.connectedCount(all), onPage.count, "every connected source is a row somewhere")
        XCTAssertEqual(SourceShelves.yours(all).map(\.id), onPage, "and Yours lists the same ones")
        XCTAssertTrue(onPage.contains("reddit") && onPage.contains("github"))
    }

    func testOnlyASourceThatReadsThroughAnAccountOrKeyCarriesAnHonestLineAndItIsReadOnly() {
        for id in ["notion", "linear", "github", TelegramChats.channel] {
            XCTAssertNotNil(WebReadingScene.honestLine(id), id)
        }
        for id in ["notes", "files", "folders", "spotify", "imessage", "x"] {
            XCTAssertNil(WebReadingScene.honestLine(id), id)
        }
        XCTAssertTrue(Copy.Honest.notion.hasPrefix("Read-only"))
        XCTAssertTrue(Copy.Honest.telegram.contains("one-to-one chats you tick"))
    }

    func testTheWeekStartsOnMondayAndHoldsToday() {
        let today = ISODay(year: 2026, month: 11, day: 6)   // a Friday
        let week = SourceWeekStrip.week(containing: today)
        XCTAssertEqual(week.count, 7)
        XCTAssertEqual(week[0].description, "2026-11-02")
        XCTAssertEqual(week[4], today)
        let items = [ChannelItem(kind: .page, id: "a", title: "A", day: "2026-11-03"),
                     ChannelItem(kind: .page, id: "b", title: "B", day: "2026-11-20")]
        XCTAssertEqual(SourceWeekStrip.busy(items, in: week), [ISODay(year: 2026, month: 11, day: 3)])
        XCTAssertEqual(SourceWeekStrip.upcoming(items, today: today, limit: 1).map(\.id), ["b"])
    }

    // MARK: The website-reading card

    func testOnlySourcesAnAgentReadsInTheBrowserGetTheCard() {
        let all = rows()
        for id in ["x", "instagram", "linkedin", "reddit", "pinterest", "tiktok", "youtube", SourceCatalog.substackId] {
            XCTAssertTrue(WebReadingScene.applies(all.first { $0.id == id }!.entry), id)
        }
        for id in ["notes", "github", "spotify", "imessage"] {
            XCTAssertFalse(WebReadingScene.applies(all.first { $0.id == id }!.entry), id)
        }
    }

    func testThePersonsOwnLocalAppStandsInTheScene() {
        XCTAssertNil(WebReadingScene.app(rows: []))
        XCTAssertNil(WebReadingScene.app(rows: [AgentLiveRow(id: "chatgpt", connected: true, via: "remote")]),
                     "a remote connection cannot read a list in this Mac's browser")
        XCTAssertEqual(WebReadingScene.app(rows: [AgentLiveRow(id: "codex", connected: true, via: "config"),
                                                  AgentLiveRow(id: "claude-code", connected: true, via: "mcp")])?.id,
                       "claude-code", "the Agents page's order")
    }

    func testTheSceneNeverPlaysTwiceByItselfNorWithNothingToPlayItFor() {
        XCTAssertTrue(WebReadingScene.autoplays(seen: false, hasApp: true, reduceMotion: false))
        XCTAssertFalse(WebReadingScene.autoplays(seen: true, hasApp: true, reduceMotion: false), "Replay is the way back")
        XCTAssertFalse(WebReadingScene.autoplays(seen: false, hasApp: false, reduceMotion: false))
        XCTAssertFalse(WebReadingScene.autoplays(seen: false, hasApp: true, reduceMotion: true), "Reduce Motion")
        XCTAssertEqual(WebReadingScene.litNodes(atBeat: -1), 1)
        XCTAssertEqual(WebReadingScene.litNodes(atBeat: 4), 4)
    }

    func testTheCardSaysItInPlainStepsWithNoWordThePersonHasToKnow() throws {
        let entry = rows().first { $0.id == "x" }!.entry
        let steps = WebReadingScene.steps(entry: entry, app: "Claude Code", browser: "Chrome")
        XCTAssertEqual(steps.count, 4)
        XCTAssertTrue(steps[1].contains("Next time you use Claude Code"), "when it happens")
        XCTAssertTrue(steps[1].contains("At most once a day"), "G206's 20-hour offer")
        XCTAssertTrue(steps[2].contains("where you are already signed in"), "whose session")
        XCTAssertTrue(steps[2].contains("only at your Bookmarks"), "what is read")
        XCTAssertTrue(steps[3].contains("link and words"), "the post's words are kept too (mcp.md)")
        XCTAssertTrue(steps[3].contains("posted or changed"))
        let headline = Copy.WebReading.headline(site: "X", app: "Claude Code", list: "your Bookmarks")
        let all = (steps + [headline, Copy.WebReading.headlineNoAI, Copy.WebReading.roleAI, Copy.WebReading.whoseSession,
                            Copy.WebReading.whoSees(app: "Claude Code"), Copy.WebReading.oneClick]).joined(separator: " ")
        for word in ["assistant app", "agent", "AI app", "switch"] {
            XCTAssertFalse(all.localizedCaseInsensitiveContains(word), word)
        }
        XCTAssertTrue(Copy.WebReading.whoseSession.contains("never sees your password"))
        XCTAssertTrue(Copy.WebReading.whoSees(app: "Claude Code").contains("company sees what it reads"))
        XCTAssertTrue(Copy.WebReading.oneClick.contains(Copy.SourceLayout.readInBrowser), "names the control that is there")
        let view = try String(contentsOf: Self.source("Views/Sources/WebReadingCard.swift"), encoding: .utf8)
        XCTAssertFalse(view.contains("duration:"), "no duration is spelled in the view")
        XCTAssertFalse(view.contains(".seconds(0") || view.contains(".seconds(1"), "nor a sleep")
    }

    func testTheStepLitFollowsTheBeatAndASiteReadThroughAnAIIsNotReadingYetRatherThanOff() {
        XCTAssertEqual((-1...4).map(WebReadingScene.step(atBeat:)), [0, 0, 1, 2, 2, 3])
        XCTAssertEqual(WebReadingScene.laneGlyphs.count, 3, "one thing travels each lane")
        XCTAssertEqual(SourcePageStatus.of(row: .off, run: .idle, latest: nil, readsThroughAI: true).word, "Not reading yet")
        XCTAssertEqual(SourcePageStatus.of(row: .off, run: .idle, latest: nil).word, "Off", "every other source keeps its word")
        XCTAssertEqual(SourcePageStatus.of(row: .connected, run: .idle, latest: nil, readsThroughAI: true).word, "Connected")
    }

    static func source(_ path: String) -> URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp").appendingPathComponent(path)
    }
}
