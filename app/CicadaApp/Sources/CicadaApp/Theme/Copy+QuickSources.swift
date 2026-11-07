import Foundation

/// G61 (owner 2026-10-26) — the "Reading in your browser" area's quick add and its list of where to check. Plain words;
/// an agent is named only by the harness that wrote the entry (its own name, never a model).
extension Copy {
    enum QuickSources {
        static let title = "Where to check"
        static let intro = "Links Cicada and your agents keep pages up to date from. Add one here, or tell your agent "
            + "\"add this source\" — what they add shows below, with who added it."
        static let linkPrompt = "Paste a link"
        static let pagePrompt = "For a page (optional)"
        static let clearPage = "Choose another page"
        static let noPage = "No page with that name. A link with no page is saved for Sleep to read."
        static let add = "Add"
        static let addHelp = "Add this link as where to check this page, as yours."
        static let addHelpNoPage = "Save this link for Sleep to read. Choose a page to keep checking it."
        static func added(_ page: String) -> String { "Added as where to check \(page)." }
        static let savedAsLink = "Saved as a link for Sleep to read. Choose a page to keep checking it."
        static let notALink = "That isn't a web link. Paste one that starts with https://."
        static let couldNotRead = "Couldn't read the list right now."
        static let failed = "Couldn't save that. Try again in a moment."
        static let empty = "Nothing yet. A link you add for a page, or one your agent adds, shows here."
        static func more(_ n: Int) -> String { n == 1 ? "1 more on its page." : "\(n) more on their pages." }
        static let you = "You"
        static let anAgent = "An agent"
        static let waiting = "waiting for your yes"
        static let remove = "Remove"
        static func removeHelp(_ page: String) -> String {
            "Remove this source from \(page). Cicada remembers, so it isn't added back."
        }
        static let removed = "Removed. Cicada won't add it back."
    }
}
