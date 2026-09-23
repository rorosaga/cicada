import Foundation

/// Clusters' search, precomputed (G136 S5; design §3.7). The old filter
/// lowercased every entity's name, tags and summary on every keystroke
/// (`TopicsView.filteredEntities`); this folds them once per graph snapshot
/// (`GraphViewModel.clusterSearchIndex()`) and ranks through `QuickMatch`.
struct ClusterSearchIndex {
    struct Entry {
        let entity: Entity
        let fields: [QuickMatch.Field]
    }

    private(set) var entries: [Entry] = []

    init(_ entities: [Entity] = []) {
        entries = entities.map { entity in
            var fields = [QuickMatch.Field(entity.name, weight: QuickMatch.Weight.name)]
            fields += entity.tags.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
            if !entity.markdownContent.isEmpty {
                fields.append(QuickMatch.Field(entity.markdownContent, weight: QuickMatch.Weight.body))
            }
            return Entry(entity: entity, fields: fields)
        }
    }

    /// Best first — the flat ranked list Clusters shows while searching.
    func rank(_ query: String) -> [Entity] {
        QuickMatch.rank(entries, query: query, fields: { $0.fields }, tieBreak: { _ in 0 },
                        name: { $0.entity.name.lowercased() }).map { $0.item.entity }
    }

    /// A row's bold runs in its name.
    static func titleRanges(_ name: String, query: String) -> [[Int]] {
        QuickMatch.match(QuickMatch.tokens(query), fields: [QuickMatch.Field(name, weight: 1)])?.ranges(inField: 0) ?? []
    }
}
