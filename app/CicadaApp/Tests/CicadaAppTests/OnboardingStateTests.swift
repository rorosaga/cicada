import XCTest
@testable import CicadaApp

/// G117 R5 — `hasOnboarded` is a plain per-bank `UserDefaults` flag, not
/// `@AppStorage` (that property wrapper's key must be static at declaration,
/// and the bank name is only known at runtime).
final class OnboardingStateTests: XCTestCase {
    override func setUp() {
        UserDefaults.standard.removeObject(forKey: "cicada.hasOnboarded.alpha-project")
    }

    func testDefaultsToNotOnboarded() {
        XCTAssertFalse(OnboardingState.isOnboarded(bank: "alpha-project"))
    }

    func testMarkingOnboardedPersistsPerBank() {
        OnboardingState.markOnboarded(bank: "alpha-project")
        XCTAssertTrue(OnboardingState.isOnboarded(bank: "alpha-project"))
        XCTAssertFalse(OnboardingState.isOnboarded(bank: "bob-example"))
    }

    /// Settings → General's "Run setup again" clears the flag so the sheet
    /// re-shows even on a non-empty bank.
    func testResetClearsTheFlag() {
        OnboardingState.markOnboarded(bank: "alpha-project")
        OnboardingState.reset(bank: "alpha-project")
        XCTAssertFalse(OnboardingState.isOnboarded(bank: "alpha-project"))
    }

    // MARK: Onboarding v2 — the step reached (2026-10-22)

    private func scratchDefaults() throws -> UserDefaults {
        let name = "cicada.onboarding-state-tests"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: name))
        defaults.removePersistentDomain(forName: name)
        return defaults
    }

    func testTheStepReachedResumesAndFinishingForgetsIt() throws {
        let d = try scratchDefaults()
        XCTAssertNil(OnboardingState.savedStep(bank: "alpha-project", defaults: d))
        OnboardingState.saveStep(.agents, bank: "alpha-project", defaults: d)
        XCTAssertEqual(OnboardingState.savedStep(bank: "alpha-project", defaults: d), .agents)
        XCTAssertNil(OnboardingState.savedStep(bank: "bob-example", defaults: d), "per bank")
        OnboardingState.markOnboarded(bank: "alpha-project", defaults: d)
        XCTAssertNil(OnboardingState.savedStep(bank: "alpha-project", defaults: d), "a finished setup starts over")
        OnboardingState.saveStep(.sources, bank: "alpha-project", defaults: d)
        OnboardingState.reset(bank: "alpha-project", defaults: d)
        XCTAssertNil(OnboardingState.savedStep(bank: "alpha-project", defaults: d), "Run setup again starts at Welcome")
    }

    /// Hyrum mode B — a stored word from the seven-step flow, or a stored Welcome, lands somewhere sensible; junk is
    /// ignored rather than trapping.
    func testStoredWordsFromEitherFlowResumeSensibly() throws {
        let d = try scratchDefaults()
        let key = "cicada.onboarding.step.alpha-project"
        for (raw, expected) in [("import", OnboardingPage.sources), ("whoReads", .intelligence),
                                ("keepRunning", .done), ("ready", .done)] {
            d.set(raw, forKey: key)
            XCTAssertEqual(OnboardingState.savedStep(bank: "alpha-project", defaults: d), expected, raw)
        }
        for raw in ["welcome", "nonsense"] {
            d.set(raw, forKey: key)
            XCTAssertNil(OnboardingState.savedStep(bank: "alpha-project", defaults: d), raw)
        }
        d.set(true, forKey: "cicada.hasOnboarded.alpha-project")
        XCTAssertTrue(OnboardingState.isOnboarded(bank: "alpha-project", defaults: d), "the flag keeps its key")
    }
}
