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

    private func item(_ id: FoundItemID, _ readiness: FoundItem.Readiness = .ready, opens: Bool = false,
                      group: FoundGroup = .agents) -> FoundItem {
        FoundItem(id: id, group: group, title: id.key, isPresent: true, content: .ownIntentionalAct,
                  readiness: readiness, opensAnotherApp: opens)
    }

    func testTicksStartAtThePolicyAndThenBelongToThePerson() {
        let cc = item(.agent("claude-code")), cursor = item(.agent("cursor"), opens: true)
        let chrome = item(.browser("chrome-bookmarks"), group: .browsers)
        var ticks = WelcomeTicks.reconcile(items: [cc, cursor, chrome], current: [], touched: [], allowRequested: [])
        XCTAssertEqual(ticks, [.agent("claude-code"), .browser("chrome-bookmarks")], "D-2: own acts, no prompt, no other app")
        ticks.remove(.agent("claude-code"))
        ticks = WelcomeTicks.reconcile(items: [cc, cursor, chrome], current: ticks,
                                       touched: [.agent("claude-code")], allowRequested: [])
        XCTAssertFalse(ticks.contains(.agent("claude-code")), "a re-probe never re-ticks what the person unticked")
    }

    func testAPermissionGrantedFromTheRowTicksIt() {
        let id = FoundItemID.browser("safari-bookmarks")
        let blocked = item(id, .needsPermission, group: .browsers)
        XCTAssertFalse(WelcomeTicks.reconcile(items: [blocked], current: [], touched: [], allowRequested: []).contains(id))
        let granted = item(id, .ready, group: .browsers)
        XCTAssertTrue(WelcomeTicks.reconcile(items: [granted], current: [], touched: [id], allowRequested: [id]).contains(id),
                      "W5: the click on Allow… stated the intent")
    }

    func testAnAlreadyOnOrFailedRowIsNeverTicked() {
        let ids: Set<FoundItemID> = [.agent("codex"), .agent("claude-code")]
        XCTAssertTrue(WelcomeTicks.reconcile(items: [item(.agent("codex"), .alreadyOn), item(.agent("claude-code"), .failed("x"))],
                                             current: ids, touched: ids, allowRequested: []).isEmpty,
                      "nothing to run, or nothing that can run")
    }

    func testTheCardScrollsInsideAPinnedFooterAtEveryZoom() {
        for scale in stride(from: CGFloat(0.8), through: 1.4001, by: 0.1) {
            for (w, h) in [(CGFloat(900), CGFloat(600)), (1200, 800), (1600, 1000)] {
                let band = WelcomeLayout.bandHeight(windowHeight: h, scale: scale)
                let top = WelcomeLayout.cardTop(windowHeight: h, scale: scale)
                XCTAssertLessThanOrEqual(band, h * WelcomeLayout.maxBandFraction)
                XCTAssertGreaterThan(top, 0)
                XCTAssertLessThan(top, band, "the card rises into the meadow, so the headline sits on the card")
                XCTAssertGreaterThanOrEqual(WelcomeLayout.cardViewport(windowHeight: h, scale: scale), 160 * scale,
                                            "\(w)×\(h) at \(scale)")
                XCTAssertLessThanOrEqual(WelcomeLayout.cardWidth(windowWidth: w, scale: scale), w - 32 * scale)
            }
        }
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
