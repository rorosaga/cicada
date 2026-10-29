import Foundation

/// source-page-v3 (owner 2026-10-29: "Better generalizable components for each sources page like searching and what
/// comes from the sources … a better status for when it's connected and not so much text") — the words of the one
/// source page every source shares. Provider-neutral: a service is named only as the source itself.
extension Copy {
    enum SourcePage {
        static let connected = "Connected"
        static let syncing = "Syncing"
        static let needsYou = "Needs you"
        static let off = "Off"
        /// "last item today" — the day the newest item came in, after the status word.
        static func lastItem(_ day: String) -> String { "last item \(day)" }
        static let nothingYet = "nothing in yet"
        static let signInAgain = "sign in again"
        static let connectAnAgent = "connect an agent on this Mac"
        static let allowAccess = "allow Full Disk Access"
        /// The quiet link to the source's full words (the connect sheets' words, DESIGN_RULES 2026-10-29).
        static let whatItReads = Copy.Connect.whatItReads
        static let factsTitle = "What Cicada reads"
        static let close = "Close"
        /// The one search, its prompt naming what the list holds ("Search 6 chats").
        static func searchPrompt(total: Int?, noun: (one: String, many: String)) -> String {
            guard let total, total > 0 else { return "Search" }
            return "Search \(UsageFormat.count(total)) \(total == 1 ? noun.one : noun.many)"
        }
        static func noMatch(_ query: String) -> String {
            "Nothing here matches “\(query.trimmingCharacters(in: .whitespacesAndNewlines))”."
        }
        /// DR-81's plain "All N" under a capped list.
        static func all(_ total: Int) -> String { "All \(UsageFormat.count(total))" }
        static let allHelp = "Show the whole list here (Esc returns)"
        static func back(_ source: String) -> String { source }
        static let backHelp = "Back to the source (Esc)"
        static let settings = "Settings"
        /// A group's second words: how many it holds and its newest day ("12 messages · Today").
        static func conversations(_ n: Int) -> String { n == 1 ? "1 conversation" : "\(UsageFormat.count(n)) conversations" }
        static func messages(_ n: Int) -> String { n == 1 ? "1 message" : "\(UsageFormat.count(n)) messages" }
        static let groupOpenHelp = "Open what came in here"
    }
}
