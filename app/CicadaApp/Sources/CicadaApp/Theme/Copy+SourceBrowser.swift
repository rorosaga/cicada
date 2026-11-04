import Foundation

extension Copy {
    /// 2026-11-04 — the accounts → collections → items browser on the This Mac source pages (`SourceBrowser`): short
    /// and said once (DESIGN_RULES §9 2026-11-03: no paragraphs, one line at most, no repeated titles).
    enum SourceBrowser {
        static let accounts = "Accounts"
        static let recent = "Recent"
        static let openHelp = "Open"
        static func back(_ to: String) -> String { "‹ \(to)" }
        static let backHelp = "Back (Esc)"

        /// A nameless account (a sync from before accounts were named) by its kind.
        static func unnamedAccount(_ kind: SourceAccountProvider) -> String {
            switch kind {
            case .icloud: "iCloud"
            case .local: "On My Mac"
            case .google: "Google"
            case .exchange: "Exchange"
            case .subscribed: "Subscribed"
            case .other: "Other"
            }
        }

        /// What a channel's items are called, one and many.
        static func noun(_ channel: String) -> (one: String, many: String) {
            switch channel {
            case "notes": ("note", "notes")
            case "calendar-local": ("event", "events")
            case "reminders-local": ("reminder", "reminders")
            case "contacts-local": ("person", "people")
            default: channel.hasPrefix("meetings:") ? ("meeting", "meetings") : ("item", "items")
            }
        }

        static func count(_ n: Int, channel: String, locale: Locale = .autoupdatingCurrent) -> String {
            let noun = noun(channel)
            return "\(UsageFormat.count(n, locale: locale)) \(n == 1 ? noun.one : noun.many)"
        }

        static func search(_ n: Int?, channel: String, in place: String? = nil,
                           locale: Locale = .autoupdatingCurrent) -> String {
            let noun = noun(channel)
            let what = n.map { "\(UsageFormat.count($0, locale: locale)) \($0 == 1 ? noun.one : noun.many)" } ?? noun.many
            return place.map { "Search \(what) in \($0)" } ?? "Search \(what)"
        }

        static let loading = "Reading…"
        static let nothing = "Nothing here yet."
        static let contactsNone = "No one from your Contacts is in memory yet."
        static func contactHelp(_ name: String) -> String { "Open \(name)'s page" }

        // Meeting recorders
        static func recorderFolder(_ path: String) -> String { "Found \(path)" }
        static let recorderFolderHelp = "Where Hex saves each meeting it records"
        static let hexConnect = "Connect Hex"
        static let hexNoFolder = "Hex hasn't saved a meeting on this Mac yet."
        static let otherFolder = "Choose another folder…"

        // Not installed (owner 2026-11-04: "I deleted Whisperflow today, and the app should have detected that")
        static func notInstalled(_ app: String) -> String { "\(app) isn't on this Mac" }
        static let notInstalledWord = "not installed"
    }
}
