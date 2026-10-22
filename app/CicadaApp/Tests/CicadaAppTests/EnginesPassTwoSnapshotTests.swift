import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Review renders for Settings → Engines, Auto first (settings defaults pass 2, 2026-10-22): the states a verify run
/// can't reach, because its backend fixes the engine. Synthetic responses only, light and dark, offscreen.
/// Env-gated: `CICADA_ENGINES_SNAPSHOTS=<dir>`.
@MainActor
final class EnginesPassTwoSnapshotTests: XCTestCase {
    private func candidate(_ id: String, _ label: String, available: Bool = true, connected: Bool = true,
                           detail: String? = nil) -> SleepEngineCandidate {
        SleepEngineCandidate(id: id, label: label, available: available, connected: connected, models: [], detail: detail)
    }

    private func response(selected: String, engine: String, claudeSignedIn: Bool = true) -> SleepEngineResponse {
        let candidates = [
            candidate("auto", "Auto", detail: "Your Claude plan if it's signed in, else your ChatGPT plan, else Ollama."),
            candidate("agent", "Claude plan", connected: claudeSignedIn),
            candidate("codex", "ChatGPT plan", connected: !claudeSignedIn),
            candidate("openrouter", "OpenRouter", connected: false, detail: "Sign in with OpenRouter, or paste a key."),
            candidate("local", "Ollama", available: false, connected: false),
            candidate("byok", "API key", detail: "Your own key from Anthropic, OpenAI, Gemini, xAI, Groq or Mistral."),
        ]
        let preview = SleepEnginePreview(engine: engine, model: "", why: "")
        return SleepEngineResponse(mode: selected, model: "", disambiguationModel: "", source: "prefs",
                                   candidates: candidates,
                                   preview: SleepEnginePreviews(manual: preview, scheduled: preview), selected: selected)
    }

    func test_writeTheEnginesStates() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_ENGINES_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_ENGINES_SNAPSHOTS=<dir> to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        let out = URL(fileURLWithPath: dir)
        let suite = "cicada.snapshot.engines.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }

        let states: [(String, SleepEngineResponse, Bool)] = [
            ("auto-claude-plan", response(selected: "auto", engine: "claude-cli"), false),
            ("auto-nothing-yet", response(selected: "auto", engine: "none", claudeSignedIn: false), false),
            ("chosen-chatgpt-plan", response(selected: "codex", engine: "codex-cli", claudeSignedIn: false), false),
            ("auto-fold-open", response(selected: "auto", engine: "claude-cli"), true),
        ]
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let name = mode == .dark ? "dark" : "light"
            for (state, body, open) in states {
                defaults.set(open, forKey: EngineChooser.othersOpenKey)
                let store = Store(cache: SnapshotCache(
                    root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
                ), api: FakeSyncAPI())
                let vm = SleepEngineViewModel(fetch: { body }, update: { _, _, _, _ in body })
                await vm.load()
                let page = EnginesView()
                    .environment(vm)
                    .environment(store)
                    .environment(ConnectionsViewModel(store: store))
                    .defaultAppStorage(defaults)
                    .frame(width: 640, alignment: .topLeading)
                    .background(CicadaTheme.bgBase)
                try snapshot(page, size: CGSize(width: 640, height: open ? 860 : 560), mode: mode,
                             to: out.appendingPathComponent("engines-\(state)-\(name).png"))
            }
        }
    }

    private func snapshot<V: View>(_ view: V, size: CGSize, mode: AppColorScheme, to url: URL) throws {
        let host = NSHostingView(rootView: view.environment(\.colorScheme, mode == .dark ? .dark : .light))
        host.frame = NSRect(origin: .zero, size: size)
        let window = NSWindow(contentRect: host.frame.offsetBy(dx: -20_000, dy: -20_000), styleMask: [.borderless],
                              backing: .buffered, defer: false)
        window.appearance = NSAppearance(named: mode == .dark ? .darkAqua : .aqua)
        window.contentView = host
        window.orderFrontRegardless()
        defer { window.orderOut(nil) }
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.4))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}
