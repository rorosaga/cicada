import Foundation

/// G245 (ruling 79 (b), owner 2026-11-24, "Should the accounts you follow be read?" "2. yes") — the words of X's Following
/// stream and its list. Few words, no provider named but the site itself (the site's own name is the page's), the AI the
/// person uses is "your AI app" (provider-neutral copy, owner 2026-09-30).
extension Copy.Streams {
    /// A following stream's purpose, when its name does not say.
    static let followingFor = "Kept outside memory; only added to pages you already have"
    static let followingLabel = "Following"
    static func followingSearch(_ total: Int?) -> String {
        total.map { "Search \(UsageFormat.count($0)) account\($0 == 1 ? "" : "s")" } ?? "Search accounts"
    }
    static let followingOff = "Following is off. Turn it on above and your AI app reads who you follow."
    static let followingWaiting = "Nothing read yet. Your AI app reads it on its next visit."
    static let followingFailed = "Couldn't read the kept accounts. Try again in a moment."
    static let followingLoading = "Reading the accounts you follow"
    static let followingPageChip = "Their page"
    static let followingMaybePageChip = "Maybe their page"
    static let followingMatchHelp = "Open this page in your memory"
    static let followingMaybeHelp = "Matched by name alone; it is only a suggestion until you take its link"
    static func followingSince(_ when: String) -> String { "since \(when)" }
    static func followingSinceHelp(_ day: String) -> String { "First seen in your following list on \(day)." }
    static func followingOpenProfile(_ name: String) -> String { "Open \(name) on X" }
    static let followingForget = "Forget kept accounts"
    static func followingForgotten(_ n: Int) -> String {
        n == 0 ? "No accounts were kept for this memory."
            : "Forgot \(n) kept account\(n == 1 ? "" : "s"). Pages that already gained a link keep it."
    }
    static let followingForgetHelp = "Pages that already gained a link keep it."
}
