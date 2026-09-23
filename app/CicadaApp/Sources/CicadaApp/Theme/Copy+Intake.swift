import Foundation

/// Track I (part a) — the intake and found-row strings, in their own file so
/// this track and the sibling tracks appending to `Copy.swift` never edit the
/// same lines (R-IA19). Plain words for a person who has never heard "episode"
/// or "claim"; `CopyConstantsTests.testIntakeLabelsAreShortAndNeverSayClaim`
/// holds `intakeLabels` to 60 characters.
extension Copy {
    // MARK: The intake panel (Task 7)
    static let intakeDropTitle = "Drop an export here. The .zip is fine."
    static let intakeDropSubtitle = "Cicada works out what it is. Nothing is read until you say so."
    static let intakeChooseFile = "Choose a file…"
    static let intakeNoExportYet = "Don't have one yet?"
    static let intakeOpenExportPage = "Open export page"
    static let intakeHowToGet = "How to get it"
    static let intakeVeil = "Drop to bring into Cicada"
    static let intakeCancel = "Cancel"
    static let intakeDone = "Done"
    static let intakeReadNow = "Read now"
    static let intakeReadingNowShort = "Reading…"
    static let intakeReadingNow = "Reading now. Follow along on the Sleep page."
    static let intakeChooseWhoReads = "Choose who reads first"
    static let intakeChooseAnother = "Choose another file"
    static let intakeNothingNew = "Nothing new"
    static let intakeNothingNewLine = "Everything in this export is already in your memory."
    static let intakeNothingNewHeadline = "Nothing new came in."
    static let intakeInto = "Into"
    static let intakeActiveSuffix = "(active)"
    static let intakeNewMemory = "New memory…"
    static let intakeNewMemoryPlaceholder = "Name the new memory"
    static let intakeFileMenuItem = "Import…"
    static let intakeMenuBarItem = "Import a file…"
    static let intakeBusy = "Finish the import in progress first."
    static let intakeNothingReadable = "Nothing here is an export Cicada can read."
    static let intakeUnreadable = "Cicada couldn't read this file."
    static let intakeFailed = "The import didn't finish."
    static let intakeFilterPlaceholder = "Filter titles"
    static let intakeFilterLabel = "Filter conversation titles"
    static let emptyStateDropHint = "Or drop a chat export here"

    static func intakeReading(_ names: [String]) -> String {
        names.count == 1 ? "Reading \(names[0])…" : "Reading \(UsageFormat.count(names.count)) files…"
    }
    static func intakeImportButton(_ n: Int) -> String { "Import \(UsageFormat.count(n))" }
    static func intakeSkipped(_ name: String, _ reason: String) -> String { "Skipped: \(name) (\(reason))" }
    static func intakeInactiveBank(_ bank: String) -> String {
        "Imported into “\(bank)”. It isn't your active memory, so it won't be read yet."
    }
    static func intakeSwitchTo(_ bank: String) -> String { "Switch to “\(bank)”" }
    static func whatNextShowsIn(_ name: String) -> String { "They'll show in Sources as “\(name)”" }
    static func intakeCapped(_ n: Int) -> String { "Only the first \(UsageFormat.count(n)) files were read." }
    static func intakeTitlesCapped(_ n: Int) -> String { "Filtering the first \(UsageFormat.count(n)) titles." }
    static func intakeCouldNotCreate(_ name: String) -> String { "Couldn't create “\(name)”." }

    // MARK: Found rows (Tasks 5 and 8)
    static let foundOnThisMac = "On this Mac"
    static let foundTurnOn = "Turn on"
    static let foundOn = "On"
    static let foundOff = "Off"
    static let foundRetry = "Retry"
    static let foundAllow = "Allow…"
    static let foundConnecting = "Connecting…"
    static let foundSavingBookmarks = "Saving bookmarks…"
    static let foundWhatThisChanges = "What this changes"
    static let foundCopyCommands = "Copy commands"
    static let foundAgentDetail = "New sessions are remembered. Past ones stay."
    static let foundBrowserDetail = "Your bookmarks, and new ones as you save them"
    static let foundCursorDetail = "Opens Cursor to add Cicada"
    static let foundClaudeDesktopDetail = "Finish in Settings → Agents"
    static let foundNeedsDiskAccess = "Needs Full Disk Access to read"
    static let foundCheckingApps = "Checking your AI apps…"
    static let foundCouldNotCheck = "Couldn't check this app in time. Try again."
    static let foundPastStays = "Past sessions stay where they are. Cicada never reads them."
    static let foundInvalidSettings = "Its settings file isn't valid JSON, so Cicada didn't touch it. Fix it, then Retry."
    static let foundRefused = "Cicada couldn't vouch for these commands, so it didn't run them. Copy them into Terminal instead."
    static let foundBackendDown = "Waiting for Cicada's background service…"

    // MARK: Honesty (Task 6, design §5.3) — ruling 4, said out loud
    static let afterImportWhenYouAsk = "Cicada reads these when you ask."
    static let afterImportPlanWaits = "Scheduled reads never use a plan, so these wait until you read them. Read now, or add a key."
    static let afterImportWaits = "Nothing can read these on a schedule yet, so they wait until you read them."
    static func afterImportScheduled(when: String, engine: String) -> String { "Cicada reads these \(when), using \(engine)." }
    static let honestyPlanThenKey = "Your plan reads when you ask. Scheduled reads use your API key."
    static let honestyPlanThenOllama = "Your plan reads when you ask. Scheduled reads run on this Mac."
    static let honestyPlanBoth = "Your plan reads, when you ask and on a schedule."
    static let honestyPlanOnly = "Plans read when you ask. A key or Ollama can also read on a schedule."
    static let honestyOllama = "Reads on this Mac, whenever it runs. Nothing leaves this Mac."
    static let honestyKey = "Your key reads, when you ask and on a schedule. Your provider bills per use."
    static let honestyNothingYet = "Nothing can read yet. Choose who reads before the first read."
    static let foundStartNothing = "Sets your name. You can add sources any time."

    /// The engine as a person says it, inside a sentence ("using your API key").
    /// `Copy.engineLabel` stays the noun for pickers and pills.
    static func engineUse(_ engine: String) -> String {
        switch engine {
        case "claude-cli": "your Claude plan"
        case "codex-cli": "your ChatGPT plan"
        case "ollama": "Ollama on this Mac"
        case "litellm": "your API key"
        default: engineLabel(engine)
        }
    }

    /// Buttons, titles and one-line captions — held to 60 characters.
    static let intakeLabels: [String] = [
        intakeDropTitle, intakeChooseFile, intakeNoExportYet, intakeOpenExportPage, intakeHowToGet,
        intakeVeil, intakeCancel, intakeDone, intakeReadNow, intakeReadingNowShort, intakeReadingNow,
        intakeChooseWhoReads, intakeChooseAnother, intakeNothingNew, intakeNothingNewLine,
        intakeNothingNewHeadline, intakeInto, intakeNewMemory, intakeNewMemoryPlaceholder,
        intakeFileMenuItem, intakeMenuBarItem, intakeBusy, intakeNothingReadable, intakeUnreadable,
        intakeFailed, intakeFilterPlaceholder, intakeFilterLabel, emptyStateDropHint,
        foundOnThisMac, foundTurnOn, foundOn, foundOff, foundRetry, foundAllow, foundConnecting,
        foundSavingBookmarks, foundWhatThisChanges, foundCopyCommands, foundAgentDetail,
        foundBrowserDetail, foundCursorDetail, foundClaudeDesktopDetail, foundNeedsDiskAccess,
        foundCheckingApps, foundCouldNotCheck, foundPastStays, foundBackendDown,
        afterImportWhenYouAsk, honestyPlanBoth, foundStartNothing,
    ]
    /// Longer sentences — no length rule, the same vocabulary rule.
    /// `honestyPlanThenKey` (63) and `honestyPlanThenOllama` (62) are two-sentence
    /// captions, so they live here rather than failing the 60-character rule.
    static let intakeSentences: [String] = [
        intakeDropSubtitle, foundInvalidSettings, foundRefused,
        afterImportPlanWaits, afterImportWaits, honestyPlanThenKey, honestyPlanThenOllama,
        honestyPlanOnly, honestyOllama, honestyKey, honestyNothingYet,
    ]
}
