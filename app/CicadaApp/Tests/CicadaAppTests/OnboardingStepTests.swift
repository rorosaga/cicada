import XCTest
@testable import CicadaApp

/// G117 — the four-step wizard's ordering is a pure function, independent of
/// the view that renders it, so the sequence (and its termination) is
/// verifiable without standing up a `FirstRunSheet`.
final class OnboardingStepTests: XCTestCase {
    func testStepsAdvanceInOrderThenStop() {
        XCTAssertEqual(OnboardingStep.next(.identity), .engine)
        XCTAssertEqual(OnboardingStep.next(.engine), .channel)
        XCTAssertEqual(OnboardingStep.next(.channel), .sleep)
        XCTAssertNil(OnboardingStep.next(.sleep))
    }

    func testAllCasesAreOrderedIdentityFirst() {
        XCTAssertEqual(OnboardingStep.allCases, [.identity, .engine, .channel, .sleep])
    }
}
