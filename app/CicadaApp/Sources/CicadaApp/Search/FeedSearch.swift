import Foundation

/// Every field a saved item is found by — ONE list, read by the Feed page and
/// by the palette (design §3.7: title, site, tags plus description, about, url,
/// channel, origin). Paper authors / arXiv id / DOI join here when Track F's
/// `MediaFeedItem.paper` is on the wire (R-SU21).
enum FeedSearch {
    static func fields(_ item: MediaFeedItem) -> [QuickMatch.Field] {
        var fields = [QuickMatch.Field(item.title.isEmpty ? item.url : item.title, weight: QuickMatch.Weight.name)]
        for value in [item.site, item.channel, item.origin].compactMap({ $0 }) where !value.isEmpty {
            fields.append(QuickMatch.Field(value, weight: QuickMatch.Weight.keyword))
        }
        fields += item.tags.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
        if let description = item.description, !description.isEmpty {
            fields.append(QuickMatch.Field(description, weight: QuickMatch.Weight.body))
        }
        fields.append(QuickMatch.Field(item.url, weight: QuickMatch.Weight.body))
        fields += (item.about ?? []).map { QuickMatch.Field($0, weight: QuickMatch.Weight.body) }
        return fields
    }

    static func matches(_ item: MediaFeedItem, query: String) -> Bool {
        QuickMatch.matches(query, fields: fields(item))
    }

    /// R-SU20: the Feed's own sort is kept; this only filters.
    static func filter(_ items: [MediaFeedItem], query: String) -> [MediaFeedItem] {
        let tokens = QuickMatch.tokens(query)
        guard !tokens.isEmpty else { return items }
        return items.filter { QuickMatch.match(tokens, fields: fields($0)) != nil }
    }
}
