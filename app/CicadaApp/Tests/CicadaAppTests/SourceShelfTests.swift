import XCTest
@testable import CicadaApp

/// ROR-118 — the Sources page's six kinds (the root's tabs, G245) and the website-reading card's scene, all pure. The
/// shelves' grids, the add overlay and the week strip left with the card root (ruling 78).
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

    func testAKindListsWhatIsConnectedAndWhatCouldStillBeAdded() {
        let all = rows(channels: [channel("reddit")])
        let saved = SourceShelves.shelves(all).first { $0.shelf == .saved }!
        XCTAssertEqual(saved.connected.map(\.id), ["reddit"])
        XCTAssertFalse(saved.addable.contains { $0.id == "reddit" }, "connected already")
        XCTAssertTrue(saved.addable.contains { $0.id == "instagram" })
    }

    func testEveryKindHoldsOnePlaceAndAnEmptyOneStillHoldsWhatItTakes() {
        let all = rows(channels: [channel("reddit"), channel("github")])
        let shelves = SourceShelves.shelves(all)
        XCTAssertEqual(shelves.map(\.shelf), SourceShelf.allCases, "one fixed order: a kind never moves when a source joins it")
        let documents = shelves.first { $0.shelf == .documents }!
        XCTAssertTrue(documents.connected.isEmpty)
        XCTAssertTrue(documents.addable.contains { $0.id == "notes" }, "Apple Notes is findable by name")
        let events = shelves.first { $0.shelf == .events }!
        XCTAssertTrue(events.addable.contains { $0.id == "calendar-local" }, "so is the Mac's Calendar")
    }

    func testTheCountInTheTitleIsTheConnectedSourcesOfTheKinds() {
        let all = rows(channels: [channel("reddit"), channel("github")])
        let onPage = SourceShelves.shelves(all).flatMap(\.connected).map(\.id)
        XCTAssertEqual(SourceCatalog.connectedCount(all), onPage.count, "every connected source is in some kind")
        XCTAssertTrue(onPage.contains("reddit") && onPage.contains("github"))
    }

    func testOnlyASourceThatReadsThroughAnAccountOrKeyCarriesAnHonestLineAndItIsReadOnly() {
        for id in ["notion", "linear", "github", TelegramChats.channel] {
            XCTAssertNotNil(SourceHeadLine.honestLine(id), id)
        }
        for id in ["notes", "files", "folders", "spotify", "imessage", "x"] {
            XCTAssertNil(SourceHeadLine.honestLine(id), id)
        }
        XCTAssertTrue(Copy.Honest.notion.hasPrefix("Read-only"))
        XCTAssertTrue(Copy.Honest.telegram.contains("one-to-one chats you tick"))
    }

    // MARK: A source read through the person's own agent

    func testOnlySourcesAnAgentReadsInTheBrowserReadThroughTheAI() {
        let all = rows()
        for id in ["x", "instagram", "linkedin", "reddit", "pinterest", "tiktok", "spotify", "youtube",
                   SourceCatalog.substackId] {
            XCTAssertTrue(SourceHeadLine.readsThroughAI(all.first { $0.id == id }!.entry), id)
        }
        for id in ["notes", "github", "imessage"] {
            XCTAssertFalse(SourceHeadLine.readsThroughAI(all.first { $0.id == id }!.entry), id)
        }
    }

    func testThePersonsOwnLocalAppIsTheOneTheHeadNames() {
        XCTAssertNil(SourceHeadLine.app(rows: []))
        XCTAssertNil(SourceHeadLine.app(rows: [AgentLiveRow(id: "chatgpt", connected: true, via: "remote")]),
                     "a remote connection cannot read a list in this Mac's browser")
        XCTAssertEqual(SourceHeadLine.app(rows: [AgentLiveRow(id: "codex", connected: true, via: "config"),
                                                 AgentLiveRow(id: "claude-code", connected: true, via: "mcp")])?.id,
                       "claude-code", "the Agents page's order")
    }

    func testASiteReadThroughAnAIIsNotReadingYetRatherThanOff() {
        XCTAssertEqual(SourcePageStatus.of(row: .off, run: .idle, latest: nil, readsThroughAI: true).word, "Not reading yet")
        XCTAssertEqual(SourcePageStatus.of(row: .off, run: .idle, latest: nil).word, "Off", "every other source keeps its word")
        XCTAssertEqual(SourcePageStatus.of(row: .connected, run: .idle, latest: nil, readsThroughAI: true).word, "Connected")
    }

    func testTheDrawnDiagramIsGone() throws {
        for path in ["Views/Sources/WebReadingCard.swift", "Models/WebReadingScene.swift"] {
            XCTAssertFalse(FileManager.default.fileExists(atPath: Self.source(path).path), "\(path) is gone (ruling 78)")
        }
    }

    static func source(_ path: String) -> URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp").appendingPathComponent(path)
    }
}
