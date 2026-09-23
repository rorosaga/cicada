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

    // MARK: The Welcome (Task 4, design §4.1)
    static let welcomeHelloNoName = "Hello."
    static let welcomeFound = "Here's what Cicada found on this Mac."
    static let welcomeSubline = "One memory for every AI you use. It lives on this Mac, in plain files you own."
    static let welcomeYourName = "Your name"
    static let welcomeAddName = "Add your name to start"
    static let welcomeYourAIApps = "Your AI apps"
    static let welcomeYourBrowsers = "Your browsers"
    static let welcomeYourChatHistory = "Your chat history"
    static let welcomeWhoReads = "Who reads what you save"
    static let welcomeNothingFound = "Nothing to bring over automatically. That's fine."
    static let welcomeDropExport = "Drop a Claude, ChatGPT or Gemini export here"
    static let welcomeStart = "Start remembering"
    static let welcomeSaveChanges = "Save changes"
    static let welcomeStarting = "Starting…"
    static let welcomeTryDemo = "Try the demo instead"
    static let welcomeSetUpLater = "Set up later"
    static let welcomeSetUpLaterNeedsName = "Set up later (add your name first)"
    static let welcomeClose = "Close"
    static let welcomeAllowed = "Allowed. Safari bookmarks will come along."
    /// The ✕ beside a staged export: it only un-stages it (nothing was imported yet).
    static let welcomeRemoveDrop = "Remove"
    static func welcomeHello(_ first: String) -> String { "Hello, \(first)." }
    static func welcomeNotYou(_ first: String) -> String { "Not \(first)? Change" }
    static func welcomeSettingUp(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        n == 1 ? "Cicada is setting up 1 thing." : "Cicada is setting up \(UsageFormat.count(n, locale: locale)) things."
    }

    /// Buttons, titles and one-line captions — ≤ 60 characters (CopyConstantsTests).
    // MARK: Reminders (Task 5, design §5.5, R-IB22)
    static let reminderRemindMe = "Remind me"
    static let reminderInThreeHours = "In 3 hours"
    static let reminderTomorrowMorning = "Tomorrow at 9:00"
    static let reminderInTwoDays = "In 2 days"
    static let reminderBody = "Drop the .zip on Cicada."
    static let reminderDropHere = "Drop it here"
    static let reminderDismiss = "Stop waiting"
    static let welcomeAskForOne = "No export yet? Ask for one"
    /// A denial still records the wait (R-IB22), so the line says where it waits
    /// instead of asking the person to go and change a system setting.
    static let reminderNotificationsOff = "Notifications are off, so the reminder waits here and in the menu bar."
    static func reminderTitle(_ vendor: String) -> String { "Your \(vendor) export should be in your email." }
    static func reminderStripLine(_ vendor: String, requested: String) -> String {
        "Waiting for your \(vendor) export · requested \(requested)"
    }
    static func reminderMenuLine(_ vendor: String, requested: String) -> String {
        "Waiting for \(vendor) export, requested \(requested)"
    }
    static func reminderRowLine(requested: String, reminder: String?) -> String {
        reminder.map { "Requested \(requested) · reminder \($0)" } ?? "Requested \(requested)"
    }

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
        welcomeHelloNoName, welcomeFound, welcomeYourName, welcomeAddName, welcomeYourAIApps, welcomeYourBrowsers,
        welcomeYourChatHistory, welcomeWhoReads, welcomeNothingFound, welcomeDropExport, welcomeStart,
        welcomeSaveChanges, welcomeStarting, welcomeTryDemo, welcomeSetUpLater, welcomeSetUpLaterNeedsName,
        welcomeClose, welcomeAllowed, welcomeRemoveDrop, welcomeHello("Ada"), welcomeNotYou("Ada"),
        welcomeSettingUp(1), welcomeSettingUp(1_061),
        reminderRemindMe, reminderInThreeHours, reminderTomorrowMorning, reminderInTwoDays, reminderBody,
        reminderDropHere, reminderDismiss, welcomeAskForOne,
        reminderRowLine(requested: "2 hours ago", reminder: "in 21 hours"),
    ]
    /// Longer sentences — the vocabulary rule only.
    /// `welcomeDemoFailed` carries the server's own reason, so its length is not ours.
    static let welcomeHomeSentences: [String] = [welcomeDemoFailed("the service is not running"),
                                                 gsNothingYet, gsLeaveWhileReading, welcomeSubline,
                                                 reminderNotificationsOff, reminderTitle("ChatGPT"),
                                                 reminderStripLine("ChatGPT", requested: "2 hours ago"),
                                                 reminderMenuLine("ChatGPT", requested: "2 hours ago")]
}
