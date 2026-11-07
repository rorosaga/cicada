import XCTest
@testable import CicadaApp

/// G49/G50 (2026-10-28) — the picker is data-driven: a card the server declares (`kind`, `engine`, `mark`,
/// `billingNote`, `modelNote`, `signIn`) renders, selects, names its runs and lists its models without an id
/// table, and a body from an older backend (no `kind`) keeps every answer it gave before.
@MainActor
final class EnginePlanToolsTests: XCTestCase {
    private static let cursorJSON = """
    {"id":"cursor","label":"Cursor","available":true,"connected":false,"models":["auto"],
     "detail":"Cursor is signed out — run `agent login`.","kind":"plan","engine":"cursor-cli","mark":"cursor",
     "billingNote":"Runs on your Cursor plan.","modelNote":null,"signIn":"agent login"}
    """

    private func cursor(connected: Bool, models: [String] = ["auto", "sonnet-5"], modelNote: String? = nil)
        -> SleepEngineCandidate {
        var c = SleepEngineCandidate(id: "cursor", label: "Cursor", available: true, connected: connected,
                                     models: models, detail: connected ? "Signed in to Cursor." : "Cursor is signed out.")
        c.kind = "plan"; c.engine = "cursor-cli"; c.mark = "cursor"
        c.billingNote = "Runs on your Cursor plan."; c.modelNote = modelNote; c.signIn = "agent login"
        return c
    }

    private func response(selected: String, model: String = "auto", cursorConnected: Bool = true,
                          manual: (String, String) = ("cursor-cli", "auto")) -> SleepEngineResponse {
        SleepEngineResponse(
            mode: selected, model: model, disambiguationModel: "", source: "prefs",
            candidates: [
                SleepEngineCandidate(id: "auto", label: "Auto", available: true, connected: false, models: [], detail: nil),
                SleepEngineCandidate(id: "agent", label: "Claude plan", available: true, connected: true,
                                     models: ["sonnet"], detail: nil),
                cursor(connected: cursorConnected),
                SleepEngineCandidate(id: "byok", label: "API key", available: true, connected: true, models: [], detail: nil),
            ],
            preview: SleepEnginePreviews(manual: SleepEnginePreview(engine: manual.0, model: manual.1, why: "chosen"),
                                         scheduled: SleepEnginePreview(engine: "none", model: "", why: "ruling 4")))
    }

    func testTheNewFieldsDecodeAndAnOlderBodyStillDecodes() throws {
        let c = try JSONDecoder().decode(SleepEngineCandidate.self, from: Data(Self.cursorJSON.utf8))
        XCTAssertEqual(c.kind, "plan")
        XCTAssertEqual(c.engine, "cursor-cli")
        XCTAssertEqual(c.mark, "cursor")
        XCTAssertEqual(c.signIn, "agent login")
        XCTAssertNil(c.modelNote)
        let old = try JSONDecoder().decode(SleepEngineCandidate.self, from: Data(
            #"{"id":"agent","label":"Claude plan","available":true,"connected":true,"models":["sonnet"]}"#.utf8))
        XCTAssertNil(old.kind)
        XCTAssertTrue(EngineOption.isPlan(old), "an older backend's plan is still a plan by its id")
        XCTAssertFalse(EngineOption.isOwnTool(old))
    }

    func testADeclaredPlanNeedsASignInBeforeItIsChosen() {
        XCTAssertFalse(EngineOption.isSelectable(cursor(connected: false), selectedMode: "auto"))
        XCTAssertTrue(EngineOption.isSelectable(cursor(connected: true), selectedMode: "auto"))
        // A signed-out current pick stays visible and says why (R-E25).
        XCTAssertTrue(EngineOption.isSelectable(cursor(connected: false), selectedMode: "cursor"))
        XCTAssertNil(EngineWrite.choosing(cursor(connected: false), current: "auto"))
        XCTAssertEqual(EngineWrite.choosing(cursor(connected: true), current: "auto"),
                       EngineWrite(mode: "cursor", model: "auto"))
    }

    func testTheCardWearsItsDeclaredMarkAndCostModel() {
        XCTAssertEqual(EngineOption.logoName(for: cursor(connected: true)), "cursor")
        XCTAssertEqual(EngineOption.costModel(for: cursor(connected: true)), Copy.costModelPlan)
        XCTAssertEqual(EngineOption.caption(for: cursor(connected: false)), "Not signed in")
    }

    func testARunOnTheToolIsNamedAndMarkedByItsCard() {
        let body = response(selected: "cursor")
        XCTAssertEqual(EngineOption.previewName(engine: "cursor-cli", model: "auto", candidates: body.candidates), "Cursor")
        XCTAssertEqual(EngineOption.previewMark(engine: "cursor-cli", candidates: body.candidates), "cursor")
        XCTAssertEqual(EngineOption.candidateId(forEngine: "cursor-cli", candidates: body.candidates), "cursor")
        XCTAssertEqual(EngineMark.source(for: "cursor-cli"), .logo("cursor"))
        XCTAssertEqual(EngineMark.source(for: "litellm"), .symbol("key"))
        XCTAssertEqual(Copy.engineLabel("grok-cli"), "Grok (your plan)")
    }

    func testReadinessFollowsTheToolsSignIn() {
        let ready = response(selected: "cursor")
        XCTAssertEqual(EngineReadiness.resolve(candidates: ready.candidates, connections: [], preview: ready.preview),
                       .ready(candidate: "cursor"))
        let out = response(selected: "cursor", cursorConnected: false)
        XCTAssertEqual(EngineReadiness.resolve(candidates: out.candidates, connections: [], preview: out.preview),
                       .needsChoice)
    }

    func testTheQuickMenuListsTheToolsModelsAndSaysAStaleOne() {
        var body = response(selected: "cursor", model: "gone-1")
        body = SleepEngineResponse(mode: body.mode, model: body.model, disambiguationModel: "", source: "prefs",
                                   candidates: body.candidates.map { $0.id == "cursor"
                                       ? cursor(connected: true, models: ["auto", "sonnet-5", "gone-1"],
                                                modelNote: "Cursor no longer lists gone-1.") : $0 },
                                   preview: body.preview)
        let menu = EngineQuickMenuModel.from(body)
        XCTAssertEqual(menu.models, ["auto", "sonnet-5", "gone-1"])
        XCTAssertEqual(menu.note, "Cursor no longer lists gone-1.")
        XCTAssertEqual(menu.rows.first { $0.id == "cursor" }?.logo, "cursor")
        XCTAssertEqual(EngineQuickMenuModel.buttonLabel(body), "Cursor · auto")
    }

    func testOnboardingKeepsItsFourAndTheToolsNeverJoinAutosSignInHint() {
        let body = response(selected: "auto", cursorConnected: false)
        XCTAssertFalse(EngineOption.compactCandidates(body.candidates).contains { $0.id == "cursor" })
        XCTAssertNil(EngineOption.signInHint(body.candidates), "the tool signs in in its own terminal, not Plans & keys")
    }
}
