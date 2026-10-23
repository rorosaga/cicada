import Foundation

/// Design taste (owner, 2026-10-14) — the looks' words, on the pages of the things they show since 2026-10-20 (DR-59: sentence case, plain verbs, no "!"). Provider-
/// neutral (owner 2026-09-30) and plain (Search & files, owner 2026-10-14): "understand images", the same words as
/// Settings → Privacy & data, never a model; a download says its size before the click.
extension Copy {
    enum Looks {
        static let page = "Looks"
        /// DR-27 — the board hid beside a look and the Reader: "‹ 12 looks" brings it back.
        static func looksBack(_ n: Int) -> String { n == 1 ? "‹ 1 look" : "‹ \(UsageFormat.count(n)) looks" }
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
        static let remove = "Remove this look"
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
        /// Looks polish — a colour's share of the picture shows only where area means something: the ground, a wash
        /// and an unnamed colour. Ink and accent are thin lines that cover almost nothing ("0 %" said nothing true),
        /// so they show none; a share that rounds to nothing reads "< 1 %", and no share at all (a colour the page
        /// declares that the picture barely shows) shows none.
        static func share(_ share: Double, role: String?) -> String? {
            if role == "ink" || role == "accent" || share <= 0 { return nil }
            return share < 0.005 ? "< 1 %" : Self.share(share)
        }

        // MARK: Understanding images (the in-context shortcut to Search & files' second click)
        static let pictureOff = "To find looks by what they show, Cicada needs to understand images."
        /// The Looks shortcut keeps its one click (coordinator's call, 2026-10-14): on a Mac without the meaning part
        /// it fetches both, so the combined size is stated before the click.
        static func pictureDownload(_ bytes: Int, includesMeaning: Bool = false) -> String {
            let mb = max(1, Int((Double(bytes) / 1_000_000).rounded()))
            return includesMeaning
                ? "A one-time download of about \(mb) MB, which also sets up the sharper search. It stays on this Mac; your screenshots never leave it."
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
        // MARK: Looks polish (2026-10-15) — type specimens and the enlarged screenshot
        /// "Body 19 px · Links 19 px · Drop cap 88 px" — where a family is used, and how big.
        static func specimenUses(_ roles: [DesignSpecimen.Role]) -> String {
            roles.map { r in
                guard let size = r.size else { return typeRole(r.role) }
                let px = size == size.rounded() ? "\(Int(size)) px" : String(format: "%.1f px", size)
                return "\(typeRole(r.role)) \(px)"
            }.joined(separator: " · ")
        }
        /// Said under a specimen the capture could not draw: the "Aa" is the generic kind, not the page's face.
        static func specimenGeneric(_ generic: String?) -> String {
            switch generic {
            case "serif", "ui-serif": "Shown in a generic serif; the page's own face wasn't drawn"
            case "monospace", "ui-monospace": "Shown in a generic monospace; the page's own face wasn't drawn"
            case "sans-serif", "ui-sans-serif", "system-ui": "Shown in a generic sans serif; the page's own face wasn't drawn"
            default: "Shown in the system face; the page's own face wasn't drawn"
            }
        }
        static func specimenLabel(_ family: String) -> String { "Aa, set in \(family)" }
        static let enlarge = "Enlarge the screenshot"
        static let enlargeHelp = "Enlarge the screenshot (⌘Y)"
        static let closeEnlarged = "Close (Esc)"

        static let saveLook = "Save its look"
        static let saveLookHelp = "Asks your agent to capture this page's look — a screenshot, its type and colours — "
            + "and keep it with the page"
        static let saveLookQueued = "Queued for your agent. The prompt to hand it is copied."
        static let saveLookFailed = "Couldn't queue that look."

        // MARK: Looks on pages (owner 2026-10-20) — a look lives on the page of the thing it shows
        /// The card's section, and Clusters' filter.
        static let section = "Looks"
        static let noneYet = "None yet"
        static func sectionCount(_ n: Int) -> String { n == 1 ? "1 look" : "\(n) looks" }
        static let linkPrompt = "Paste a website link"
        static let capture = "Capture its look"
        static let captureHelp = "Saves the link and asks your agent to capture the site's look for this page"
        static let dropHint = "Or drop a picture anywhere on this page."
        static let placeSaved = "Put a saved look here"
        static let placeSavedHelp = "Looks you saved that aren't on a page yet"
        static let dropped = "Added to this page's looks."
        static let placed = "Moved to this page."
        static let takeOff = "Take it off this page"
        static let takeOffHelp = "Keeps the look, on no page, until you put it on one"
        static let similar = "Similar looks"
        static let noSimilar = "Nothing else you saved looks like this yet."
        static func onPage(_ name: String) -> String { "On \(name)" }
        static let notOnAPage = "Not on a page"
        static let notALink = "That isn't a website link. Paste one that starts with http:// or https://."
        // MARK: Clusters' Looks tab (review of #384, owner intent 2026-10-20: "filter looks inside the entities page")
        static let tab = "Looks"
        static let galleryFind = "Search looks by words, or drop a picture"
        static let galleryEmpty = "No looks yet. Paste a website link on a page, or drop a picture on it, to keep one."
        static let galleryNoMatch = "None of your looks matches that."
        static func galleryCount(_ n: Int) -> String { n == 1 ? "1 look" : "\(n) looks" }
        static let yourWords = "Your words"
        static let saveWords = "Save"
        static let savedWords = "Saved."
        static let placeOn = "Put it on a page"
        static let moveTo = "Move it to another page"
        static let findPage = "Find a page"
        static let withLooks = "Only pages with looks"
        static let withLooksHelp = "Pages that show a look you saved"
    }
}
