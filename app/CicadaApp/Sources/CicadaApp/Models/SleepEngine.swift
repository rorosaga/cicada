import Foundation

/// Wire mirror of `api.models.schemas.SleepEngineCandidate` — one row of the
/// G122 Settings → Engines picker's segmented control. Deliberately NOT a
/// reuse of `ConnectionStatus` (that model carries login/billing fields no
/// candidate needs) — a candidate only needs enough to render a segment and, once
/// selected, a model list. Since the 2026-09-28 ruling it may also carry one `usage`
/// caption source and the picker's per-model list prices (Sleep page only); both are
/// decoded leniently, so a malformed one never empties the picker. The *response's*
/// `candidates`/`preview` fields (below) need the extra decode tolerance a
/// cached-from-before-G122 payload requires.
struct SleepEngineCandidate: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let available: Bool
    let connected: Bool
    let models: [String]
    let detail: String?
    /// R-AG12 — what a tap writes when it is not the card's own id: the OpenRouter card is `byok`
    /// under the hood. Absent (an older backend, or any other card) → `nil`, and the id is the
    /// mode; read only through `EngineWrite.mode(of:)`.
    var mode: String? = nil
    /// 2026-09-28 — a plan's window state or a key card's model price; absent on an older backend.
    var usage: SleepEngineUsage? = nil
    /// Model id → list price per million tokens, a parallel map so `models` keeps its type.
    var modelPrices: [String: SleepEngineModelPrice] = [:]
}

extension SleepEngineCandidate {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decode(String.self, forKey: .label)
        available = try c.decode(Bool.self, forKey: .available)
        connected = try c.decode(Bool.self, forKey: .connected)
        models = try c.decode([String].self, forKey: .models)
        detail = try c.decodeIfPresent(String.self, forKey: .detail)
        mode = try c.decodeIfPresent(String.self, forKey: .mode)
        usage = (try? c.decodeIfPresent(SleepEngineUsage.self, forKey: .usage)) ?? nil
        modelPrices = ((try? c.decodeIfPresent([String: SleepEngineModelPrice].self, forKey: .modelPrices)) ?? nil) ?? [:]
    }
}

/// R-AG11 — one row of the API-key card's provider picker, from `GET /sleep/engine`.
/// Names and ids only: `hasKey` is presence, never a value.
struct SleepEngineProvider: Codable, Hashable, Identifiable {
    let id: String
    let label: String
    let connectionId: String
    var hasKey: Bool = false
    let defaultModel: String
    let keyUrl: String
}

/// What the NEXT cycle would actually run on, for one trigger source
/// (`manual` or `scheduled`). `engine` is an `ENGINE_LABELS` id
/// (`claude-cli|codex-cli|ollama|litellm`) — `Copy.engineLabel(_:)` turns it into the
/// word the rest of the app already uses.
struct SleepEnginePreview: Codable, Hashable {
    let engine: String
    let model: String
    let why: String
    /// Sleep page v5 — how a run on this engine is billed, from the engine id alone and never a provider name:
    /// `plan` (a plan you signed in to), `charged` (per use, on a key), `local` (this Mac) or `unknown`. A
    /// scheduled preview is never `plan` (ruling 4). `nil` on an older backend.
    var billing: String? = nil
}

/// Both previews, always both — ruling 4 (a scheduled cycle never spends
/// plan quota) is made VISIBLE here rather than hidden: `EngineChooser` renders
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
    /// `CICADA_LLM_MODE` in the backend's environment outranks the stored choice (`source == "env"`): a
    /// card or a menu row would write and change nothing, so every surface says so and chooses nothing.
    var isPinnedByEnvironment: Bool { source == "env" }

    let mode: String
    let model: String
    let disambiguationModel: String
    let source: String
    let candidates: [SleepEngineCandidate]
    let preview: SleepEnginePreviews?
    /// R-E13 — the Settings → Engines "Keep going on extra usage" switch;
    /// absent on an older backend → false (off is the safe default: a Claude
    /// plan cycle stops at the included usage rather than billing past it).
    let allowOverage: Bool
    /// R-AG12 — the CARD the current choice belongs to (`openrouter` for a `byok` mode with an
    /// `openrouter/` model, else the mode). Absent or malformed on an older backend → `mode`,
    /// which is exactly what the card row highlighted before OpenRouter existed.
    let selected: String
    /// R-AG12 / R-AG14 — the key provider the chosen card reads through, when it reads through one.
    let provider: String?
    /// R-AG11 — the API-key card's provider picker; one malformed row empties the list rather
    /// than failing the whole card.
    let providers: [SleepEngineProvider]
    /// Sleep page v5 — "Leave room in my plan": the line, its choices, whether it applies to the engine a run you
    /// start would use, and which windows the last run could enforce. `nil` on an older backend.
    var reserve: SleepReserveStatus? = nil

    enum CodingKeys: String, CodingKey {
        case mode, model, disambiguationModel, source, candidates, preview, allowOverage
        case selected, provider, providers, reserve
    }

    init(
        mode: String, model: String, disambiguationModel: String, source: String,
        candidates: [SleepEngineCandidate], preview: SleepEnginePreviews?,
        allowOverage: Bool = false, selected: String? = nil, provider: String? = nil,
        providers: [SleepEngineProvider] = []
    ) {
        self.mode = mode
        self.model = model
        self.disambiguationModel = disambiguationModel
        self.source = source
        self.candidates = candidates
        self.preview = preview
        self.allowOverage = allowOverage
        self.selected = selected ?? mode
        self.provider = provider
        self.providers = providers
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
        allowOverage = ((try? c.decodeIfPresent(Bool.self, forKey: .allowOverage)) ?? nil) ?? false
        let decodedSelected = ((try? c.decodeIfPresent(String.self, forKey: .selected)) ?? nil) ?? ""
        selected = decodedSelected.isEmpty ? mode : decodedSelected
        provider = (try? c.decodeIfPresent(String.self, forKey: .provider)) ?? nil
        providers = ((try? c.decodeIfPresent([SleepEngineProvider].self, forKey: .providers)) ?? nil) ?? []
        reserve = (try? c.decodeIfPresent(SleepReserveStatus.self, forKey: .reserve)) ?? nil
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
