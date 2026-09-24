import Foundation

/// §10 Clusters (DR-25, DR-45, DR-46; R-DL9; F-11/F-12 since G146, R-PE12/R-PE13) — what the list shows, pure. The View menu is the ONE filter (the Graph's
/// types, labels); the tabs are navigation over what it lets through; find (⌘F) ranks by name across every group.
enum ClustersModel {
    /// DR-39 — "Expand all" is the viewer's to keep.
    static let expandAllKey = "cicada.clusters.expandAll"

    struct Group: Identifiable {
        let type: EntityType
        let entities: [Entity]
        var id: EntityType { type }
    }

    /// One drawn line. Rows are direct children of the lazy stack (a group's header, its rows and its "Show all" are
    /// siblings), so a 600-entity type expanded by "Expand all" never builds more rows than fit on screen.
    enum ClusterLine: Identifiable {
        /// `recency` — a tab's header says its order ("· recently mentioned first", R-PE13); All's does not repeat it
        /// once per group.
        case header(EntityType, count: Int, first: Bool, recency: Bool)
        case row(Entity, showsType: Bool)
        case more(EntityType, count: Int)

        var id: String {
            switch self {
            case .header(let t, _, _, _): "header:\(t.rawValue)"
            case .row(let e, _): e.id
            case .more(let t, _): "more:\(t.rawValue)"
            }
        }

        var entity: Entity? {
            if case .row(let e, _) = self { return e }
            return nil
        }
    }

    /// F-11 (R-PE12) — the six primary types lead, then every other selectable type in its usual order.
    static let typeOrder: [EntityType] = ClustersGrid.primary
        + EntityType.selectableCases.filter { !ClustersGrid.primary.contains($0) }

    /// The View menu's filter: a type the Graph hides is hidden here too (one filter, two surfaces); a label narrows to
    /// pages carrying any chosen label. Recency first (R-PE13 — F-12's "recently mentioned first"), A→Z to break a tie.
    /// `lastReferenced` is an ISO day, so a string compare is a date compare; a page with none sorts last.
    static func filtered(_ all: [Entity], types: Set<EntityType>, labels: Set<String>) -> [Entity] {
        all.filter { types.contains($0.type) && (labels.isEmpty || !labels.isDisjoint(with: Set($0.tags))) }
            .sorted { a, b in
                if a.lastReferenced != b.lastReferenced { return a.lastReferenced > b.lastReferenced }
                return a.name.localizedCaseInsensitiveCompare(b.name) == .orderedAscending
            }
    }

    /// In `typeOrder` (the grid's order, so the tabs, the cards and All's list agree), empty types dropped.
    static func groups(_ filtered: [Entity]) -> [Group] {
        let buckets = Dictionary(grouping: filtered, by: \.type)
        return typeOrder.compactMap { type in buckets[type].map { Group(type: type, entities: $0) } }
    }

    static func tabs(_ groups: [Group]) -> [TextTab<EntityType>] {
        [TextTab(id: nil, label: Copy.Lists.all, count: groups.reduce(0) { $0 + $1.entities.count })]
            + groups.map { TextTab(id: $0.type, label: $0.type.groupLabel, count: $0.entities.count) }
    }

    /// G136 S5 — ranked by `QuickMatch` (`rank`, the graph's cached index), never showing what the View menu hides.
    /// `nil` while the words hold no token: a field of spaces lists the clusters, not an empty "no match".
    static func matches(query: String, within filtered: [Entity], rank: (String) -> [Entity]) -> [Entity]? {
        guard !QuickMatch.tokens(query).isEmpty else { return nil }
        let allowed = Set(filtered.map(\.id))
        return rank(query).filter { allowed.contains($0.id) }
    }

    /// §10 — five rows a group with nothing open, three beside a card; "Show all N ›" opens the group's tab.
    static func cap(for style: ColumnPlan.ListStyle) -> Int { style == .wide ? 5 : 3 }

    /// The lines in the order they are drawn: find's ranked matches (types mixed, so each row names its own); a tab's
    /// group under one header that names its order (R-PE13); or All's groups, each capped unless Expand all.
    static func lines(groups: [Group], tab: EntityType?, matches: [Entity]?, expandAll: Bool, cap: Int) -> [ClusterLine] {
        if let matches { return matches.map { .row($0, showsType: true) } }
        if let tab {
            let rows = groups.first { $0.type == tab }?.entities ?? []
            return [.header(tab, count: rows.count, first: true, recency: true)] + rows.map { .row($0, showsType: false) }
        }
        return groups.enumerated().flatMap { index, group -> [ClusterLine] in
            let shown = expandAll ? group.entities : Array(group.entities.prefix(cap))
            var out: [ClusterLine] = [.header(group.type, count: group.entities.count,
                                                         first: index == 0, recency: false)]
            out += shown.map { .row($0, showsType: false) }
            if shown.count < group.entities.count { out.append(.more(group.type, count: group.entities.count)) }
            return out
        }
    }

    /// DR-25 — "Clusters · 957 entities in 11 groups" / "· Projects · 42 entities" / "· Projects · 3 of 42" / "· 12 matches".
    static func eyebrow(groups: [Group], tab: EntityType?, matches: [Entity]?, openId: String?) -> String {
        if let matches { return Eyebrow.text(Copy.Lists.clusters, Copy.Lists.matches(matches.count)) }
        if let tab, let group = groups.first(where: { $0.type == tab }) {
            if let openId, let i = group.entities.firstIndex(where: { $0.id == openId }) {
                return Eyebrow.text(Copy.Lists.clusters, tab.groupLabel, Copy.Inbox.position(i + 1, of: group.entities.count))
            }
            return Eyebrow.text(Copy.Lists.clusters, tab.groupLabel, Copy.Lists.entities(group.entities.count))
        }
        let total = groups.reduce(0) { $0 + $1.entities.count }
        return Eyebrow.text(Copy.Lists.clusters,
                            total == 0 ? "" : Copy.Lists.entitiesInGroups(total, groups: groups.count))
    }

    /// F-11 — a tile's one line in words: the page's Summary, else the graph's preview. Never tags, a percentage or a
    /// confidence (the owner: "no tags, no percentages").
    static func line(_ e: Entity) -> String? {
        guard let text = EntityHeaderWords.summary(markdown: e.markdownContent, isStub: e.rawMarkdown.isEmpty) else {
            return nil
        }
        let first = ExcerptText.clean(text).split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        let trimmed = first.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// A row beside a card: the type only where types mix (find's matches), then the line.
    static func detail(_ e: Entity, showsType: Bool) -> String? {
        let parts = [showsType ? e.type.label : nil, line(e)].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// F-12 — a row's age since it was last mentioned (DR-58: `RelativeDay`'s words).
    static func age(_ e: Entity, today: ISODay) -> String {
        RelativeDay.compactAge(ISODay(e.lastReferenced), today: today)
    }

    /// Every label in the bank with its count, A→Z — the View menu's list (the retired label popover's).
    static func labelCounts(_ all: [Entity]) -> [(label: String, count: Int)] {
        var counts: [String: Int] = [:]
        for e in all { for t in e.tags where !t.isEmpty { counts[t, default: 0] += 1 } }
        return counts.map { (label: $0.key, count: $0.value) }
            .sorted { $0.label.localizedCaseInsensitiveCompare($1.label) == .orderedAscending }
    }
}

extension EntityType {
    /// R-PE13 — a group's name as a person says it: plural, and "Places"/"Folders" rather than the schema's words.
    var groupLabel: String {
        switch self {
        case .person: "People"
        case .project: "Projects"
        case .company: "Companies"
        case .concept: "Concepts"
        case .tool: "Tools"
        case .deadline: "Deadlines"
        case .skill: "Skills"
        case .location: "Places"
        case .media: "Media"
        case .hub: "Hubs"
        case .directory: "Folders"
        case .unknown: "Other"
        }
    }
}
