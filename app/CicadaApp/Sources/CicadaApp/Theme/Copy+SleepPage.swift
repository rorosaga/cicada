import Foundation

extension Copy {
    /// The Sleep page redesign (owner 2026-11-24) — the run bar's words and the tab row's More menu. Provider-neutral
    /// (owner, 2026-09-30): nothing here names who reads.
    enum SleepPage {
        // The schedule in a few words (the sentence is the control's `.help` and the lamp popover's).
        static let scheduleOff = "Off"
        static func scheduleDaily(_ clock: String) -> String { "Daily at \(clock)" }
        static let scheduleHourly = "Hourly"
        static func scheduleEvery(_ hours: Int) -> String { "Every \(UsageFormat.count(hours)) h" }
        static let scheduleAfterImports = "After imports"

        /// The run bar's primary when the column is too narrow for `Copy.consolidateNow` (its `.accessibilityLabel` and
        /// `.help` keep the full words).
        static let consolidateShort = "Consolidate"

        /// The tab row's trailing menu: what is not a Sleep list folds in here (Saved, Videos).
        static let moreHelp = "Saved and videos"
        static let moreAccessibility = "More lists"
    }
}
