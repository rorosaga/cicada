import Foundation

/// DS-3c — the list pages' words (Clusters, the Feed, Sources), in D (DR-59: sentence case, plain verbs, no "!", no bare
/// "%", no ids — DR-54). Its own file for the reason `Copy+Inbox.swift` gives: parallel tracks edit `Copy.swift`.
extension Copy {
    enum Lists {
        // Shared
        static let all = "All"
        static let findHelp = "Find on this page (⌘F)"
        static let closeCard = "Close (Esc)"
        static let showList = "Show the list"
        static func matches(_ n: Int) -> String { n == 1 ? "1 match" : "\(UsageFormat.count(n)) matches" }

        // Clusters
        static let clusters = "Clusters"
        static let type = "Type"
        static let openCard = "Open the card"
        static let decaying = "decaying"
        static let confidenceHelp = "How sure Cicada is about this page"
        static let findClusters = "Search clusters…"
        static let view = "View"
        static let viewFiltered = "View · filtered"
        static let viewHelp = "Types (shared with the Graph), labels and groups"
        static let typesShared = "Types · shared with the Graph"
        static let showEveryType = "Show every type"
        static let labels = "Labels"
        static let searchLabels = "Search labels…"
        static let noLabels = "No labels yet"
        static let noLabelMatch = "No label matches"
        static let clearLabels = "Clear labels"
        static let groupsInAll = "Groups in All"
        static let expandAll = "Expand all"
        static let collapseAll = "Collapse all"
        static let readingMemory = "Reading your memory…"
        static let nothingInView = "Nothing in your memory matches this view."
        static let showEverything = "Show every type and label"
        static func entities(_ n: Int) -> String { n == 1 ? "1 entity" : "\(UsageFormat.count(n)) entities" }
        static func entitiesInGroups(_ n: Int, groups: Int) -> String {
            "\(entities(n)) in \(UsageFormat.count(groups)) \(groups == 1 ? "group" : "groups")"
        }
        static func entitiesBack(_ n: Int) -> String { "‹ \(entities(n))" }
        static func showAll(_ n: Int) -> String { "Show all \(UsageFormat.count(n)) ›" }
        static func typesShown(_ on: Int, of all: Int) -> String { "\(UsageFormat.count(on)) of \(UsageFormat.count(all))" }
        static func labelCount(_ n: Int) -> String { n == 1 ? "1 label" : "\(UsageFormat.count(n)) labels" }
        static func labelsOn(_ n: Int) -> String { "\(UsageFormat.count(n)) on" }
        static func moreLabels(_ n: Int) -> String { "\(UsageFormat.count(n)) more — search to narrow" }
        static func noEntityMatch(_ q: String) -> String { "No entity matches “\(q)”." }
        static func entityRow(type: String, name: String, open: Bool) -> String {
            open ? "Open: \(type), \(name)" : "\(type), \(name)"
        }
    }
}
