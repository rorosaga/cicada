import Foundation

/// The run card (owner 2026-10-26: "this consolidation ran at this time and it included this thing, with a dropdown")
/// — every word Past nights' cards and their dropdown say. Provider-neutral: an engine or a model is named only as the
/// person's own choice, passed in as data (`Copy.engineLabel`, the ledger's model ids). Ruling 12: no figure is spelled
/// here; a run's plan usage or cost is `CycleUsageText`'s, with its basis.
extension Copy {
    enum RunCard {
        static func count(_ n: Int, _ locale: Locale) -> String { UsageFormat.count(n, locale: locale) }
        private static func noun(_ n: Int, _ one: String, _ many: String, _ locale: Locale) -> String {
            "\(count(n, locale)) \(n == 1 ? one : many)"
        }

        // MARK: The card's one-line summary — "12 conversations · 3 new pages · 18 updates · 2 questions"

        /// Parts with nothing to say drop out, except what it read: a run that read and wrote nothing still says what
        /// it read. Unknown (`nil`) is never a zero.
        static func summary(conversations: Int?, created: Int?, updated: Int?, questions: Int?,
                            locale: Locale = .autoupdatingCurrent) -> String {
            var parts: [String] = []
            if let conversations { parts.append(noun(conversations, "conversation", "conversations", locale)) }
            if let created, created > 0 { parts.append(noun(created, "new page", "new pages", locale)) }
            if let updated, updated > 0 { parts.append(noun(updated, "update", "updates", locale)) }
            if let questions, questions > 0 { parts.append(noun(questions, "question", "questions", locale)) }
            if parts.count == 1, created == 0, updated == 0 { parts.append(nothingNew) }
            return parts.isEmpty ? nothingRecorded : parts.joined(separator: " · ")
        }
        static let nothingNew = "nothing new"
        static let nothingRecorded = "What it read was not recorded"

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
        static let questionsRaised = "Questions raised"
        static let questionsSettled = "Questions settled"
        static let loading = "Reading what it consolidated…"
        static let unavailable = "What this run consolidated is not recorded."
        static let untitled = "Untitled conversation"
        static let moreNotListed = "More than the list shows — the counts are whole."
        static func showAll(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "Show all \(count(n, locale))" }
        static let showFewer = "Show fewer"
        static let goneHelp = "This page is no longer in your memory (merged or removed since)."
        static let detailsTitle = "Models and batches"
        static func openConversation(_ title: String) -> String { "Open \(title)" }
        static func openPage(_ name: String) -> String { "Open \(name)" }
        static func openQuestion(_ title: String) -> String { "Open \(title) in the Inbox" }

        /// Short labels the copy lints read.
        static let labels = [startedByYou, startedBySchedule, finished, reading, pausedPlanLimit, pausedReserve, paused,
                             stopped, failed, conversationsRead, pagesCreated, pagesUpdated, questionsRaised,
                             questionsSettled, detailsTitle]
    }
}
