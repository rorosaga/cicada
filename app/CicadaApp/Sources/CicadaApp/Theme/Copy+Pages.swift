import Foundation

/// Ruling 48 (3), (4), (7), (16), (17) — the entity page's words (DR-59: sentence case, plain verbs). Provider-neutral
/// (owner 2026-09-30): an app is named only as where the person said something, never as the one doing a job.
extension Copy {
    enum Pages {
        // In short (DR-78): Sleep's summary lands here in part B; today the why-it-matters line and its counts.
        static let inShort = "In short"

        // Where to check (DR-79)
        static let whereToCheck = "Where to check"
        static let addLink = "Add a link"
        static let addPrompt = "A link to check this page by"
        static func all(_ n: Int) -> String { "All \(UsageFormat.count(n))" }
        static func suggested(_ n: Int) -> String { n == 1 ? "1 suggested link" : "\(UsageFormat.count(n)) suggested links" }
        static let review = "Review"
        static let useThis = "Use this"
        static let notThis = "Not this"
        static let remove = "Remove"
        static func open(_ ref: String) -> String { "Open \(ref)" }
        static func checked(_ when: String) -> String { "checked \(when)" }
        static let notChecked = "not checked yet"
        static let stale = "looks stale"
        static func lastChecked(_ when: String) -> String { "last checked \(when)" }
        static let changed = "the page changed"
        static let dead = "not reachable"
        static let unconfirmed = "not confirmed yet"
        static let suggestedBy = "suggested"

        // Ongoing (ruling 48 (4))
        static let ongoing = "Ongoing"
        static func since(_ when: String) -> String { "Since \(when)" }
        static func planned(_ when: String) -> String { "planned for \(when)" }
        static let inYourWords = "in your words"

        // The article's citations (DR-80)
        static let references = "References"
        static let history = "History"
        static let historyHelp = "Who wrote each change to this page"
        static func citeHelp(_ n: Int) -> String { "Source \(n): who said it and when" }
        static func citeSpoken(_ n: Int) -> String { "Source \(n)" }
        static let readingSource = "Reading where this came from…"
        static let sourceUnavailable = "Couldn't read this source."
        static let sourceMoved = "This line changed since the page was drawn. Its sources are being read again."
        static let showInConversation = "Show in conversation"
        static let fromConversation = "From this conversation"
        static let lookedUp = "Looked up"
        static let fromPage = "From the page"
        static let inferred = "Inferred"
        static func noticed(_ agent: String) -> String { "\(agent) noticed" }
        static func you(in place: String) -> String { "You, in \(place)" }
        static func with(_ name: String) -> String { "with \(name)" }
        static func conversations(_ n: Int) -> String { n == 1 ? "1 conversation" : "\(UsageFormat.count(n)) conversations" }
        static func webPages(_ n: Int) -> String { n == 1 ? "1 web page" : "\(UsageFormat.count(n)) web pages" }
        static func otherPages(_ n: Int) -> String { n == 1 ? "1 page" : "\(UsageFormat.count(n)) pages" }
        static func inAll(_ parts: [String]) -> String {
            switch parts.count {
            case 0: ""
            case 1: "\(parts[0]) in all"
            default: "\(parts.dropLast().joined(separator: ", ")) and \(parts.last!) in all"
            }
        }
        static let whoWroteIt = "who wrote each change is in History"
        static func linesCite(_ n: Int) -> String { n == 1 ? "cited on 1 line" : "cited on \(UsageFormat.count(n)) lines" }
        static func until(_ when: String) -> String { "until \(when)" }
        static let itSeems = "It seems that"
        static let morePerspectives = "More in Perspectives"
        static func moreBeliefs(_ n: Int) -> String { n == 1 ? "1 more in Perspectives" : "\(UsageFormat.count(n)) more in Perspectives" }

        // The brand block (ruling 48 (7))
        static func brand(looks n: Int) -> String { n == 1 ? "Brand · from 1 look" : "Brand · from \(n) looks" }
        static let copyTokens = "Copy as tokens"
        static let tokensCopied = "Copied the palette and type as CSS variables"
        static let typeSample = "Aa"

        // The page's menu (DR-81: what used to sit in the Details fold)
        static let more = "More"
        static let fades = "How it fades"
        static let addLook = "Add a look…"
    }
}
