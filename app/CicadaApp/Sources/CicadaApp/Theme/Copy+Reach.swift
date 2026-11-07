import Foundation

/// Production blocker (2026-11-06) — what the app says when it cannot reach, or cannot read, its own memory. One line
/// each, plain verbs (DR-59), provider-neutral (owner 2026-09-30): no backend, port-as-jargon or domain name where a
/// person reads it. The port is the one number, because it is the thing the person can go and look for.
extension Copy {
    enum Reach {
        // The shell's one line (`BackendBanner`)
        static let stopped = "Cicada's memory stopped answering."
        static let restarting = "Starting Cicada's memory again…"
        static let keyRefused = "Cicada's memory refused this app's key."
        static let serverSilent = "Your Cicada server isn't answering."
        static let serverKeyRefused = "Your Cicada server refused this device's key."
        static func portHeld(_ port: Int) -> String {
            "Another program is using port \(port)."
        }
        static let restart = "Restart"
        static let tryAgain = "Try again"

        // A page that could not read, said instead of "empty"
        static let unreadTitle = "Couldn't read your memory"
        static let beliefsUnread = "Couldn't read this page's beliefs."
        static let searchFailed = "Conversations and beliefs couldn't be read."

        /// A Store domain's failure in the person's words — never the domain's name.
        static func readFailed(_ domain: SyncDomain) -> String { "Couldn't read \(what(domain))" }

        private static func what(_ domain: SyncDomain) -> String {
            switch domain {
            case .graph: "your memory"
            case .inbox: "your questions"
            case .banks: "your memories"
            case .sources, .sourcesOverview: "your sources"
            case .channels, .connections: "your connections"
            case .feeds: "your feeds"
            case .calendars: "your calendars"
            case .contributors: "your contributors"
            case .origins: "where things came from"
            case .status: "Sleep's status"
            case .consumption: "your usage"
            case .askHistory, .quickRecents: "your history"
            }
        }
    }
}
