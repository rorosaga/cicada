import XCTest
@testable import CicadaApp

/// Rules a rendered view cannot show, held as source checks (the `HomeF09Tests` pattern).
final class OnboardingSourceTests: XCTestCase {
    func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix(suffix) }, suffix)
        return try String(contentsOf: file, encoding: .utf8)
    }

    /// R-OB5 (kept by v2) — an untouched step keeps the configured engine: the Intelligence step writes only from a
    /// click inside a row (`IntelligenceRow`'s Sign in / Verify / Use), never on appear, Continue or Skip.
    func testTheIntelligenceStepWritesOnlyFromARowsClick() throws {
        let text = try source("Views/Onboarding/IntelligenceStep.swift")
        XCTAssertTrue(text.contains("IntelligenceRow("), "Settings → Intelligence's own row")
        XCTAssertEqual(text.components(separatedBy: "engineVM.apply(").count - 1, 1, "only Use writes")
        XCTAssertTrue(text.contains("private func use("))
        XCTAssertFalse(text.contains("kind == \"local\""), "D1: a local model is never pitched")
        for write in [".set(mode:", "saveEngine", "PUT"] { XCTAssertFalse(text.contains(write), write) }
    }

    /// R-OB12 — onboarding's Connect bundles Remembers automatically; Settings' Agents never does (R-H11). Connect for
    /// me runs only through `AgentConnect.run` with the one wiring answer's binaries (R-FA15), its commands shown first.
    func testOnlyOnboardingBundlesRecallAndConnectRunsSettingsOwnPath() throws {
        XCTAssertTrue(try source("Support/OnboardingSteps.swift").contains("AgentSteps.recallSteps(for: wiring)"))
        let step = try source("Views/Onboarding/AgentsStep.swift")
        XCTAssertTrue(step.contains("AgentConnect.run(steps, runtime: runtime, binaries: binaries)"))
        XCTAssertTrue(step.contains("CommandBox(command:"), "the commands are shown before Run")
        XCTAssertFalse(try source("Views/Connect/ConnectView.swift").contains("bundleAutoRecall"))
    }

    /// The Sources step opens the Sources page's own detail for Messages and the browser-read accounts, so every consent
    /// and switch there is the page's (one source of words), and ticks go through the one turn-on.
    func testTheSourcesStepReusesTheSourcesPagesRows() throws {
        let text = try source("Views/Onboarding/SourcesStep.swift")
        XCTAssertTrue(text.contains("SourceCatalogDetail(row:"))
        XCTAssertTrue(text.contains("onTick(entry, !on)"))
        XCTAssertTrue(try source("Views/Onboarding/OnboardingView.swift").contains("runner.start(entry.id"))
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
        let text = try source("Views/Onboarding/DonePage.swift")
        XCTAssertFalse(text.contains("quoteFont"))
        XCTAssertFalse(text.contains("CitedSpan"))
    }

    /// Owner 2026-10-16 — onboarding's illustration is the study room, not a painting (R-OB20's pane retired).
    func testTheOnboardingIllustrationIsTheRoom() throws {
        XCTAssertTrue(try source("Views/Onboarding/OnboardingRoom.swift").contains("SceneryRoomArt("))
        XCTAssertFalse(try source("Views/Onboarding/OnboardingView.swift").contains("PaintedScene"))
    }

    /// Design-refs pattern 12 — the working steps show Skip beside the one primary.
    func testTheWorkingStepsShowAVisibleSkip() throws {
        let text = try source("Views/Onboarding/OnboardingView.swift")
        XCTAssertTrue(text.contains("if page.skippable"))
        XCTAssertTrue(text.contains("Copy.onboardingSkip"))
    }

    /// QA 2026-10-16 — every step opens at its top: the frame's one ScrollView is identified by the step, so a step
    /// never inherits the previous step's scroll offset.
    func testEachStepOpensAtTheTop() throws {
        XCTAssertTrue(try source("Views/Onboarding/OnboardingView.swift").contains(".id(page)"))
    }
}
