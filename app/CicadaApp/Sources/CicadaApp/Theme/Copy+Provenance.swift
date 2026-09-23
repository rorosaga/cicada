import Foundation

/// G118 slice 2 — every sentence the provenance viewer says, in one place,
/// written for someone who has never heard the words "span", "episode" or
/// "hash" (the brief: plain and friendly, no jargon). Its own file rather than
/// more lines in `Copy.swift` because four round-3 tracks edit that file in
/// parallel; an `extension` here merges with none of them.
///
/// The honesty rules of design §4.9 live in these strings as much as in the
/// code: a derived match is never "You said", a stale quote never claims to
/// be where it was, and a hook-captured conversation never pretends to be the
/// whole session.
extension Copy {
    enum Provenance {
        // MARK: The Reader (§4.4)

        static let untitled = "Untitled conversation"
        /// G105 — the Stop hook keeps the person's turns and each final reply,
        /// never tool calls or code (`transcript_extract.py`). Said once, in
        /// the header, so the Reader never implies it shows the whole session.
        static let captureHonesty = "Your words and each final reply. Tool calls and code aren't kept."
        static func importedFrom(_ vendor: String) -> String { "Imported from a \(vendor) export" }

        static let stale = "This conversation changed after this was noted. The words may have moved."
        static let grown = "The conversation continued after this was noted."
        static let inferred = "Cicada inferred this. No sentence says it in so many words."
        /// The owner's wording (2026-09-23 brief): a derived match is labelled
        /// for what it is — found by searching, not quoted by a contributor.
        static let derived = "Found by searching the conversation. This was noted before Cicada kept exact quotes."
        static let notFound = "Cicada couldn't find the name in this conversation, so it opens at the top."
        static let truncated = "This conversation is very long, so only the first part is shown."
        static let gone = "This conversation isn't in this bank any more."
        static let failed = "Couldn't open this conversation."
        static let empty = "Nothing was captured in this conversation."
        static let retry = "Try again"

        static let theAgent = "The agent"
        static let setupMessage = "Setup message"
        static let unlabelledMessage = "Unlabelled message"
        static let someoneElse = "Someone else"
        static let fromThePage = "From the page"

        static func turn(_ n: Int) -> String { "turn \(n)" }
        static func turnCount(_ n: Int) -> String {
            n == 1 ? "1 turn" : "\(UsageFormat.count(n)) turns"
        }
        static let resume = "Resume"
        static let close = "Close the conversation"
        static let back = "Back to the previous conversation"
        static func citedPassage(_ text: String) -> String { "Cited passage: \(text)" }
    }
}
