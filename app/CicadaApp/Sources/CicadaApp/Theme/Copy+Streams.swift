import Foundation

/// G245 (ruling 78) — the words of a source's streams: the definite word a check ends in (plan 3.3), the root card's
/// second line, and the one line a stream says when this Mac cannot read it yet. Few words, no provider named: the AI
/// the person uses is "your AI app" (provider-neutral copy, owner 2026-09-30).
extension Copy {
    enum Streams {
        /// The root's first tab: every source.
        static let all = "All"

        // The six words a check ends in, then the ones a stream rests in.
        static let read = "Read"
        static let signedOut = "Signed out"
        static let couldntRead = "Couldn't read"
        static let needsAccess = "Needs access"
        static let yourAIAppReadsNext = "Your AI app reads it next"
        static let notInstalled = "Not installed"
        static let notReadYet = "Not read yet"
        static let paused = "Paused"
        static let off = "Off"
        static let unavailable = "Unavailable"

        /// The root card's second line, after the streams: "3 folders".
        static func folders(_ n: Int) -> String {
            n == 1 ? "1 folder" : "\(UsageFormat.count(n)) folders"
        }

        /// The "Saves you make" row, when macOS has not been given Accessibility (ruling 77: never prompted for).
        static let accessibilityWhy = "Seeing a save needs Accessibility, which Cicada never asks for on its own."
        static let openAccessibility = "Open Accessibility settings"
        /// A reader that needs a permission the person can give from Settings.
        static let permissionWhy = "macOS has not given Cicada access to read it."
        static let openSetting = "Open the setting"

        /// A check in progress, and a check the backend could not be asked.
        static let checking = "Checking"
        static let checkFailed = "Couldn't ask Cicada's memory to check. Try again in a moment."
        /// The last result beside "Your AI app reads it next".
        static func lastResult(_ word: String) -> String { "last: \(word.lowercased())" }
    }
}
