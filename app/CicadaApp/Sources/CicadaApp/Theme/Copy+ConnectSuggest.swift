import Foundation

/// G231 — the notch's suggestion to connect the app in front, and its Settings row. Short and provider-neutral (owner
/// 2026-09-30): the app named is the person's own; no model or provider is named doing anything. Said once (owner
/// 2026-11-03: no title that repeats its body): the title asks and the one line under it says what is read. The chips
/// of what Cicada does with it are gone (owner 2026-11-23).
extension Copy {
    enum ConnectSuggest {
        static func title(_ app: String) -> String { "Connect \(app) to Cicada?" }
        static let no = "No"
        static let notNow = "Not now"
        static let yes = "Yes"
        /// G245 (plan section 7, "Honest words") — what the Yes did, said as little as it is true: the write returns
        /// before anything is confirmed, so it is "Turned on", never "Connected" (the source's page says Connected once
        /// a read is dated); the question is promised only where it will really be asked.
        static let turningOn = "Turning on…"
        static let turnedOn = "Turned on"
        static let couldntTurnOn = "Couldn't turn it on"
        static let tryOnSources = "Try again from Sources."
        static func willAskWhy(_ site: String) -> String { "Saving on \(site) will ask why." }
        /// Noticing saves is on, but Accessibility is how a save is seen and it is not given yet (never prompted for).
        static func needsAccessibility(_ site: String) -> String { "Seeing saves on \(site) needs Accessibility." }
        static let openSettings = "Open Settings"

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
            case .saves:
                // GitHub has no saved list to read: a star is noticed when you click it, nothing else.
                target.entryId == ConnectSuggestApps.sitePrefix + "github"
                    ? "Only the save you click and its post are read."
                    : "Reads your saved list and notices the saves you click."
            case .savedList: "Reads your saved list, never more."
            }
        }

        /// G221 (ruling 77b) — the offer came from a save the person just made on a site that is not connected.
        static let keepsSave = "Yes keeps this save. Only saves you click are read."

        // MARK: - Settings → General

        static let settingTitle = "Suggest connecting apps"
        static let settingDetail = "When you open an app Cicada can read and it isn't connected, the notch may offer "
            + "it — at most once a day."
        static let declinedLabel = "Not suggested"
        static let suggestAgain = "Suggest again"
        static func suggestAgainHelp(_ name: String) -> String { "Let Cicada suggest \(name) again" }
    }
}
