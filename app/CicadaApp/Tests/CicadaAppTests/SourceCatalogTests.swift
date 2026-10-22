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

    func testSignInWordsAreReadFromTheFailure() {
        XCTAssertTrue(SourceCatalog.readsAsSignIn("401 Unauthorized"))
        XCTAssertFalse(SourceCatalog.readsAsSignIn("Timed out"))
        XCTAssertFalse(SourceCatalog.readsAsSignIn(nil))
    }
}
