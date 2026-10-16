import Foundation

/// G198 (owner ruling 2026-10-14) — agents editing a page's words: who wrote each part of a page ("Who wrote it",
/// inside "Where this comes from") and the Settings switch for the agents that may edit directly. Provider-neutral:
/// an agent is named only by the app it is, the person's own choice.
extension Copy {
    enum PageEdits {
        // "Who wrote it"
        static let sectionLabel = "Who wrote it"
        static let lead = "Opening"
        static let notSavedYet = "Not saved to history yet"
        static func lines(_ n: Int) -> String { n == 1 ? "1 line" : "\(UsageFormat.count(n)) lines" }
        static func reason(_ text: String) -> String { "“\(text)”" }
        static func reasonAccepted(_ text: String) -> String { "“\(text)” · accepted by you" }
        static func moreWriters(_ n: Int) -> String { n == 1 ? "and 1 more" : "and \(UsageFormat.count(n)) more" }
        static let help = "Read from the page's history: who last changed each line of this part, and when."

        // Settings → Agents
        static let groupHeader = "Editing pages"
        static let rowTitle = "Agents that can edit pages directly"
        static let rowDetail = "An agent on this list fixes a page's words or aliases right away, with its reason in "
            + "the page's history. Any other agent asks in your inbox first."
        static let loading = "Reading the list…"
        static let unavailable = "This list couldn't be read. It loads again when the backend answers."
        static let noAgents = "No agent on this Mac can edit pages yet."
        static func switchLabel(_ agent: String) -> String { "Let \(agent) edit pages directly" }
        static func allowedSince(_ day: String) -> String { "Allowed since \(day)" }
        static let asksFirst = "Asks in your inbox first"
        static let allowed = "Edits pages directly"
        static let onByDefault = "On by default"
        /// The note under the list while the person never changed it, naming their own agents the backend trusts by
        /// default: "Claude Code and Codex edit pages directly unless you turn them off."
        static func defaultsNote(_ agents: [String]) -> String? {
            guard let last = agents.last else { return nil }
            let names = agents.count == 1 ? last : agents.dropLast().joined(separator: ", ") + " and " + last
            let verb = agents.count == 1 ? "edits" : "edit"
            return "\(names) \(verb) pages directly unless you turn \(agents.count == 1 ? "it" : "them") off."
        }
        static let saveFailed = "That change wasn't saved. Try again in a moment."
    }
}
