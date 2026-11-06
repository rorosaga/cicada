import XCTest
@testable import CicadaApp

/// ROR-114 (G206, G228, G232) — a source the person's own agent reads in their browser: a switch for each of the six
/// saved lists, its own colour and words beside a connection's green, "Signed out" when the last attempt met a login
/// wall, and whose list it is (handle and profile link) on the source's page.
final class BrowserSourcesTests: XCTestCase {
    private let six = ["x", "instagram", "linkedin", "reddit", "pinterest", "tiktok"]
    private let entries = SourceCatalog.entries(browsers: [], wisprPresent: false, overview: [])

    private func rows(on: Set<String>, agent: Bool = true, channels: [SourceChannel] = [],
                      overview: [SourceOverview] = [], reads: [String: BrowserRead] = [:]) -> [SourceCatalogRow] {
        SourceCatalog.rows(entries: entries, channels: channels, overview: overview, readableSites: [],
                           savedListsOn: on, localAgent: agent, browserReads: reads)
    }

    private func row(_ id: String, _ all: [SourceCatalogRow]) throws -> SourceCatalogRow {
        try XCTUnwrap(all.first { $0.id == id }, id)
    }

    // MARK: The six switches

    func testEachOfTheSixSavedListsHasAKeyAndPinterestNeedsNoWalledSite() throws {
        XCTAssertEqual(SourceCatalog.savedListSites, Set(six + ["spotify", "goodreads"]))   // ROR-128 added the last two
        for id in six {
            let entry = try XCTUnwrap(entries.first { $0.id == id })
            XCTAssertEqual(entry.savedListKey, id, id)
        }
        let pinterest = try XCTUnwrap(entries.first { $0.id == "pinterest" })
        XCTAssertNil(pinterest.site, "no walled site: the switch must not depend on one")
        XCTAssertNil(entries.first { $0.id == "github" }?.savedListKey)
        XCTAssertEqual(entries.first { $0.id == SourceCatalog.substackId }?.browserKey, SourceCatalog.substackId)
    }

    func testEverySavedListOnWaitsForAnAgentThenReadsThroughTheBrowser() throws {
        for id in six {
            XCTAssertEqual(try row(id, rows(on: [id], agent: false)).status, .waitingForAgent, id)
            let on = try row(id, rows(on: [id]))
            XCTAssertEqual(on.status, .connected, id)
            XCTAssertEqual(on.browser?.state, .notReadYet, "\(id): on, and no agent has tried the page")
        }
    }

    func testAnImportNoLongerPaintsABrowserSourceGreen() throws {
        let imported = [SourceOverview(id: "instagram", label: "Instagram", kind: .social, episodes: 40)]
        let imageOnly = try row("instagram", rows(on: [], overview: imported))
        XCTAssertEqual(imageOnly.status, .connected, "an import alone is still a connection")
        XCTAssertNil(imageOnly.browser)
        let both = try row("instagram", rows(on: ["instagram"], overview: imported))
        XCTAssertEqual(both.browser?.state, .notReadYet, "the list is read through the browser, whatever came in")
        XCTAssertEqual(both.word, Copy.Browser.notReadYet)
    }

    func testARealConnectionStaysGreenAndNeverClaimsToBeABrowserRead() throws {
        let connected = [SourceChannel(id: "reddit", label: "Reddit", connected: true)]
        let reddit = try row("reddit", rows(on: ["reddit"], channels: connected))
        XCTAssertEqual(reddit.status, .connected)
        XCTAssertNil(reddit.browser)
        XCTAssertEqual(reddit.tone, .on)
        XCTAssertEqual(reddit.word, Copy.Catalog.connected)
    }

    // MARK: The words and colours

    func testEachBrowserStateHasItsOwnWordAndColour() throws {
        let read = BrowserRead(state: .read, lastRead: Date(timeIntervalSince1970: 1_800_000_000))
        let all = rows(on: ["x", "instagram", "reddit", "tiktok"], reads: [
            "x": read,
            "instagram": BrowserRead(state: .signedOut),
            "reddit": BrowserRead(state: .couldntRead),
        ])
        let healthy = try row("x", all)
        XCTAssertEqual(healthy.word, "Through your browser")
        XCTAssertEqual(healthy.tone, .browser)
        XCTAssertNotEqual(healthy.tone, SourceCatalogStatus.connected.tone, "never the green of a connection")
        XCTAssertEqual(try row("tiktok", all).word, "Not read yet")
        XCTAssertEqual(try row("tiktok", all).tone, .off)
        XCTAssertEqual(try row("instagram", all).word, "Signed out")
        XCTAssertEqual(try row("instagram", all).tone, .attention)
        XCTAssertEqual(try row("reddit", all).word, "Couldn't read")
        XCTAssertEqual(try row("reddit", all).tone, .attention)
    }

    func testSignedOutNeedsYouAndIsNotCountedWhileTheOtherStatesStayConnected() throws {
        let all = rows(on: ["x", "instagram", "reddit", "tiktok"], reads: [
            "x": BrowserRead(state: .read), "instagram": BrowserRead(state: .signedOut),
            "reddit": BrowserRead(state: .couldntRead),
        ])
        XCTAssertEqual(try row("instagram", all).section, .needsYou)
        XCTAssertEqual(try row("x", all).section, .shelf(.saved))
        XCTAssertEqual(try row("reddit", all).section, .shelf(.saved))
        XCTAssertTrue(try row("tiktok", all).isConnectedHere)
        XCTAssertEqual(SourceCatalog.connectedCount(all), 3, "signed out is waiting on the person")
        let line = SourceGrid.line(try row("instagram", all), now: Date())
        XCTAssertEqual(line, SourceGrid.Line(word: "Signed out", tone: .attention))
        XCTAssertEqual(SourceGrid.line(try row("x", all), now: Date()),
                       SourceGrid.Line(word: "Through your browser", tone: .browser),
                       "the word says how it is read")
        XCTAssertEqual(SourceGrid.line(try row("reddit", all), now: Date())?.tone, .attention)
    }

    func testTheBrowserHueIsTheInfoHueNotTheAccent() {
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            XCTAssertNotEqual(CicadaTheme.info, CicadaTheme.success)
            XCTAssertNotEqual(CicadaTheme.info, CicadaTheme.warning)
        }
        let source = try? String(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/Views/Sources/SourceLogoTile.swift"), encoding: .utf8)
        XCTAssertTrue(source?.contains("case .browser: CicadaTheme.info") == true)
    }

    // MARK: The page

    func testThePageStatusSaysHowItIsReadAndWhatToDo() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let today = ISODay.today(now: now)
        let en = Locale(identifier: "en_US")
        let read = SourcePageStatus.of(row: .connected, run: .idle, latest: nil,
                                       browser: BrowserRead(state: .read, lastRead: now.addingTimeInterval(-7_200)))
        XCTAssertEqual(read.word, "Through your browser")
        XCTAssertEqual(read.tone, .browser)
        XCTAssertTrue(read.detail(today: today, now: now, locale: en)?.hasPrefix("last read") == true)
        XCTAssertEqual(SourceConnectState.of(read), .connected)
        let out = SourcePageStatus.of(row: .connected, run: .idle, latest: nil, browser: BrowserRead(state: .signedOut))
        XCTAssertEqual(out.line(today: today, now: now, locale: en), "Signed out · sign in, then try again")
        XCTAssertEqual(SourceConnectState.of(out), .needsAttention)
        let none = SourcePageStatus.of(row: .connected, run: .idle, latest: nil, browser: BrowserRead())
        XCTAssertEqual(none.line(today: today, now: now, locale: en), "Not read yet")
        XCTAssertEqual(SourceConnectState.of(none), .connected)
        XCTAssertEqual(SourcePageStatus.of(row: .connected, run: .idle, latest: nil),
                       .connected(lastItem: nil), "a connection is untouched")
    }

    // MARK: What the backend sends

    func testTheSavedBlockDecodesAndBecomesEachListsRead() throws {
        let json = #"""
        {"agentEnabled": true, "savedLists": {"instagram": true},
         "saved": {"readsToday": 1, "dailyReads": 10, "lists": {
           "instagram": {"state": "read", "lastReadAt": "2026-11-05T09:00:00Z", "handle": "alpha-person",
                         "profileUrl": "https://www.instagram.com/alpha-person/", "through": "browser"},
           "reddit": {"state": "signed_out"},
           "tiktok": {"state": "couldnt_read"},
           "pinterest": {}}}}
        """#
        let settings = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(json.utf8))
        let reads = settings.browserReads
        XCTAssertEqual(reads["instagram"]?.state, .read)
        XCTAssertEqual(reads["instagram"]?.handle, "alpha-person")
        XCTAssertEqual(reads["instagram"]?.profileURL, "https://www.instagram.com/alpha-person/")
        XCTAssertNotNil(reads["instagram"]?.lastRead)
        XCTAssertEqual(reads["reddit"]?.state, .signedOut)
        XCTAssertEqual(reads["tiktok"]?.state, .couldntRead)
        XCTAssertEqual(reads["pinterest"]?.state, .notReadYet)
        let old = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(#"{"agentEnabled": true}"#.utf8))
        XCTAssertNil(old.saved, "an older backend sends none")
        XCTAssertEqual(old.browserReads["x"]?.state ?? .notReadYet, .notReadYet)
    }

    func testYouTubeAndSubstackShareTheSameStatesFromTheirPauses() throws {
        let json = #"""
        {"agentEnabled": true,
         "youtube": {"pausedUntil": "2026-11-12", "lists": {"watch_later": {"lastOutcome": "needs_login"}}},
         "substack": {"lists": {"saved": {"lastReadAt": "2026-11-05T09:00:00Z", "lastOutcome": "read"}}}}
        """#
        let reads = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(json.utf8)).browserReads
        XCTAssertEqual(reads["youtube"]?.state, .signedOut)
        XCTAssertEqual(reads[SourceCatalog.substackId]?.state, .read)
        let all = rows(on: ["youtube", SourceCatalog.substackId], reads: reads)
        XCTAssertEqual(try row("youtube", all).word, "Signed out")
        XCTAssertEqual(try row("youtube", all).section, .needsYou)
        XCTAssertEqual(try row(SourceCatalog.substackId, all).word, "Through your browser")
    }

    // MARK: Whose list it is

    func testAProfileLinkOpensOnlyAsAPlainHttpsLinkAndAHandleShowsAsTheSiteWritesIt() {
        XCTAssertNotNil(BrowserIdentity.profileURL("https://www.example-social.test/alpha-person"))
        for bad in ["http://www.example-social.test/a", "javascript:alert(1)", "file:///etc/passwd",
                    "https://user:pw@example-social.test/a", "https://", "https://exa mple.test/a", "", nil] {
            XCTAssertNil(BrowserIdentity.profileURL(bad), bad ?? "nil")
        }
        XCTAssertEqual(BrowserIdentity.display("alpha-person"), "@alpha-person")
        XCTAssertEqual(BrowserIdentity.display("@alpha-person"), "@alpha-person")
        XCTAssertEqual(BrowserIdentity.display("u/alpha-person"), "u/alpha-person")
        XCTAssertNil(BrowserIdentity.display("  "))
        XCTAssertNil(BrowserIdentity.display(nil))
    }
}
