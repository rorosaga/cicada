import Foundation

/// One `GET /search` row (G136 server half, PR #74; `api/models/schemas.py`
/// `SearchHit`, verified field by field). Decode-tolerant: a pre-G136 backend
/// sends the old seven fields and no `kind` — every row was an entity — and
/// that must never blank the palette (R10).
struct MemorySearchHit: Decodable, Equatable, Sendable {
    let id: String
    let name: String
    let type: String
    let status: String
    let score: Double
    let snippet: String
    let kind: String
    let subtitle: String?
    let snippetOffsets: [[Int]]
    let matchedField: String?
    let subjectId: String?
    let episodeId: String?
    let conversationId: String?
    let harness: String?
    let origin: String?
    let timestamp: String?
    let start: Int?
    let end: Int?
    let hash: String?
    let evidenceKind: String?
    let validFrom: String?
    let validTo: String?
    let supersededBy: String?

    enum CodingKeys: String, CodingKey {
        case id, name, type, status, score, snippet, kind, subtitle, snippetOffsets, matchedField, subjectId
        case episodeId, conversationId, harness, origin, timestamp, start, end, hash, evidenceKind
        case validFrom, validTo, supersededBy
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? ""
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? "concept"
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "active"
        score = try c.decodeIfPresent(Double.self, forKey: .score) ?? 0
        snippet = try c.decodeIfPresent(String.self, forKey: .snippet) ?? ""
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "entity"
        subtitle = try c.decodeIfPresent(String.self, forKey: .subtitle)
        snippetOffsets = (try? c.decodeIfPresent([[Int]].self, forKey: .snippetOffsets)) ?? []
        matchedField = try c.decodeIfPresent(String.self, forKey: .matchedField)
        subjectId = try c.decodeIfPresent(String.self, forKey: .subjectId)
        episodeId = try c.decodeIfPresent(String.self, forKey: .episodeId)
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp)
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        hash = try c.decodeIfPresent(String.self, forKey: .hash)
        evidenceKind = try c.decodeIfPresent(String.self, forKey: .evidenceKind)
        validFrom = try c.decodeIfPresent(String.self, forKey: .validFrom)
        validTo = try c.decodeIfPresent(String.self, forKey: .validTo)
        supersededBy = try c.decodeIfPresent(String.self, forKey: .supersededBy)
    }
}

/// `totals` are exact LEXICAL counts per kind (G136 R11); `indexState`
/// `building | unavailable` means claims and conversations are empty on
/// purpose, and the palette hides those groups rather than showing them empty.
struct MemorySearchResponse: Decodable, Equatable, Sendable {
    let results: [MemorySearchHit]
    let totals: [String: Int]
    let mode: String
    let indexState: String

    enum CodingKeys: String, CodingKey { case results, totals, mode, indexState }

    init(results: [MemorySearchHit] = [], totals: [String: Int] = [:], mode: String = "prefix", indexState: String = "ready") {
        self.results = results
        self.totals = totals
        self.mode = mode
        self.indexState = indexState
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        results = try c.decodeIfPresent([MemorySearchHit].self, forKey: .results) ?? []
        totals = (try? c.decodeIfPresent([String: Int].self, forKey: .totals)) ?? [:]
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "hybrid"
        indexState = try c.decodeIfPresent(String.self, forKey: .indexState) ?? "ready"
    }
}

/// The palette's one network dependency, injected so the passes are tested
/// with a fake (design §3.10) and no test can reach the live backend.
protocol FindSearchAPI: Sendable {
    func searchMemory(_ query: String, kinds: [String], mode: String, perKind: Int) async throws -> MemorySearchResponse
}

extension APIClient: FindSearchAPI {}

/// The debounce clock, injected (the `SyncEngine` pattern).
typealias FindSleeper = @Sendable (Duration) async throws -> Void

enum FindSleepers {
    static let real: FindSleeper = { try await Task.sleep(for: $0) }
}

enum FindServerPhase: Equatable, Sendable {
    case idle, searching, done, unreachable

    /// A backend that is not answering — as opposed to a cancelled request
    /// (the next keystroke) or an error reply (an old backend, a 422), which
    /// leave the local rows standing without a banner.
    static func isUnreachable(_ error: Error) -> Bool {
        if let api = error as? APIError, case .serverUnreachable = api { return true }
        if let url = error as? URLError { return url.code != .cancelled }
        return false
    }
}
