import Foundation

// MARK: - The menu-bar menu (consistency pass, round 3, 2026-10-20)

/// Every word the menu-bar bookworm says: its menu, its hover text, its mood. They were string literals in
/// `MenuBarManager` and `BookwormState` until round 3; now the one place they are spelled, like every other surface's
/// words (`MenuBarCopyLintTests`). Provider-neutral (owner 2026-09-30): no line names an engine, a plan or a model.
extension Copy {
    enum MenuBar {
        /// The status item's name in VoiceOver and its hover text: "Cicada — Happy, nothing waiting for Sleep".
        static func itemLabel(_ title: String, _ detail: String) -> String { "Cicada — \(title), \(detail)" }
        /// The hover text while the badge counts: "Cicada — 12 conversations waiting for Sleep".
        static func itemWaiting(_ n: Int) -> String { "Cicada — \(Copy.waitingForSleep(n))" }
        /// The header line when no Sleep door is known yet: "Happy — nothing waiting for Sleep".
        static func header(_ title: String, _ detail: String) -> String { "\(title) — \(detail)" }

        /// "Last sleep: 2 hours ago" / "Last sleep: never".
        static func lastSleep(_ phrase: String?) -> String { "Last sleep: \(phrase ?? "never")" }
        /// "Next sleep: Today, 3:00 AM" (the day in `RelativeDay`'s words, DR-58) / "Next sleep: not scheduled".
        static func nextSleep(day: String?, time: String?) -> String {
            guard let day else { return "Next sleep: not scheduled" }
            return time.map { "Next sleep: \(day), \($0)" } ?? "Next sleep: \(day)"
        }
        /// The prefix `refreshExportWaitItems` finds the "Next sleep" line by.
        static let nextSleepPrefix = "Next sleep:"

        static let saveClipboardURL = "Save clipboard URL"
        static let openCicada = "Open Cicada"
        static let quitCicada = "Quit Cicada"

        /// What *Save clipboard URL* did, said for a moment in the header line.
        static func flash(_ message: String) -> String { "Cicada: \(message)" }
        static let clipboardHasNoURL = "Clipboard has no URL"
        static func saved(_ url: String) -> String { "Saved \(url)" }
        static let saveComingSoon = "Save URL — coming soon"
        static let saveFailed = "Save failed"
    }

    /// The bookworm's moods (`BookwormState`): a title and one line under it, in the menu's header, the status item's
    /// hover text and VoiceOver. "Conversations", the app's word, where the old lines said "episodes".
    enum Mood {
        static let awake = "Awake"
        static let sleeping = "Sleeping"
        static let digesting = "Digesting"
        static let happy = "Happy"
        static let curious = "Curious"
        static let hungry = "Hungry"
        static let reading = "Reading"
        static let error = "Error"

        static let awakeDetail = "idle — listening for conversations"
        static func sleepingDetail(stage: Int, of total: Int = 5) -> String { "stage \(stage)/\(total)" }
        static let digestingDetail = "chewing on new memories…"
        static let hungryDetail = "no conversations in 48h"
        static let readingDetail = "reading what's waiting"
        static let errorDetail = "last sleep cycle failed"
        static let happyDetail = "nothing waiting for Sleep"
    }
}
