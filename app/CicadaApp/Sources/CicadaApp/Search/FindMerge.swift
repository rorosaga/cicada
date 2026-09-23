import Foundation

/// Design §3.2's merge rule, as pure functions: local rows render first; server
/// rows dedupe against them by `(kind, id)` and APPEND in their group; rows
/// already shown for this query never reorder; a new keystroke re-sorts
/// everything; the top hit comes from the local tier only.
enum FindMerge {
    static func fresh(query: String, local: QuickIndex.Result) -> FindResults {
        var results = FindResults(query: query)
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return results }
        results.ask = FindRow(key: FindRowKey(kind: .ask, id: "ask"), group: .ask,
                              title: "Ask Cicada: “\(trimmed)”", mark: .symbol("sparkle.magnifyingglass"),
                              trailing: "⌘⏎", destination: .ask(trimmed))
        var groups = Dictionary(grouping: local.rows, by: \.group)
        results.localCounts = local.counts
        // An Asked-before row repeats a question; it never stands for the thing searched.
        var top: FindRow?
        for row in local.rows where row.group != .askedBefore {
            if let best = top, !(row.score > best.score || (row.score == best.score && row.group < best.group)) { continue }
            top = row
        }
        if var hit = top {
            groups[hit.group]?.removeAll { $0.key == hit.key }
            results.localCounts[hit.group] = max(0, (local.counts[hit.group] ?? 1) - 1)
            hit.group = .topHit
            results.topHit = hit
        }
        results.groups = groups.filter { !$0.value.isEmpty }
        return results
    }

    static func append(_ server: [FindRow], totals: [FindGroupID: FindCount], to results: FindResults) -> FindResults {
        var out = results
        var seen = out.keys
        for row in server where seen.insert(row.key).inserted {
            out.groups[row.group, default: []].append(row)
        }
        for (group, count) in totals { out.serverCounts[group] = count }
        return out
    }
}

enum FindStep: Equatable, Sendable { case next, previous, first, last, nextGroup, previousGroup }

/// The keyboard walk over what renders (design §3.4). The selection is a
/// key, never an index, so an append can never move it (§3.2).
enum FindSelection {
    static func flat(_ sections: [FindSection]) -> [(group: FindGroupID, key: FindRowKey)] {
        sections.flatMap { section in section.rows.map { (group: section.group, key: $0.key) } }
    }

    /// The top hit, else the first row that is not the Ask row, else the Ask row.
    static func initial(_ sections: [FindSection]) -> FindRowKey? {
        if let top = sections.first(where: { $0.group == .topHit })?.rows.first { return top.key }
        if let first = sections.first(where: { $0.group != .ask })?.rows.first { return first.key }
        return sections.first?.rows.first?.key
    }

    /// R-SU11: clamps at both ends.
    static func move(_ current: FindRowKey?, _ step: FindStep, in sections: [FindSection]) -> FindRowKey? {
        let rows = flat(sections)
        guard !rows.isEmpty else { return nil }
        guard let current, let index = rows.firstIndex(where: { $0.key == current }) else { return initial(sections) }
        switch step {
        case .next: return rows[min(index + 1, rows.count - 1)].key
        case .previous: return rows[max(index - 1, 0)].key
        case .first: return rows[0].key
        case .last: return rows[rows.count - 1].key
        case .nextGroup:
            let group = rows[index].group
            return rows[index...].first(where: { $0.group != group })?.key ?? current
        case .previousGroup:
            let group = rows[index].group
            guard let previous = rows[..<index].last(where: { $0.group != group })?.group else { return current }
            return rows.first(where: { $0.group == previous })?.key
        }
    }
}

/// R-SU6 — ids only, per bank, and only what the local tier can draw again.
enum FindRecents {
    static let limit = 6
    static let recordable: Set<FindKind> = [.entity, .media, .source, .inbox, .setting, .action, .bank]

    static func push(_ key: FindRowKey, into list: [FindRowKey]) -> [FindRowKey] {
        guard recordable.contains(key.kind) else { return list }
        return Array(([key] + list.filter { $0 != key }).prefix(limit))
    }
}

/// Every string a row speaks, pure so VoiceOver's text is tested (design §3.8).
enum FindRowText {
    static func kindLabel(_ row: FindRow) -> String {
        switch row.key.kind {
        case .ask: "Ask"
        case .entity: row.badge ?? "Entity"
        case .conversation: "Conversation"
        case .belief: row.history == nil ? "Belief" : "Earlier belief"
        case .media: "Saved item"
        case .source: "Source"
        case .inbox: "Question"
        case .setting: "Setting"
        case .action: "Action"
        case .bank: "Memory bank"
        case .askedBefore: "Asked before"
        }
    }

    static func accessibilityLabel(_ row: FindRow) -> String {
        let quote = row.snippet.map { snippet in row.speaker.map { "\($0): \(snippet)" } ?? snippet }
        return [kindLabel(row), row.title, row.detail, row.history, quote]
            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
    }

    static func announcement(_ row: FindRow, position: Int, of total: Int) -> String {
        "\(kindLabel(row)), \(row.title), \(position) of \(total)"
    }

    static func moreLabel(_ count: FindCount) -> String {
        switch count {
        case .exact(let n): "Show all \(UsageFormat.count(n))"
        case .atLeast: "More…"
        }
    }

    static func primaryVerb(_ destination: FindDestination) -> String {
        switch destination {
        case .entity, .belief: "Show on graph"
        case .entityInClusters: "Open in Clusters"
        case .feedItem: "Preview"
        case .openURL: "Open in browser"
        case .source, .conversations: "Open in Sources"
        case .conversation, .evidence: FindReaderSeam.isAvailable ? "Open conversation" : "Open in Sources"
        case .inbox: "Answer"
        case .settings: "Open in Settings"
        case .tab: "Go"
        case .action: "Run"
        case .bank: "Switch"
        case .ask: "Ask"
        case .askedBefore: "Show answer"
        }
    }

    static func secondaryVerb(_ destination: FindDestination?) -> String? {
        switch destination {
        case .entityInClusters?: "Open in Clusters"
        case .openURL?: "Open in browser"
        case .conversations?: "All from this app"
        case .evidence?: "Where it was said"
        case .ask?: "Ask again"
        default: nil
        }
    }
}
