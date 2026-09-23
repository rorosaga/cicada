import Foundation

/// Track I (part b) — the Welcome, Getting started, Home and reminder strings,
/// in their own file for part a's R-IA19 reason: sibling tracks append to
/// `Copy.swift`, and one file per track means no two of them ever edit the same
/// lines. Plain words for a person who has never heard "episode" or "claim",
/// and no price or token count anywhere (2026-09-03).
///
/// Two lists feed `CopyConstantsTests.testWelcomeAndHomeCopyIsShortPlainAndPriceless`:
/// `welcomeHomeLabels` (buttons, titles, one-line captions — ≤ 60 characters)
/// and `welcomeHomeSentences` (longer lines — the vocabulary rule only). A new
/// string joins one of them, or the lint does not see it.
extension Copy {
    // MARK: Home (Task 1, design §6)
    static let homeHeadline = "What would you like"
    static let homeHeadlineItalic = "to remember?"
    static let homeFieldPrompt = "Search, paste a link, or drop a file"
    static let homeToday = "Today"
    static let homeNeedsYou = "Needs you"
    static let homeLastRead = "Last read"
    /// The TODAY sum is the UTC bucket `source_overview` writes (R-A16), so the
    /// hover says which midnight it counts from rather than pretending local.
    static let homeCapturedHelp = "Captured since 00:00 UTC"
    static let homeLoading = "Loading…"
    static let homeNothingCapturedToday = "Nothing captured yet today"
    static let homeNothingWaiting = "Nothing waiting to be read"
    static let homeNothingNeedsYou = "Nothing needs you right now."
    static let homeNothingReadYet = "Nothing read yet"
    static let homeNothingChanged = "nothing changed"
    /// A link to the Sleep page, never a trigger (G125 R10 in steady state).
    static let homeOpenSleep = "Sleep ›"
    static let homeSaveLink = "Save this link"
    static func homeCapturedToday(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) captured today"
    }
    static func homeWaiting(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) waiting to be read"
    }
    static func homeAllInbox(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "All \(UsageFormat.count(n, locale: locale)) ›"
    }
    static func homeMoreChips(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "+\(UsageFormat.count(n, locale: locale))"
    }
    static func homeSaveLinkRow(_ host: String) -> String { "\(homeSaveLink) · \(host)" }
    static func homeLinkSaved(_ host: String) -> String { "Saved \(host)" }

    /// Buttons, titles and one-line captions — ≤ 60 characters (CopyConstantsTests).
    static let welcomeHomeLabels: [String] = [
        homeHeadline, homeHeadlineItalic, homeFieldPrompt, homeToday, homeNeedsYou, homeLastRead,
        homeCapturedHelp, homeLoading, homeNothingCapturedToday, homeNothingWaiting, homeNothingNeedsYou,
        homeNothingReadYet, homeNothingChanged, homeOpenSleep, homeSaveLink,
    ]
    /// Longer sentences — the vocabulary rule only.
    static let welcomeHomeSentences: [String] = []
}
