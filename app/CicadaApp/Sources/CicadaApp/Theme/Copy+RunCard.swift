import Foundation

/// The run card (owner 2026-10-26: "this consolidation ran at this time and it included this thing, with a dropdown")
/// — every word Past nights' cards and their dropdown say. Provider-neutral: an engine or a model is named only as the
/// person's own choice, passed in as data (`Copy.engineLabel`, the ledger's model ids). Ruling 12: no figure is spelled
/// here; a run's plan usage or cost is `CycleUsageText`'s, with its basis.
extension Copy {
    enum RunCard {
        /// G227 — a page whose title another page shares, inside its own `Tag`: "<name-a> · IDE".
        static func qualified(_ name: String, _ qualifier: String) -> String { "\(name) · \(qualifier)" }
        static func count(_ n: Int, _ locale: Locale) -> String { UsageFormat.count(n, locale: locale) }
        private static func noun(_ n: Int, _ one: String, _ many: String, _ locale: Locale) -> String {
            "\(count(n, locale)) \(n == 1 ? one : many)"
        }

        // MARK: The card's one line — "12 conversations → 1 new page, 18 updated"

        /// What it read, then what that made of the memory (owner 2026-11-23: "less dense … I want to easily see what was
        /// consolidated"). Questions are the dropdown's, not the card's. A run that read and wrote nothing still says
        /// what it read. Unknown (`nil`) is never a zero.
        static func summary(conversations: Int?, created: Int?, updated: Int?,
                            locale: Locale = .autoupdatingCurrent) -> String {
            var wrote: [String] = []
            if let created, created > 0 { wrote.append(noun(created, "new page", "new pages", locale)) }
            if let updated, updated > 0 {
                wrote.append(wrote.isEmpty ? noun(updated, "page updated", "pages updated", locale)
                                           : "\(count(updated, locale)) updated")
            }
            let written = wrote.isEmpty ? nil : wrote.joined(separator: ", ")
            guard let conversations else { return written ?? nothingRecorded }
            let read = noun(conversations, "conversation", "conversations", locale)
            if let written { return "\(read) → \(written)" }
            return created == 0 && updated == 0 ? "\(read) → \(nothingNew)" : read
        }
        static let nothingNew = "nothing new"
        static let nothingRecorded = "Not recorded"
        /// The pages a collapsed card could not fit: "+3".
        static func morePages(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "+\(count(n, locale))" }
        /// The sources a card's marks could not fit, on the last mark's place: "+2".
        static func moreSources(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "+\(count(n, locale))" }
        /// "Read from Claude Code, ChatGPT" — the card's marks in words, for the pointer and VoiceOver.
        static func readFrom(_ names: [String]) -> String { "Read from \(names.joined(separator: ", "))" }

        // MARK: Who started it

        static let startedByYou = "You started it"
        static let startedBySchedule = "On schedule"

        // MARK: How it ended

        static let finished = "Finished"
        static let reading = "Reading now"
        static let pausedPlanLimit = "Paused at your plan's limit"
        static let pausedReserve = "Paused to leave room in your plan"
        static let paused = "Paused"
        static let stopped = "Stopped"
        static let failed = "Didn't finish"

        // MARK: The dropdown

        static let conversationsRead = "Conversations read"
        static let pagesCreated = "New pages"
        static let pagesUpdated = "Updated pages"
        /// Owner 2026-11-23 ("see what page or chunk of page/pages was modified"): every page the read made or changed,
        /// one row each; a click shows what changed on it.
        static let pagesChanged = "Pages changed"
        static let newPage = "New"
        static let showChange = "Show change"
        static let hideChange = "Hide change"
        static func changeHelp(_ name: String) -> String { "What this read changed on \(name)" }
        static let noChange = "No line changed on this page."
        static func took(_ length: String) -> String { "Read for \(length)" }
        static let questionsRaised = "Questions raised"
        static let questionsSettled = "Questions settled"
        static let loading = "Loading…"
        static let unavailable = "Not recorded"
        static let untitled = "Untitled conversation"
        static let moreNotListed = "Not all listed"
        static func showAll(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "Show all \(count(n, locale))" }
        static let showFewer = "Show fewer"
        static let goneHelp = "No longer in your memory"
        static let detailsTitle = "Models and batches"
        static func openConversation(_ title: String) -> String { "Open \(title)" }
        static func openPage(_ name: String) -> String { "Open \(name)" }
        static func openQuestion(_ title: String) -> String { "Open \(title) in your questions" }

        /// Short labels the copy lints read.
        static let labels = [startedByYou, startedBySchedule, finished, reading, pausedPlanLimit, pausedReserve, paused,
                             stopped, failed, conversationsRead, pagesCreated, pagesUpdated, pagesChanged, newPage,
                             showChange, hideChange, questionsRaised, questionsSettled, detailsTitle]
    }
}
