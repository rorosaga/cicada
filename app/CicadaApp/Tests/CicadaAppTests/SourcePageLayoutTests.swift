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

    func testDisconnectAsksFirstAndRefreshDoesNot() {
        XCTAssertNil(SourceFooterAction.refresh {}.confirm)
        let disconnect = SourceFooterAction.disconnect("GitHub") {}
        XCTAssertEqual(disconnect.confirm?.title, "Disconnect GitHub?")
        XCTAssertEqual(disconnect.confirm?.button, Copy.SourceLayout.disconnect)
    }
}
