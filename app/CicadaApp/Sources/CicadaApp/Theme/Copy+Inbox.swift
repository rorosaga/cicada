import Foundation

/// DS-2 — every sentence the Inbox's columns say, in one place (DR-59: sentence case, plain verbs,
/// no "!", no bare "%", no ids — DR-54). Its own file for the reason `Copy+Provenance.swift` gives:
/// parallel tracks edit `Copy.swift`.
extension Copy {
    enum Inbox {
        static let title = "Inbox"
        static func pending(_ n: Int) -> String { "\(UsageFormat.count(n)) pending" }
        static func position(_ i: Int, of n: Int) -> String { "\(UsageFormat.count(i)) of \(UsageFormat.count(n))" }
        static let all = "All"

        // The Undo row (R-DI5)
        static let answered = "Answered"
        static func answered(_ what: String) -> String { "Answered · \(what)" }
        static let notNow = "Not now"
        static let gotIt = "Got it"
        static let dismissed = "Dismissed"
        static let skipped = "Skipped"
        static let keptSeparate = "Kept separate"
        static let kept = "Kept"
        static let merged = "Merged"
        static let archived = "Archived"
        static let undo = "Undo"
        static let undoHelp = "Undo (⌘Z)"
        /// R-DI3 — another client moved the active bank inside the window.
        static let answerNotSaved = "Your last answer wasn't saved because the memory bank changed. It's still in the inbox."
    }
}
