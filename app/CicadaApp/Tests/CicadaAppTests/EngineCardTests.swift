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
}
