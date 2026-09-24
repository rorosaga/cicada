import Foundation

/// Direction D, part 3b (DS-3b): the Sleep page's quick engine menu, Details, the Settings sheets
/// and the ⌘K Settings rows. Their own file for Track I's R-IA19 reason — sibling tracks append to
/// `Copy.swift`, and one file per track means two tracks never edit the same lines. Plain words, no
/// "!", no bare "%", no price or token count (DR-59, 2026-09-03); `HomeSleepCopyTests` holds every
/// string in `homeSleepLabels` to that.
extension Copy {
    /// The owner's quick switch (2026-09-23; R-HS7…R-HS11).
    enum EngineMenu {
        static let title = "Engine for the cycles you start"
        static let buttonHelp = "Engine and model for the cycles you start"
        static func buttonAccessibility(_ label: String) -> String { "\(title): \(label)" }
        static let model = "Model"
        static let howAutoPicks = "How Auto picks"
        /// R-HS11 — the one pair of preview labels, app-wide (the menu, Settings → Engines,
        /// Settings → Sleep). Three places said it two ways before.
        static let whenYouStart = "When you start a cycle"
        static let scheduledCycles = "Scheduled cycles"
        static let writeFailed = "Couldn't change the engine — nothing changed."
        static let moreInSettings = "More in Settings → Engines ›"
        static let plansAndKeys = "Plans & keys ›"
        static let autoPrefix = "Auto"
        static func signInFirst(_ label: String) -> String { "Sign in on Plans & keys to use your \(label)" }
    }

    /// Details (R-HS15): Last cycle's rows, the readout's keys, and the untitled episode.
    enum SleepDetailsWords {
        static let failedTitle = "Sleep cycle error"
        static let cancelledTitle = "Cancelled"
        static let cancelledText = "Stopped cleanly before any writes — nothing was lost."
        static func capTitle(_ cap: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "Episode cap reached (\(UsageFormat.count(cap, locale: locale)))"
        }
        static func capText(processed: Int, queued: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "\(UsageFormat.count(processed, locale: locale)) of \(UsageFormat.count(queued, locale: locale)) processed — the rest stay queued for the next cycle."
        }
        static let warningTitle = "Completed with warnings"
        static let inMemory = "In memory"
        static let feedingIt = "Feeding it"
        static let lastCycleTook = "Last cycle took"
        static let lastEngine = "Last engine"
        /// The engine row's dash reason. Not "Sleep hasn't run": `lastEngine` is also nil while the
        /// status is still loading and on an older backend, and a dash's reason is never a guess (R-A14).
        static let noEngineYet = "No cycle has reported its engine yet."
        static let untitled = "Untitled"
    }

    /// Every DS-3b label `HomeSleepCopyTests` holds to DR-59. Later tasks append here.
    static let homeSleepLabels: [String] = [
        EngineMenu.title, EngineMenu.buttonHelp, EngineMenu.model, EngineMenu.howAutoPicks,
        EngineMenu.whenYouStart, EngineMenu.scheduledCycles, EngineMenu.writeFailed, EngineMenu.moreInSettings,
        EngineMenu.plansAndKeys, EngineMenu.signInFirst("ChatGPT plan"),
        // `capText` is a sentence that passes 60 characters once its counts have four digits, so it
        // stays off this list (Task 3).
        SleepDetailsWords.failedTitle, SleepDetailsWords.cancelledTitle, SleepDetailsWords.cancelledText,
        SleepDetailsWords.capTitle(2), SleepDetailsWords.warningTitle, SleepDetailsWords.inMemory,
        SleepDetailsWords.feedingIt, SleepDetailsWords.lastCycleTook, SleepDetailsWords.lastEngine,
        SleepDetailsWords.noEngineYet, SleepDetailsWords.untitled,
    ]
}
