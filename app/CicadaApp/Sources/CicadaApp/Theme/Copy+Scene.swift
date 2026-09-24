import Foundation

/// Round-4 T-Home — the living painting's, Home's (F-09) and Settings → General's (F-10) new words, in this track's
/// own file (R-IA19: sibling tracks append to the shared Copy files, and one file per track means no two edit the same
/// lines). Plain words, no price or token count (2026-09-03). `sceneLabels` (≤ 60 characters) and `sceneSentences`
/// feed `HomeF09Tests`' copy lint the way `welcomeHomeLabels` feeds `CopyConstantsTests`.
extension Copy {
    // MARK: Home (F-09)
    static let homeOpenInbox = "Open Inbox"
    static let homeMostly = "mostly"

    /// The label carries the count; an empty queue reads as the plain label (R-HO12).
    static func homeNeedsYouCount(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        n > 0 ? "\(homeNeedsYou) · \(UsageFormat.count(n, locale: locale))" : homeNeedsYou
    }

    static func homeOriginCount(_ label: String, _ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(label) \(UsageFormat.count(n, locale: locale))"
    }

    /// Today's row for VoiceOver: the marks are pictures, so the names and counts are spoken (DR-69).
    static func homeTodayAccessibility(_ captured: Int, origins: [(String, Int)],
                                       locale: Locale = .autoupdatingCurrent) -> String {
        let head = homeCapturedToday(captured, locale: locale)
        guard !origins.isEmpty else { return head }
        return head + ", \(homeMostly) " + origins.map { homeOriginCount($0.0, $0.1, locale: locale) }.joined(separator: ", ")
    }

    // MARK: Make it yours (F-09, R-HO15)
    static let tipTitle = "Make it yours"
    static let tipHide = "Hide"
    static let tipFindIt = "— find it in"
    static let tipDismiss = "Hide this card"

    // MARK: Settings → General (F-10, R-HO16)
    static let lookGroup = "Look"
    static let startupGroup = "Startup"
    static let whenClosedGroup = "When Cicada is closed"
    static let appearanceDetail = "Follows your Mac, or pick one"
    static let sceneAutomaticExplainer = "Automatic follows your sunrise and sunset from your time zone — no location needed."
    static let sceneCrossfadeExplainer = "Switching crossfades over about a second: the same meadow, in a different light. "
        + "Scene is separate from Appearance, so a light window can show the night meadow."
    static let showInMenuBar = "Show in menu bar"
    /// R-HO16 — never F-10's "no window, just the bookworm": Cicada opens its window at login today (R-FA7).
    static let showInMenuBarDetail = "Sleep and your Inbox at a glance. Closing the window never stops Cicada."

    /// What the clock paints right now, beside the Scene row's title (F-10) — whatever is picked.
    static func sceneNow(_ time: SceneTime) -> String {
        switch time {
        case .day: "Day now"
        case .afternoon: "Afternoon now"
        case .night: "Night now"
        }
    }

    static let sceneLabels: [String] = [homeOpenInbox, homeMostly, homeNeedsYouCount(3), homeOriginCount("Chrome", 2_104),
                                        tipTitle, tipHide, tipFindIt, tipDismiss,
                                        lookGroup, startupGroup, whenClosedGroup, appearanceDetail, showInMenuBar,
                                        sceneNow(.day), sceneNow(.afternoon), sceneNow(.night)]
    // `showInMenuBarDetail` is 71 characters — a sentence, not a label, so it is held to the sentence rules only.
    static let sceneSentences: [String] = [homeTodayAccessibility(2_540, origins: [("Chrome", 2_104)]),
                                           sceneAutomaticExplainer, sceneCrossfadeExplainer, showInMenuBarDetail]
}
