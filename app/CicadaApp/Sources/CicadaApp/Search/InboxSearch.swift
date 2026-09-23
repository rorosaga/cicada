import Foundation

/// The fields an inbox question is found by — the palette and the Inbox page's
/// own field read this one list (design §3.2's Inbox row: question/title 1.0,
/// entity name 0.7, the cause excerpt 0.4).
enum InboxSearch {
    static func title(_ item: InboxItem) -> String {
        if let question = item.question, !question.isEmpty { return question }
        return item.title
    }

    static func fields(_ item: InboxItem) -> [QuickMatch.Field] {
        var fields = [QuickMatch.Field(title(item), weight: QuickMatch.Weight.name)]
        if !item.entityName.isEmpty { fields.append(QuickMatch.Field(item.entityName, weight: QuickMatch.Weight.keyword)) }
        if let excerpt = item.cause?.excerpt, !excerpt.isEmpty {
            fields.append(QuickMatch.Field(excerpt, weight: QuickMatch.Weight.body))
        }
        return fields
    }

    /// R-SU20: the Inbox keeps its priority order.
    static func filter(_ items: [InboxItem], query: String) -> [InboxItem] {
        let tokens = QuickMatch.tokens(query)
        guard !tokens.isEmpty else { return items }
        return items.filter { QuickMatch.match(tokens, fields: fields($0)) != nil }
    }
}
