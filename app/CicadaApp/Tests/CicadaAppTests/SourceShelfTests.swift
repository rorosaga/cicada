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
        XCTAssertLessThanOrEqual(saved.addNames.count, 2, "one line: two names")
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

    func testTwoColumnsAreDealtToTheShorterOneAndKeepEveryShelfOnce() {
        let all = rows(channels: [channel("reddit"), channel("github")])
        let shelves = SourceShelves.shelves(all)
        let split = SourceShelfLayout.columns(shelves)
        XCTAssertEqual((split.left + split.right).map(\.shelf).sorted { $0.rawValue < $1.rawValue },
                       SourceShelf.allCases.sorted { $0.rawValue < $1.rawValue })
        let heights = [split.left, split.right].map { $0.reduce(0) { $0 + SourceShelfLayout.weight($1) } }
        XCTAssertLessThanOrEqual(abs(heights[0] - heights[1]), 8)
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

    func testTheCardCarriesTheHonestLinesAndItsDurationsAreSpelledInCicadaMotion() throws {
        let lines = [Copy.WebReading.whatIsRead(list: "your Bookmarks"), Copy.WebReading.whoseSession,
                     Copy.WebReading.whoSees(app: "an app"), Copy.WebReading.oneClick]
        XCTAssertTrue(lines[0].contains("10 times a day"), "G206's bound")
        XCTAssertTrue(lines[1].contains("never sees a password"))
        XCTAssertTrue(lines[2].contains("company sees what it reads"))
        let view = try String(contentsOf: Self.source("Views/Sources/WebReadingCard.swift"), encoding: .utf8)
        XCTAssertFalse(view.contains("duration:"), "no duration is spelled in the view")
        XCTAssertFalse(view.contains(".seconds(0") || view.contains(".seconds(1"), "nor a sleep")
    }

    static func source(_ path: String) -> URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp").appendingPathComponent(path)
    }
}
