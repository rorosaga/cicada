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

    // MARK: Import categories and rows (Task 3)
    static let importBrowsers = "Browsers"
    static let importCalendar = "Calendar"
    static let importCalendarAndContacts = "Calendar & contacts"
    static let importNotesAndFiles = "Notes & files"
    static let importVoice = "Voice & meetings"
    static let importNotes = "Apple Notes"
    static let importWispr = "Wispr Flow"
    static let importTickToBringIn = "Tick to bring it in"
    static let importCalendarMeta = "Every calendar on this Mac"
    static let importCalendarIdle = "Asks macOS once for your calendars"
    static let importNotesMeta = "Every folder"
    /// R-OB11 — Notes syncs on demand; the row never says "keeps up".
    static let importNotesIdle = "Reads your notes now; sync again any time"
    static let importWisprMeta = "Meetings · dictation stays off"
}
