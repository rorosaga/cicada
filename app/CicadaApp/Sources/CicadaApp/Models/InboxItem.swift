import Foundation
import SwiftUI

/// Discriminator for a unified inbox item. Matches `InboxKind` in
/// `api/models/schemas.py` (wire values are snake_case for `merge_suggestion`).
enum InboxKind: String, Codable {
    case decay, conflict, clarification
    case mergeSuggestion = "merge_suggestion"

    var label: String {
        switch self {
        case .decay: "Decay"
        case .conflict: "Conflict"
        case .clarification: "Clarification"
        case .mergeSuggestion: "Possible duplicate"
        }
    }

    /// Leading-icon SF Symbol per kind.
    var icon: String {
        switch self {
        case .decay: "clock.arrow.circlepath"
        case .conflict: "exclamationmark.triangle.fill"
        case .clarification: "questionmark.circle.fill"
        case .mergeSuggestion: "arrow.triangle.merge"
        }
    }

    var color: Color { CicadaTheme.inboxColor(for: self) }
}

/// What input the card's action row needs. Matches `RequiredInput` in the API.
enum RequiredInput: String, Codable {
    case none, choice, freetext, merge
}

/// One answerable option on an inbox question. Matches `InboxOption` in
/// `api/models/schemas.py`. `ageDays` is derived server-side at read time.
/// G115 Phase 1: `recommended` marks the ONE option Sleep proposed (the key the
/// ledger's `_verdict` grades `agreed`); `verdict` is on the wire for agents and
/// tests and is never rendered as copy.
struct InboxOption: Identifiable, Hashable {
    var key: String
    var label: String
    var description: String?
    var claimId: String?
    var observedAt: String?
    var lastReferenced: String?
    var ageDays: Int?
    var recommended: Bool = false
    var verdict: String? = nil

    var id: String { key }

    /// A trailing muted capsule: "today", "5 d", "3 wk", "6 mo", "2 y".
    /// `nil` when the option has no claim behind it (the synthetic rows).
    var ageCapsule: String? {
        guard let days = ageDays else { return nil }
        if days == 0 { return "today" }
        if days < 14 { return "\(days) d" }
        if days < 60 { return "\(Int((Double(days) / 7).rounded())) wk" }
        if days < 365 { return "\(Int((Double(days) / 30).rounded())) mo" }
        return "\(Int((Double(days) / 365).rounded())) y"
    }
}

// `Codable` is declared in an EXTENSION on purpose: a custom `init(from:)` in
// the struct body would suppress the memberwise initialiser, and
// `InboxItem.init(from:)`'s legacy flat-`[String]` branch calls it with seven
// labelled arguments. In an extension the memberwise init survives, and
// `recommended`/`verdict` — `var`s with defaults, declared last — are simply
// omitted by that call.
extension InboxOption: Codable {
    enum CodingKeys: String, CodingKey {
        case key, label, description, claimId, observedAt, lastReferenced, ageDays, recommended, verdict
    }

    /// Tolerant on purpose: a `SnapshotCache` payload written before G115 has
    /// no `recommended`/`verdict`, and a synthesized decoder would refuse the
    /// whole inbox over one missing key.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? ""
        description = try c.decodeIfPresent(String.self, forKey: .description)
        claimId = try c.decodeIfPresent(String.self, forKey: .claimId)
        observedAt = try c.decodeIfPresent(String.self, forKey: .observedAt)
        lastReferenced = try c.decodeIfPresent(String.self, forKey: .lastReferenced)
        ageDays = try c.decodeIfPresent(Int.self, forKey: .ageDays)
        recommended = try c.decodeIfPresent(Bool.self, forKey: .recommended) ?? false
        verdict = try c.decodeIfPresent(String.self, forKey: .verdict)
    }
}

/// Why an item exists (G97): the conversation and sentence that raised it,
/// resolved server-side at read. `mentionOffsets` index the EXCERPT as
/// Unicode-scalar offsets (Python `str` indices); `start`/`end` are the
/// absolute offsets into the episode body. `tier == "none"` carries the literal
/// `[ no source recorded ]` in `excerpt` — shown, never hidden.
struct InboxCause: Codable, Hashable {
    var episodeId: String?
    var timestamp: String?
    var conversationId: String?
    var harness: String?
    var origin: String?
    var conversationTitle: String?
    var excerpt: String = ""
    var mentionOffsets: [[Int]] = []
    var start: Int?
    var end: Int?
    var tier: String = "none"
    var spanKind: String = "derived"

    enum CodingKeys: String, CodingKey {
        case episodeId, timestamp, conversationId, harness, origin, conversationTitle
        case excerpt, mentionOffsets, start, end, tier, spanKind
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episodeId = try c.decodeIfPresent(String.self, forKey: .episodeId)
        timestamp = try c.decodeIfPresent(String.self, forKey: .timestamp)
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
        harness = try c.decodeIfPresent(String.self, forKey: .harness)
        origin = try c.decodeIfPresent(String.self, forKey: .origin)
        conversationTitle = try c.decodeIfPresent(String.self, forKey: .conversationTitle)
        excerpt = try c.decodeIfPresent(String.self, forKey: .excerpt) ?? ""
        mentionOffsets = try c.decodeIfPresent([[Int]].self, forKey: .mentionOffsets) ?? []
        start = try c.decodeIfPresent(Int.self, forKey: .start)
        end = try c.decodeIfPresent(Int.self, forKey: .end)
        tier = try c.decodeIfPresent(String.self, forKey: .tier) ?? "none"
        spanKind = try c.decodeIfPresent(String.self, forKey: .spanKind) ?? "derived"
    }
}

/// One unified inbox item. Decodes the camelCase payload from `GET /inbox`
/// (`api/routers/inbox.py` → `InboxItem`). `options` decodes both the current
/// object form and the legacy flat `[String]`, so an item written before G60
/// still renders.
struct InboxItem: Identifiable, Codable {
    let id: String
    var kind: InboxKind
    var requiredInput: RequiredInput
    var status: String
    var priority: Double
    var entityId: String
    var entityName: String
    var title: String
    var body: String
    var options: [InboxOption]
    var createdDate: String
    // G60 question object
    var question: String?
    var allowOther: Bool
    var allowDefer: Bool
    var predicate: String?
    var hint: String?
    var remindAfter: String?
    var updatedDate: String?
    // clarification / merge extras
    var uncertaintyType: String?
    var suggestedClassification: String?
    var suggestedConfidence: Double?
    var mergeTargetHint: String?
    // G115 Phase 1 — every one optional so a pre-G115 cache still decodes.
    var entityType: String?
    var sourceEpisode: String?
    var sourceEpisodeTimestamp: String?
    var claimId: String?
    var cause: InboxCause?
    var extractorConfidence: Double?
    var extractorModel: String?
    var recommendedKey: String?
    /// G98: a conflict on a multi-valued predicate — shown, never asked.
    var informational: Bool

    enum CodingKeys: String, CodingKey {
        case id, kind, requiredInput, status, priority
        case entityId, entityName, title, body, options, createdDate
        case question, allowOther, allowDefer, predicate, hint, remindAfter, updatedDate
        case uncertaintyType, suggestedClassification, suggestedConfidence, mergeTargetHint
        case entityType, sourceEpisode, sourceEpisodeTimestamp, claimId, cause
        case extractorConfidence, extractorModel, recommendedKey, informational
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = try c.decode(InboxKind.self, forKey: .kind)
        requiredInput = try c.decode(RequiredInput.self, forKey: .requiredInput)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "pending"
        priority = try c.decodeIfPresent(Double.self, forKey: .priority) ?? 0
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        entityName = try c.decodeIfPresent(String.self, forKey: .entityName) ?? ""
        title = try c.decode(String.self, forKey: .title)
        body = try c.decodeIfPresent(String.self, forKey: .body) ?? ""
        // Object form first; a server or cached payload from before G60 hands
        // back `["A","B"]`, which becomes positionally-keyed options.
        if let objects = try? c.decodeIfPresent([InboxOption].self, forKey: .options) {
            options = objects ?? []
        } else if let labels = try c.decodeIfPresent([String].self, forKey: .options) {
            options = labels.enumerated().map {
                InboxOption(key: "\($0.offset)", label: $0.element, description: nil,
                            claimId: nil, observedAt: nil, lastReferenced: nil, ageDays: nil)
            }
        } else {
            options = []
        }
        createdDate = try c.decodeIfPresent(String.self, forKey: .createdDate) ?? ""
        question = try c.decodeIfPresent(String.self, forKey: .question)
        allowOther = try c.decodeIfPresent(Bool.self, forKey: .allowOther) ?? false
        allowDefer = try c.decodeIfPresent(Bool.self, forKey: .allowDefer) ?? false
        predicate = try c.decodeIfPresent(String.self, forKey: .predicate)
        hint = try c.decodeIfPresent(String.self, forKey: .hint)
        remindAfter = try c.decodeIfPresent(String.self, forKey: .remindAfter)
        updatedDate = try c.decodeIfPresent(String.self, forKey: .updatedDate)
        uncertaintyType = try c.decodeIfPresent(String.self, forKey: .uncertaintyType)
        suggestedClassification = try c.decodeIfPresent(String.self, forKey: .suggestedClassification)
        suggestedConfidence = try c.decodeIfPresent(Double.self, forKey: .suggestedConfidence)
        mergeTargetHint = try c.decodeIfPresent(String.self, forKey: .mergeTargetHint)
        entityType = try c.decodeIfPresent(String.self, forKey: .entityType)
        sourceEpisode = try c.decodeIfPresent(String.self, forKey: .sourceEpisode)
        sourceEpisodeTimestamp = try c.decodeIfPresent(String.self, forKey: .sourceEpisodeTimestamp)
        claimId = try c.decodeIfPresent(String.self, forKey: .claimId)
        cause = try c.decodeIfPresent(InboxCause.self, forKey: .cause)
        extractorConfidence = try c.decodeIfPresent(Double.self, forKey: .extractorConfidence)
        extractorModel = try c.decodeIfPresent(String.self, forKey: .extractorModel)
        recommendedKey = try c.decodeIfPresent(String.self, forKey: .recommendedKey)
        informational = try c.decodeIfPresent(Bool.self, forKey: .informational) ?? false
    }

    /// Display name for the card header, falling back to the title when no
    /// entity name is attached (pure clarification with no entity yet).
    var displayName: String {
        entityName.isEmpty ? title : entityName
    }

    /// What `QuestionView` shows as the question line.
    var questionText: String {
        if let question, !question.isEmpty { return question }
        return title.isEmpty ? body : title
    }

    var createdDateValue: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: createdDate) ?? .now
    }
}
