import XCTest
@testable import CicadaApp

/// R-OB11 / R-OB14 — F-06 says only what is true, and F-05's foot follows where reads go.
@MainActor
final class KeepRunningTests: XCTestCase {
    func testIfYouQuitDependsOnTheBackgroundService() {
        XCTAssertTrue(KeepRunning.afterQuit(backgroundRunning: true).contains(Copy.keepQuitAgentsSave))
        let without = KeepRunning.afterQuit(backgroundRunning: false)
        XCTAssertFalse(without.contains(Copy.keepQuitAgentsSave), "the app's own backend stops with it")
        XCTAssertTrue(without.contains(Copy.keepQuitAgentsWait))
    }

    func testNothingPromisesNotesKeepUp() {
        for line in KeepRunning.whileOpen() + KeepRunning.afterQuit(backgroundRunning: true) {
            XCTAssertFalse(line.lowercased().contains("notes keep up"), line)
        }
    }

    func testWhoReadsFootFollowsTheNote() {
        XCTAssertEqual(WhoReadsFoot.line(note: nil), Copy.privacyEverything, "Ollama: nothing leaves this Mac")
        XCTAssertEqual(WhoReadsFoot.line(note: "This is where information leaves your Mac…"), Copy.privacyEverythingElse)
    }
}
