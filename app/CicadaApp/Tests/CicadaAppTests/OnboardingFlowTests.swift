import XCTest
@testable import CicadaApp

/// Track I T6 (design §4.1.7) — what Start does, in order. The owner save runs
/// alone and first: it is the observer every later write carries (G117 R1).
final class OnboardingFlowTests: XCTestCase {
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

    /// R-OB2 — Get started is the owner PUT alone: the observer every later write carries (G117 R1).
    func testGetStartedIsTheOwnerSaveAlone() {
        XCTAssertEqual(OnboardingFlow.beginSteps(name: "  Ada  "), [.saveOwner("Ada")])
    }

    func testSetUpLaterSavesTheNameOnlyIfWelcomeHasNotAndNeverOffersTheTour() {
        XCTAssertEqual(OnboardingFlow.laterSteps(name: "Ada", ownerSaved: false),
                       [.saveOwner("Ada"), .markOnboarded, .recordGettingStarted([]), .showHome])
        XCTAssertEqual(OnboardingFlow.laterSteps(name: "Ada", ownerSaved: true),
                       [.markOnboarded, .recordGettingStarted([]), .showHome])
    }

    /// R-OB15 — Open Cicada marks the live bank (a rerun too: I-b final review, finding 2), records the agents Cicada
    /// saw connect, offers the tour (seam 3) and lands on Home.
    func testOpenCicadaMarksRecordsOffersTheTourAndShowsHome() {
        XCTAssertEqual(OnboardingFlow.finishSteps(recorded: [.agent("claude-code")]),
                       [.markOnboarded, .recordGettingStarted([.agent("claude-code")]), .offerTour, .showHome])
    }

    /// R-OB19 — a rerun's Close (I-b final review, finding 2, kept): Run setup again reset the bank's flag, so once
    /// the person changed something (Get started re-saved the owner; ticks may have started sources) Close marks the
    /// live bank again — else an empty bank re-raises the first-run flow on the next graph reload. Close with no
    /// change still leaves it unmarked ("shows again next launch").
    func testARerunsCloseMarksTheBankOnlyOnceSomethingChanged() {
        XCTAssertEqual(OnboardingFlow.closeSteps(ownerSaved: true), [.markOnboarded, .close])
        XCTAssertEqual(OnboardingFlow.closeSteps(ownerSaved: false), [.close])
    }

    func testOnlyTheAgentsGettingStartedKnowsAreRecorded() {
        XCTAssertEqual(OnboardingFlow.recordedAgents(connected: ["grok", "codex", "claude-code", "hermes"]),
                       [.agent("claude-code"), .agent("codex")], "catalog order; a cloud agent has no Home row")
    }
}
