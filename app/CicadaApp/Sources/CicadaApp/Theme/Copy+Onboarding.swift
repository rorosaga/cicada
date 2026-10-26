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
    /// R-OB11 — Notes syncs on demand; the row never says "keeps up". A tick runs the backend's osascript read at
    /// once, which raises macOS's Automation prompt (api/services/notes_sync.py), so the line names that prompt the way
    /// Calendar's does — G145: no permission prompt beyond the one a row names (final review).
    static let importNotesIdle = "macOS asks once for Notes, then Cicada reads them now"
    /// The driver keeps the person's own dictation setting, so the meta follows it (`ImportContext.wisprDictation`)
    /// rather than promising dictation stays off.
    static let importWisprMeta = "Meetings and notes"
    static let importWisprMetaDictation = "Meetings, notes and dictation"
    /// G154 — what a tick does: one macOS prompt; it fills in people Cicada already knows and never adds a page.
    static let importContactsMeta = "Fills in people Cicada already knows"
    static let importContactsIdle = "Asks macOS once. Never a page per contact"
    /// G160 — what the sub-row reads; Chrome keeps no private window on disk, so none is ever read.
    static let importTabGroupsMeta = "Group names, colours, tab titles and links"
    static let importTabGroupsIdle = "Tick to bring them in. Never private windows"

    // MARK: F-02 (Task 4)
    static let importTitle = "Bring in what you have"
    static let importTickHelp = "Tick to bring it in now"
    static let importUntickHelp = "Untick to stop keeping up. What came in stays."
    static let importDoneOnce = "Brought in. Sync again any time in \(settings) → \(integrations)."
    static let importLockedHelp = "Reading now. A one-time read finishes on its own, and what came in stays."
    /// R-OB7 — a blocked browser's row before (and after) its tick: the tick opens the setting; the grant starts it.
    static let importNeedsAccess = "Needs Full Disk Access. Tick it to open the setting; it starts once allowed."
    static let importDropLead = "Drop an export, or"
    static let importDropDetail = "A .zip, a folder or one file, read on this Mac."
    static let importSeeHow = "See how ›"
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

    // MARK: F-04 (Task 5)
    /// R-OB12 — said on the step whose click also turns it on.
    static let agentStepAlsoRecalls = "It also turns on Remembers automatically; undo that in \(settings) → \(agents)."
    static let agentStepRecallHow = "Before your agent answers, Cicada adds a short note about who and what you mention. Undo it in \(settings) → \(agents)."
    static let agentStepStartupHow = "Cicada offers context when a new local chat starts. Saving chats is its own step. Undo it in \(settings) → \(agents)."

    // MARK: F-05 (Task 5)

    // MARK: F-06 (Task 5)

    // MARK: The frame, F-01, F-07 (Task 6)
    static let onboardingContinue = "Continue"
    static let onboardingBack = "Back"
    static let onboardingOpenCicada = "Open Cicada"
    static func onboardingStepOf(_ n: Int) -> String { "Step \(n) of \(OnboardingPage.stepCount)" }
    static func onboardingComingIn(_ k: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(k, locale: locale)) still coming in"
    }
    /// A page's opening line: the source that just finished and what came in (its count line is already localised).
    static func onboardingArrival(title: String, line: String?) -> String { line.map { "\(title) · \($0)" } ?? title }
    static let welcomeTryTheDemo = "Try the demo"
    /// R-OB2 — a drop on Welcome is held until Get started; the card says so.
    static func welcomeDropsWaiting(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        n == 1 ? "1 export is waiting. It comes in after Continue."
               : "\(UsageFormat.count(n, locale: locale)) exports are waiting. They come in after Continue."
    }
    static let readyTitle = "You’re set."
    static func readyQuoteLine(_ text: String) -> String { "“\(text)”" }
    static func readyQuoteAuthor(_ author: String) -> String { "\(author), " }
    /// A year is a name, not a count: never grouped.
    static func readyQuoteYear(_ year: Int) -> String { " (\(String(year)))" }

    // MARK: Onboarding v2 (G217, G92, ruling 36; 2026-10-22) — five steps, under 40 words each

    /// Welcome: what Cicada is, in one sentence.
    static let welcomeLine = "One memory on this Mac that every agent you use reads and adds to."
    static let onboardingSkip = "Skip"

    /// Intelligence (ruling 36 D1): a signed-in plan is pre-selected and said in words, with what will run; a key is
    /// an equal option one click away; a local model is never pitched.
    static let intelTitle = "Who reads your memory"
    /// Onboarding v3: the worm speaks, lightly, in the first person (HeyClicky's "I hear best on…").
    static let intelSubline = "I build your pages while you sleep."
    /// The plan's card names the plan once (ruling 39, 2026-10-24: "avoid repetition"). Settings → Intelligence keeps
    /// its own headline (`Copy.EngineHeadline.usingPlan`); this card stands alone, so "you're signed in" goes unsaid.
    static func intelUsing(_ plan: String) -> String { "Using your \(plan)" }
    /// D1 — "that step says in words what will run": the person's own harness, on the plan the line above names. The
    /// name is the person's own current choice (provider-neutral copy's one exception).
    static func intelRuns(_ harness: String) -> String { "Cicada runs your own \(harness)." }
    static let intelUseKey = "Use an API key"
    static let intelUsePlan = "Use my plan"
    static let intelMoreKeys = "More keys in"
    static let intelMoreKeysWhere = "\(settings) → Intelligence"
    static let intelNothing = "Nothing can read yet. Sign in to a plan or add a key."

    /// Agents.
    static let agentsTitle = "Connect your agents"
    static let agentsSubline = "They read your memory and add to it."
    /// Tester readiness (2026-10-26) — the one prerequisite, said where agents are connected: consolidation runs on the
    /// person's own Claude Code or Codex plan (or a key they add). Names the two tools as what to have, never as a
    /// choice Cicada made for them (provider-neutral copy, owner 2026-09-30).
    static let agentsNeedsPlan = "To read your conversations into memory, Cicada needs Claude Code or Codex signed in "
        + "to a paid plan, or an API key added in Settings."
    static let agentsConnect = "Connect"
    static let agentsRun = "Run these"
    static let agentsShowCommands = "Show commands"
    static let agentsDone = "Done"
    static let agentsNoneFound = "No agents found on this Mac."
    static let agentsAnother = "Another agent"
    static let agentsPersonal = "Personal agents"
    static let agentsPersonalNames = "Grok Bot, Muse, Instinct, Dots"
    /// Onboarding v3 (DR-39): *Another agent* and *Personal agents* fold under one remembered disclosure.
    static let agentsOther = "Other agents"
    static let agentsOtherSummary = "Any other agent · personal agents"
    /// The one live check (after HeyClicky's "Testing, testing, 1, 2, 3" chip): the exact words to say to the person's
    /// own agent — named only when it is theirs (provider-neutral copy), else "your agent".
    static let agentsTryLead = "Then try it:"
    static let agentsTryPrompt = "What do you remember about me?"
    static func agentsTryAsk(_ agent: String?) -> String {
        "Ask \(agent ?? "your agent"): what do you remember about me?"
    }
    static let agentsTryCopyHelp = "Copy the question"
    /// The moment the first call lands: the agent that called, by its own name.
    static func agentsFirstCall(_ agent: String) -> String { "\(agent) just called me. It works." }

    /// Sources.
    static let sourcesSubline = "Tick what I may read. I read nothing before you tick."
    static let sourcesChats = "Chat history"
    static let sourcesDropFile = "Drop a file"
    static let sourcesHowToExport = "How to get an export"
    static let sourcesOn = "On"
    static let sourcesComingIn = "Coming in"
    static let sourcesNeedsYou = "Needs you"
    static let sourcesOff = "Off"
    /// R-OB7's consent, on the tile itself: the tick shows the drag helper and the source starts once it is allowed.
    static let sourcesNeedsAccess = "Needs Full Disk Access. A tick shows you how"
    /// Onboarding v3 (DR-39): the tiles this Mac has data for lead; the accounts and Messages fold under one disclosure.
    static let sourcesMore = "More sources"

    /// Saved lists (owner 2026-10-26, ruling 39's dated line): asked once, pre-ticked; the button's answer is the
    /// consent. One plain line on how (their own agent, their own signed-in browser, the cap) and on the sites' terms.
    static let savedListsTitle = "Keep your saved lists current"
    static let savedListsSubline = "Your own agent reads these in your signed-in browser, at most 10 times a day. "
        + "These sites' terms discourage automated access, even to your own account."
    static let savedListsNoAgent = "No agent is connected yet, so nothing reads these until you connect one."
    static let savedListsKeep = "Keep them current"
    static let savedListsSaveFailed = "That didn't save. Try again, or turn the lists on later on the Sources page."
    static func savedListsItem(_ item: SavedListItem) -> String {
        switch item {
        case .youtubeWatchLater: "YouTube Watch later"
        case .youtubeHistory: "YouTube history"
        case .x: "X Bookmarks"
        case .instagram: "Instagram Saved"
        case .linkedin: "LinkedIn Saved posts"
        }
    }

    /// Home's Getting started after onboarding: what onboarding covered, as one line (`GettingStartedFold`).
    static func gsCoveredInSetup(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        n == 1 ? "1 thing already set up" : "\(UsageFormat.count(n, locale: locale)) things already set up"
    }

    /// Done: what happens next, in one line (`DoneLine`) — in the worm's voice since onboarding v3.
    static let doneLead = "Talk to your agent; I'll remember."
    static func doneScheduled(_ when: String) -> String { "I read \(when)." }
    /// The owner's words (2026-10-22): "Cicada reads tonight, and now for what you brought in".
    static func doneScheduledAndNow(_ when: String) -> String { "I read \(when), and now for what you brought in." }
    static let doneImportsNow = "I read what you brought in now."
    /// The same "now", when it runs on a key the person chose — named, never left unsaid (re-review 2026-10-22).
    static func doneImportsNowOnKey(_ provider: String) -> String { "I read what you brought in now, on your \(provider) key." }
    static func doneScheduledAndNowOnKey(_ when: String, _ provider: String) -> String {
        "I read \(when), and now, on your \(provider) key, for what you brought in."
    }
    static let doneReadNow = "Read now on Home builds your first pages."

    /// Done (onboarding v3, 2026-10-24): it ends on the person's own memory, not "You're set." The flow's one wink is
    /// the title.
    static let doneTitle = "That's it. I'll take it from here."
    static let doneAlready = "In your memory"
    static let doneReading = "Reading now"
    static let doneEmpty = "Nothing yet."
    /// A conversation that came in with no title of its own.
    static let doneUntitled = "A conversation"
    /// The count under the first few: "and 9 more".
    static func doneMore(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "and \(UsageFormat.count(n, locale: locale)) more"
    }
    /// What a revealed row is, for VoiceOver: a page, or a conversation waiting to be read.
    static let donePage = "Page"
    static let doneWaiting = "Waiting to be read"

    /// Buttons, titles and one-line captions — ≤ 60 characters (CopyConstantsTests).
    static var onboardingLabels: [String] {
        [importReading(9, of: 17, noun: "conversations"), importBrowsers, importCalendar, importCalendarAndContacts,
         importNotesAndFiles, importVoice, importNotes, importWispr, importTickToBringIn, importCalendarMeta,
         importCalendarIdle, importNotesMeta, importNotesIdle, importWisprMeta, importWisprMetaDictation,
         importContactsMeta, importContactsIdle, importTabGroupsMeta, importTabGroupsIdle, importTitle, importTickHelp, importUntickHelp, importDropLead, importDropDetail, importSeeHow,
         seeHowTitle, seeHowReplay, seeHowDone, seeHowClaudePath,
         seeHowChatGPTPath, seeHowGeminiPath, seeHowOpenPage("ChatGPT"), seeHowSteps(11), seeHowStepOf(11, 11),
         seeHowWhere(host: "takeout.google.com", path: seeHowGeminiPath), onboardingContinue, onboardingBack,
         onboardingOpenCicada, onboardingStepOf(6), onboardingComingIn(4), welcomeTryTheDemo, readyTitle, onboardingSkip, intelTitle,
         intelSubline, intelUsing("Claude plan"), intelRuns("Claude Code"), intelUseKey, intelUsePlan, intelMoreKeys, intelMoreKeysWhere, intelNothing, agentsTitle, agentsSubline,
         agentsConnect, agentsRun, agentsShowCommands, agentsDone, agentsNoneFound, agentsAnother, agentsPersonal,
         agentsPersonalNames, sourcesSubline, sourcesChats, sourcesDropFile, sourcesHowToExport, sourcesOn,
         sourcesComingIn, sourcesNeedsYou, sourcesOff, sourcesNeedsAccess, doneLead, doneScheduled("tonight at 3:00"), doneImportsNow,
         doneReadNow, gsCoveredInSetup(1), gsCoveredInSetup(4), agentsOther, agentsOtherSummary, agentsTryLead,
         agentsTryPrompt, agentsTryAsk("Claude Code"), agentsTryAsk(nil), agentsTryCopyHelp,
         agentsFirstCall("Claude Code"), sourcesMore, doneTitle, doneAlready, doneReading, doneEmpty, doneUntitled, doneMore(9),
         donePage, doneWaiting]
            + Copy.Permission.labels
            + ChatVendor.allCases.map(importWait)
    }

    /// Longer sentences — the vocabulary rule only.
    static var onboardingSentences: [String] {
        [importDoneOnce, importLockedHelp, importNeedsAccess, seeHowClaudeHonest, seeHowChatGPTHonest,
         seeHowGeminiHonest, agentStepAlsoRecalls, agentStepRecallHow, welcomeDropsWaiting(1), welcomeDropsWaiting(3), welcomeLine, doneScheduledAndNow("tonight at 3:00"), doneImportsNowOnKey("OpenAI"), doneScheduledAndNowOnKey("tonight at 3:00", "OpenAI")]
    }
}
