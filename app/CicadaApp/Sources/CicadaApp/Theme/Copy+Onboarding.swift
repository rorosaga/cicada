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

    // MARK: F-02 (Task 4)
    static let importTitle = "Bring in what you have"
    static let importSubline = "A tick starts that source right away, and it keeps going while you continue. What comes in stays."
    /// R-OB17 — "kept", not "everything stays": a reader may send what it reads (F-05 says where), so the banner
    /// promises only what is true of storage.
    static let importPrivateLead = "Private by design: what comes in is kept on this Mac."
    static let importPrivateTail = "Plain files you own. Bringing things in uploads nothing."
    static let importTickHelp = "Tick to bring it in now"
    static let importUntickHelp = "Untick to stop keeping up. What came in stays."
    static let importDoneOnce = "Brought in. Sync again any time in \(settings) → \(integrations)."
    static let importLockedHelp = "Reading now. A one-time read finishes on its own, and what came in stays."
    /// R-OB7 — a blocked browser's row before (and after) its tick: the tick opens the setting; the grant starts it.
    static let importNeedsAccess = "Needs Full Disk Access. Tick it to open the setting; it starts once allowed."
    static let importDropLead = "Drop an export, or"
    static let importDropDetail = "A .zip, a folder or one file, read on this Mac."
    static let importSeeHow = "See how ›"
    static let importMoreSources = "More sources any time in"
    static let onboardingSettingsIntegrations = "\(settings) → \(integrations)"
    static func importWait(_ vendor: ChatVendor) -> String {
        switch vendor {
        case .claude: "Ready in minutes to hours"
        case .chatgpt: "Can take up to 7 days"
        case .gemini: "Through Google Takeout"
        }
    }

    // MARK: F-03 (Task 4)
    static let seeHowTitle = "Ask for your chat history"
    static let seeHowReplay = "Replay"
    static let seeHowDone = "Done"
    static let seeHowClaudePath = "Settings → Privacy"
    static let seeHowChatGPTPath = "Settings → Data controls"
    static let seeHowGeminiPath = "My Activity → Gemini Apps"
    static let seeHowClaudeHonest = "Claude emails a link, usually within minutes to hours, and it works for 24 hours. Drop the .zip on this page when it comes."
    static let seeHowChatGPTHonest = "ChatGPT emails a link, which can take up to 7 days and works for 24 hours. Drop the .zip on this page when it comes: Cicada reads your conversations and skips the rest."
    static let seeHowGeminiHonest = "Google emails a link, usually the same day, and it works for 7 days. Pick My Activity → Gemini Apps, not the Gemini product. Drop the .zip on this page when it comes."
    static func seeHowOpenPage(_ vendor: String) -> String { "Open \(vendor)’s export page" }
    static func seeHowSteps(_ n: Int) -> String { "\(n) steps" }
    static func seeHowStepOf(_ n: Int, _ total: Int) -> String { "Step \(n) of \(total)" }
    static func seeHowWhere(host: String, path: String) -> String { "\(host) · \(path)" }

    /// Buttons, titles and one-line captions — ≤ 60 characters (CopyConstantsTests).
    static var onboardingLabels: [String] {
        [importReading(9, of: 17, noun: "conversations"), importBrowsers, importCalendar, importCalendarAndContacts,
         importNotesAndFiles, importVoice, importNotes, importWispr, importTickToBringIn, importCalendarMeta,
         importCalendarIdle, importNotesMeta, importNotesIdle, importWisprMeta, importTitle, importPrivateLead,
         importPrivateTail, importTickHelp, importUntickHelp, importDropLead, importDropDetail, importSeeHow,
         importMoreSources, onboardingSettingsIntegrations, seeHowTitle, seeHowReplay, seeHowDone, seeHowClaudePath,
         seeHowChatGPTPath, seeHowGeminiPath, seeHowOpenPage("ChatGPT"), seeHowSteps(11), seeHowStepOf(11, 11),
         seeHowWhere(host: "takeout.google.com", path: seeHowGeminiPath)]
            + ChatVendor.allCases.map(importWait)
    }

    /// Longer sentences — the vocabulary rule only.
    static var onboardingSentences: [String] {
        [importSubline, importDoneOnce, importLockedHelp, importNeedsAccess, seeHowClaudeHonest, seeHowChatGPTHonest,
         seeHowGeminiHonest]
    }
}
