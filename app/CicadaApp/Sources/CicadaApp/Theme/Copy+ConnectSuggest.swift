import Foundation

/// G231 — the notch's suggestion to connect the app in front, and its Settings row. Short and provider-neutral (owner
/// 2026-09-30): the app named is the person's own; no model or provider is named doing anything. Said once (owner
/// 2026-11-03: no title that repeats its body): the title asks, the chips say what Cicada does with it, the one line
/// under them says what is read — none repeats another.
extension Copy {
    enum ConnectSuggest {
        static func title(_ app: String) -> String { "Connect \(app) to Cicada?" }
        static let no = "No"
        static let notNow = "Not now"
        static let yes = "Yes"
        static let usesLabel = "What Cicada does with it"

        /// Two or three concrete things Cicada does with that kind of source.
        static func uses(_ kind: ConnectSuggestApps.Kind) -> [String] {
            switch kind {
            case .chats: ["Remember what friends tell you", "Find that link someone sent", "Recall plans you made"]
            case .notes: ["Find a note by what it means", "Tie notes to your projects"]
            case .calendar: ["Know who you met and when", "Tie meetings to your projects"]
            case .reminders: ["Keep track of what you planned", "Notice to-dos gone quiet"]
            case .contacts: ["Put a face to people you mention", "Know who's who across chats"]
            case .browser: ["Remember why you saved a page", "Find a bookmark by what it's about"]
            case .meetings: ["Remember what a meeting decided", "Find who said what"]
            case .dictation: ["Remember what you said aloud", "Find a thought you dictated"]
            case .notion: ["Find a page by what it means", "Tie docs to your projects"]
            }
        }

        /// What Yes leads to being read — never more or less than the source's own page then offers. A browser says
        /// what its own entry reads (`BrowserSpec.reads` and its extra switches): Chrome's tab groups and watched
        /// videos are separate switches, Safari's Reading List comes with its bookmarks and its iCloud tabs are an
        /// import the person starts; every other browser is bookmarks only.
        static func reads(_ target: ConnectSuggestApps.Target) -> String {
            switch target.kind {
            case .chats: "Only the chats you tick are read."
            case .reminders: "Only the lists you tick are read."
            case .notes, .calendar, .contacts: "macOS asks you first."
            case .browser:
                switch target.entryId {
                case SourceCatalog.browserPrefix + "chrome":
                    "Bookmarks; tab groups and watched videos only if you turn them on."
                case SourceCatalog.browserPrefix + "safari":
                    "Bookmarks and Reading List; iCloud tabs only if you import them."
                default: "Only your bookmarks are read."
                }
            case .meetings: "Only transcripts are read, never audio."
            case .dictation: "Only what you dictate is read."
            case .notion: "Only pages you share are read."
            }
        }

        // MARK: - Settings → General

        static let settingTitle = "Suggest connecting apps"
        static let settingDetail = "When you open an app Cicada can read and it isn't connected, the notch may offer "
            + "it — at most once a day."
        static let declinedLabel = "Not suggested"
        static let suggestAgain = "Suggest again"
        static func suggestAgainHelp(_ name: String) -> String { "Let Cicada suggest \(name) again" }
    }
}
