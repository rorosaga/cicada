import Foundation

extension Copy {
    /// G246 (ruling 81) — "Keep as a page" on a saved post drawn as a row, and the dated line on Home that says the
    /// posts moved under their lists. Plain words; no internal term, no provider named.
    enum Keep {
        static let keep = "Keep as a page"
        static let keepHelp = "Give this post a page of its own. It keeps it, and it shows in your graph."
        static let back = "Back to a row"
        static let backHelp = "Show it under its list again, without a page of its own."
        static let kept = "Kept as a page"
        static let backed = "Back under its list"
        static let busy = "Cicada is busy updating your memory. Try again in a moment."
        static let failed = "Couldn't change that. Try again in a moment."
        /// A server sentence is shown as it is; these are only for a refusal that arrives with no sentence.
        static let gotIt = "Got it"

        /// Home's one line after the posts moved (`GraphResponse.hiddenPosts`), dated by the first day this Mac saw them.
        static func moved(_ n: Int, since day: String, locale: Locale = .autoupdatingCurrent) -> String {
            let count = UsageFormat.count(n, locale: locale)
            return n == 1
                ? "1 saved post now shows under its list (since \(day)). Open it to keep it as a page."
                : "\(count) saved posts now show under their lists (since \(day)). Open one to keep it as a page."
        }
    }
}
