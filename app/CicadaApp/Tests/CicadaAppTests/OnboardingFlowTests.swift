import XCTest
@testable import CicadaApp

/// Track I T6 (design §4.1.7) — what Start does, in order. The owner save runs
/// alone and first: it is the observer every later write carries (G117 R1).
final class OnboardingFlowTests: XCTestCase {
    func testFirstRunSavesTheOwnerFirstThenTheEngineOnlyIfPicked() {
        XCTAssertEqual(OnboardingFlow.plan(name: "Ada", pickedEngine: nil, ticked: [.agent("claude-code")], mode: .firstRun),
                       [.saveOwner("Ada"), .markOnboarded, .recordGettingStarted([.agent("claude-code")]), .showHome,
                        .turnOn(.agent("claude-code"))])
        XCTAssertEqual(OnboardingFlow.plan(name: " Ada ", pickedEngine: "agent", ticked: [], mode: .firstRun).prefix(2),
                       [.saveOwner("Ada"), .saveEngine("agent")])
    }

    func testSetUpLaterTurnsNothingOn() {
        XCTAssertEqual(OnboardingFlow.plan(name: "Ada", pickedEngine: "agent", ticked: [.agent("codex")], mode: .setUpLater),
                       [.saveOwner("Ada"), .markOnboarded, .recordGettingStarted([]), .showHome])
    }

    /// I-b final review, finding 2 — Run setup again cleared the flag, so a saved
    /// rerun marks the bank onboarded again, or an empty bank would re-raise
    /// the first-run Welcome at the next launch.
    func testRerunSavesChangesMarksTheBankAgainAndCloses() {
        XCTAssertEqual(OnboardingFlow.plan(name: "Ada", pickedEngine: nil, ticked: [.browser("chrome-bookmarks")], mode: .rerun),
                       [.saveOwner("Ada"), .markOnboarded, .recordGettingStarted([.browser("chrome-bookmarks")]), .close,
                        .turnOn(.browser("chrome-bookmarks"))])
    }

    func testAFailedOwnerSaveStopsEverythingAfterIt() {
        XCTAssertFalse(OnboardingFlow.shouldContinue(after: .saveOwner("Ada"), succeeded: false))
        XCTAssertTrue(OnboardingFlow.shouldContinue(after: .saveOwner("Ada"), succeeded: true))
        XCTAssertTrue(OnboardingFlow.shouldContinue(after: .turnOn(.agent("codex")), succeeded: false),
                      "a row's failure is that row's, never global")
    }

    func testTheNameIsRequired() {
        XCTAssertFalse(OnboardingFlow.canStart(name: "   "))
        XCTAssertTrue(OnboardingFlow.canStart(name: "Ada"))
    }

    func testTheDemoCreatesThenMarksTheLiveBank() {
        XCTAssertEqual(OnboardingFlow.demoSteps, [.createDemoBank, .markOnboarded])
    }
}
