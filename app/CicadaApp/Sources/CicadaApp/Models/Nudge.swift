import Foundation

enum NudgeType: String, Codable {
    case decay, conflict, clarification

    var icon: String {
        switch self {
        case .decay: "clock.arrow.circlepath"
        case .conflict: "exclamationmark.triangle.fill"
        case .clarification: "questionmark.circle.fill"
        }
    }

    var label: String {
        rawValue.capitalized
    }

    var color: UInt32 {
        switch self {
        case .decay: 0xF59E0B
        case .conflict: 0xEF4444
        case .clarification: 0x7C8FFF
        }
    }
}

struct Nudge: Identifiable, Codable {
    let id: String
    var entityName: String
    var entityId: String
    var type: NudgeType
    var shortDescription: String
    var fullContext: String
    var options: [String]?
    var createdDate: String

    var createdDateValue: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: createdDate) ?? .now
    }
}
