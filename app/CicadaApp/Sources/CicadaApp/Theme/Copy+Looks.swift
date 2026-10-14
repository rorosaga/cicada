import Foundation

/// Design taste (owner, 2026-10-14) — the Looks page's words (DR-59: sentence case, plain verbs, no "!"). Provider-
/// neutral (owner 2026-09-30): the image model is "the image model", never a name; a download says its size.
extension Copy {
    enum Looks {
        static let page = "Looks"
        static let untitled = "A look"
        static let find = "Search by words, or drop a picture"
        static let searchHelp = "Find looks by what they're like: \"dark dashboard\", \"serif headlines\"…"
        static let addHelp = "Add a screenshot (or drop or paste one anywhere on this page)"
        static let add = "Add a look"
        static let emptyTitle = "No looks yet"
        static let emptyMessage = "Drop or paste a screenshot of a site whose look you like. Cicada keeps the picture, "
            + "your note and its colours, so your agents can build in that style."
        static let loading = "Gathering your looks…"
        static let loadFailedTitle = "Couldn't load your looks"
        static let noMatch = "Nothing on your board matches that."
        static let closeHelp = "Close (Esc)"
        static let liked = "What you liked"
        static let noNote = "No note yet."
        static let palette = "Colours"
        static let type = "Type"
        static let snippets = "Snippets"
        static let savedFrom = "Saved"
        static let openPage = "Open the page"
        static let remove = "Remove from Looks"
        static let removeHelp = "Removes the screenshot and its note from this memory"
        static let findSimilar = "Find similar"
        static let save = "Save to Looks"
        static let cancel = "Cancel"
        static let composerTitle = "Save this look"
        static let linkField = "Link to the page (optional)"
        static let titleField = "A name for it (optional)"
        static let noteField = "What do you like about it?"
        static let saving = "Saving…"
        static let byYou = "you"

        static func eyebrowCount(_ n: Int) -> String { n == 1 ? "1 saved" : "\(n) saved" }
        static func matches(_ n: Int) -> String { n == 1 ? "1 match" : "\(n) matches" }
        static func savedLine(day: String, by: String, via: String) -> String {
            [day.isEmpty ? nil : day, "by \(by)", via.isEmpty ? nil : via].compactMap { $0 }.joined(separator: " · ")
        }
        static func via(_ raw: String) -> String {
            switch raw {
            case "app_capture": "captured in Cicada"
            case "paste": "pasted"
            case "drop": "dropped in"
            case "agent": "sent by an agent"
            case "demo": "example"
            default: ""
            }
        }
        static func share(_ share: Double) -> String { "\(Int((share * 100).rounded())) %" }

        // MARK: Searching by picture (the image model's own click)
        static let pictureOff = "Searching by picture needs the image model on this Mac."
        static func pictureDownload(_ bytes: Int) -> String {
            let mb = max(1, Int((Double(bytes) / 1_000_000).rounded()))
            return "A one-time download of about \(mb) MB. It stays on this Mac; your screenshots never leave it."
        }
        static let turnOn = "Turn on"
        static let pictureUnsupported = "Searching by picture needs macOS 15 or later on Apple silicon. Words still work."
        static let pictureMissing = "Searching by picture isn't on, so this compared words."
    }
}
