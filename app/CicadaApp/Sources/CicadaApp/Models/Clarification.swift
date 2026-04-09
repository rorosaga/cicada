import Foundation

struct Clarification: Identifiable, Codable {
    let id: String
    var entityMention: String
    var uncertaintyType: String
    var sourceContext: String
    var suggestedClassification: String?
    var suggestedConfidence: Double?
    var createdDate: String

    var createdDateValue: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: createdDate) ?? .now
    }
}
