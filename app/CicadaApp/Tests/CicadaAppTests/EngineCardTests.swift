import SwiftUI
import XCTest
@testable import CicadaApp

/// G122 — the Settings → Engines engine-and-model picker. `OllamaGuideState`
/// is a pure state machine over a `SleepEngineCandidate` (no network, no
/// view), `EngineChooser.previewLine` is a pure formatter over one
/// `SleepEnginePreview` (ruling 4's two-line display), and
/// `SleepEngineResponse` must decode a payload from before `candidates`/
/// `preview` existed on the wire without crashing (decode tolerance).
@MainActor
final class EngineCardTests: XCTestCase {

    private func candidate(
        available: Bool, connected: Bool = false, models: [String] = []
    ) -> SleepEngineCandidate {
        SleepEngineCandidate(
            id: "local", label: "Ollama (local)", available: available,
            connected: connected, models: models, detail: nil
        )
    }

    func testOllamaGuideStateProgression() {
        let notInstalled = OllamaGuideState.from(candidate: candidate(available: false))
        XCTAssertEqual(notInstalled, .notInstalled)
        XCTAssertEqual(notInstalled.command, "brew install ollama")

        let notRunning = OllamaGuideState.from(candidate: candidate(available: true, connected: false))
        XCTAssertEqual(notRunning, .notRunning)
        XCTAssertEqual(notRunning.command, "ollama serve")

        let noModel = OllamaGuideState.from(candidate: candidate(available: true, connected: true, models: []))
        XCTAssertEqual(noModel, .noModel)
        XCTAssertEqual(noModel.command, "ollama pull llama3.1")

        let ready = OllamaGuideState.from(
            candidate: candidate(available: true, connected: true, models: ["llama3.1"])
        )
        XCTAssertEqual(ready, .ready)
        XCTAssertNil(ready.command)
    }

    /// The engine half of each preview line is exactly `Copy.engineLabel`'s
    /// existing three-way mapping — never a fresh coinage that could drift
    /// from what the rest of the app already calls each engine.
    func testPreviewLineFormatting() {
        let manual = SleepEnginePreview(engine: "claude-cli", model: "sonnet", why: "user-triggered")
        XCTAssertEqual(
            EngineChooser.previewLine(manual, label: Copy.EngineMenu.whenYouStart),
            "\(Copy.EngineMenu.whenYouStart): \(Copy.engineLabel("claude-cli")) · sonnet"
        )

        let scheduled = SleepEnginePreview(engine: "litellm", model: "gpt-5.4-mini", why: "scheduled cycle")
        XCTAssertEqual(
            EngineChooser.previewLine(scheduled, label: Copy.EngineMenu.scheduledCycles),
            "\(Copy.EngineMenu.scheduledCycles): \(Copy.engineLabel("litellm")) · gpt-5.4-mini"
        )
    }

    /// A payload cached before this feature's `candidates`/`preview` fields
    /// existed on the wire must still decode — the Sleep settings page reads
    /// this from disk before the first network round-trip.
    func testDecodesAnOlderPayloadMissingCandidatesAndPreview() throws {
        let json = #"{"mode":"byok","model":"gpt-5.4-mini","disambiguationModel":"gpt-5.4-nano","source":"default"}"#
        let response = try JSONDecoder().decode(SleepEngineResponse.self, from: Data(json.utf8))
        XCTAssertEqual(response.mode, "byok")
        XCTAssertEqual(response.model, "gpt-5.4-mini")
        XCTAssertEqual(response.disambiguationModel, "gpt-5.4-nano")
        XCTAssertEqual(response.source, "default")
        XCTAssertEqual(response.candidates, [])
        XCTAssertNil(response.preview)
    }

    /// The full shape (what Task 1's backend always sends) still decodes
    /// correctly — the tolerant path must never swallow real data.
    func testDecodesTheFullShape() throws {
        let json = """
        {"mode":"agent","model":"sonnet","disambiguationModel":"haiku","source":"prefs",
         "candidates":[{"id":"agent","label":"Claude Code (your plan)","available":true,
                        "connected":true,"models":["sonnet","haiku"],"detail":"Signed in."}],
         "preview":{"manual":{"engine":"claude-cli","model":"sonnet","why":"user-triggered"},
                    "scheduled":{"engine":"litellm","model":"gpt-5.4-mini","why":"scheduled cycle"}}}
        """
        let response = try JSONDecoder().decode(SleepEngineResponse.self, from: Data(json.utf8))
        XCTAssertEqual(response.candidates.count, 1)
        XCTAssertEqual(response.candidates.first?.id, "agent")
        XCTAssertEqual(response.preview?.manual.engine, "claude-cli")
        XCTAssertEqual(response.preview?.scheduled.model, "gpt-5.4-mini")
    }

    func testTheCodexPreviewLineNamesTheChatGPTPlan() {
        let manual = SleepEnginePreview(engine: "codex-cli", model: "gpt-5.6-luna",
                                        why: "Sleep engine set to 'codex' in Settings")
        XCTAssertEqual(EngineChooser.previewLine(manual, label: Copy.EngineMenu.whenYouStart),
                       "\(Copy.EngineMenu.whenYouStart): Codex (your ChatGPT plan) · gpt-5.6-luna")
    }

    func testAllowOverageDecodesTolerantly() throws {
        let old = #"{"mode":"agent","model":"sonnet","disambiguationModel":"haiku","source":"prefs"}"#
        XCTAssertFalse(try JSONDecoder().decode(SleepEngineResponse.self, from: Data(old.utf8)).allowOverage)
        let new = #"{"mode":"agent","model":"sonnet","disambiguationModel":"haiku","source":"prefs","allowOverage":true}"#
        XCTAssertTrue(try JSONDecoder().decode(SleepEngineResponse.self, from: Data(new.utf8)).allowOverage)
    }

    /// G122 live pass — `GridItem.adaptive`'s column count and one height per row: the tallest card's.
    func testTheCardGridCountsColumnsLikeAdaptiveAndSizesARowByItsTallestCard() {
        XCTAssertEqual(EngineCardGrid.columns(width: 532, minimum: 112, spacing: 8, count: 6), 4)
        XCTAssertEqual(EngineCardGrid.columns(width: 240, minimum: 112, spacing: 8, count: 6), 2)
        XCTAssertEqual(EngineCardGrid.columns(width: 60, minimum: 112, spacing: 8, count: 6), 1, "never fewer than one")
        XCTAssertEqual(EngineCardGrid.columns(width: .infinity, minimum: 112, spacing: 8, count: 6), 6)
        XCTAssertEqual(EngineCardGrid.rowHeights([80, 104, 80, 80, 92, 80], columns: 4), [104, 92])
        XCTAssertEqual(EngineCardGrid.rowHeights([], columns: 4), [])
    }

    /// G122 live pass — in onboarding's column (1200 × 800) and Settings' panel, at every zoom, OpenRouter's cost line
    /// and caption no longer make it taller than Auto and the plans in its row: every card in a row is one height.
    func testEveryCardInARowIsOneHeight() throws {
        final class Heights { var byID: [String: CGFloat] = [:] }
        let saved = CicadaTheme.uiScale
        defer { CicadaTheme.uiScale = saved }
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let cards = [("auto", "Auto"), ("agent", "Claude plan"), ("codex", "ChatGPT plan"), ("openrouter", "OpenRouter")]
            .map { SleepEngineCandidate(id: $0.0, label: $0.1, available: true, connected: true, models: [], detail: nil) }
        for scale in [1.0, 1.2, 1.4] {
            CicadaTheme.uiScale = scale
            let heights = Heights()
            let grid = EngineCardGrid(minimum: CicadaTheme.scaled(112), spacing: CicadaTheme.spacingSM) {
                ForEach(cards) { candidate in
                    EngineOptionCard(candidate: candidate, isSelected: candidate.id == "auto", isSelectable: true,
                                     costModel: candidate.id == "openrouter"
                                         ? EngineOption.costModel(for: candidate.id) : nil) {}
                        .background(GeometryReader { proxy -> Color in
                            heights.byID[candidate.id] = proxy.size.height
                            return Color.clear
                        })
                }
            }
            .environment(store)
            let width = 532 * CGFloat(scale)
            let renderer = ImageRenderer(content: grid)
            renderer.proposedSize = ProposedViewSize(width: width, height: nil)
            _ = try XCTUnwrap(renderer.nsImage)
            let columns = EngineCardGrid.columns(width: width, minimum: CicadaTheme.scaled(112),
                                                 spacing: CicadaTheme.spacingSM, count: cards.count)
            for row in stride(from: 0, to: cards.count, by: columns) {
                let ids = cards[row..<min(row + columns, cards.count)].map(\.id)
                let row = ids.compactMap { heights.byID[$0] }
                XCTAssertEqual(row.count, ids.count, "\(scale): every card laid out")
                XCTAssertEqual((row.max() ?? 0) - (row.min() ?? 0), 0, accuracy: 0.5, "\(scale): \(ids) \(row)")
            }
        }
    }
}
