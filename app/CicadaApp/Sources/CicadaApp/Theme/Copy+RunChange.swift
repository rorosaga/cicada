import Foundation

/// What one page's change in a past sleep says (owner 2026-11-24: "pages render normally, not as raw markdown … and I
/// don't get why a page was modified, what influenced this change?"): the step that changed a page, in plain words, and
/// what moved in a fact or in the page's own record. Provider-neutral: a step is named by what it did, never by who ran
/// it. Pure strings and functions, so `RunPageChangeModelTests` holds every sentence without a view.
extension Copy {
    enum RunChange {
        // MARK: The steps — a card's title, and the sentence a page's own change says

        /// The card a step's pages sit under (the plural noun phrase, said once: the count is the card's own).
        static func stepTitle(_ step: SleepConsolidated.Step) -> String {
            switch step {
            case .reading: "Changed while reading"
            case .decay: "Not mentioned for a while"
            case .conflict: "Conflicts settled"
            case .settled: "Questions settled"
            case .join: "Pages joined"
            case .sourceCheck: "Sources re-checked"
            case .linkEnrichment: "Links looked up"
            case .summary: "Summaries rewritten"
            case .web: "Public facts looked up"
            case .expiry: "Facts that reached their end"
            case .import: "Imported"
            case .other: "Other upkeep"
            }
        }

        /// What the step did to a page, as a sentence (a page changed by more than one step names the others).
        static func stepSentence(_ step: SleepConsolidated.Step) -> String {
            switch step {
            case .reading: "Changed while Sleep read"
            case .decay: "Nothing mentioned it for a while"
            case .conflict: "Two facts disagreed and one was settled"
            case .settled: "A question was settled from your own words"
            case .join: "Two pages were joined"
            case .sourceCheck: "A source was re-checked"
            case .linkEnrichment: "A link was looked up"
            case .summary: "Its short summary was rewritten"
            case .web: "Public facts about it were looked up"
            case .expiry: "A fact reached its end date"
            case .import: "An import added it"
            case .other: "A step Cicada could not name"
            }
        }

        /// A step card's hover: what its pages have in common.
        static let stepHelp = "Pages Sleep changed in this step, with no conversation of this read behind them"

        // MARK: The opened change

        static let alsoChangedBy = "Also changed by"
        static let changedBy = "Changed by"
        static let factsAdded = "New facts"
        static let factsChanged = "Facts that changed"
        static let factsWithdrawn = "Facts withdrawn"
        static let text = "Text"
        static let pageRecord = "The page"
        static let loading = "Loading…"
        static let unavailable = "Could not read this page's change."
        static let retry = "Try again"
        static let faded = "Its facts lost a little confidence because nothing mentioned them."

        /// "3 more facts lost confidence — nothing mentioned them", beside the facts that did change.
        static func otherFacts(fadedCount n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) other \(n == 1 ? "fact" : "facts") lost a little confidence from silence"
        }

        static func moreFacts(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "+\(count(n, locale)) more" }
        /// A block of the page's text in words, for VoiceOver (the bar at its edge is colour).
        static func blockWord(_ op: SleepPageChange.Block.Op) -> String {
            switch op {
            case .added: "Added"
            case .removed: "Removed"
            case .edited: "Edited"
            case .context: ""
            }
        }
        static let showFewer = "Show fewer"
        static let cut = "Only part of the change is shown."

        /// "2 smaller changes to the page's record" — the details no sentence says.
        static func smaller(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) smaller \(n == 1 ? "change" : "changes") to the page's record"
        }

        private static func count(_ n: Int, _ locale: Locale) -> String { UsageFormat.count(n, locale: locale) }

        // MARK: The line over it — what is in it, once

        /// "1 new fact · 1 fact changed · 2 passages edited": only what happened, each part said once.
        static func summary(added: Int, changed: Int, withdrawn: Int, passagesAdded: Int, passagesEdited: Int,
                            passagesRemoved: Int, other: Int, _ locale: Locale = .autoupdatingCurrent) -> String? {
            func noun(_ n: Int, _ one: String, _ many: String) -> String { "\(count(n, locale)) \(n == 1 ? one : many)" }
            var parts: [String] = []
            if added > 0 { parts.append(noun(added, "new fact", "new facts")) }
            if changed > 0 { parts.append(noun(changed, "fact changed", "facts changed")) }
            if withdrawn > 0 { parts.append(noun(withdrawn, "fact withdrawn", "facts withdrawn")) }
            if passagesAdded > 0 { parts.append(noun(passagesAdded, "passage added", "passages added")) }
            if passagesEdited > 0 { parts.append(noun(passagesEdited, "passage edited", "passages edited")) }
            if passagesRemoved > 0 { parts.append(noun(passagesRemoved, "passage removed", "passages removed")) }
            if other > 0 { parts.append(noun(other, "other change", "other changes")) }
            return parts.isEmpty ? nil : parts.joined(separator: " · ")
        }

        // MARK: What moved in a fact

        static let reworded = "Reworded"
        static let reopened = "No longer ended"
        static let noExpectedEnd = "No longer expected to end"
        static let replaced = "Replaced by another fact"
        static let replacesOne = "Now replaces an earlier fact"
        static let stoppedReplaced = "No longer replaced"
        static let aboutAnotherPage = "Now about another page"
        static let detailsChanged = "Other details changed"
        static func startsOn(_ day: String) -> String { "Starts \(day)" }
        static func endedOn(_ day: String) -> String { "Ended \(day)" }
        static func expectedToEnd(_ day: String) -> String { "Expected to end \(day)" }
        static func confidence(_ before: String?, _ after: String) -> String {
            before.map { "Confidence \($0) → \(after)" } ?? "Confidence \(after)"
        }
        static func status(_ after: String) -> String { "Now marked \(after)" }
        static func movedTo(_ context: String) -> String { "Now filed under \(context)" }
        static func trust(_ words: String) -> String { "Now counted as: \(words)" }
        static func heldBy(_ who: String) -> String { "Now held by \(who)" }
        static func readAs(_ how: String) -> String { "Now read as \(how)" }
        static func moreConversations(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "Backed by \(count(n, locale)) more \(n == 1 ? "conversation" : "conversations")"
        }
        static func fewerConversations(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            "\(count(n, locale)) \(n == 1 ? "conversation" : "conversations") no longer back it"
        }

        // MARK: What moved on the page

        static func statusMoved(from before: String, to after: String) -> String { "\(before) → \(after)" }
        static func renamed(from before: String, to after: String) -> String { "Renamed from \(before) to \(after)" }
        static func retyped(from before: String, to after: String) -> String { "Now a \(after), was a \(before)" }
        static func keptAs(_ after: String) -> String { "Kept as \(after)" }
        static func addedAlias(_ names: [String]) -> String { "Also called \(names.joined(separator: ", "))" }
        static func removedAlias(_ names: [String]) -> String { "No longer called \(names.joined(separator: ", "))" }
        static func addedTag(_ names: [String]) -> String { "Tagged \(names.joined(separator: ", "))" }
        static func removedTag(_ names: [String]) -> String { "Untagged \(names.joined(separator: ", "))" }
        static func addedSource(_ names: [String]) -> String { "Now checks \(names.joined(separator: ", "))" }
        static func removedSource(_ names: [String]) -> String { "No longer checks \(names.joined(separator: ", "))" }
        static func statusWord(_ raw: String) -> String {
            switch raw {
            case "active": "Active"
            case "decaying": "Fading"
            case "archived": "Archived"
            case "dropped": "Dropped"
            default: raw.prefix(1).uppercased() + raw.dropFirst()
            }
        }
    }
}
