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
    // G118 slice 2 (R-PB12): set when the retrieval hit was a claim — the
    // claim and the spans behind it, raw as stored (freshness is `/span`'s
    // job). Absent for an entity-only hit and against an older backend.
    let claimId: String?
    let evidence: [Evidence]

    var id: String { entityId }

    enum CodingKeys: String, CodingKey {
        case entityId, entityName, filePath, snippet, sourceEpisodes, claimId, evidence
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        entityName = try c.decodeIfPresent(String.self, forKey: .entityName) ?? ""
        filePath = try c.decodeIfPresent(String.self, forKey: .filePath) ?? ""
        snippet = try c.decodeIfPresent(String.self, forKey: .snippet) ?? ""
        sourceEpisodes = try c.decodeIfPresent([String].self, forKey: .sourceEpisodes) ?? []
        claimId = try c.decodeIfPresent(String.self, forKey: .claimId)
        evidence = try c.decodeIfPresent([Evidence].self, forKey: .evidence) ?? []
    }

    init(entityId: String, entityName: String, filePath: String, snippet: String, sourceEpisodes: [String] = [],
         claimId: String? = nil, evidence: [Evidence] = []) {
        self.entityId = entityId
        self.entityName = entityName
        self.filePath = filePath
        self.snippet = snippet
        self.sourceEpisodes = sourceEpisodes
        self.claimId = claimId
        self.evidence = evidence
    }
}

/// A conversation no page cites whose words the answer used (`AskConversation` on the wire, Ask's search leg,
/// 2026-10-19): the episode id the Reader opens, its title and the day it was said (`YYYY-MM-DD`). Who spoke is not
/// on the wire — the Reader says it when the conversation opens.
struct AskConversation: Codable, Identifiable, Equatable {
    let episodeId: String
    let title: String
    let day: String

    var id: String { episodeId }

    enum CodingKeys: String, CodingKey {
        case episodeId, title, day
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episodeId = try c.decodeIfPresent(String.self, forKey: .episodeId) ?? ""
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        day = try c.decodeIfPresent(String.self, forKey: .day) ?? ""
    }

    init(episodeId: String, title: String = "", day: String = "") {
        self.episodeId = episodeId
        self.title = title
        self.day = day
    }
}

struct AskResponse: Codable, Equatable {
    let answer: String
    let confidence: Double
    let citations: [AskCitation]
    let gaps: [String]
    let usedEntities: [String]
    /// Additive (2026-10-19): the conversations the answer used that no page cites. Empty against an older backend
    /// and for an answer cached in history before the field existed; a row without an id is dropped (nothing to open).
    let conversations: [AskConversation]

    enum CodingKeys: String, CodingKey {
        case answer, confidence, citations, gaps, usedEntities, conversations
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        answer = try c.decodeIfPresent(String.self, forKey: .answer) ?? ""
        confidence = try c.decodeIfPresent(Double.self, forKey: .confidence) ?? 0
        citations = try c.decodeIfPresent([AskCitation].self, forKey: .citations) ?? []
        gaps = try c.decodeIfPresent([String].self, forKey: .gaps) ?? []
        usedEntities = try c.decodeIfPresent([String].self, forKey: .usedEntities) ?? []
        conversations = (try? c.decodeIfPresent([AskConversation].self, forKey: .conversations) ?? [])?
            .filter { !$0.episodeId.isEmpty } ?? []
    }

    init(answer: String, confidence: Double, citations: [AskCitation] = [], gaps: [String] = [], usedEntities: [String] = [],
         conversations: [AskConversation] = []) {
        self.answer = answer
        self.confidence = confidence
        self.citations = citations
        self.gaps = gaps
        self.usedEntities = usedEntities
        self.conversations = conversations
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

    /// One row per conversation, in the backend's order (first used first); a repeated id once.
    var conversationRows: [AskConversation] {
        var seen = Set<String>()
        return conversations.filter { seen.insert($0.episodeId).inserted }
    }
}

/// An Ask conversation row's words and action, pure (`AskConversationsTests`). DR-54: a source is named the way a
/// person would — its title and its day; the episode id lives only in `.help`.
enum AskConversationRow {
    /// The row's title; a conversation stored without one reads "A conversation" (the day ends the row).
    static func title(_ conversation: AskConversation) -> String {
        let trimmed = conversation.title.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? Copy.AskWords.untitledConversation : trimmed
    }

    /// "Oct 3", with the year only when it is not this year; empty for a day that does not parse, so the row never
    /// ends with a raw string.
    static func day(_ raw: String, now: Date = Date(), calendar: Calendar = .current) -> String {
        guard let date = parse(raw, calendar: calendar) else { return "" }
        let sameYear = calendar.component(.year, from: date) == calendar.component(.year, from: now)
        let format = DateFormatter()
        format.calendar = calendar
        format.timeZone = calendar.timeZone
        format.setLocalizedDateFormatFromTemplate(sameYear ? "MMM d" : "MMM d yyyy")
        return format.string(from: date)
    }

    /// What a click does and the episode id (DR-54: reachable in `.help`, never on the row).
    static func help(_ conversation: AskConversation) -> String {
        "\(Copy.AskWords.openConversationHint) · \(Copy.SleepDetailsWords.episodeIdHelp(conversation.episodeId))"
    }

    /// A click opens the stored conversation in the Reader (DR-31), from the top — the same target a Sleep page row
    /// opens (`EpisodeRowAction.reader`). With no Reader in the environment (a preview, a test host) it copies the
    /// episode id instead, so the row never does nothing.
    static func primary(_ conversation: AskConversation, readerAvailable: Bool) -> EpisodeRowAction {
        readerAvailable ? .open(reader(conversation)) : .copy(conversation.episodeId)
    }

    static func reader(_ conversation: AskConversation) -> ReaderTarget {
        let title = conversation.title.trimmingCharacters(in: .whitespacesAndNewlines)
        return ReaderTarget(episode: conversation.episodeId, knownTitle: title.isEmpty ? nil : title)
    }

    private static func parse(_ raw: String, calendar: Calendar) -> Date? {
        let parts = raw.prefix(10).split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var comps = DateComponents()
        comps.year = parts[0]
        comps.month = parts[1]
        comps.day = parts[2]
        comps.hour = 12
        guard let date = calendar.date(from: comps),
              calendar.component(.month, from: date) == parts[1] else { return nil }
        return date
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
