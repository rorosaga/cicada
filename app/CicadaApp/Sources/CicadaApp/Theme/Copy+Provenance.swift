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

        // MARK: The Reader as a column (DS-2 Task 4, R-DI6)

        static let closeHelp = "Close (Esc)"
        static func resumeHelp(_ agent: String?) -> String { "Resume this conversation in \(agent ?? "its app")" }
        /// "Noted from this conversation (3)" — the count through `UsageFormat` (R-DI23).
        static func noted(count: Int, isPage: Bool) -> String {
            "\(isPage ? notedFromThisPage : notedFromThisConversation) (\(UsageFormat.count(count)))"
        }
        /// A rotor entry's words, composed here so no `Text(` line interpolates a count (R-DI23).
        static func rotorLabel(speaker: String, turn n: Int) -> String { "\(speaker), \(turn(n))" }
        /// A turn's accessibility label: who spoke, which turn, the words.
        static func turnLabel(speaker: String, turn n: Int, text: String) -> String {
            "\(rotorLabel(speaker: speaker, turn: n)): \(text)"
        }
        /// "Noted" row's who-line when the belief was since replaced.
        static func notCurrent(_ label: String) -> String { "\(label) · \(noLongerCurrent)" }
        /// The header mark's hover — an id only ever in `.help` (DR-54).
        static func episodeHelp(_ id: String) -> String { "Episode \(id)" }
    }
}

// MARK: - The evidence chip (§4.2) — Task 3

extension Copy.Provenance {
    static let youSaid = "You said"
    static let theAgentReplied = "The agent replied"
    static func replied(_ agent: String) -> String { "\(agent) replied" }
    static let inTheVideo = "In the video"
    static let someoneElseSaid = "Someone else said"
    static func said(_ name: String) -> String { "\(name) said" }
    static let inferredLabel = "Inferred"
    static let mentionedHere = "Mentioned here"

    /// The two captions the brief asked for by name (2026-09-23): whether the
    /// words were QUOTED by whoever wrote the belief, or FOUND afterwards.
    static let quotedCaption = "Quoted by the contributor"
    static let derivedCaption = "Found by searching the conversation"

    static let openConversation = "Open conversation"
    static let opensTheConversation = "Opens the conversation."
    static let previewQuote = "Preview quote"
    static func moreEvidence(_ n: Int) -> String { "+\(UsageFormat.count(n)) more" }
    static let fewerEvidence = "Show fewer"
    static let previewNotFound = "Cicada couldn't find the name in this conversation."

    // MARK: Plain trust labels (§4.6) — what the `source_trust` axis MEANS,
    // not its enum name ("agent extracted" read as jargon to everyone but us).
    static let youToldCicada = "You told Cicada"
    static let cicadaNoticed = "Cicada noticed"
    static let cicadaConcluded = "Cicada concluded"
    static let fromASource = "From a source"
    static let notRecorded = "Not recorded"
}

// MARK: - "Where this came from" on the entity card (§4.5) — Task 4

extension Copy.Provenance {
    static let whereThisCameFrom = "Where this came from"
    /// G61's "Sources" section, renamed so "where to refresh this fact" can
    /// never be read as "where this belief came from" (§4.5, R6 §5.3.7).
    static let lookItUpAt = "Look it up at"

    static let noConversations = "Recorded before Cicada kept conversation links."
    static let noBeliefs = "No beliefs are recorded on this page yet."
    static let unavailable = "Couldn't load where this came from."
    static let notInBank = "No longer in this bank"
    static let staleCaption = "This conversation changed since, so the words may have moved"
    static let inferredByCicada = "Inferred by Cicada"
    static func showAllConversations(_ n: Int) -> String { "Show all \(UsageFormat.count(n))" }
    static let showFewerConversations = "Show fewer"
    /// A contributor chip's hover: what "N beliefs · N edits" counts.
    static func contributorHelp(_ name: String) -> String {
        "Beliefs on this page written by \(name), and edits \(name) made to it."
    }
    static let beforeProvenanceHelp = "Edits made before Cicada recorded who made them."

    static func beliefs(_ n: Int) -> String { n == 1 ? "1 belief" : "\(UsageFormat.count(n)) beliefs" }
    static func edits(_ n: Int) -> String { n == 1 ? "1 edit" : "\(UsageFormat.count(n)) edits" }
    static func conversations(_ n: Int) -> String {
        n == 1 ? "1 conversation" : "\(UsageFormat.count(n)) conversations"
    }
}

// MARK: - The Reader's reverse direction (§4.4, G106 (ii)) — Task 5

extension Copy.Provenance {
    static let notedFromThisConversation = "Noted from this conversation"
    static let notedFromThisPage = "Noted from this page"
    static let nothingNoted = "Nothing in memory cites this yet."
    /// R-PB10: `partial` means the server stopped at its page cap.
    static let notedPartial = "Some pages that name this conversation aren't listed here."
    static func alsoOn(_ names: [String]) -> String { "Also on: \(names.joined(separator: ", "))" }
    static let nextCited = "Next cited passage"
    static let previousCited = "Previous cited passage"
    static func showOnGraph(_ name: String) -> String { "Show \(name) on the graph" }
    static let noLongerCurrent = "No longer current"
}

// MARK: - Inbox and Ask (§4.7, P5) — Task 6

extension Copy.Provenance {
    static let showInConversation = "Show in conversation"
}
