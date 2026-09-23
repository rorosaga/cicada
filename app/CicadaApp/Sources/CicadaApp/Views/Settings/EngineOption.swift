import Foundation

/// R-E4 / R-E25 — every decision Settings → Sleep's engine row makes, as pure
/// functions with table tests, so `EngineCard` is a renderer.
///
/// The row is `GET /sleep/engine`'s five candidates in the server's order
/// (Auto, Claude plan, ChatGPT plan, Ollama, API key). Marks come through
/// `ConnectionMark` — the translation Plans & keys uses — so the two surfaces
/// never disagree about what a plan looks like.
enum EngineOption {
    /// The two cards that spend a subscription (ruling 4's `SUBSCRIPTION_MODES`).
    static let planIds: Set<String> = ["agent", "codex"]

    /// R-E25: a plan card is selectable once that plan is signed in, or when
    /// it is already the saved choice — a signed-out current pick stays
    /// visible (and says why) instead of vanishing. The server accepts any
    /// valid mode; this is UX, not validation.
    static func isSelectable(_ candidate: SleepEngineCandidate, selectedMode: String) -> Bool {
        guard planIds.contains(candidate.id) else { return true }
        return candidate.connected || candidate.id == selectedMode
    }

    static func caption(for candidate: SleepEngineCandidate) -> String {
        switch candidate.id {
        case "auto": return "Picks for you"
        case "byok": return "Uses your key"
        case "local":
            switch OllamaGuideState.from(candidate: candidate) {
            case .notInstalled: return "Not installed"
            case .notRunning: return "Not running"
            case .noModel: return "No model yet"
            case .ready: return "Ready"
            }
        default:
            if !candidate.available { return "Not installed" }
            return candidate.connected ? "Signed in" : "Not signed in"
        }
    }

    static func connectionId(for candidateId: String) -> String? {
        switch candidateId {
        case "agent": "claude-plan"
        case "codex": "chatgpt-plan"
        case "local": "ollama-local"
        default: nil
        }
    }

    static func logoName(for candidateId: String) -> String? {
        connectionId(for: candidateId).flatMap { ConnectionMark.logoName(connectionId: $0) }
    }

    static func symbol(for candidateId: String) -> String {
        switch candidateId {
        case "auto": "sparkles"
        case "byok": "key.fill"
        default: "cpu"
        }
    }

    /// "To use your ChatGPT plan, sign in on" + a Plans & keys link — only for
    /// an INSTALLED plan that is signed out (installing is its own step, named
    /// on the card).
    static func signInHint(_ candidates: [SleepEngineCandidate]) -> String? {
        let names = candidates
            .filter { planIds.contains($0.id) && $0.available && !$0.connected }
            .map(\.label)
        guard !names.isEmpty else { return nil }
        return "To use your \(names.joined(separator: " or ")), sign in on"
    }

    /// R-E13: extra usage is a Claude-only choice and only matters where a
    /// cycle can run on the Claude plan — chosen outright, or through Auto.
    static func showsOverageToggle(selectedMode: String) -> Bool {
        selectedMode == "agent" || selectedMode == "auto"
    }
}
