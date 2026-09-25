import XCTest
@testable import CicadaApp

/// G152 + G117 round 4 — Settings → General's *Getting to know Cicada* rows are found by what a person would type
/// (G139's one index), and each is rendered once (`SettingsRowLintTests` holds the rendering).
@MainActor
final class DemoSettingsTests: XCTestCase {
    func testSettingsSearchFindsTheTourAndTheDemo() {
        let all = SettingsIndex.staticEntries
        XCTAssertEqual(SettingsIndex.search("tour", in: all).first?.entry.id, .guidedTour)
        XCTAssertEqual(SettingsIndex.search("tutorial", in: all).first?.entry.id, .guidedTour)
        XCTAssertEqual(SettingsIndex.search("demo", in: all).first?.entry.id, .demoMemory)
        XCTAssertEqual(SettingsIndex.entry(for: .demoMemory, in: all)?.section, .general)
        XCTAssertTrue(SettingsIndex.staticIDs.contains(.guidedTour) && SettingsIndex.staticIDs.contains(.demoMemory))
    }
}
