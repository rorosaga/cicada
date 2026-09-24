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

    static let sceneLabels: [String] = [homeOpenInbox, homeMostly, homeNeedsYouCount(3), homeOriginCount("Chrome", 2_104),
                                        tipTitle, tipHide, tipFindIt, tipDismiss]
    static let sceneSentences: [String] = [homeTodayAccessibility(2_540, origins: [("Chrome", 2_104)])]
}
