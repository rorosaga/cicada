import SwiftUI
import XCTest
@testable import CicadaApp

/// The picker's open cost (engine-picker-v2, 2026-10-28): the menu's model built from a `/sleep/engine` body and drawn
/// once, as the popover draws it, for a Cursor card listing 31 models. Prints p50/p95 over 40 opens; fails only on a
/// gross regression (a p95 over 250 ms), never on a noisy machine's small one.
@MainActor
final class EnginePickerTimingTests: XCTestCase {
    static func longRoster() -> [String] {
        var ids = ["auto", "composer-2", "composer-1.5", "grok-4.7", "grok-4.6", "grok-4.5"]
        ids += ["sonnet-5", "opus-5.5", "sonnet-4.6", "opus-4.5", "haiku-4.5", "sonnet-4.5"]
        ids += ["gpt-6", "gpt-5.5", "gpt-5.5-mini", "gpt-5.4", "gpt-5.3-codex", "gpt-5.2", "gpt-5.1", "gpt-5", "o4-mini"]
        ids += ["gemini-3-pro", "gemini-3-flash", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-pro"]
        ids += ["kimi-k3", "kimi-k2.5", "deepseek-v4", "qwen-4-coder", "glm-5.2"]
        return ids
    }

    /// The backend's grouping for the roster (`model_catalogue.ordered`), written out: families in first-listed order.
    static func catalogue() -> ModelCatalogue {
        func fam(_ id: String) -> (String, String) {
            if ["auto", "composer"].contains(where: id.hasPrefix) { return ("own", "Cursor's own") }
            if ["sonnet", "opus", "haiku"].contains(where: id.hasPrefix) { return ("claude", "Claude") }
            if ["gpt", "o4"].contains(where: id.hasPrefix) { return ("gpt", "GPT") }
            if id.hasPrefix("gemini") { return ("gemini", "Gemini") }
            if id.hasPrefix("grok") { return ("grok", "Grok") }
            let first = String(id.prefix { $0.isLetter })
            return (first, first.capitalized)
        }
        let models = longRoster().map { id -> ModelCatalogue.Model in
            let (key, label) = fam(id)
            return ModelCatalogue.Model(id: id, source: "harness", asOf: "2026-10-28T10:00:00Z", family: key,
                                        familyLabel: label, firstSeen: id == "gpt-6" ? "2026-10-27" : nil,
                                        new: id == "gpt-6")
        }
        return ModelCatalogue(engine: "cursor-cli", asOf: "2026-10-28T10:00:00Z", source: "agent models",
                              models: models)
    }

    static func response() -> SleepEngineResponse {
        SleepEngineResponse(
            mode: "cursor", model: "sonnet-5", disambiguationModel: "", source: "prefs",
            candidates: [
                SleepEngineCandidate(id: "auto", label: "Auto", available: true, connected: false, models: [], detail: nil),
                SleepEngineCandidate(id: "agent", label: "Claude plan", available: true, connected: true,
                                     models: ["sonnet", "haiku", "opus", "fable"], detail: nil),
                SleepEngineCandidate(id: "cursor", label: "Cursor", available: true, connected: true,
                                     models: longRoster(), detail: "Signed in to Cursor.", kind: "plan",
                                     engine: "cursor-cli", mark: "cursor", catalogue: catalogue()),
                SleepEngineCandidate(id: "byok", label: "API key", available: true, connected: true, models: [], detail: nil),
            ],
            preview: SleepEnginePreviews(manual: SleepEnginePreview(engine: "cursor-cli", model: "sonnet-5", why: "chosen"),
                                         scheduled: SleepEnginePreview(engine: "cursor-cli", model: "sonnet-5",
                                                                       why: "chosen")))
    }

    func testThePickerOpensQuickly() {
        let body = Self.response()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        var times: [Double] = []
        for _ in 0..<40 {
            let start = Date()
            let model = EngineQuickMenuModel.from(body)
            let renderer = ImageRenderer(content: EngineQuickMenu(model: model, choose: { _ in }, pickModel: { _ in },
                                                                  openSettings: { _, _ in })
                .frame(width: EngineQuickMenu.width(for: model)).environment(store))
            _ = renderer.nsImage
            times.append(Date().timeIntervalSince(start) * 1000)
        }
        times.sort()
        let p50 = times[times.count / 2], p95 = times[Int(Double(times.count - 1) * 0.95)]
        print(String(format: "PICKER_OPEN_MS p50=%.1f p95=%.1f n=%d", p50, p95, times.count))
        XCTAssertLessThan(p95, 250)
    }
}
