import Foundation

// MARK: - Evidence (G118 slice 1 on the wire, read back by slice 2)
//
// A claim points at the words it came from as `(episode, start, end, kind,
// hash)` — offsets into a stored document, never a copy (`EvidenceModel`,
// `api/models/schemas.py`). Slice 1 shipped the field; the app dropped it
// because `Claim.CodingKeys` never named it. These types read it back, and
// every one decodes tolerantly: an older backend, a legacy claim with no
// evidence, or a kind this build has never heard of must never blank a view
// (design §4.1, R10 — the same rule `Epistemic`/`SourceTrust` follow).

/// What kind of words a span points at. The server stores six
/// (`claims.EVIDENCE_KINDS`): `user`, `assistant`, `page`, `reasoning`,
/// `speaker` (a meeting utterance, R-N2 / G134) and `media` (a video excerpt,
/// a timed `video [m:ss]:` line, R5 D4 / G140); `derived` exists ONLY on read payloads —
/// a name match found at read, never written (R-PB9, §4.9). `unknown` is the
/// forward-compatible tail and renders like `reasoning`.
enum EvidenceKind: String, Codable, Hashable, CaseIterable {
    case user, assistant, page, reasoning, media, speaker, derived, unknown

    init(wire: String?) {
        self = EvidenceKind(rawValue: (wire ?? "").lowercased()) ?? .unknown
    }

    init(from decoder: Decoder) throws {
        self.init(wire: try? decoder.singleValueContainer().decode(String.self))
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(rawValue)
    }

    /// Kinds whose stored offsets index words the Reader can wash. `reasoning`
    /// is the contributor citing itself (`start == end == -1`); `derived`
    /// offsets are real but are a name match, styled bold, never washed.
    var hasOffsets: Bool {
        switch self {
        case .user, .assistant, .page, .media, .speaker: true
        case .reasoning, .derived, .unknown: false
        }
    }
}

/// One evidence entry on a claim (`EvidenceModel`). `episode` is a
/// source-document id: `ep_*` is an episode, anything else an entity page (a
/// `page` span cites the media entity, `evidence.source_path`).
struct Evidence: Codable, Hashable {
    let episode: String
    let start: Int
    let end: Int
    let kind: EvidenceKind
    let hash: String
    /// Round-4 C3 (D1) — on an `assistant` span, the model and effort of the
    /// agent turn it cites, when capture recorded them. Absent everywhere else.
    let model: String?
    let effort: String?

    /// A span the Reader can land on and wash. Never true for `reasoning`
    /// (design §4.10) — offsets of -1 are "no sentence", not "sentence zero".
    var isSpan: Bool { kind.hasOffsets && !episode.isEmpty && start >= 0 && end > start }

    /// `ep_*` → an episode (a conversation); anything else → a page.
    var isEpisode: Bool { episode.hasPrefix("ep_") }

    init(episode: String, start: Int, end: Int, kind: EvidenceKind, hash: String = "",
         model: String? = nil, effort: String? = nil) {
        self.episode = episode
        self.start = start
        self.end = end
        self.kind = kind
        self.hash = hash
        self.model = model
        self.effort = effort
    }

    enum CodingKeys: String, CodingKey { case episode, start, end, kind, hash, model, effort }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        start = try c.decodeIfPresent(Int.self, forKey: .start) ?? -1
        end = try c.decodeIfPresent(Int.self, forKey: .end) ?? -1
        // The server's own default is `reasoning` (`EvidenceModel.kind`): an
        // entry that names no kind makes no claim about whose words these are.
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .reasoning
        hash = try c.decodeIfPresent(String.self, forKey: .hash) ?? ""
        // `try?`: a mistyped optional must never drop the whole span (C3).
        model = (try? c.decodeIfPresent(String.self, forKey: .model)) ?? nil
        effort = (try? c.decodeIfPresent(String.self, forKey: .effort)) ?? nil
    }
}

// MARK: - GET /episodes/{id}/span

/// `EpisodeSpan` — the cited words with context either side, for the hover
/// preview. `stale` and `grown` are never both true (amendment A7): `grown`
/// means the conversation continued and the offsets are still exact, so it
/// highlights; `stale` never does (§4.9).
struct EpisodeSpan: Codable, Hashable {
    let episode: String
    let text: String
    let before: String
    let after: String
    let start: Int
    let end: Int
    let length: Int
    let stale: Bool
    let grown: Bool
    let kind: EvidenceKind

    /// Built client-side for one case only: a span the document no longer
    /// reaches (`/span` answers 422 once a rewrite made the text shorter than
    /// `end`) is served as a stale span with no words (R-PU25), because "the
    /// words moved" is the truth and "couldn't open" is not.
    init(episode: String, text: String = "", before: String = "", after: String = "", start: Int, end: Int,
         length: Int = 0, stale: Bool = false, grown: Bool = false, kind: EvidenceKind = .user) {
        self.episode = episode
        self.text = text
        self.before = before
        self.after = after
        self.start = start
        self.end = end
        self.length = length
        self.stale = stale
        self.grown = grown
        self.kind = kind
    }

    enum CodingKeys: String, CodingKey { case episode, text, before, after, start, end, length, stale, grown, kind }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        before = try c.decodeIfPresent(String.self, forKey: .before) ?? ""
        after = try c.decodeIfPresent(String.self, forKey: .after) ?? ""
        start = try c.decodeIfPresent(Int.self, forKey: .start) ?? 0
        end = try c.decodeIfPresent(Int.self, forKey: .end) ?? 0
        length = try c.decodeIfPresent(Int.self, forKey: .length) ?? 0
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
        // A slice-1 backend has no `grown`; absent reads as "not grown", which
        // is exactly what that backend meant.
        grown = try c.decodeIfPresent(Bool.self, forKey: .grown) ?? false
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .user
    }
}

// MARK: - GET /episodes/{id}/text

/// One turn of a document (`EpisodeTurn`) — offsets into the evidence text,
/// never a copy. `role` is `user` | `assistant` | `page` (and `speaker` once
/// the note-taker track extends the one marker parser, R-PB3); `marker` is
/// the word as written (`nil` for a marker-less block); `ts`/`speaker` exist
/// only where the episode stores a `turns` sidecar entry — a time is never
/// inferred (§4.4).
struct EpisodeTurn: Codable, Hashable, Identifiable {
    let index: Int
    let start: Int
    let contentStart: Int
    let end: Int
    let role: String
    let marker: String?
    let speaker: String?
    let ts: String?
    /// Round-4 C4 (D1) — on an assistant turn, the model and effort capture
    /// recorded for it; nil for every other role and before D1.
    let model: String?
    let effort: String?

    var id: Int { index }

    init(index: Int, start: Int, contentStart: Int, end: Int, role: String = "user",
         marker: String? = nil, speaker: String? = nil, ts: String? = nil,
         model: String? = nil, effort: String? = nil) {
        self.index = index
        self.start = start
        self.contentStart = contentStart
        self.end = end
        self.role = role
        self.marker = marker
        self.speaker = speaker
        self.ts = ts
        self.model = model
        self.effort = effort
    }

    enum CodingKeys: String, CodingKey { case index, start, contentStart, end, role, marker, speaker, ts, model, effort }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        index = try c.decodeIfPresent(Int.self, forKey: .index) ?? 0
        start = try c.decodeIfPresent(Int.self, forKey: .start) ?? 0
        contentStart = try c.decodeIfPresent(Int.self, forKey: .contentStart) ?? start
        end = try c.decodeIfPresent(Int.self, forKey: .end) ?? start
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? "user"
        marker = try c.decodeIfPresent(String.self, forKey: .marker)
        speaker = try c.decodeIfPresent(String.self, forKey: .speaker)
        ts = try c.decodeIfPresent(String.self, forKey: .ts)
        model = (try? c.decodeIfPresent(String.self, forKey: .model)) ?? nil
        effort = (try? c.decodeIfPresent(String.self, forKey: .effort)) ?? nil
    }
}

/// The span the Reader lands on (`EpisodeFocus`). A stale focus carries NO
/// offsets (R-PB2) — "stale never highlights" is unrepresentable, not a
/// client convention. `derived` is a name match found at read (R-PB9).
struct EpisodeFocus: Codable, Hashable {
    let start: Int?
    let end: Int?
    let kind: EvidenceKind
    let derived: Bool
    let stale: Bool
    let grown: Bool

    init(start: Int?, end: Int?, kind: EvidenceKind = .user, derived: Bool = false,
         stale: Bool = false, grown: Bool = false) {
        self.start = start
        self.end = end
        self.kind = kind
        self.derived = derived
        self.stale = stale
        self.grown = grown
    }

    enum CodingKeys: String, CodingKey { case start, end, kind, derived, stale, grown }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        kind = try c.decodeIfPresent(EvidenceKind.self, forKey: .kind) ?? .user
        derived = try c.decodeIfPresent(Bool.self, forKey: .derived) ?? false
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
        grown = try c.decodeIfPresent(Bool.self, forKey: .grown) ?? false
    }

    /// `[start, end)` when the server sent a washable pair, else nil.
    var range: Range<Int>? {
        guard let start, let end, start >= 0, end > start else { return nil }
        return start..<end
    }
}

/// Round-4 C4 (D1) — the document's most recent agent turn's model and effort,
/// for the Reader's meta line. Both optional: capture may know neither.
struct EpisodeAgent: Codable, Hashable {
    let model: String?
    let effort: String?

    init(model: String? = nil, effort: String? = nil) {
        self.model = model
        self.effort = effort
    }

    enum CodingKeys: String, CodingKey { case model, effort }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        model = (try? c.decodeIfPresent(String.self, forKey: .model)) ?? nil
        effort = (try? c.decodeIfPresent(String.self, forKey: .effort)) ?? nil
    }
}

/// `EpisodeText` — a whole stored document for the Reader. `text` is capped
/// at 400,000 characters server-side (`truncated`, R-PB5); `length` and
/// `hash` always describe the WHOLE text. `conversationId` is the stamped
/// `session_id` or G20's `source_id`. `projectDir`/`resumable` are
/// deliberately absent — `GET /conversations/{id}` is the one place a
/// transcript is `isfile()`-d.
struct EpisodeText: Codable, Hashable {
    let episode: String
    let kind: String
    let text: String
    let length: Int
    let hash: String
    let truncated: Bool
    let title: String
    let timestamp: String?
    let harness: String?
    let origin: String?
    let conversationId: String?
    let captureKind: String?
    let turns: [EpisodeTurn]
    let focus: EpisodeFocus?
    /// Round-4 C4 — nil against a backend before D1 and for a harness that never
    /// tells its model.
    let agent: EpisodeAgent?

    var isPage: Bool { kind == "page" }

    init(episode: String, kind: String = "episode", text: String, length: Int? = nil, hash: String = "",
         truncated: Bool = false, title: String = "", timestamp: String? = nil, harness: String? = nil,
         origin: String? = nil, conversationId: String? = nil, captureKind: String? = nil,
         turns: [EpisodeTurn] = [], focus: EpisodeFocus? = nil, agent: EpisodeAgent? = nil) {
        self.episode = episode
        self.kind = kind
        self.text = text
        self.length = length ?? text.unicodeScalars.count
        self.hash = hash
        self.truncated = truncated
        self.title = title
        self.timestamp = timestamp
        self.harness = harness
        self.origin = origin
        self.conversationId = conversationId
        self.captureKind = captureKind
        self.turns = turns
        self.focus = focus
        self.agent = agent
    }

    enum CodingKeys: String, CodingKey {
        case episode, kind, text, length, hash, truncated, title, timestamp, harness, origin
        case conversationId, captureKind, turns, focus, agent
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episode = try c.decodeIfPresent(String.self, forKey: .episode) ?? ""
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "episode"
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        length = try c.decodeIfPresent(Int.self, forKey: .length) ?? text.unicodeScalars.count
        hash = try c.decodeIfPresent(String.self, forKey: .hash) ?? ""
        truncated = try c.decodeIfPresent(Bool.self, forKey: .truncated) ?? false
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp)
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
        captureKind = try c.decodeIfPresent(String.self, forKey: .captureKind)
        turns = try c.decodeIfPresent([EpisodeTurn].self, forKey: .turns) ?? []
        focus = try c.decodeIfPresent(EpisodeFocus.self, forKey: .focus)
        agent = (try? c.decodeIfPresent(EpisodeAgent.self, forKey: .agent)) ?? nil
    }
}
