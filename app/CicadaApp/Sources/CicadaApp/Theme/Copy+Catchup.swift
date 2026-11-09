import Foundation

/// Ruling 48 (1), (8) — Home's questions and the catch-up chat, in one place (DR-59: sentence case, plain verbs, no "!",
/// no ids — DR-54). Provider-neutral (owner 2026-09-30): the chat never names the engine that answers.
extension Copy {
    enum Catchup {
        // Home's catch-up block (`07-home-b`: its own block, above the questions).
        static let title = "Catch me up"
        static func summary(questions: Int, pages: Int) -> String {
            let q = questions == 1 ? "1 question" : "\(UsageFormat.count(questions)) questions"
            let p = pages == 1 ? "1 page" : "\(UsageFormat.count(pages)) pages"
            return "\(q) about \(p), the ones you use most first"
        }
        static let start = "Start"
        static let startHelp = "Catch Cicada up in a short chat, one question at a time"
        static let anyAgent = "or say “catch me up” to your agent"
        static func blockLine(questions: Int, pages: Int) -> String {
            "\(summary(questions: questions, pages: pages)) · \(anyAgent)"
        }

        // Home's questions block.
        static let pagesWithAQuestion = "Pages with a question"
        static func allQuestions(_ n: Int) -> String { "All \(UsageFormat.count(n)) questions" }
        static let allHelp = "Every open question, grouped by kind"
        static func moreOnPage(_ n: Int) -> String { n == 1 ? "1 question" : "\(UsageFormat.count(n)) questions" }
        static func openPage(_ name: String) -> String { "Open \(name)" }
        static let answerHelp = "Answer this question"
        /// Round 4 — the lead question's one next act on Home.
        static let answer = "Answer"

        // The chat (`08-catchup`).
        static let eyebrow = "Home · Catching up"
        static func position(_ i: Int, of n: Int) -> String { "\(UsageFormat.count(i)) of \(UsageFormat.count(n))" }
        static let speaker = "Cicada"
        static let you = "You"
        static let stop = "Stop for now"
        static let closeHelp = "Close the chat"
        static let composer = "Or answer in your own words…"
        static let send = "Send"
        static let thinking = "Thinking…"
        static let notNow = "Not now"
        static let skip = "Skip"
        static let same = "Yes, the same"
        static let different = "No, different"
        /// A same-person chain's pair, one tap each (ruling 41: one pair at a time, never the whole chain at once).
        static func pairSame(_ a: String, _ b: String) -> String { "\(a) is \(b)" }
        static func pairDifferent(_ a: String, _ b: String) -> String { "\(a) isn't \(b)" }
        static let undo = "Undo"
        static func noted(_ what: String) -> String { what.isEmpty ? "Noted" : "Noted: \(what)" }
        static let notedSame = "Noted: one and the same"
        static let notedDifferent = "Noted: kept apart"
        static let notedLater = "I'll ask another day"
        static func propose(_ what: String) -> String { "Note it as “\(what)”?" }
        static let yes = "Yes"
        static let notQuite = "Not quite"
        static let notQuiteHelp = "Nothing is noted; say it again in your own words"
        /// Two names the person joined with no question to carry it: said, never dropped in silence.
        static func cannotJoin(_ a: String, _ b: String) -> String { "I couldn't join \(a) and \(b) from here." }
        /// What each page of a possible duplicate says, side by side (`CatchupContext`).
        static func contextBoth(_ a: String, _ aSays: String, _ b: String, _ bSays: String) -> String {
            "\(a): \(aSays)\n\(b): \(bSays)"
        }
        static func contextOne(_ name: String, _ says: String) -> String { "\(name): \(says)" }
        static let opening = "A few quick ones, the things you use most first."
        static let skipped = "Let's leave that one."
        static let done = "That's everything for now. Thanks for catching me up."
        static let stopped = "Okay — we can pick this up any time."
        static let didNotCatch = "I didn't quite catch that. Tap an answer, or say it another way."
        static func tapsOnly(_ why: String?) -> String {
            let reason = (why ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return reason.isEmpty ? "I can only take taps right now." : "I can only take taps right now — \(reason)"
        }
        static let notOpen = "That one was already answered."
        static let openFull = "Open the full question"
        static let demoNotKept = "This is the demo memory, so this chat isn't kept."

        // A page's own questions strip.
        static func stripTitle(_ i: Int, of n: Int) -> String {
            n > 1 ? "A question · \(UsageFormat.count(i)) of \(UsageFormat.count(n))" : "A question"
        }
        static let previous = "Previous question"
        static let next = "Next question"
    }
}
