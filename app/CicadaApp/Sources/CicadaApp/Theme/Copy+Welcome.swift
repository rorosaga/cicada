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

    // MARK: Who reads (Task 2, R-IB13)
    static let costModelPlan = "Uses your plan"
    static let costModelLocal = "Free, on this Mac. Slower."
    static let costModelKey = "Billed per use by your provider"
    static let engineKeySaved = "Key saved"
    static let engineAddKey = "Add a key in \(plansAndKeys)"
    static let welcomeNotChosen = "Not chosen yet. Cicada asks before its first read."
    static let welcomeWillRead = "Will read"
    static let welcomeProviderLine = "Plans and keys send what Cicada reads to that provider."
    static func welcomePickSaved(_ label: String) -> String { "\(label) · saved when you press Start" }
    static func welcomeDemoFailed(_ why: String) -> String { "Couldn't create the demo memory: \(why)" }

    // MARK: Getting started (Tasks 2–3)
    static let gsBringingIn = "Bringing it in…"
    static let gsEngineFailed = "Couldn't save who reads. Choose again below."
    static let gsTitle = "Getting started"
    static let gsHide = "Hide"
    static let gsDone = "You're set up."
    static let gsAgentOn = "New sessions are remembered"
    static let gsAgentGone = "Not found on this Mac any more"
    /// A pointer names its destination exactly as Settings spells it (G68 §2.8).
    static let gsFinishInIntegrations = "Finish in \(settings) → \(integrations)"
    static let gsChatHistory = "Your chat history"
    static let gsChatDrop = "Drop an export here, or choose a file"
    static let gsReading = "Reading what came in"
    static let gsNothingYet = "Nothing to read yet. Drop an export, or chat with a connected app."
    static let gsFinishedNoCount = "Your first read is done."
    static let gsLeaveWhileReading = "You can leave this page. The bookworm keeps reading."
    static let gsWatchOnSleep = "Watch on the Sleep page"
    static let gsOpenGraph = "Open the graph"
    static let gsTryAgain = "Try again"
    static let gsScheduleQuestion = "Keep reading on its own?"
    static let gsWhenIAsk = "When I ask"
    static let gsAfterImports = "After imports"
    static let gsNightly = "Every night at 3:00"
    static let gsNotNow = "Not now"
    static let gsAlsoFound = "Also found"
    static let gsDismiss = "Dismiss"
    static let gsShowChecklist = "Show setup checklist"
    /// The disclosure under a failed first read: change who reads, then try again.
    static let gsWhoReads = "Who reads"
    static func gsWaiting(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(n, locale: locale)) waiting to be read."
    }
    static func gsRunning(read: Int, total: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Reading · Read \(UsageFormat.count(read, locale: locale)) of \(UsageFormat.count(total, locale: locale))"
    }
    static func gsFinished(pages: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Your memory has \(UsageFormat.count(pages, locale: locale)) pages now."
    }
    static func gsCapped(read: Int, left: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Read \(UsageFormat.count(read, locale: locale)) this round. \(UsageFormat.count(left, locale: locale)) still waiting."
    }
    static func gsReadNext(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Read the next \(UsageFormat.count(n, locale: locale))"
    }

    /// Buttons, titles and one-line captions — ≤ 60 characters (CopyConstantsTests).
    static let welcomeHomeLabels: [String] = [
        homeHeadline, homeHeadlineItalic, homeFieldPrompt, homeToday, homeNeedsYou, homeLastRead,
        homeCapturedHelp, homeLoading, homeNothingCapturedToday, homeNothingWaiting, homeNothingNeedsYou,
        homeNothingReadYet, homeNothingChanged, homeOpenSleep, homeSaveLink,
        costModelPlan, costModelLocal, costModelKey, engineKeySaved, engineAddKey, welcomeWillRead,
        welcomeNotChosen, welcomeProviderLine, welcomePickSaved("ChatGPT plan"), gsBringingIn, gsEngineFailed,
        gsTitle, gsHide, gsDone, gsAgentOn, gsAgentGone, gsFinishInIntegrations, gsChatHistory, gsChatDrop,
        gsReading, gsFinishedNoCount, gsWatchOnSleep, gsOpenGraph, gsTryAgain, gsScheduleQuestion, gsWhenIAsk,
        gsAfterImports, gsNightly, gsNotNow, gsAlsoFound, gsDismiss, gsShowChecklist, gsWhoReads,
        gsWaiting(1_061), gsRunning(read: 1_061, total: 1_061), gsFinished(pages: 1_061),
        gsCapped(read: 1_061, left: 1_061), gsReadNext(1_061),
    ]
    /// Longer sentences — the vocabulary rule only.
    /// `welcomeDemoFailed` carries the server's own reason, so its length is not ours.
    static let welcomeHomeSentences: [String] = [welcomeDemoFailed("the service is not running"),
                                                 gsNothingYet, gsLeaveWhileReading]
}
