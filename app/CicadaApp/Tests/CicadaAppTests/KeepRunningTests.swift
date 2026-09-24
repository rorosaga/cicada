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

    /// F-07 (R-OB15) — the summary's words from real state.
    func testYoureSetNamesTheConnectedAgentsAndHowCicadaStarts() {
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(ReadySummary.agents(connected: ["codex", "claude-code", "hermes"], locale: en),
                       Copy.readyAgentsConnected("Claude Code, Codex, and Hermes"))
        XCTAssertNil(ReadySummary.agents(connected: [], locale: en))
        XCTAssertEqual(ReadySummary.startup(opensAtLogin: true, menuBar: true), Copy.readyOpensAtLoginMenuBar)
        XCTAssertEqual(ReadySummary.startup(opensAtLogin: false, menuBar: true), Copy.readyMenuBar)
        XCTAssertNil(ReadySummary.startup(opensAtLogin: false, menuBar: false))
    }

    /// F-01's marks: every featured agent with a real mark (DR-52), never a glyph standing in for one.
    func testWelcomeShowsOnlyRealMarks() {
        let ids = WelcomeMarks.entries.map(\.id)
        XCTAssertTrue(ids.contains("claude-code"))
        XCTAssertFalse(ids.contains("grok"), "no sourced xAI mark yet (R-AG9)")
    }
}
