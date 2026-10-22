import Foundation

/// G205 / G61 — the Inbox's top cards: an agent asking, and the grouped Where-to-check review.
extension Copy {
    enum AgentRequests {
        static let signedIn = "I signed in"
        static let notNow = "Not now"
        static func title(site: String?) -> String { site.map { "Sign in to \($0)" } ?? "An agent needs you" }
        static func open(_ site: String) -> String { "Open \(site) in your browser" }
        static let askLine = "Get a notification when an agent asks?"
        static let notifyMe = "Notify me"
    }

    enum WhereToCheck {
        static let yes = "Yes"
        static let no = "No"
        static let fromYou = "You mentioned it in a conversation"
        static let fromAgent = "An agent found it in a conversation"
        static let fromPage = "Written on the page"
        static func rowHelp(yes: Bool, label: String) -> String {
            yes ? "Keep \(label) as a place to check" : "Not a place to check — never proposed again"
        }
        static let failed = "Couldn't save that answer"
    }
}
