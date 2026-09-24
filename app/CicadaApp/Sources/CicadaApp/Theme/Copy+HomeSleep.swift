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

    /// Every DS-3b label `HomeSleepCopyTests` holds to DR-59. Later tasks append here.
    static let homeSleepLabels: [String] = [
        EngineMenu.title, EngineMenu.buttonHelp, EngineMenu.model, EngineMenu.howAutoPicks,
        EngineMenu.whenYouStart, EngineMenu.scheduledCycles, EngineMenu.writeFailed, EngineMenu.moreInSettings,
        EngineMenu.plansAndKeys, EngineMenu.signInFirst("ChatGPT plan"),
    ]
}
