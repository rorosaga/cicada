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

    /// Final review — the first-run sentences only while they are true; a rerun after a schedule was chosen, or
    /// after Getting started asked, reads what the schedule and previews actually do; unknown shows nothing.
    func testScheduleLineIsTheFirstRunSentenceOnlyOnAFirstRun() {
        func inputs(_ mode: String, scheduled: String = "ollama") -> HonestyInputs {
            let p = SleepEnginePreviews(manual: SleepEnginePreview(engine: "ollama", model: "m", why: ""),
                                        scheduled: SleepEnginePreview(engine: scheduled, model: "m", why: ""))
            return HonestyInputs(schedule: ScheduleConfig(mode: mode, hour: 3, minute: 0), preview: p,
                                 hasKey: false, ollamaReady: true, claudeConnected: false)
        }
        XCTAssertNil(OnboardingScheduleLine.line(.whoReads, loaded: false, asked: false, honesty: inputs("manual")),
                     "a placeholder manual is not an answer (R-IB20)")
        XCTAssertEqual(OnboardingScheduleLine.line(.whoReads, loaded: true, asked: false, honesty: inputs("manual")),
                       Copy.whoReadsNothingYet)
        XCTAssertEqual(OnboardingScheduleLine.line(.ready, loaded: true, asked: false, honesty: inputs("manual")),
                       Copy.readyNothingRead)
        for page in [OnboardingScheduleLine.Page.whoReads, .ready] {
            XCTAssertEqual(OnboardingScheduleLine.line(page, loaded: true, asked: true, honesty: inputs("manual")),
                           Copy.afterImportWhenYouAsk, "already asked: never 'asked after your first read'")
            for mode in ["daily", "interval", "after_import"] {
                let line = OnboardingScheduleLine.line(page, loaded: true, asked: false, honesty: inputs(mode))
                XCTAssertNotEqual(line, Copy.whoReadsNothingYet, mode)
                XCTAssertNotEqual(line, Copy.readyNothingRead, mode)
                XCTAssertEqual(line, ScheduleHonesty.afterImportLine(inputs(mode)), mode)
            }
        }
    }

    /// F-02 (G145) — ticking Apple Notes reads at once through osascript, which raises macOS's prompt; the row says so.
    func testNotesRowNamesItsPrompt() {
        XCTAssertTrue(Copy.importNotesIdle.contains("macOS asks once"))
        XCTAssertLessThanOrEqual(Copy.importNotesIdle.count, 60)
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
