import Foundation

/// ROR-114 (owner: "just saying these get read through your browser should be fine … if I'm logged out Cicada should
/// detect this") — the words of a source the person's own agent reads in their browser. One line each, no paragraph;
/// a service is named only as the source itself.
extension Copy {
    enum Browser {
        /// The healthy state, in its own colour next to a connection's green.
        static let through = "Through your browser"
        static let notReadYet = "Not read yet"
        static let signedOut = "Signed out"
        static let couldntRead = "Couldn't read"
        static func lastRead(_ ago: String) -> String { "last read \(ago)" }
        static let signedOutDetail = "sign in, then try again"
        static let couldntReadDetail = "try again"
        /// The attention line under a signed-out source's head, with its one action.
        static func signIn(_ site: String) -> String { "Sign in to \(site) in your browser, then try again." }
        static let tryAgain = "Try again"
        /// A link, in link ink with the chevron every link in the app wears (`SettingsInlineLink`).
        static let openProfile = "Open profile ›"
        static func profileHelp(_ site: String) -> String { "Open your \(site) profile in your browser" }
    }
}
