import Foundation

/// G191 — the "What made you save this?" panel and its Settings switch. The reason labels themselves come from the
/// backend (`GET /sources/saved-why/options`), so the words the panel shows are the words the record keeps.
extension Copy {
    enum SaveWhy {
        static let question = "What made you save this?"
        static let somethingElse = "Something else…"
        static let placeholder = "In a few words — Return to save"
        /// Esc reaches the panel only once it has been clicked (it never takes the keyboard from the browser), so
        /// the hint names the way that always works.
        static let hint = "Tap one or more. Click anywhere else to skip it."
        static let savingHint = "Saving your answer…"
        static let dontAsk = "Don’t ask for this site"
        static func forProject(_ name: String) -> String { "For \(name)" }
        static func subject(title: String, host: String?) -> String {
            let name = title.trimmingCharacters(in: .whitespacesAndNewlines)
            switch (name.isEmpty, host) {
            case (false, let host?): return "\(name) · \(host)"
            case (false, nil): return name
            case (true, let host?): return host
            case (true, nil): return "A new bookmark"
            }
        }

        // MARK: Settings → Integrations → Browsers
        static let switchTitle = "Ask why when I bookmark something"
        static let switchDetail = "When you bookmark a page, a small question grows out of the top of the screen: what made you save it? One tap answers; the answer is kept with the bookmark and the time you saved it. Never after an import or a reorganised bookmark bar."
        /// Before the switch is on: what turning it on also does (consent, named).
        static func willWatch(_ names: [String]) -> String {
            "Turning this on also watches your bookmarks in \(list(names))."
        }
        /// On, and watching: the seed sentence, so the person knows the next bookmark is the first one asked about.
        static func watching(_ names: [String]) -> String {
            "Watching \(list(names)). Your next bookmark will ask — the ones you already have never do."
        }
        static func needsFullDiskAccess(_ name: String) -> String {
            "\(name) keeps its bookmarks in a folder macOS protects. Allow Cicada under Privacy & Security → Full Disk Access, then check again."
        }
        static let openFullDiskAccess = "Open Full Disk Access"
        static let checkAgain = "Check again"
        static let nothingWatched = "No browser on this Mac is watched, so nothing will ask. Turn one on above."
        static func leftOff(_ names: [String]) -> String {
            "\(list(names)) \(names.count == 1 ? "is" : "are") off, so \(names.count == 1 ? "its" : "their") bookmarks won't ask."
        }
        /// The developer-only preview item (`SaveWhyPreview`), never in a release app.
        static func previewItem(_ browser: String) -> String { "Preview “Ask why” (\(browser))" }

        static func list(_ names: [String]) -> String {
            switch names.count {
            case 0: return ""
            case 1: return names[0]
            case 2: return "\(names[0]) and \(names[1])"
            default: return names.dropLast().joined(separator: ", ") + " and " + names[names.count - 1]
            }
        }
        static func mutedLine(_ count: Int) -> String {
            count == 1 ? "1 site is never asked about." : "\(count) sites are never asked about."
        }
        static let unmuteAll = "Ask about every site again"
    }
}

// MARK: - The menu-bar badge (2026-10-14)
extension Copy {
    /// What the bookworm's badge counts, in words: the inbox's questions (owner 2026-10-14 read "99" as a
    /// consolidation count). The header line, the inbox line and the status item's tooltip all say it.
    static func questionsWaiting(_ n: Int) -> String {
        "\(UsageFormat.count(n)) question\(n == 1 ? "" : "s") waiting"
    }
    static func menuBarInboxLine(_ n: Int) -> String {
        n == 0 ? "Inbox: no questions waiting" : "Inbox: \(questionsWaiting(n))"
    }
}
