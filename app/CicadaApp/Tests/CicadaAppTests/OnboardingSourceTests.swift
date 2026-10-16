import XCTest
@testable import CicadaApp

/// Rules a rendered view cannot show, held as source checks (the `HomeF09Tests` pattern).
final class OnboardingSourceTests: XCTestCase {
    func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    /// R-OB5 — "an untouched engine choice keeps the configured engine": F-05 writes nothing itself; only
    /// `EngineChooser`'s click does (R-AG12's one write rule).
    func testWhoReadsWritesNothingOfItsOwn() throws {
        let text = try source("Views/Onboarding/WhoReadsPage.swift")
        XCTAssertTrue(text.contains("EngineChooser()"))
        for write in [".apply(", ".set(mode:", "saveEngine", "PUT"] { XCTAssertFalse(text.contains(write), write) }
    }

    /// R-OB14 — F-06 turns nothing on for the person: no switch is set on appear.
    func testKeepRunningSetsNothingOnAppear() throws {
        let text = try source("Views/Onboarding/KeepRunningPage.swift")
        XCTAssertFalse(text.contains("setEnabled(true)"))
        XCTAssertTrue(text.contains("BackgroundServiceButton"), "the same control as Settings → General")
        XCTAssertTrue(try source("Views/Settings/SettingsGeneralView.swift").contains("BackgroundServiceButton"))
    }

    /// R-OB12 — onboarding bundles; Settings → Agents never does (R-H11).
    func testOnlyOnboardingBundlesRecall() throws {
        XCTAssertTrue(try source("Views/Onboarding/AgentsPage.swift").contains("bundleAutoRecall: true"))
        XCTAssertFalse(try source("Views/Connect/ConnectView.swift").contains("bundleAutoRecall"))
    }

    /// Seam 1 — the one door opens the paged flow; the demo is still `SetupRunner.demoPlan` (seam 2).
    func testTheGateAndTheDoorsRaiseThePagedFlow() throws {
        let content = try source("/ContentView.swift")
        XCTAssertTrue(content.contains("OnboardingView(mode: welcomeMode"))
        XCTAssertFalse(content.contains("WelcomeView("))
        XCTAssertTrue(try source("Views/Onboarding/OnboardingView.swift").contains("SetupRunner.demoPlan"))
    }

    /// R-OB2 — Get started runs the owner PUT alone and first; nothing else before it.
    func testGetStartedRunsTheOwnerSaveBeforeAnythingStarts() throws {
        let text = try source("Views/Onboarding/OnboardingView.swift")
        XCTAssertTrue(text.contains("OnboardingFlow.beginSteps(name:"))
        let tick = try XCTUnwrap(text.range(of: "private func tick(")).upperBound
        XCTAssertTrue(text[tick...].prefix(200).contains("guard ownerSaved"), "no tick before the owner is saved")
    }

    /// DR-60 — ⏎ never animates.
    func testReturnAdvancesWithTheKeyboardInput() throws {
        let text = try source("Views/Onboarding/OnboardingView.swift")
        XCTAssertTrue(text.contains(".onKeyPress(.return)"))
        XCTAssertTrue(text.contains("advance(.keyboard)"))
    }

    /// R-OB15 / DR-18 / G153 — the quote is not the quote face and not a cited span.
    func testTheQuoteIsNeverTheQuoteFace() throws {
        let text = try source("Views/Onboarding/ReadyPage.swift")
        XCTAssertFalse(text.contains("quoteFont"))
        XCTAssertFalse(text.contains("CitedSpan"))
    }

    /// Owner 2026-10-16 — onboarding's illustration is the study room, not a painting (R-OB20's pane retired).
    func testTheOnboardingIllustrationIsTheRoom() throws {
        XCTAssertTrue(try source("Views/Onboarding/OnboardingRoom.swift").contains("SceneryRoomArt("))
        XCTAssertFalse(try source("Views/Onboarding/OnboardingView.swift").contains("PaintedScene"))
    }

    /// DR-38 (QA 2026-10-16) — "Connect or disconnect agents any time in Settings → Agents" is the frame's foot line
    /// on the Agents step; the page itself does not say it again.
    func testTheAgentsStepSaysItsSettingsPointerOnce() throws {
        XCTAssertFalse(try source("Views/Onboarding/AgentsPage.swift").contains("Copy.agentsFoot"))
        XCTAssertTrue(try source("Views/Onboarding/OnboardingView.swift").contains("Copy.agentsFoot"))
    }

    /// QA 2026-10-16 — every step opens at its top: the frame's one ScrollView is identified by the step, so a step
    /// never inherits the previous step's scroll offset.
    func testEachStepOpensAtTheTop() throws {
        XCTAssertTrue(try source("Views/Onboarding/OnboardingView.swift").contains(".id(page)"))
    }
}
