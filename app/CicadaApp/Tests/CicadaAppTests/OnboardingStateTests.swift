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
}
