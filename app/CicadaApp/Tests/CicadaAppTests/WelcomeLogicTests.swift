import XCTest
@testable import CicadaApp

/// Track I part b (design §4.1, R-IB11–R-IB13) — the Welcome's rules without a window.
final class WelcomeLogicTests: XCTestCase {
    func testTheSavedNameWinsThenTheMacAccountName() {
        XCTAssertEqual(WelcomeName.initial(saved: "Ada Example", fullUserName: "Someone Else"), "Ada Example")
        XCTAssertEqual(WelcomeName.initial(saved: "  ", fullUserName: "Ada Example"), "Ada Example")
        XCTAssertEqual(WelcomeName.initial(saved: nil, fullUserName: ""), "")
        XCTAssertEqual(WelcomeName.firstWord("Ada Example"), "Ada")
        XCTAssertEqual(WelcomeName.firstWord("  "), "")
    }

    /// Tester readiness (2026-10-26) — the Mac account's full name is a suggestion the person confirms or edits, never a
    /// name stored unseen: offered only when nothing is saved, and "unconfirmed" while it sits untouched in the field.
    func testTheMacAccountNameIsOnlyASuggestionUntilConfirmed() {
        XCTAssertEqual(WelcomeName.suggestion(saved: nil, fullUserName: " Ada Example "), "Ada Example")
        XCTAssertNil(WelcomeName.suggestion(saved: "Bob Example", fullUserName: "Ada Example"), "a saved name wins")
        XCTAssertNil(WelcomeName.suggestion(saved: nil, fullUserName: "  "), "no name from the Mac, no suggestion")
        XCTAssertTrue(WelcomeName.unconfirmed(name: "Ada Example", suggestion: "Ada Example", editing: true))
        XCTAssertFalse(WelcomeName.unconfirmed(name: "Ada", suggestion: "Ada Example", editing: true), "edited")
        XCTAssertFalse(WelcomeName.unconfirmed(name: "Ada Example", suggestion: "Ada Example", editing: false),
                       "submitted with ⏎ is confirmed")
        XCTAssertFalse(WelcomeName.unconfirmed(name: "Ada Example", suggestion: nil, editing: true), "typed, not offered")
    }

    func testTheEngineLineNeverPromisesWhatAnUntouchedChooserWontDo() {
        let inputs = HonestyInputs(schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0), preview: nil,
                                   hasKey: false, ollamaReady: false, claudeConnected: false)
        XCTAssertEqual(EngineChoiceLine.text(pickLabel: "Ollama", readiness: .needsChoice, inputs: inputs),
                       Copy.welcomePickSaved("Ollama"))
        XCTAssertEqual(EngineChoiceLine.text(pickLabel: nil, readiness: .needsChoice, inputs: inputs), Copy.welcomeNotChosen)
        XCTAssertEqual(EngineChoiceLine.text(pickLabel: nil, readiness: .ready(candidate: "agent"), inputs: inputs),
                       ScheduleHonesty.engineLine(inputs))
    }
}
