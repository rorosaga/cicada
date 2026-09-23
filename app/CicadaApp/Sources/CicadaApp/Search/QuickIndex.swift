import Foundation

/// A value copy of what the local tier reads, taken on the main actor and
/// handed to a detached build (design §3.2: "built off the main actor").
struct QuickIndexInputs: Sendable {
    var nodes: [GraphNode] = []
    var media: [MediaFeedItem] = []
    var sources: [SourceOverview] = []
    var inbox: [InboxItem] = []
    var banks: [MemoryBank] = []
    var activeBank: String? = nil
    var askHistory: [AskHistoryEntry] = []
    var isSleeping = false
    var unprocessed = 0
    var appearance: AppColorScheme = .dark

    @MainActor
    static func from(_ store: Store, askHistory: [AskHistoryEntry]) -> QuickIndexInputs {
        QuickIndexInputs(nodes: store.graph.value?.nodes ?? [], media: store.sources.value ?? [],
                         sources: store.sourcesOverview.value ?? [], inbox: store.visibleInbox,
                         banks: store.banks.value?.banks ?? [], activeBank: store.bank,
                         askHistory: askHistory,
                         isSleeping: store.status.value?.sleep.status == "running",
                         unprocessed: store.status.value?.episodes.unprocessed ?? 0,
                         appearance: CicadaTheme.mode)
    }

    /// Changes whenever an input could have (R-SU5) — timestamps, counts and
    /// flags only, never a name or a query. `unprocessed` enters as a flag: a
    /// capture on every agent turn must not rebuild the index each time.
    @MainActor
    static func token(_ store: Store, askHistoryCount: Int) -> String {
        let stamps = [store.graph.loadedAt, store.sources.loadedAt, store.sourcesOverview.loadedAt,
                      store.inbox.loadedAt, store.banks.loadedAt]
            .map { $0.map { String($0.timeIntervalSince1970) } ?? "-" }
        let flags = ["\(store.hiddenInboxIds.count)", "\(askHistoryCount)",
                     store.status.value?.sleep.status ?? "",
                     (store.status.value?.episodes.unprocessed ?? 0) > 0 ? "waiting" : "rested",
                     CicadaTheme.mode.rawValue]
        return ([store.bank] + stamps + flags).joined(separator: "|")
    }
}

/// The palette's instant tier (G136; round-3 design §3.2 "Tier 1"): an
/// immutable value over the Store's snapshots, folded once per build and
/// queried on every keystroke with no network. Budget: R-SU24.
struct QuickIndex: Sendable {
    struct Doc: Sendable {
        let row: FindRow
        /// `fields[0]` is always the row's title — its ranges bold the title.
        let fields: [QuickMatch.Field]
    }

    struct Result: Equatable, Sendable {
        var rows: [FindRow] = []
        /// Every local match per group before the materialisation cap — the honest "Show all N".
        var counts: [FindGroupID: Int] = [:]
    }

    /// Past this, a group stops materialising rows; its count stays exact.
    static let rowCap = 50
    static let empty = QuickIndex()

    private(set) var docs: [Doc] = []
    private(set) var byKey: [FindRowKey: Int] = [:]
    private(set) var suggested: [FindRow] = []
    private(set) var askedBefore: [FindRow] = []

    init() {}

    static func build(_ inputs: QuickIndexInputs) -> QuickIndex {
        var index = QuickIndex()
        let asked = askedDocs(inputs.askHistory)
        index.docs = entityDocs(inputs.nodes) + mediaDocs(inputs.media) + sourceDocs(inputs.sources)
            + inboxDocs(inputs.inbox) + settingsDocs() + PaletteActions.docs(inputs) + asked
        for (i, doc) in index.docs.enumerated() where index.byKey[doc.row.key] == nil {
            index.byKey[doc.row.key] = i
        }
        index.suggested = PaletteActions.suggested(inputs)
        index.askedBefore = asked.prefix(3).map(\.row)
        return index
    }

    func query(_ text: String) -> Result {
        let tokens = QuickMatch.tokens(text)
        guard !tokens.isEmpty else { return Result() }
        var byGroup: [FindGroupID: [(doc: Int, match: QuickMatch.Match)]] = [:]
        for (i, doc) in docs.enumerated() {
            if let found = QuickMatch.match(tokens, fields: doc.fields) {
                byGroup[doc.row.group, default: []].append((i, found))
            }
        }
        var result = Result()
        for group in FindGroupID.allCases {
            guard let hits = byGroup[group] else { continue }
            result.counts[group] = hits.count
            let ordered = hits.sorted { a, b in
                if a.match.score != b.match.score { return a.match.score > b.match.score }
                let ra = docs[a.doc].row, rb = docs[b.doc].row
                if ra.tieBreak != rb.tieBreak { return ra.tieBreak > rb.tieBreak }
                return ra.title < rb.title
            }
            for hit in ordered.prefix(Self.rowCap) {
                var row = docs[hit.doc].row
                row.score = hit.match.score
                row.titleRanges = hit.match.ranges(inField: 0)
                result.rows.append(row)
            }
        }
        return result
    }

    /// Nothing typed (design §3.6): Recent (ids resolved here; a gone id is
    /// dropped), then Asked before (three), then Suggested.
    func emptyState(recents: [FindRowKey]) -> FindResults {
        var results = FindResults()
        let recent = recents.compactMap { key -> FindRow? in
            guard let i = byKey[key] else { return nil }
            var row = docs[i].row
            row.group = .recent
            return row
        }
        if !recent.isEmpty { results.groups[.recent] = recent }
        if !askedBefore.isEmpty { results.groups[.askedBefore] = askedBefore }
        if !suggested.isEmpty { results.groups[.suggested] = suggested }
        return results
    }
}

extension QuickIndex {
    /// Graph nodes minus facets, hubs and media pages (R-SU5).
    static func entityDocs(_ nodes: [GraphNode]) -> [Doc] {
        nodes.compactMap { node in
            guard !node.isFacet, !node.isHub, node.type != .hub, node.type != .media else { return nil }
            var fields = [QuickMatch.Field(node.name, weight: QuickMatch.Weight.name)]
            fields += node.aliases.map { QuickMatch.Field($0, weight: QuickMatch.Weight.alias) }
            fields += node.tags.map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
            if let summary = node.summary, !summary.isEmpty {
                fields.append(QuickMatch.Field(summary, weight: QuickMatch.Weight.body))
            }
            let row = FindRow(key: FindRowKey(kind: .entity, id: node.id), group: .entities, title: node.name,
                              detail: node.summary.flatMap(firstLine), badge: node.type.label,
                              mark: .entity(id: node.id, name: node.name, type: node.type),
                              tieBreak: Double(node.degree), destination: .entity(id: node.id),
                              secondary: .entityInClusters(id: node.id))
            return Doc(row: row, fields: fields)
        }
    }

    /// One row per media page, whatever number of URLs share its id.
    static func mediaDocs(_ items: [MediaFeedItem]) -> [Doc] {
        var seen = Set<String>()
        return items.compactMap { item in
            guard seen.insert(item.mediaEntityId).inserted else { return nil }
            let title = item.title.isEmpty ? item.url : item.title
            let row = FindRow(key: FindRowKey(kind: .media, id: item.mediaEntityId), group: .sources, title: title,
                              detail: item.site ?? item.channel, badge: item.mediaType,
                              mark: .entity(id: item.mediaEntityId, name: title, type: .media),
                              tieBreak: item.recencyDate.timeIntervalSince1970,
                              destination: .feedItem(mediaEntityId: item.mediaEntityId),
                              secondary: .openURL(item.url))
            return Doc(row: row, fields: FeedSearch.fields(item))
        }
    }

    /// The Sources page's cards, under the product names that page prints.
    static func sourceDocs(_ rows: [SourceOverview]) -> [Doc] {
        rows.map { source in
            let name = SourceDisplayName.of(source)
            var fields = [QuickMatch.Field(name, weight: QuickMatch.Weight.name),
                          QuickMatch.Field(source.label, weight: QuickMatch.Weight.alias)]
            fields += (source.origins + [source.harness].compactMap { $0 })
                .map { QuickMatch.Field($0, weight: QuickMatch.Weight.keyword) }
            let row = FindRow(key: FindRowKey(kind: .source, id: source.id), group: .sources, title: name,
                              badge: "Source", mark: .origin(source.mark), tieBreak: Double(source.episodes),
                              destination: .source(id: source.id))
            return Doc(row: row, fields: fields)
        }
    }

    static func inboxDocs(_ items: [InboxItem]) -> [Doc] {
        items.map { item in
            let row = FindRow(key: FindRowKey(kind: .inbox, id: item.id), group: .inbox, title: InboxSearch.title(item),
                              detail: item.entityName.isEmpty ? nil : item.entityName, badge: item.kind.label,
                              mark: .symbol(item.kind.icon), tieBreak: item.priority, destination: .inbox(id: item.id))
            return Doc(row: row, fields: InboxSearch.fields(item))
        }
    }

    /// R-SU12 — one row per Settings section, whatever sections exist.
    static func settingsDocs() -> [Doc] {
        SettingsSection.allCases.enumerated().map { i, section in
            let row = FindRow(key: FindRowKey(kind: .setting, id: section.rawValue), group: .settings,
                              title: section.title, detail: Copy.settings, mark: .symbol(section.icon),
                              tieBreak: -Double(i), destination: .settings(section))
            return Doc(row: row, fields: [QuickMatch.Field(section.title, weight: QuickMatch.Weight.name),
                                          QuickMatch.Field(Copy.settings, weight: QuickMatch.Weight.keyword)])
        }
    }

    static func askedDocs(_ history: [AskHistoryEntry]) -> [Doc] {
        history.map { entry in
            let row = FindRow(key: FindRowKey(kind: .askedBefore, id: entry.id), group: .askedBefore,
                              title: entry.question, mark: .symbol("arrow.uturn.left"),
                              tieBreak: entry.askedAt.timeIntervalSince1970,
                              destination: .askedBefore(question: entry.question), secondary: .ask(entry.question))
            return Doc(row: row, fields: [QuickMatch.Field(entry.question, weight: QuickMatch.Weight.name)])
        }
    }

    static func firstLine(_ text: String) -> String? {
        let line = text.split(whereSeparator: \.isNewline).first.map(String.init)?
            .trimmingCharacters(in: .whitespaces)
        return (line?.isEmpty ?? true) ? nil : line
    }
}
