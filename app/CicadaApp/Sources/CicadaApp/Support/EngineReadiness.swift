import Foundation

/// Track I T6 (design §4.1.5) — can the engine the NEXT manual read resolves to
/// actually run? `.ready` rings that card and lets Read now start a cycle;
/// `.needsChoice` makes Read now ask first. An untouched choice stays `auto`
/// (`sleep_engine_prefs.py:104-107`) — this only reads.
enum EngineReadiness: Equatable {
    case ready(candidate: String)
    case needsChoice

    /// `ENGINE_LABELS` id → `GET /sleep/engine` candidate id. R-AG12: a `litellm` run on an
    /// `openrouter/` model is the OpenRouter card (the server's `selected_card` rule), so onboarding
    /// rings OpenRouter, not the API key, when OpenRouter will read.
    static func candidateId(forEngine engine: String, model: String? = nil) -> String? {
        switch engine {
        case "claude-cli": "agent"
        case "codex-cli": "codex"
        case "ollama": "local"
        case "litellm": EngineOption.runsOnOpenRouter(model) ? "openrouter" : "byok"
        default: nil
        }
    }

    /// F6: a usage-billed connection that is connected — a real key.
    static func hasKey(_ connections: [ConnectionStatus]) -> Bool {
        connections.contains { $0.kind == "usage" && $0.connected }
    }

    static func connected(_ id: String, _ candidates: [SleepEngineCandidate]) -> Bool {
        candidates.first { $0.id == id }?.connected ?? false
    }

    static func ollamaReady(_ candidates: [SleepEngineCandidate]) -> Bool {
        candidates.first { $0.id == "local" }.map { OllamaGuideState.from(candidate: $0) == .ready } ?? false
    }

    static func resolve(candidates: [SleepEngineCandidate], connections: [ConnectionStatus],
                        preview: SleepEnginePreviews?) -> EngineReadiness {
        guard let engine = preview?.manual.engine,
              let id = candidateId(forEngine: engine, model: preview?.manual.model) else { return .needsChoice }
        let canRun: Bool
        switch id {
        case "agent", "codex": canRun = connected(id, candidates)
        case "local": canRun = ollamaReady(candidates)
        // `byok` and `openrouter` alike: a usage key is what lets either run (F6).
        default: canRun = hasKey(connections)
        }
        return canRun ? .ready(candidate: id) : .needsChoice
    }
}
