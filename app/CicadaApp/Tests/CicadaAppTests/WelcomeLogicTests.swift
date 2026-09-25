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
