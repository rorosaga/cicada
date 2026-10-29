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
        static let proposeSame = "Join them as one?"
        static func proposePairSame(_ a: String, _ b: String) -> String { "Join \(a) and \(b) as one?" }
        static func proposePairDifferent(_ a: String, _ b: String) -> String { "Keep \(a) and \(b) apart?" }
        static func proposeAlsoSame(_ a: String, _ b: String) -> String { "And \(a) and \(b), one too?" }
        static func proposeAlsoDifferent(_ a: String, _ b: String) -> String { "And \(a) and \(b), apart too?" }
        static let proposeDifferent = "Keep them apart?"
        static let proposeLater = "Ask again another day?"
        static let yes = "Yes"
        static let notQuite = "Not quite"
        static let notQuiteHelp = "Nothing is noted; say it again in your own words"
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
