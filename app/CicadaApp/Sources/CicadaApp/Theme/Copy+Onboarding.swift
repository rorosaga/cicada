import Foundation

/// Round-4 phase B (G145, G153) — the paged onboarding's words, in their own file (Track I's R-IA19 reason: one file
/// per track, so parallel tracks never edit the same lines). Plain words for a person who has never heard "episode"
/// or "claim"; no price and no token count anywhere (2026-09-03). Two lists feed
/// `CopyConstantsTests.testOnboardingCopyIsShortPlainAndPriceless`: `onboardingLabels` (≤ 60 characters) and
/// `onboardingSentences` (the vocabulary rule only). A new string joins one, or the lint does not see it.
extension Copy {
    // MARK: Import rows (Task 2)

    /// R-OB10 — a staged export's row while its job runs: the job's own counts, in the reader's locale.
    static func importReading(_ done: Int, of total: Int, noun: String,
                              locale: Locale = .autoupdatingCurrent) -> String {
        "Reading \(UsageFormat.count(done, locale: locale)) of \(UsageFormat.count(total, locale: locale)) \(noun)"
    }
}
