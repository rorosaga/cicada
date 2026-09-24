import XCTest
@testable import CicadaApp

/// R-HS22 — typing in the Settings panel's field and pressing ⏎ lands on the row: the same seams
/// `SettingsPanel` calls, driven with the real `SettingsFocus`. (`SettingsRowLintTests` proves every
/// indexed row carries its anchor; the scroll and wash are the live check.)
@MainActor
final class SettingsSearchLandingTests: XCTestCase {
    private let entries = SettingsIndex.pageEntries + SettingsIndex.staticEntries

    func testReturnLandsOnTheTopHitsRow() throws {
        let hit = try XCTUnwrap(SettingsSearchLanding.topHit("text size", in: entries))
        XCTAssertEqual(hit.id, .textSize)
        XCTAssertEqual(hit.section, .general)

        let focus = SettingsFocus()
        focus.go(hit.section, row: hit.anchor)
        XCTAssertEqual(focus.request?.section, .general)
        XCTAssertEqual(focus.request?.row, .textSize)
        let name = SettingsSearchLanding.announcement(section: hit.section, row: hit.anchor, in: entries)
        XCTAssertEqual(name, "\(SettingsSection.general.title), \(hit.title)", "VoiceOver hears where it landed")
        focus.land(on: hit.anchor, announcing: name, reduceMotion: true)
        XCTAssertEqual(focus.highlighted, .textSize)
        XCTAssertEqual(focus.scrollTarget, .textSize)
        focus.consumeScroll()
        XCTAssertNil(focus.scrollTarget, "scrolled once")
    }

    func testARowWithNoAnchorLandsOnItsPage() throws {
        let hit = try XCTUnwrap(SettingsSearchLanding.topHit("tailscale", in: entries))
        XCTAssertEqual(hit.id, .remoteReach)
        XCTAssertEqual(hit.anchor, .page(.remote), "R-O12 — From anywhere lands on its header")
    }

    /// Typing a setting's own name surfaces it at the top of the results (the first three — two
    /// rows may share a word, and the panel shows every hit, grouped).
    func testEverySettingIsReachableByItsOwnName() {
        for entry in SettingsIndex.staticEntries {
            let top = SettingsIndex.search(entry.title, in: entries).prefix(3).map(\.entry.id)
            XCTAssertTrue(top.contains(entry.id), "\(entry.title) → \(top)")
        }
        XCTAssertNil(SettingsSearchLanding.topHit("zzz-nothing", in: entries))
        XCTAssertNil(SettingsSearchLanding.topHit("   ", in: entries))
    }
}
