import SwiftUI
import XCTest
@testable import CicadaApp

/// The owner's quick switch (2026-09-23) — R-HS7…R-HS13. Every string it shows and every write it
/// makes is decided here, from synthetic `/sleep/engine` bodies; nothing reaches `APIClient.shared`.
@MainActor
final class EngineQuickMenuTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private static let autoDetail = "Your Claude plan if it's signed in, else your ChatGPT plan, else Ollama if it's running, else your API key."
    private static let keyDetail = "Uses the model configured on the Plans & keys page."

    private func response(mode: String, model: String = "sonnet", codexSignedIn: Bool = true,
                          manual: (String, String) = ("claude-cli", "sonnet"),
                          scheduled: (String, String) = ("litellm", "example-model"),
                          localModels: [String] = [], localAvailable: Bool = false) -> SleepEngineResponse {
        SleepEngineResponse(
            mode: mode, model: model, disambiguationModel: "", source: "prefs",
            candidates: [
                SleepEngineCandidate(id: "auto", label: "Auto", available: true, connected: false, models: [],
                                     detail: Self.autoDetail),
                SleepEngineCandidate(id: "agent", label: "Claude plan", available: true, connected: true,
                                     models: ["sonnet", "haiku", "opus"], detail: nil),
                SleepEngineCandidate(id: "codex", label: "ChatGPT plan", available: true, connected: codexSignedIn,
                                     models: codexSignedIn ? ["example-codex-model"] : [], detail: nil),
                SleepEngineCandidate(id: "local", label: "Ollama", available: localAvailable,
                                     connected: localAvailable, models: localModels, detail: nil),
                SleepEngineCandidate(id: "byok", label: "API key", available: true, connected: true, models: [],
                                     detail: Self.keyDetail),
            ],
            preview: SleepEnginePreviews(manual: SleepEnginePreview(engine: manual.0, model: manual.1, why: "chosen"),
                                         scheduled: SleepEnginePreview(engine: scheduled.0, model: scheduled.1,
                                                                       why: "ruling 4")))
    }

    // MARK: The button (R-HS8)

    func testTheButtonNamesWhatACycleYouStartWouldRun() {
        XCTAssertEqual(EngineQuickMenuModel.buttonLabel(response(mode: "auto")), "Auto · Claude plan · sonnet")
        XCTAssertEqual(EngineQuickMenuModel.buttonLabel(response(mode: "agent", model: "haiku",
                                                                 manual: ("claude-cli", "haiku"))),
                       "Claude plan · haiku")
        XCTAssertEqual(EngineQuickMenuModel.buttonLabel(response(mode: "byok", manual: ("litellm", "example-model"))),
                       "API key · example-model")
        XCTAssertEqual(EngineQuickMenuModel.buttonLabel(response(mode: "codex", manual: ("codex-cli", "default model"))),
                       "ChatGPT plan · default model")
        XCTAssertNil(EngineQuickMenuModel.buttonLabel(nil), "R-A7 — a guessed engine is worse than silence")
        let noPreview = SleepEngineResponse(mode: "auto", model: "", disambiguationModel: "", source: "default",
                                            candidates: [], preview: nil)
        XCTAssertNil(EngineQuickMenuModel.buttonLabel(noPreview))
    }

    // MARK: The rows (R-HS7, DR-52)

    func testTheRowsAreTheFiveEnginesInTheServersOrderWithTheirMarks() {
        let model = EngineQuickMenuModel.from(response(mode: "agent"))
        XCTAssertEqual(model.rows.map(\.id), ["auto", "agent", "codex", "local", "byok"])
        XCTAssertEqual(model.rows.filter(\.isSelected).map(\.id), ["agent"])
        XCTAssertNotNil(model.rows.first { $0.id == "agent" }?.logo, "the Claude plan wears its real mark")
        XCTAssertNotNil(model.rows.first { $0.id == "codex" }?.logo, "the ChatGPT plan wears its real mark")
        XCTAssertEqual(model.rows.first { $0.id == "auto" }?.symbol, "sparkles")
        XCTAssertEqual(model.rows.first { $0.id == "byok" }?.symbol, "key.fill")
        XCTAssertEqual(model.rows.first { $0.id == "auto" }?.caption, "Picks for you")
    }

    /// R-E25 — a signed-out plan stays listed and says why; the current pick is never locked out.
    func testASignedOutPlanStaysListedAndSaysWhy() {
        let out = EngineQuickMenuModel.from(response(mode: "agent", codexSignedIn: false))
        let codex = out.rows.first { $0.id == "codex" }
        XCTAssertEqual(codex?.isSelectable, false)
        XCTAssertEqual(codex?.help, Copy.EngineMenu.signInFirst("ChatGPT plan"))
        let current = EngineQuickMenuModel.from(response(mode: "codex", codexSignedIn: false))
        XCTAssertEqual(current.rows.first { $0.id == "codex" }?.isSelectable, true)
    }

    // MARK: The model section (R-HS10)

    func testTheModelSectionFollowsTheChosenEngine() {
        let agent = EngineQuickMenuModel.from(response(mode: "agent"))
        XCTAssertEqual(agent.models, ["sonnet", "haiku", "opus"])
        XCTAssertEqual(agent.selectedModel, "sonnet")
        XCTAssertEqual(agent.modelLabel, Copy.EngineMenu.model)
        XCTAssertNil(agent.note)

        let auto = EngineQuickMenuModel.from(response(mode: "auto"))
        XCTAssertEqual(auto.models, [])
        XCTAssertEqual(auto.modelLabel, Copy.EngineMenu.howAutoPicks)
        XCTAssertEqual(auto.note, Self.autoDetail, "the backend's own words for the ladder")

        let key = EngineQuickMenuModel.from(response(mode: "byok", manual: ("litellm", "example-model")))
        XCTAssertEqual(key.note, Self.keyDetail)
        XCTAssertTrue(key.showsPlansAndKeysLink)

        let local = EngineQuickMenuModel.from(response(mode: "local", manual: ("ollama", "")))
        XCTAssertEqual(local.command, "brew install ollama", "the one command that fixes the current state")
        let ready = EngineQuickMenuModel.from(response(mode: "local", model: "example-local",
                                                       manual: ("ollama", "example-local"),
                                                       localModels: ["example-local"], localAvailable: true))
        XCTAssertNil(ready.command)
        XCTAssertEqual(ready.models, ["example-local"])
    }

    // MARK: Ruling 4 stays visible (R-HS11)

    func testBothPreviewsAlwaysShowAndTheRulingOnlyWhenTheyDiffer() {
        let differ = EngineQuickMenuModel.from(response(mode: "agent"))
        XCTAssertEqual(differ.previews.map(\.label), [Copy.EngineMenu.whenYouStart, Copy.EngineMenu.scheduledCycles])
        XCTAssertEqual(differ.previews.map(\.text),
                       ["\(Copy.engineLabel("claude-cli")) · sonnet", "\(Copy.engineLabel("litellm")) · example-model"])
        XCTAssertTrue(differ.showsRuling)
        let same = EngineQuickMenuModel.from(response(mode: "byok", manual: ("litellm", "example-model")))
        XCTAssertEqual(same.previews.count, 2, "both lines, always")
        XCTAssertFalse(same.showsRuling)
    }

    // MARK: One write rule (R-HS7)

    func testATapWritesThroughTheOneRule() {
        let r = response(mode: "auto")
        let byId = Dictionary(uniqueKeysWithValues: r.candidates.map { ($0.id, $0) })
        XCTAssertEqual(EngineWrite.choosing(byId["agent"]!, current: "auto"), EngineWrite(mode: "agent", model: "sonnet"))
        XCTAssertEqual(EngineWrite.choosing(byId["byok"]!, current: "auto"), EngineWrite(mode: "byok", model: nil))
        XCTAssertNil(EngineWrite.choosing(byId["auto"]!, current: "auto"), "the current engine writes nothing")
        let out = Dictionary(uniqueKeysWithValues: response(mode: "agent", codexSignedIn: false).candidates.map { ($0.id, $0) })
        XCTAssertNil(EngineWrite.choosing(out["codex"]!, current: "agent"), "a signed-out plan writes nothing")
        XCTAssertEqual(EngineWrite.model("haiku", mode: "agent", current: "sonnet"), EngineWrite(mode: "agent", model: "haiku"))
        XCTAssertNil(EngineWrite.model("sonnet", mode: "agent", current: "sonnet"))
        XCTAssertNil(EngineWrite.model("  ", mode: "agent", current: "sonnet"))
    }

    /// R-HS12 — the page reads the chooser's echo first, so a switch anywhere shows at once.
    func testThePageReadsTheChoosersPreviewFirst() {
        let chooser = response(mode: "agent")
        let page = SleepEnginePreviews(manual: SleepEnginePreview(engine: "litellm", model: "old", why: ""),
                                       scheduled: SleepEnginePreview(engine: "litellm", model: "old", why: ""))
        XCTAssertEqual(SleepEnginePreviewSource.current(chooser: chooser, page: page), chooser.preview)
        XCTAssertEqual(SleepEnginePreviewSource.current(chooser: nil, page: page), page)
        XCTAssertNil(SleepEnginePreviewSource.current(chooser: nil, page: nil))
    }

    /// A failed write says so in words and changes nothing; the next good one clears it
    /// (the old model never cleared `errorMessage`).
    func testAFailedWriteSaysSoAndTheNextOneClearsIt() async {
        struct Refused: Error {}
        var fail = true
        // Built here, on the main actor: the closures below are nonisolated, as the real ones are.
        let start = response(mode: "auto")
        let after = response(mode: "agent", model: "haiku", manual: ("claude-cli", "haiku"))
        let vm = SleepEngineViewModel(fetch: { start }, update: { _, _, _, _ in
            if fail { throw Refused() }
            return after
        })
        await vm.load()
        await vm.apply(EngineWrite(mode: "agent", model: "haiku"))
        XCTAssertTrue(vm.writeFailed)
        XCTAssertEqual(vm.response?.mode, "auto", "nothing changed")
        XCTAssertFalse(vm.isSaving)
        fail = false
        await vm.apply(EngineWrite(mode: "agent", model: "haiku"))
        XCTAssertFalse(vm.writeFailed)
        XCTAssertNil(vm.errorMessage)
        XCTAssertEqual(vm.response?.mode, "agent")
    }

    // MARK: Marks (R-HS13)

    func testEveryEngineWearsItsVendorsMark() {
        XCTAssertEqual(EngineMark.source(for: "claude-cli"), .origin("claude-code"))
        if case .logo = EngineMark.source(for: "codex-cli") {} else {
            XCTFail("the ChatGPT plan has a real mark — never the key (DR-52)")
        }
        XCTAssertEqual(EngineMark.source(for: "ollama"), .logo("ollama"))
        XCTAssertEqual(EngineMark.source(for: "litellm"), .symbol("key"))
    }

    // MARK: No price, ever (2026-09-03)

    func testNoPriceOrTokenAnywhereInTheMenu() {
        for r in [response(mode: "auto"), response(mode: "agent", codexSignedIn: false),
                  response(mode: "byok", manual: ("litellm", "example-model")), response(mode: "local")] {
            let m = EngineQuickMenuModel.from(r)
            let words = m.rows.flatMap { [$0.label, $0.caption, $0.help] } + m.previews.flatMap { [$0.label, $0.text] }
                + [m.modelLabel, m.note ?? "", EngineQuickMenuModel.buttonLabel(r) ?? ""]
            for w in words {
                for banned in ["$", "token", "price", "cost", "%"] {
                    XCTAssertFalse(w.lowercased().contains(banned), "\"\(w)\" contains \"\(banned)\"")
                }
            }
        }
    }

    // MARK: It fits its column (DR-70)

    /// Nothing in the menu is rigid: offered its width at every zoom and in both themes, it never asks
    /// for more (a rigid child — a long model tag, a fixed frame — is how a popover grows past its
    /// design). The menu is measured UNFRAMED, as `InboxFocusCardFitTests` measures the focus card:
    /// `EngineQuickMenuButton` applies the fixed width when it presents it, so a fixed frame here
    /// would make this assertion true by construction.
    func testTheMenuFitsItsWidthAtEveryZoomAndTheme() throws {
        // `LogoImage` (the rows' marks, `EngineMark`) reads the Store from the environment.
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let long = "example-local-model-with-a-very-long-tag:8b-instruct-q4"
        let r = response(mode: "local", model: long, manual: ("ollama", long), localModels: [long], localAvailable: true)
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for scale in [0.8, 1.0, 1.4] {
                CicadaTheme.uiScale = scale
                let width = EngineQuickMenu.width * CGFloat(scale)
                let renderer = ImageRenderer(content: EngineQuickMenu(model: .from(r), choose: { _ in },
                                                                      pickModel: { _ in }, openSettings: { _, _ in })
                    .environment(store))
                renderer.proposedSize = ProposedViewSize(width: width, height: nil)
                let size = try XCTUnwrap(renderer.nsImage).size
                XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(mode) × \(scale) wants \(size.width)")
                XCTAssertGreaterThan(size.height, 80, "\(mode) × \(scale) rendered nothing")
            }
        }
    }

    // MARK: One write path (R-HS7)

    func testTheSleepPageWritesTheEngineOnlyThroughTheChoosersModel() throws {
        for file in try ThemeTokenTests.swiftSources() where file.path.contains("/Views/Sleep/") {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("updateSleepEngine("), "\(file.lastPathComponent) writes around the model")
            XCTAssertFalse(text.contains("\"/sleep/engine\""), file.lastPathComponent)
        }
        let menu = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Sleep/EngineQuickMenu.swift") })
        XCTAssertTrue(try String(contentsOf: menu, encoding: .utf8).contains("engineVM.apply("))
    }
}
