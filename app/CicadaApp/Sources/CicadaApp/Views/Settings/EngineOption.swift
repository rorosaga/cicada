import Foundation

/// R-E4 / R-E25 — every decision the engine row (Settings → Engines since
/// G139) makes, as pure functions with table tests, so `EngineChooser` is a
/// renderer.
///
/// The row is `GET /sleep/engine`'s five candidates in the server's order
/// (Auto, Claude plan, ChatGPT plan, Ollama, API key). Marks come through
/// `ConnectionMark` — the translation Plans & keys uses — so the two surfaces
/// never disagree about what a plan looks like.
enum EngineOption {
    /// The two cards that spend a subscription (ruling 4's `SUBSCRIPTION_MODES`).
    static let planIds: Set<String> = ["agent", "codex"]

    /// The cards that need a sign-in before they can run: the two plans, and OpenRouter (R-AG12),
    /// which is a key card but one you sign in to. It is NOT a plan — ruling 4 never sees it.
    static let signInIds: Set<String> = planIds.union(["openrouter"])

    /// R-E25: a sign-in card is selectable once it is signed in, or when
    /// it is already the saved choice — a signed-out current pick stays
    /// visible (and says why) instead of vanishing. The server accepts any
    /// valid mode; this is UX, not validation. `selectedMode` is the selected CARD.
    static func isSelectable(_ candidate: SleepEngineCandidate, selectedMode: String) -> Bool {
        guard signInIds.contains(candidate.id) else { return true }
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
        // R-AG12/R-AG9 — the OpenRouter card is its own card and wears OpenRouter's mark.
        case "openrouter": "byok-openrouter"
        default: nil
        }
    }

    static func logoName(for candidateId: String) -> String? {
        connectionId(for: candidateId).flatMap { ConnectionMark.logoName(connectionId: $0) }
    }

    /// The mark beside a "What runs" line — the same vendor mark the chosen
    /// card wears, from the engine id the preview reports.
    static func previewMark(engine: String) -> String? {
        switch engine {
        case "claude-cli": logoName(for: "agent")
        case "codex-cli": logoName(for: "codex")
        case "ollama": logoName(for: "local")
        default: nil
        }
    }

    /// The card a preview's engine belongs to — `previewMark`'s inverse — so a line that names what
    /// will run uses the card's own label ("Claude plan"), never a fresh coinage (R-HS8).
    static func candidateId(forEngine engine: String) -> String? {
        switch engine {
        case "claude-cli": "agent"
        case "codex-cli": "codex"
        case "ollama": "local"
        case "litellm": "byok"
        default: nil
        }
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

    /// G117 (owner 2026-09-04): each option states how it is paid for BEFORE it
    /// is chosen — a cost model in words, never a price (2026-09-03).
    static func costModel(for candidateId: String) -> String? {
        switch candidateId {
        case "agent", "codex": Copy.costModelPlan
        case "local": Copy.costModelLocal
        case "byok": Copy.costModelKey
        default: nil
        }
    }

    /// R-IB13 — onboarding offers the four engines a new person can name; the
    /// Auto ladder stays a Settings → Sleep choice. Leaving the row untouched
    /// keeps the install's configured default (`byok` unless a pref or
    /// `CICADA_LLM_MODE` says otherwise), which `EngineReadiness` reports honestly.
    static func compactCandidates(_ candidates: [SleepEngineCandidate]) -> [SleepEngineCandidate] {
        candidates.filter { $0.id != "auto" }
    }

    /// The key card's state comes from `Store.connections`, never from the byok
    /// candidate, which is `connected: true` even with no key (F6).
    static func compactCaption(for candidate: SleepEngineCandidate, hasKey: Bool) -> String {
        candidate.id == "byok" ? (hasKey ? Copy.engineKeySaved : Copy.engineAddKey) : caption(for: candidate)
    }

    /// The ring: the person's pick, else the engine a manual read would really use.
    static func ringed(pick: String?, readiness: EngineReadiness) -> String? {
        if let pick { return pick }
        if case .ready(let id) = readiness { return id }
        return nil
    }
}

/// R-HS7 — what a tap writes, as one rule shared by `EngineChooser`'s cards and the Sleep page's
/// quick menu, so the two surfaces can never write different things for the same tap.
struct EngineWrite: Equatable {
    let mode: String
    let model: String?

    /// A tap on another selectable engine writes it with its first model — the plan's own default
    /// first (R-E17); `nil` when it lists none (an API key's model lives on Plans & keys). A tap on
    /// the current engine, or on a plan that is not signed in (R-E25), writes nothing.
    /// `current` is the selected CARD (`SleepEngineResponse.selected`), so OpenRouter and the API-key
    /// card — both `byok` — are told apart.
    static func choosing(_ candidate: SleepEngineCandidate, current: String) -> EngineWrite? {
        guard candidate.id != current, EngineOption.isSelectable(candidate, selectedMode: current) else { return nil }
        let first = candidate.models.first ?? ""
        return EngineWrite(mode: mode(of: candidate), model: first.isEmpty ? nil : first)
    }

    /// R-AG12 — the ONE place a card becomes a mode. The OpenRouter card writes `byok`; spelling
    /// `mode: candidate.id` anywhere else would PUT `openrouter`, which the server refuses (422).
    static func mode(of candidate: SleepEngineCandidate) -> String { candidate.mode ?? candidate.id }

    /// A model pick on the chosen engine. The same model again, or a blank one, writes nothing.
    static func model(_ model: String, mode: String, current: String) -> EngineWrite? {
        let trimmed = model.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed != current else { return nil }
        return EngineWrite(mode: mode, model: trimmed)
    }
}
