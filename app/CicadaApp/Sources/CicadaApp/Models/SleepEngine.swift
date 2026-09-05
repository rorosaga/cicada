import Foundation

/// Wire mirror of `api.models.schemas.SleepEngineCandidate` — one row of the
/// G122 Settings → Sleep picker's segmented control. Deliberately NOT a
/// reuse of `ConnectionStatus` (that model carries login/billing fields no
/// candidate needs, and G124 bans price/token fields from this surface
/// entirely) — a candidate only needs enough to render a segment and, once
/// selected, a model list. The backend always sends every field here (Task
/// 1), so a plain synthesized `Codable` is sufficient — only the
/// *response's* `candidates`/`preview` fields (below) need the extra decode
/// tolerance a cached-from-before-G122 payload requires.
struct SleepEngineCandidate: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let available: Bool
    let connected: Bool
    let models: [String]
    let detail: String?
}

/// What the NEXT cycle would actually run on, for one trigger source
/// (`manual` or `scheduled`). `engine` is an `ENGINE_LABELS` id
/// (`claude-cli|ollama|litellm`) — `Copy.engineLabel(_:)` turns it into the
/// word the rest of the app already uses.
struct SleepEnginePreview: Codable, Hashable {
    let engine: String
    let model: String
    let why: String
}

/// Both previews, always both — ruling 4 (a scheduled cycle never spends
/// plan quota) is made VISIBLE here rather than hidden: `EngineCard` renders
/// `manual` and `scheduled` side by side so a prefs-chosen "agent" that
/// silently degrades on the nightly schedule is obvious, never a surprise.
struct SleepEnginePreviews: Codable, Hashable {
    let manual: SleepEnginePreview
    let scheduled: SleepEnginePreview
}

/// Wire mirror of `SleepEngineResponse` — the full GET/PUT `/sleep/engine`
/// body. `candidates`/`preview` decode tolerantly (defaulting to `[]`/`nil`)
/// so a payload cached on disk from before this feature shipped — the Sleep
/// settings page can render from a stale local cache before the first
/// network round-trip — still decodes instead of crashing the card.
struct SleepEngineResponse: Codable, Hashable {
    let mode: String
    let model: String
    let disambiguationModel: String
    let source: String
    let candidates: [SleepEngineCandidate]
    let preview: SleepEnginePreviews?

    enum CodingKeys: String, CodingKey {
        case mode, model, disambiguationModel, source, candidates, preview
    }

    init(
        mode: String, model: String, disambiguationModel: String, source: String,
        candidates: [SleepEngineCandidate], preview: SleepEnginePreviews?
    ) {
        self.mode = mode
        self.model = model
        self.disambiguationModel = disambiguationModel
        self.source = source
        self.candidates = candidates
        self.preview = preview
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decode(String.self, forKey: .mode)
        model = try c.decode(String.self, forKey: .model)
        disambiguationModel = try c.decode(String.self, forKey: .disambiguationModel)
        source = try c.decode(String.self, forKey: .source)
        // `decodeIfPresent` returns `[T]??` (present-but-null vs. absent) —
        // both collapse to `[]` here, and `try?` covers a malformed value.
        candidates = ((try? c.decodeIfPresent([SleepEngineCandidate].self, forKey: .candidates)) ?? nil) ?? []
        preview = (try? c.decodeIfPresent(SleepEnginePreviews.self, forKey: .preview)) ?? nil
    }
}

/// The Ollama "local" candidate's setup ladder, as a pure function of the
/// candidate the backend already probed — no view, no network of its own.
/// Mirrors the `OllamaAdapter.status()` split the backend already computes:
/// `available` = the server is reachable, `connected` = the configured
/// model is actually pulled.
enum OllamaGuideState: Equatable {
    case notInstalled
    case notRunning
    case noModel
    case ready

    static func from(candidate: SleepEngineCandidate) -> OllamaGuideState {
        guard candidate.available else { return .notInstalled }
        guard candidate.connected else { return .notRunning }
        guard !candidate.models.isEmpty else { return .noModel }
        return .ready
    }

    /// The one shell command that fixes the CURRENT state — `nil` once
    /// `.ready`, since there is nothing left to guide the reader toward.
    var command: String? {
        switch self {
        case .notInstalled: "brew install ollama"
        case .notRunning: "ollama serve"
        case .noModel: "ollama pull llama3.1"
        case .ready: nil
        }
    }
}
