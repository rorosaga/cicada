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
struct InboxOption: Identifiable, Codable, Hashable {
    var key: String
    var label: String
    var description: String?
    var claimId: String?
    var observedAt: String?
    var lastReferenced: String?
    var ageDays: Int?

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

    enum CodingKeys: String, CodingKey {
        case id, kind, requiredInput, status, priority
        case entityId, entityName, title, body, options, createdDate
        case question, allowOther, allowDefer, predicate, hint, remindAfter, updatedDate
        case uncertaintyType, suggestedClassification, suggestedConfidence, mergeTargetHint
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
