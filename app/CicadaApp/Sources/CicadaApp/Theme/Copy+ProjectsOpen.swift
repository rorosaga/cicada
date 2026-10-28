import Foundation

/// Projects v3 (decisions 9, 10 and 17, owner 2026-10-28) — the page with no folds: the pulse, the open capped
/// sections and their "All N", Pages in this project, Suggested as one line. DR-59: sentence case, plain verbs, no "!";
/// provider-neutral (an agent is named only as the one that did the tie).
extension Copy {
    enum ProjectsOpen {
        // MARK: Sections (open, capped; empty ones are never drawn)
        static let inMotion = "In motion"
        static let comingUp = "Coming up"
        static let timeline = "Timeline"
        static let backlog = "Backlog"
        static let backlogTag = "backlog"
        static let milestoneDone = "Milestone done"
        static func all(_ n: Int) -> String { "All \(UsageFormat.count(n))" }
        static func allHelp(_ title: String) -> String { "See all of \(title.lowercased()) (Esc comes back)" }
        static func titled(_ title: String, _ n: Int) -> String { "\(title) · \(UsageFormat.count(n))" }
        static let back = "Back"
        static let backHelp = "Back to the project (Esc)"
        static let addToBacklog = "Add to the backlog"
        static let pagesTitle = "Pages in this project"
        static let conversationsTitle = "Conversations"
        static let influencesTitle = "Sources & influences"

        // MARK: The header's one line
        static func nextInline(_ text: String) -> String { "Next: \(text)" }
        static func headerHelp(_ started: String, _ edited: String?) -> String {
            [started, edited].compactMap { $0 }.joined(separator: "\n")
        }

        // MARK: Pulse
        static let pulse = "Pulse"
        static let lastFourWeeks = "Last 4 weeks"
        static let waitingOn = "Waiting on"
        static let goneQuiet = "Gone quiet"
        static func pulseCounts(conversations: Int, done: Int) -> String {
            let talk = "\(UsageFormat.count(conversations)) conversation\(conversations == 1 ? "" : "s")"
            return done > 0 ? "\(talk) · \(UsageFormat.count(done)) done" : talk
        }
        static func weeksHelp(_ weeks: [Int]) -> String {
            "Conversations each week, oldest first: " + weeks.map { UsageFormat.count($0) }.joined(separator: ", ")
        }
        static func waitingLine(_ who: String, _ what: String) -> String { "\(who) · \(what)" }
        static func since(_ day: String) -> String { "Since \(day)" }
        static func quietLine(_ what: String, weeks: Int, days: Int) -> String {
            weeks >= 2 ? "\(what) · \(UsageFormat.count(weeks)) weeks" : "\(what) · \(UsageFormat.count(days)) days"
        }
        static func startedNothingSince(_ day: String) -> String { "Started \(day), nothing since" }
        static func moreWaiting(_ n: Int) -> String { "and \(UsageFormat.count(n)) more" }
        static let pulseHelp = "Counted from your conversations and what's been marked done. No model reads it."

        // MARK: Pages in this project
        static func pages(_ n: Int) -> String { "Pages in this project · \(UsageFormat.count(n))" }
        static let add = "Add"
        static let addPageHelp = "Add a page from your memory to this project"
        static let notPartOfIt = "Not part of it"
        static let notPartOfItHelp = "Leave this page out of the project. Nothing about it is deleted, and Cicada won't add it back."
        static let youTiedIt = "You tied it"
        static func agentTiedIt(_ by: String) -> String { "\(OriginIconography.label(for: by)) tied it" }
        static func suggestedBy(_ by: String) -> String { "Suggested by \(OriginIconography.label(for: by))" }
        static let takeIt = "Add"
        static let takeItHelp = "Make it part of this project"
        static func pagesLine(_ counts: [String: Int]) -> String {
            let order: [(String, String)] = [("said", "you said"), ("user", "you tied"), ("agent", "an agent tied"),
                                             ("proposed", "suggested")]
            return order.compactMap { key, words in
                guard let n = counts[key], n > 0 else { return nil }
                return "\(UsageFormat.count(n)) \(words)"
            }.joined(separator: " · ")
        }
        static let pagesHelp = "A page is part of a project when something you said ties them, or when you add it here — never because a name happens to come up."
        static let addPageTitle = "Add a page to this project"
        static let addPagePlaceholder = "Name a person, a tool, a place…"
        static let noPageMatches = "No page in your memory has that name."

        // MARK: Suggested, as one line
        static func suggestedLine(_ n: Int) -> String { "\(UsageFormat.count(n)) suggested by Cicada" }
        static let review = "Review"
        static let reviewHelp = "See the projects Cicada noticed, and add the ones that are yours"
        static let suggestedTitle = "Suggested by Cicada"
        static let suggestedBlurb = "Cicada noticed these. Add the ones that are yours; nothing here is deleted."
        static let suggestedTab = "Suggested"
        static let dismissedTab = "Not mine"
        static let closeSuggested = "Close the suggestions"
        static let noneSuggested = "Nothing waiting. Cicada suggests a project when a repository, your own words or an agent names one."
    }
}
