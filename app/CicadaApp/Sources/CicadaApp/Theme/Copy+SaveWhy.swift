import Foundation

/// G191 — the "What made you save this?" panel and its Settings switch. The reason labels themselves come from the
/// backend (`GET /sources/saved-why/options`), so the words the panel shows are the words the record keeps.
extension Copy {
    enum SaveWhy {
        static let question = "What made you save this?"
        /// G191 v4: the field is the "something else" beside the four reasons.
        static let placeholder = "Something else…"
        static let wordsLabel = "Your own words about why you saved it"
        static let save = "Save"
        /// Esc reaches the panel only once it has been clicked (it never takes the keyboard from the browser), so
        /// the hint names the ways that always work. v3: any number of reasons; leaving keeps them.
        static func hint(pending: Bool, chosen: Bool) -> String {
            if chosen { return "Save, or click anywhere else — your choice is kept." }
            return pending ? "Pick any that fit while it saves." : "Pick any that fit. Click anywhere else to skip it."
        }
        static let dontAsk = "Don’t ask for this site"
        static func forProject(_ name: String) -> String { "For \(name)" }
        static func subject(title: String, host: String?, resave: Bool = false) -> String {
            let name = title.trimmingCharacters(in: .whitespacesAndNewlines)
            let line: String
            switch (name.isEmpty, host) {
            case (false, let host?): line = "\(name) · \(host)"
            case (false, nil): line = name
            case (true, let host?): line = host
            case (true, nil): line = "A new bookmark"
            }
            return resave ? "Saved again · \(line)" : line
        }
        /// G191 v3 — the pending panel (the browser's bookmark bubble seen, its file not written yet).
        static func pendingSubject(browser: String?) -> String {
            browser.map { "Saving in \($0)…" } ?? "Saving your bookmark…"
        }

        // MARK: Settings → Integrations → Browsers
        static let switchTitle = "Ask why when I bookmark something"
        static let switchDetail = "When you bookmark a page, a small question grows out of the top of the screen: what made you save it? Pick any reasons and add a few words; they are kept with the bookmark and the time you saved it. Saving a page again asks again. Never after an import or a reorganised bookmark bar."
        /// G191 v3 — what Cicada watches to ask at once, in plain words: window positions only, no permission.
        static let bubbleLine = "To ask at once, Cicada notices when Chrome shows its bookmark bubble right after you click the star — it looks only at where Chrome’s windows are, never at what they show, and needs no permission."
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

// MARK: - G191 v3: the bookmark history and the bookmark's page
extension Copy {
    enum Bookmarks {
        static let menuItem = "Bookmarks…"
        static let searchPrompt = "Search bookmarks and why you saved them"
        static let none = "No bookmarks yet. Turn on a browser under Settings → Integrations."
        static let noMatch = "Nothing matches."
        static func footer(_ total: Int) -> String {
            total == 1 ? "1 bookmark · Return opens it in Cicada" : "\(UsageFormat.count(total)) bookmarks · Return opens one in Cicada"
        }
        /// A row's second line: the reasons, the words, the site.
        static func secondLine(_ row: BookmarkHistoryRow) -> String {
            var parts = row.reasons
            if let words = row.words { parts.append("“\(words)”") }
            if parts.isEmpty { parts.append(row.host.isEmpty ? row.url : row.host) }
            return parts.joined(separator: " · ")
        }

        // The bookmark's page (the Feed's detail).
        static let reasonsLabel = "Why you saved it"
        static let addReason = "Add why you saved it"
        static let edit = "Edit"
        static let save = "Save"
        static let cancel = "Cancel"
        static let editPrompt = "A few words of your own (optional)"
        static func answerLine(_ record: SavedWhyRecord, resave: Bool) -> String {
            var parts: [String] = []
            if let added = record.addedAt.flatMap(Self.day) { parts.append(resave ? "Saved again \(added)" : "Saved \(added)") }
            if let said = record.at.flatMap(Self.day) { parts.append("said \(said)") }
            if record.editedAt != nil { parts.append("edited") }
            return parts.joined(separator: " · ")
        }
        static func day(_ iso: String) -> String? {
            guard let date = ISO8601DateFormatter().date(from: iso) else { return nil }
            return date.formatted(.dateTime.day().month(.abbreviated).hour().minute())
        }
        static let saved = "Saved"
        static let editFailed = "Your change wasn't saved."

        // G191 v4 — a bookmark that left the browser: Cicada keeps it and says so.
        /// "No longer in Chrome since Oct 15" — one browser; several are named together, newest day first.
        static func noLongerIn(_ left: [BookmarkLeft], calendar: Calendar = .current) -> String? {
            guard !left.isEmpty else { return nil }
            let sorted = left.sorted { $0.since > $1.since }
            let names = SaveWhy.list(sorted.map(\.browser))
            guard let day = shortDay(sorted[0].since, calendar: calendar) else { return "No longer in \(names)" }
            return "No longer in \(names) since \(day)"
        }
        static func shortDay(_ iso: String, calendar: Calendar = .current) -> String? {
            let parser = ISO8601DateFormatter()
            parser.formatOptions = [.withInternetDateTime]
            var text = iso
            if let dot = text.firstIndex(of: "."), let zone = text[dot...].firstIndex(where: { $0 == "+" || $0 == "Z" || $0 == "-" }) {
                text.removeSubrange(dot..<zone)   // fractional seconds, as a sync instant may carry
            }
            guard let date = parser.date(from: text) else { return nil }
            var style = Date.FormatStyle.dateTime.month(.abbreviated).day()
            style.calendar = calendar
            style.timeZone = calendar.timeZone
            return date.formatted(style)
        }
        static let keptNote = "Cicada keeps it, with why you saved it. Bookmark it again to link it back."

        // Remove.
        static let remove = "Remove bookmark…"
        static let removeTitle = "Remove this bookmark?"
        static let removeConfirm = "Remove"
        static let removeFromChrome = "Cicada forgets it and removes it from Chrome too. The first time, macOS asks whether Cicada may control Chrome."
        static let removeCicadaOnly = "Cicada forgets it. Its page and what you said about it stay in your memory's history."
        static let safariNote = "Safari doesn’t let other apps change its bookmarks, so remove it there yourself: Bookmarks › Edit Bookmarks."
        static let openSafari = "Open Safari"
        static let removed = "Removed."
        static func removedFromChrome(_ n: Int) -> String { n == 1 ? "Removed, in Cicada and in Chrome." : "Removed, in Cicada and \(n) times in Chrome." }
        static let chromeDenied = "Removed in Cicada. Chrome still has it: allow Cicada under Privacy & Security → Automation → Google Chrome, then remove it there."
        static func chromeFailed(_ why: String) -> String { "Removed in Cicada. Chrome still has it (\(why))." }
        static let chromeNoneMatched = "Removed in Cicada. The Chrome profile that’s open doesn’t hold this bookmark, so nothing changed in Chrome."
        static func chromeCopies(_ n: Int) -> String {
            "Chrome has \(UsageFormat.count(n)) copies of this link. Cicada forgets it; in Chrome, remove only the copy from this save, or all of them?"
        }
        static func removeOneCopy(_ day: String?) -> String { day.map { "Remove the copy saved \($0)" } ?? "Remove the newest copy" }
        static func removeAllCopies(_ n: Int) -> String { "Remove all \(UsageFormat.count(n)) copies" }
        static let chromeMobileOnly = "Removed in Cicada. Chrome keeps it under Mobile bookmarks, which other apps can’t change."
        static let removeFailed = "The bookmark wasn't removed."
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
