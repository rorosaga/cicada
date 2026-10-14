import Foundation

/// "Where this comes from" (owner 2026-10-14, G61) — every sentence the section says.
extension Copy {
    enum PageSources {
        static let title = "Where this comes from"
        static let reading = "Reading where this comes from…"
        static let sitesAndLinks = "Sources and links"
        static let namedInConversations = "Named in conversations"
        static let conversationsLabel = "Conversations"
        static let nothingYetSummary = "· nothing recorded yet"
        static let nothingYet = "Nothing records where this came from yet."
        static func sources(_ n: Int) -> String { n == 1 ? "1 source" : "\(UsageFormat.count(n)) sources" }
        static func noFactCheckable(_ total: Int) -> String {
            total == 1 ? "The one belief here has no place to check it yet."
                       : "None of the \(UsageFormat.count(total)) beliefs here has a place to check it yet."
        }
        static func everyFactCheckable(_ total: Int) -> String {
            total == 1 ? "The one belief here has a place to check it."
                       : "Every one of the \(UsageFormat.count(total)) beliefs here has a place to check it."
        }
        static func someFactsCheckable(_ n: Int, of total: Int) -> String {
            "\(UsageFormat.count(n)) of \(UsageFormat.count(total)) beliefs here have a place to check them."
        }
        static func lastSaid(_ day: String) -> String { "Last said \(day)" }
        static func checkedFirst(_ day: String) -> String { "Sources last checked \(day)" }
        static func checked(_ day: String) -> String { "sources last checked \(day)" }
        static func backs(_ n: Int) -> String { n == 1 ? "backs 1 belief" : "backs \(UsageFormat.count(n)) beliefs" }
        static let backsNothingYet = "no current belief yet"
        static func andMore(_ n: Int) -> String { "and \(UsageFormat.count(n)) more" }
        static func aConversation(in place: String) -> String {
            let article = place.first.map { "aeiouAEIOU".contains($0) } == true ? "an" : "a"
            return "\(article) \(place) conversation"
        }
        static func passages(_ n: Int) -> String { n == 1 ? "1 passage" : "\(UsageFormat.count(n)) passages" }
        static func last(_ day: String) -> String { "last \(day)" }
        static func moreLinks(_ n: Int) -> String {
            n == 1 ? "1 more link on the page" : "\(UsageFormat.count(n)) more links on the page"
        }
        static func checkAt(_ site: String) -> String { "Check at \(site)" }
        static let chipFile = "Check a file"
        static let chipApp = "Check an app"
        static let chipNote = "Check a note"
        static func lookUpHelp(_ ref: String) -> String { "Where to check this: \(ref)" }
        static let openBelief = "Open this belief's timeline"
        static let openConversation = "Open the conversation that named this link"
        static let useAsSource = "Use as a source"
        static let useAsSourceHelp = "Keep this link as a place to look this page up"
        static func openLink(_ url: String) -> String { "Open \(url)" }
        static let linkMenu = "Manage this link"
    }
}
