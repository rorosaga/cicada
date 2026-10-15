import Foundation

/// Design taste (owner, 2026-10-14) — the Looks page's words (DR-59: sentence case, plain verbs, no "!"). Provider-
/// neutral (owner 2026-09-30) and plain (Search & files, owner 2026-10-14): "understand images", the same words as
/// Settings → Search & files, never a model; a download says its size before the click.
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
            case "explore": "kept while exploring"
            case "demo": "example"
            default: ""
            }
        }
        static func share(_ share: Double) -> String { "\(Int((share * 100).rounded())) %" }

        // MARK: Understanding images (the in-context shortcut to Search & files' second click)
        static let pictureOff = "To find looks by what they show, Cicada needs to understand images."
        /// The Looks shortcut keeps its one click (coordinator's call, 2026-10-14): on a Mac without the meaning part
        /// it fetches both, so the combined size is stated before the click.
        static func pictureDownload(_ bytes: Int, includesMeaning: Bool = false) -> String {
            let mb = max(1, Int((Double(bytes) / 1_000_000).rounded()))
            return includesMeaning
                ? "A one-time download of about \(mb) MB, which also sets up Understand what you mean. It stays on this Mac; your screenshots never leave it."
                : "A one-time download of about \(mb) MB. It stays on this Mac; your screenshots never leave it."
        }
        static let turnOn = "Turn on"
        static let pictureUnsupported = "Understanding images needs macOS 15 or later on a Mac with Apple silicon. Words still work."
        static let pictureMissing = "Cicada doesn't understand images yet, so this compared words."

        // MARK: Looks v2 (2026-10-15) — whose words, the page's type and colour roles, and "Save its look"
        /// An agent's note, under its own name — never "What you liked", which is only ever the person's words.
        static func notedBy(_ agent: String) -> String { "Noted by \(agent)" }
        static let anAgent = "an agent"
        static let colourRoles = "Colour roles"
        static func typeRole(_ role: String) -> String {
            switch role {
            case "body": "Body"
            case "heading": "Headings"
            case "subheading": "Subheadings"
            case "caption": "Captions"
            case "link": "Links"
            case "drop_cap": "Drop cap"
            default: role.capitalized
            }
        }
        static func colourRole(_ role: String) -> String {
            switch role {
            case "ground": "Ground"
            case "ink": "Ink"
            case "accent": "Accent"
            case "wash": "Wash"
            default: role.capitalized
            }
        }
        static func colourSource(_ source: String) -> String { source == "page" ? "from the page" : "from the picture" }
        /// "19 px · 400 · 30.4 px leading" — the size, the weight and the line height when the page set them.
        static func typeDetail(size: Double?, weight: Int?, lineHeight: Double?) -> String {
            func px(_ v: Double) -> String { v == v.rounded() ? "\(Int(v)) px" : String(format: "%.1f px", v) }
            return [size.map(px), weight.map { "\($0)" }, lineHeight.map { "\(px($0)) leading" }]
                .compactMap { $0 }.joined(separator: " · ")
        }
        static let saveLook = "Save its look"
        static let saveLookHelp = "Asks your agent to capture this page's look — a screenshot, its type and colours — "
            + "and keep it in Looks"
        static let saveLookQueued = "Queued for your agent. The prompt to hand it is copied."
        static let saveLookFailed = "Couldn't queue that look."
    }
}
