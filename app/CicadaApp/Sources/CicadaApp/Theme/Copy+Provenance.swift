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
        /// G110 gate B2 — the line Cicada writes where a long conversation's middle was not kept: its own note,
        /// never anyone's words.
        static let notCaptured = "Not captured · Cicada's note"
        static let fromThePage = "From the page"
        /// A quote an agent reported from a page (G166): Cicada never had the page and cannot check it, so the label
        /// says whose reading it is.
        static func fromThePageAsRead(by agent: String?) -> String {
            "From the page, as \(agent ?? "an agent") read it"
        }
        /// The Reader's line over a file's text that Claude extracted from an upload (`attachment [<name>]:`).
        static func attached(_ fileName: String) -> String { "Attached · \(fileName)" }

        static func turn(_ n: Int) -> String { "turn \(n)" }
        static func turnCount(_ n: Int) -> String {
            n == 1 ? "1 turn" : "\(UsageFormat.count(n)) turns"
        }
        /// Ruling 39 — when Cicada received an item, said only when it is days after the item's own date
        /// ("3 May 2023 · added 24 Oct 2026").
        static func added(_ day: String) -> String { "added \(day)" }
        static let resume = "Resume"
        static let close = "Close the conversation"
        static let back = "Back to the previous conversation"
        static func citedPassage(_ text: String) -> String { "Cited passage: \(text)" }
        /// The quiet marker beside a chat message that holds a cited passage (2026-10-20): one word on screen, the
        /// whole thought for VoiceOver — the span landed on, or another this conversation's citations name.
        static let citedMarker = "Cited"
        static let citedHere = "Cited here"
        static let alsoCitedHere = "Also cited here"
        static let citedMarkerHelp = "Words from this message are cited by what Cicada noted"

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
        // MARK: The Reader as a chat (owner, 2026-10-19)

        static let today = "Today"
        static let yesterday = "Yesterday"
        /// Ruling 32 — a relayed person's turn: on their side, never "You"; `app` is the person's own app.
        static func relayedBy(_ app: String?) -> String { "Relayed by \(app ?? "an app")" }
        /// The capture line over a relayed conversation (the app is named once, on the person's first run).
        static let relayHonesty = "Relayed by the app's model as you talked, so your side may not be word for word."
        static let showMore = "Show more"
        static let showLess = "Show less"
        static let showMoreHelp = "Show the whole message"
        static let showLessHelp = "Fold this message back"
        /// A chat message's words for VoiceOver and the rotors: who, when, what — no turn number (the layout has none).
        static func chatRotorLabel(speaker: String, time: String?) -> String {
            [speaker, time].compactMap { $0 }.joined(separator: ", ")
        }
        static func chatLabel(speaker: String, time: String?, text: String) -> String {
            "\(chatRotorLabel(speaker: speaker, time: time)): \(text)"
        }

        // MARK: What made it a conversation (2026-10-20): reactions, replies, attachments, edits, unsends

        static let edited = "Edited"
        static let chatSomeone = "Someone"
        static let earlierMessage = "Replying to an earlier message"
        static func replyingTo(_ who: String, excerpt: String?) -> String {
            guard let excerpt, !excerpt.isEmpty else { return "Replying to \(who)" }
            return "Replying to \(who): \u{201C}\(excerpt)\u{201D}"
        }
        static let replyHelp = "Go to the message this replies to"
        static func unsent(_ who: String) -> String { who == Copy.you ? "You unsent a message" : "\(who) unsent a message" }
        static func forwardedFrom(_ who: String) -> String { "Forwarded from \(who)" }
        /// A reaction chip's hover: who reacted, and with what — "Sam reacted ❤️", "You and Sam reacted 👍".
        static func reacted(_ who: [String], emoji: String) -> String {
            let names = who.count <= 1 ? (who.first ?? Copy.you)
                : who.dropLast().joined(separator: ", ") + " and " + (who.last ?? "")
            return "\(names) reacted \(emoji)"
        }
        static func ranCode(_ n: Int) -> String { n == 1 ? "Ran code" : "Ran code \(n) times" }
        static func attachmentKind(_ kind: String, generated: Bool) -> String {
            if generated { return kind == "image" ? "Generated image" : "Generated file" }
            switch kind {
            case "image": return "Image"
            case "video": return "Video"
            case "audio": return "Audio"
            case "sticker": return "Sticker"
            default: return "File"
            }
        }
        /// An attachment chip's words: its kind, then its name and size when known — "Image · photo.jpg · 1 MB".
        static func attachment(kind: String, name: String, size: Int?, generated: Bool) -> String {
            var parts = [attachmentKind(kind, generated: generated)]
            if !name.isEmpty { parts.append(name) }
            if let size, size > 0 { parts.append(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file)) }
            return parts.joined(separator: " · ")
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
    /// DR-57 — a passage from a feed or a calendar: what arrived, never what the person said (⌘K, QA 2026-10-16).
    static let fromTheFeed = "From the feed"
    static let onYourCalendar = "On your calendar"
    static let theAgentReplied = "The agent replied"
    static func replied(_ agent: String) -> String { "\(agent) replied" }
    static let inTheVideo = "In the video"
    static let someoneElseSaid = "Someone else said"
    static func said(_ name: String) -> String { "\(name) said" }
    static let inferredLabel = "Inferred"
    static let mentionedHere = "Mentioned here"
    /// Round-4 D1 — an app with no capture hook (Claude desktop, ChatGPT,
    /// Cursor) never tells Cicada its model; said in the hover, never guessed.
    static let modelNotShared = "model not shared by this app"

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
