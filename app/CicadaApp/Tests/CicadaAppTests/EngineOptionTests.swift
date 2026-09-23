import XCTest
@testable import CicadaApp

/// R-E4 / R-E25 — every decision the Settings → Sleep engine row makes.
final class EngineOptionTests: XCTestCase {
    private func card(_ id: String, available: Bool = true, connected: Bool = true,
                      models: [String] = [], label: String? = nil) -> SleepEngineCandidate {
        SleepEngineCandidate(id: id, label: label ?? id, available: available,
                             connected: connected, models: models, detail: nil)
    }

    func testAPlanCardIsSelectableOnlyWhenSignedInOrAlreadyChosen() {
        XCTAssertTrue(EngineOption.isSelectable(card("codex"), selectedMode: "auto"))
        XCTAssertFalse(EngineOption.isSelectable(card("codex", connected: false), selectedMode: "auto"))
        XCTAssertTrue(EngineOption.isSelectable(card("codex", connected: false), selectedMode: "codex"))
        XCTAssertFalse(EngineOption.isSelectable(card("agent", available: false, connected: false),
                                                 selectedMode: "byok"))
        for id in ["auto", "local", "byok"] {
            XCTAssertTrue(EngineOption.isSelectable(card(id, available: false, connected: false),
                                                    selectedMode: "agent"), id)
        }
    }

    func testEveryCardSaysItsStateInPlainWords() {
        XCTAssertEqual(EngineOption.caption(for: card("codex")), "Signed in")
        XCTAssertEqual(EngineOption.caption(for: card("codex", connected: false)), "Not signed in")
        XCTAssertEqual(EngineOption.caption(for: card("agent", available: false, connected: false)), "Not installed")
        XCTAssertEqual(EngineOption.caption(for: card("local", models: ["llama3.1"])), "Ready")
        XCTAssertEqual(EngineOption.caption(for: card("local", connected: false)), "Not running")
        XCTAssertEqual(EngineOption.caption(for: card("local", available: false, connected: false)), "Not installed")
        XCTAssertEqual(EngineOption.caption(for: card("auto")), "Picks for you")
        XCTAssertEqual(EngineOption.caption(for: card("byok")), "Uses your key")
    }

    func testThePlanCardsWearTheSameMarksAsPlansAndKeys() {
        XCTAssertEqual(EngineOption.logoName(for: "agent"), ConnectionMark.logoName(connectionId: "claude-plan"))
        XCTAssertEqual(EngineOption.logoName(for: "codex"), ConnectionMark.logoName(connectionId: "chatgpt-plan"))
        XCTAssertEqual(EngineOption.logoName(for: "local"), ConnectionMark.logoName(connectionId: "ollama-local"))
        XCTAssertNil(EngineOption.logoName(for: "byok"))
        XCTAssertEqual(EngineOption.symbol(for: "byok"), "key.fill")
        XCTAssertNil(EngineOption.logoName(for: "auto"))
        XCTAssertEqual(EngineOption.symbol(for: "auto"), "sparkles")
    }

    func testTheSignInHintNamesOnlyInstalledSignedOutPlans() {
        let cards = [card("agent", label: "Claude plan"),
                     card("codex", connected: false, label: "ChatGPT plan"),
                     card("local", connected: false)]
        XCTAssertEqual(EngineOption.signInHint(cards), "To use your ChatGPT plan, sign in on")
        XCTAssertNil(EngineOption.signInHint([card("codex", available: false, connected: false)]))
        XCTAssertNil(EngineOption.signInHint([card("agent"), card("codex")]))
    }

    func testTheExtraUsageSwitchShowsOnlyWhereTheClaudePlanCanRun() {
        XCTAssertTrue(EngineOption.showsOverageToggle(selectedMode: "agent"))
        XCTAssertTrue(EngineOption.showsOverageToggle(selectedMode: "auto"))
        XCTAssertFalse(EngineOption.showsOverageToggle(selectedMode: "codex"))
        XCTAssertFalse(EngineOption.showsOverageToggle(selectedMode: "local"))
    }
}
