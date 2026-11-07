import XCTest
@testable import CicadaApp

/// The standard source page (owner 2026-11-04; DESIGN_RULES §9 2026-11-04): its pure parts, and the source guards that
/// keep every source page on it.
@MainActor
final class SourcePageLayoutTests: XCTestCase {
    func testTheConnectStateFollowsThePageStatus() {
        XCTAssertEqual(SourceConnectState.of(.off(lastItem: nil)), .notConnected)
        XCTAssertEqual(SourceConnectState.of(.off(lastItem: "2026-10-01")), .notConnected)
        XCTAssertEqual(SourceConnectState.of(.connected(lastItem: nil)), .connected)
        XCTAssertEqual(SourceConnectState.of(.syncing(detail: nil)), .connecting)
        XCTAssertEqual(SourceConnectState.of(.needsYou("sign in again")), .needsAttention)
        // An app removed from this Mac reads Off, says why, and offers nothing to connect.
        let gone = SourcePageStatus.of(row: .connected, run: .idle, latest: nil, notInstalled: true)
        XCTAssertEqual(gone, .notInstalled)
        XCTAssertEqual(SourceConnectState.of(gone), .notConnected)
        XCTAssertEqual(gone.line(today: ISODay.today()), "\(Copy.SourcePage.off) · \(Copy.SourcePage.notInstalled)")
    }

    func testTheStandardWaysCarryTheirOwnIcons() {
        let browser = SourceWayIn.browser(on: true) { _ in }
        XCTAssertEqual(browser.icon, .symbol("globe"))
        XCTAssertEqual(browser.title, Copy.SourceLayout.readInBrowser)
        // "Import a file" wears the source's own mark on a file — never another company's mark.
        let file = SourceWayIn.importFile(origin: "spotify-saved") {}
        XCTAssertEqual(file.icon, .file("spotify-saved"))
        XCTAssertEqual(file.title, Copy.SourceLayout.importFile)
    }

    // MARK: - Review of #593

    /// Blocker 1 — Substack (#594) on the layout: its three lists as switches, each flipping through the page's own
    /// consent path, never a paragraph.
    func testSubstacksListsAreFourSwitchesThatFlipThroughThePage() {
        var flipped: [(SubstackList, Bool)] = []
        let ways = SourceCatalogDetail.substackWays(isOn: { $0 == .saved }, status: nil) { flipped.append(($0, $1)) }
        XCTAssertEqual(ways.map(\.id), ["substack-saved", "substack-liked", "substack-history", "substack-subscriptions"])
        XCTAssertEqual(ways.map(\.title), SubstackList.allCases.map(SubstackListWords.title))
        for way in ways {
            guard case .toggle(let on, let set) = way.control else { return XCTFail("\(way.id) is not a switch") }
            XCTAssertEqual(on, way.id == "substack-saved")
            set(!on)
        }
        XCTAssertEqual(flipped.map(\.0), SubstackList.allCases)
        XCTAssertEqual(flipped.map(\.1), [false, true, true, true])
    }

    /// Blocker 2 — the backend sends `["connect"]` before a connector is connected and `["sync", "disconnect"]` after
    /// (`channel_registry._connector_channel`): both are the connector, so a connected account keeps Disconnect and a
    /// lapsed one Reconnect.
    func testAConnectorIsFoundInEitherOfTheBackendsShapes() throws {
        func channel(_ actions: String, connected: Bool) throws -> SourceChannel {
            try JSONDecoder().decode(SourceChannel.self, from: Data("""
                {"id": "x", "label": "X", "connected": \(connected), "count": 0, "actions": \(actions)}
                """.utf8))
        }
        XCTAssertEqual(SourceCatalogDetail.connectorChannel(in: [try channel(#"["connect"]"#, connected: false)])?.id,
                       "x")
        XCTAssertEqual(SourceCatalogDetail.connectorChannel(in: [try channel(#"["sync", "disconnect"]"#,
                                                                             connected: true)])?.id, "x")
        XCTAssertNil(SourceCatalogDetail.connectorChannel(in: [try channel(#"["sync"]"#, connected: true)]))
    }

    /// Blocker 3 — "Unmute all" for the sites the ask-why question was muted on: on a browser page, only while
    /// something is muted.
    func testUnmuteAllShowsOnlyWhileASiteIsMuted() {
        XCTAssertTrue(BrowserWayRules.showsUnmute(muted: 2, hasBookmarks: true))
        XCTAssertFalse(BrowserWayRules.showsUnmute(muted: 0, hasBookmarks: true))
        XCTAssertFalse(BrowserWayRules.showsUnmute(muted: 2, hasBookmarks: false))
    }

    /// Blocker 4 — the YouTube watch-history read says a failure in its own words and offers Stop while it reads.
    func testTheWatchHistoryReadSaysItsFailureAndCanBeStopped() {
        XCTAssertEqual(WatchHistoryLine.of(enabled: true, status: .failed("Allow Full Disk Access"), run: nil),
                       .failed("Allow Full Disk Access"))
        XCTAssertEqual(WatchHistoryLine.of(enabled: true, status: .syncing,
                                           run: SyncActivity.Run(detail: "12 of 40", cancellable: true)),
                       .reading("12 of 40", cancellable: true))
        XCTAssertEqual(WatchHistoryLine.of(enabled: true, status: .syncing, run: SyncActivity.Run(cancellable: false)),
                       .reading(Copy.watchHistoryReading, cancellable: false))
        XCTAssertEqual(WatchHistoryLine.of(enabled: false, status: .failed("old"), run: nil), .none)
        XCTAssertEqual(WatchHistoryLine.of(enabled: true, status: .watching, run: nil), .none)
    }

    /// Chat exports: each app's "request your export" is a way in wearing that app's own mark.
    func testEachChatAppsExportRequestIsAWayWithItsOwnMark() {
        let ways = ChatVendor.allCases.map(ChatExportWay.of)
        XCTAssertEqual(ways.map(\.icon), ChatVendor.allCases.map { .mark($0.origin) })
        XCTAssertEqual(ways.map(\.title), ChatVendor.allCases.map { Copy.SourceLayout.requestExport($0.title) })
    }

    func testDisconnectAsksFirstAndRefreshDoesNot() {
        XCTAssertNil(SourceFooterAction.refresh {}.confirm)
        let disconnect = SourceFooterAction.disconnect("GitHub") {}
        XCTAssertEqual(disconnect.confirm?.title, "Disconnect GitHub?")
        XCTAssertEqual(disconnect.confirm?.button, Copy.SourceLayout.disconnect)
    }
}
