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

        // MARK: The card's one line — "12 conversations · 4 new pages · 9 updated · 1 archived"

        /// What it read, then what that did to the memory, one part for each thing that happened (owner 2026-11-24:
        /// "showing less unnecessary information"): a part that is zero is dropped, the first page part spells its noun
        /// and the rest are short. A run that read and wrote nothing still says what it read. Unknown (`nil`) is never
        /// a zero. Questions are the opened card's own line, never this one.
        static func summary(conversations: Int?, created: Int?, updated: Int?, archived: Int? = nil, removed: Int? = nil,
                            faded: Int? = nil, locale: Locale = .autoupdatingCurrent) -> String {
            var wrote: [String] = []
            func part(_ n: Int?, first: (Int) -> String, later: (Int) -> String) {
                guard let n, n > 0 else { return }
                wrote.append(wrote.isEmpty ? first(n) : later(n))
            }
            part(created, first: { noun($0, "new page", "new pages", locale) },
                 later: { noun($0, "new page", "new pages", locale) })
            part(updated, first: { noun($0, "page updated", "pages updated", locale) },
                 later: { "\(count($0, locale)) updated" })
            part(archived, first: { noun($0, "page archived", "pages archived", locale) },
                 later: { "\(count($0, locale)) archived" })
            part(removed, first: { noun($0, "page removed", "pages removed", locale) },
                 later: { "\(count($0, locale)) removed" })
            // Owner 2026-11-24: fading is its own quiet thing — last, never counted among the changes.
            part(faded, first: { noun($0, "page faded", "pages faded", locale) },
                 later: { "\(count($0, locale)) faded" })
            guard let conversations else { return wrote.isEmpty ? nothingRecorded : wrote.joined(separator: " · ") }
            // A read of no conversations (a plain cycle's decay and upkeep) names only what it did to the pages.
            if conversations == 0 { return wrote.isEmpty ? nothingNewSentence : wrote.joined(separator: " · ") }
            let read = noun(conversations, "conversation", "conversations", locale)
            if !wrote.isEmpty { return ([read] + wrote).joined(separator: " · ") }
            let known = [created, updated, archived, removed, faded].compactMap { $0 }
            return !known.isEmpty && known.allSatisfy({ $0 == 0 }) ? "\(read) · \(nothingNew)" : read
        }
        static let nothingNew = "nothing new"
        static let nothingNewSentence = "Nothing new"
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

        // Owner 2026-11-24 — the opened card: a filter of what happened to the pages, a card per source, and one last
        // group for the pages no conversation of the run stands behind.
        static let filterAll = "All"
        static let filterCreated = "New"
        static let filterUpdated = "Updated"
        static let filterArchived = "Archived"
        static let filterRemoved = "Removed"
        /// Owner 2026-11-24: a page whose facts only lost confidence to silence — a trailing tab, never in All.
        static let filterFaded = "Faded"
        static let filterLabel = "Show pages by what the read did to them"
        static func filterWord(_ change: SleepConsolidated.Change) -> String {
            switch change {
            case .created: filterCreated
            case .updated: filterUpdated
            case .archived: filterArchived
            case .removed: filterRemoved
            case .faded: filterFaded
            }
        }
        static let today = "Today"
        static let yesterday = "Yesterday"
        static let nothingYet = "Nothing consolidated yet."
        static let nothingListed = "Nothing listed for this read."
        static let changeHint = "Shows what this read changed on the page"
        /// A page chip's change in words (its dot's twin, for `.help` and VoiceOver).
        static func changeWord(_ change: SleepConsolidated.Change) -> String {
            switch change {
            case .created: "New page"
            case .updated: "Updated"
            case .archived: "Archived"
            case .removed: "Removed"
            case .faded: "Faded"
            }
        }
        /// Pages a conversation past the server's list fed: not upkeep, and no row to sit under.
        static let unlistedTitle = "From conversations not listed"
        static let unlistedHelp = "Pages made or changed by conversations of this read that are not listed here"
        /// With one machine selected on a run the server listed in part: the numbers cover what is listed.
        static let countsPartial = "Counts cover only the conversations listed here."
        /// An older backend does not say which conversation or step changed a page: one group names them all. A current
        /// backend always says (owner 2026-11-24: no card of pages with no reason), so this is that fallback alone.
        static let pagesTitle = "Pages changed"
        static func conversationsIn(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String {
            noun(n, "conversation", "conversations", locale)
        }
        static func pagesIn(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { noun(n, "page", "pages", locale) }
        static func moreOnRow(_ n: Int, _ locale: Locale = .autoupdatingCurrent) -> String { "+\(count(n, locale)) more" }
        static func pageHelp(_ name: String, _ change: SleepConsolidated.Change, canShow: Bool) -> String {
            canShow ? "\(name) — \(changeWord(change).lowercased()). Click to see what changed." : "\(name) — \(changeWord(change).lowercased())"
        }
        static func pageLabel(_ name: String, _ change: SleepConsolidated.Change) -> String {
            "\(name), \(changeWord(change).lowercased())"
        }
        static let openPageAction = "Open page"
        static func nothingFrom(_ machine: String) -> String { "Nothing from \(machine) was read in these sleeps." }
        /// "3 questions raised · 2 settled" — the one quiet line for the questions; nothing when there are none.
        static func questionsLine(raised: Int, settled: Int, _ locale: Locale = .autoupdatingCurrent) -> String? {
            switch (raised > 0, settled > 0) {
            case (true, true): "\(noun(raised, "question raised", "questions raised", locale)) · \(count(settled, locale)) settled"
            case (true, false): noun(raised, "question raised", "questions raised", locale)
            case (false, true): noun(settled, "question settled", "questions settled", locale)
            case (false, false): nil
            }
        }
        static let questionRaisedWord = "Raised"
        static let questionSettledWord = "Settled"
        static let showQuestions = "Show"
        static let hideQuestions = "Hide"

        // Owner 2026-11-23 ("see what page or chunk of page/pages was modified"): a click on a page's chip shows what
        // changed on it.
        static let noChange = "Nothing changed on this page in the end."
        static func took(_ length: String) -> String { "Read for \(length)" }
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
        static let labels = [filterAll, filterCreated, filterUpdated, filterArchived, filterRemoved, filterFaded,
                             unlistedTitle, countsPartial, pagesTitle, openPageAction, startedByYou, startedBySchedule, finished, reading, pausedPlanLimit, pausedReserve, paused,
                             stopped, failed, detailsTitle]
    }
}
