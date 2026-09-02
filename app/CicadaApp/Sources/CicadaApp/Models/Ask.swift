import Foundation

// MARK: - Ask (G52)
//
// Wire models for `POST /ask` (`api/models/schemas.py::AskResponse`). The
// backend's `CamelModel` already emits camelCase keys, so these decode with
// plain `CodingKeys` — no snake_case conversion needed. Every field besides
// `answer` is decode-tolerant (`decodeIfPresent … ?? []` / `?? 0`) so an
// older backend, or a response that only fills in a subset of fields, still
// renders instead of blanking the whole panel.

struct AskCitation: Codable, Identifiable, Equatable {
    let entityId: String
    let entityName: String
    let filePath: String
    let snippet: String
    let sourceEpisodes: [String]

    var id: String { entityId }

    enum CodingKeys: String, CodingKey {
        case entityId, entityName, filePath, snippet, sourceEpisodes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        entityName = try c.decodeIfPresent(String.self, forKey: .entityName) ?? ""
        filePath = try c.decodeIfPresent(String.self, forKey: .filePath) ?? ""
        snippet = try c.decodeIfPresent(String.self, forKey: .snippet) ?? ""
        sourceEpisodes = try c.decodeIfPresent([String].self, forKey: .sourceEpisodes) ?? []
    }

    init(entityId: String, entityName: String, filePath: String, snippet: String, sourceEpisodes: [String] = []) {
        self.entityId = entityId
        self.entityName = entityName
        self.filePath = filePath
        self.snippet = snippet
        self.sourceEpisodes = sourceEpisodes
    }
}

struct AskResponse: Codable, Equatable {
    let answer: String
    let confidence: Double
    let citations: [AskCitation]
    let gaps: [String]
    let usedEntities: [String]

    enum CodingKeys: String, CodingKey {
        case answer, confidence, citations, gaps, usedEntities
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        answer = try c.decodeIfPresent(String.self, forKey: .answer) ?? ""
        confidence = try c.decodeIfPresent(Double.self, forKey: .confidence) ?? 0
        citations = try c.decodeIfPresent([AskCitation].self, forKey: .citations) ?? []
        gaps = try c.decodeIfPresent([String].self, forKey: .gaps) ?? []
        usedEntities = try c.decodeIfPresent([String].self, forKey: .usedEntities) ?? []
    }

    init(answer: String, confidence: Double, citations: [AskCitation] = [], gaps: [String] = [], usedEntities: [String] = []) {
        self.answer = answer
        self.confidence = confidence
        self.citations = citations
        self.gaps = gaps
        self.usedEntities = usedEntities
    }

    // MARK: Row identities
    //
    // `AskCitation.id` is the entity id and gaps are bare strings, so a second
    // snippet from the same entity — or a repeated gap phrase — silently
    // disappears from a `ForEach`. Both lists are short and fixed for the life
    // of one answer, so the index IS the identity.

    var citationRows: [(id: Int, citation: AskCitation)] {
        citations.enumerated().map { (id: $0.offset, citation: $0.element) }
    }

    var gapRows: [(id: Int, text: String)] {
        gaps.enumerated().map { (id: $0.offset, text: $0.element) }
    }
}

// MARK: - Ask history (per-bank, persisted via SnapshotCache under .askHistory)

/// One asked question, persisted so the panel can show "recent questions"
/// across launches. `answer` is `nil` only if the request never completed
/// (rare — history is pushed on success), kept optional so tolerant decoding
/// never fails on a legacy entry.
struct AskHistoryEntry: Codable, Identifiable, Equatable {
    var id: String { question.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() + "|" + ISO8601DateFormatter().string(from: askedAt) }
    let question: String
    let askedAt: Date
    var answer: AskResponse?

    enum CodingKeys: String, CodingKey {
        case question, askedAt, answer
    }

    init(question: String, askedAt: Date, answer: AskResponse?) {
        self.question = question
        self.askedAt = askedAt
        self.answer = answer
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        question = try c.decodeIfPresent(String.self, forKey: .question) ?? ""
        askedAt = try c.decodeIfPresent(Date.self, forKey: .askedAt) ?? Date()
        answer = try c.decodeIfPresent(AskResponse.self, forKey: .answer)
    }
}

/// Pure ring-buffer logic for ask history, split out so it's unit-testable
/// without a `Store`/`SnapshotCache` in the loop.
enum AskHistory {
    static let maxEntries = 20

    /// Push `entry` onto `history`, most-recent-first, deduping by question
    /// (case-insensitive, trimmed) — a repeat of the same question replaces
    /// its prior occurrence rather than appearing twice — and capped at
    /// `maxEntries`.
    static func push(_ entry: AskHistoryEntry, into history: [AskHistoryEntry]) -> [AskHistoryEntry] {
        let key = entry.question.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        var deduped = history.filter {
            $0.question.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() != key
        }
        deduped.insert(entry, at: 0)
        if deduped.count > maxEntries {
            deduped.removeLast(deduped.count - maxEntries)
        }
        return deduped
    }
}
