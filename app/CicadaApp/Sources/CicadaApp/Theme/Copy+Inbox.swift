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

        // The focus card (Task 3 — DR-41, DR-42, DR-43, DR-54, R-DI12, R-DI15)
        static func aConversation(_ app: String) -> String { "a \(app) conversation" }
        static let aConversationPlain = "a conversation"
        static let noSourceAge = "No source recorded, so no date to measure from"
        static let recommended = "Recommended"
        static let other = "Other…"
        static let otherPrompt = "What's actually true?"
        static let answerPrompt = "Type your answer…"
        static let submit = "Submit"
        /// DR-41 — a disabled control says why in `.help`.
        static let submitNeedsText = "Type what's actually true first"
        static let answerNeedsText = "Type an answer first"
        static let mergeNeedsTarget = "Name the existing entity first"
        static func pressKey(_ n: Int) -> String { "Press \(n)" }
        static let notNowSevenDays = "Not now — ask again in 7 days"
        static let notNowHelp = "Ask again in 7 days (L)"
        static let close = "Close (Esc)"
        static let showConversationHelp = "Open the conversation beside this question"
        static let hideConversation = "Hide conversation"
        static let hideConversationHelp = "Close the conversation (Esc)"
        static let openSource = "Open source"
        static func openSourceHelp(_ where: String) -> String { "Open \(`where`)" }
        static func informational(_ predicate: String?) -> String {
            "These can all be true — \(predicate ?? "this") holds several values. Nothing to pick."
        }
        static let describeEntity = "Describe this entity"
        static let describePrompt = "Describe this entity…"
        static let existingEntity = "Existing entity"
        static let existingPrompt = "Existing entity…"
        static let keepAsCanonical = "Keep as canonical"
        static let newFromExtraction = "New from extraction"
        static let existingPage = "Existing page"
        static let answer = "Answer"
        static let merge = "Merge"
        static let keepSeparate = "Keep separate"
        static let skip = "Skip"
        static let dismiss = "Dismiss"
        static let keepActive = "Keep active"
        static let archive = "Archive"
        static func questions(_ n: Int) -> String { n == 1 ? "‹ 1 question" : "‹ \(UsageFormat.count(n)) questions" }
        static let showQuestions = "Show the questions"
        static let showFewer = "Show fewer"
        static func showAll(_ n: Int) -> String { "Show all \(UsageFormat.count(n))" }
        static let openQuestion = "Open this question"
    }
}
