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

/// One unified inbox item. Decodes the camelCase payload from `GET /inbox`
/// (`api/routers/inbox.py` → `InboxItem`). Optional fields are only populated
/// for clarification / merge kinds.
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
    var options: [String]?
    var createdDate: String
    var uncertaintyType: String?
    var suggestedClassification: String?
    var suggestedConfidence: Double?
    var mergeTargetHint: String?

    enum CodingKeys: String, CodingKey {
        case id, kind, requiredInput, status, priority
        case entityId, entityName, title, body, options, createdDate
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
        options = try c.decodeIfPresent([String].self, forKey: .options)
        createdDate = try c.decodeIfPresent(String.self, forKey: .createdDate) ?? ""
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

    var createdDateValue: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: createdDate) ?? .now
    }
}
