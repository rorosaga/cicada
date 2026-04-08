import Foundation

struct Clarification: Identifiable {
    let id: String
    var entityMention: String
    var uncertaintyType: String
    var sourceContext: String
    var suggestedClassification: String?
    var suggestedConfidence: Double?
    var createdDate: Date
}
