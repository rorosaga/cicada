import XCTest
@testable import CicadaApp

/// Track I T4 — a found row's text twin: VoiceOver hears the name, what it is,
/// and its state, in that order (design W4).
final class FoundRowTests: XCTestCase {
    func testTheLabelNamesTheRowItsDetailAndItsState() {
        XCTAssertEqual(FoundRow.accessibilityLabel(title: "Chrome", detail: Copy.foundBrowserDetail, state: .on),
                       "Chrome. \(Copy.foundBrowserDetail). \(Copy.foundOn)")
        XCTAssertEqual(FoundRow.accessibilityLabel(title: "Codex", detail: Copy.foundAgentDetail,
                                                   state: .failed("Couldn't connect")),
                       "Codex. \(Copy.foundAgentDetail). Couldn't connect")
    }

    func testEveryStateSaysSomething() {
        for state: FoundRowState in [.off, .on, .working("Connecting…"), .needsAction("Allow…"), .failed("x")] {
            XCTAssertFalse(FoundRow.stateText(state).isEmpty)
        }
    }

    func testTheDefaultActionTitleFollowsTheState() {
        XCTAssertEqual(FoundRow.defaultActionTitle(.off), Copy.foundTurnOn)
        XCTAssertEqual(FoundRow.defaultActionTitle(.failed("x")), Copy.foundRetry)
        XCTAssertEqual(FoundRow.defaultActionTitle(.needsAction(Copy.foundAllow)), Copy.foundAllow)
        XCTAssertNil(FoundRow.defaultActionTitle(.on))
        XCTAssertNil(FoundRow.defaultActionTitle(.working("…")))
    }
}
