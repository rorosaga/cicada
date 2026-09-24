import Foundation

/// Every string that points the reader at another part of the app, plus the
/// page subtitles and the shared action verbs (G68 §2.8).
///
/// Two rules, enforced by `CopyConstantsTests`:
///  1. A cross-page pointer names its destination exactly as the sidebar or
///     the Settings tab spells it, so what the user reads is what they can
///     look for.
///  2. A page subtitle is one sentence, ≤ 60 characters, never a repeat of
///     the title above it, and never says "page".
enum Copy {

    // MARK: Destinations

    static let settings = "Settings"
    /// The Settings scene's first tab (G130 R8) — appearance and text size.
    /// Named after what macOS itself calls this kind of page, not "Display"
    /// or "Appearance", since it holds both the dark/light toggle and the
    /// zoom slider, and Track C's future sidebar redesign turns this same
    /// tab into its General section rather than renaming it again.
    static let general = "General"
    static let plansAndKeys = "Plans & keys"
    static let agents = "Agents"
    static let feed = "Feed"
    static let sources = "Sources"
    /// The Settings sidebar's Sleep section (Track C: the four-tab `TabView`
    /// became a five-section `NavigationSplitView`). Named "Sleep", matching
    /// the main sidebar's own row — the old "Schedule" name predates the
    /// section holding the schedule editor AND the G122 engine picker, and
    /// "Schedule" undersold the latter.
    static let sleepSettings = "Sleep"
    /// The Settings sidebar's Integrations section (G126) — every connected
    /// app in one categorized, logo-first page over the existing channel
    /// registry.
    static let integrations = "Integrations"

    /// The canonical way to send someone to the connections settings. Built
    /// from the parts above so a rename can never desync the two halves.
    static let settingsPlansAndKeys = "\(settings) → \(plansAndKeys)"
    /// Ditto, for the Sleep section.
    static let settingsSleep = "\(settings) → \(sleepSettings)"
    /// Ditto, for the General tab (G130).
    static let settingsGeneral = "\(settings) → \(general)"
    /// Ditto, for the Integrations section (G126).
    static let settingsIntegrations = "\(settings) → \(integrations)"

    /// The study list's footer line (G125) when `ScheduleConfig.mode` is
    /// `"manual"` — there is no next run to name, only the button.
    static let nextRunManual = "Manual only"
    /// The long-form pointer to where the schedule itself is edited — built
    /// from `settingsSleep` so a rename can't desync the two halves. Kept for
    /// any surface that names the destination with no context around it; the
    /// queue card's schedule row uses `changeEllipsis` instead, because the
    /// sentence beside it already says what is being changed.
    static let changeInSettingsSleep = "Change in \(settingsSleep)"

    /// The queue card's schedule ROW says the destination in its own words
    /// already ("Every 6 h" sits right beside it and the link opens Settings →
    /// Sleep), so the affordance next to it is the verb alone — the long form
    /// above stays for the callers that have no such context.
    static let changeEllipsis = "Change…"

    /// The worm's accessibility hint (Track Z §11) — both clauses now that
    /// feeding shipped (Z9; Z-P16 held the second back until it was true).
    static let wormHint = "Click to ask what it's doing. Drop a file to import it."
    /// Z9 (I16) — the worm's named action and context-menu item: the intake's
    /// own picker, for anyone without a file to drag.
    static let feedAFile = "Feed a file…"
    /// The worm's named action and context-menu item: every answer at once.
    static let wormWhatAreYouDoing = "What are you doing?"
    /// Track Z §6.5 / §11 — the cheer's text twin, announced when a real
    /// completion's commit arrives (never on a cancel or a failure, I18).
    static let sleepFinished = "Sleep finished."
    /// The worm's named action while T7's "See what changed ›" link lives.
    static let whatChanged = "What changed"

    /// The queue card's footer line, shown ONLY when `preview.manual` and
    /// `preview.scheduled` name different engines (R-A9). The standing ruling
    /// — a scheduled cycle never spends plan quota — makes that difference
    /// real on a plan-backed bank, and this is where it is *shown* rather than
    /// silently applied. It names the scheduled engine only: which engine THIS
    /// click would use is the engine menu beside Consolidate
    /// (R-HS8), and repeating both here would put the same fact on
    /// the page twice.
    static func scheduledRunsOn(engine: String) -> String {
        "Scheduled runs use \(engineLabel(engine))"
    }

    // Track Z §7 — the room's props as controls (the lamp's popover, a
    // spine's popover). Plain words: the lamp is the schedule, and lighting
    // it is the one thing the toggle does.
    static let whenIRead = "When I read"
    static let lampOn = "The lamp is on."
    static let lampOff = "The lamp is off."
    static let lampOffExplainer = "I read only when you press Consolidate now."
    static let lampHint = "Opens the schedule"
    static let readOnSchedule = "Read on a schedule"
    static let rhythmAndTime = "Rhythm and time:"
    static let scheduleWriteFailed = "Couldn't change the schedule — nothing changed."
    static let openInSources = "Open in Sources ›"
    static func moreInDetails(_ n: Int) -> String { "+\(UsageFormat.count(n)) more in Details" }
    /// The lamp popover's line while the lamp is off (§7.2): what a scheduled
    /// run WOULD use, shown before the person lights it (ruling 4 at the
    /// moment of choice).
    static func scheduledRunsWouldUse(engine: String) -> String {
        "If you light it, scheduled runs would use \(engineLabel(engine))"
    }
    // Track Z §7.3 — the window's weather and its legend (the text twin).
    static let windowLegendHeader = "The window shows how Sleep is doing, not the time of day."
    static let windowLegendPointer = "The window in the room shows how Sleep is doing — click it to see what each sky means."
    static let windowHint = "Shows what the sky means"
    // MARK: The `?` popover (Track P)
    //
    // Shown on Graph, Clusters and Feed, so every sentence has to be true on
    // all three — and on a DEFAULT install, which is where the old "About
    // these actions" copy went wrong twice over. One paragraph per half of
    // the Awake/Sleep split. Both interpolate pointers declared LATER in the
    // file (`settingsIntegrations`, `settingsSleep` above it): `Copy` is an
    // `enum` of lazily-initialised `static let` globals, so declaration order
    // does not constrain them.

    /// Awake. Capture is the harness's own Stop hook (G105 — not a model
    /// choosing to call a tool, and not a property of any one MCP client),
    /// so the sentence names the harnesses rather than the client.
    static let aboutCicadaCapture =
        "Every Claude Code and Codex session is saved as it ends, by the harness's own hook — no button, no tool call. "
        + "Bookmarks, feeds, calendars and chat exports arrive through \(settingsIntegrations) and the Feed's + button."

    /// Sleep. Nothing consolidates until a schedule is chosen
    /// (`sleep_scheduler._DEFAULT` is `manual`), so the popover says so and
    /// points at the one place a schedule is set. The last clause is
    /// TODO.md ruling 4 — a scheduled cycle passes `user_triggered=False`
    /// and never spends plan quota — stated rather than hidden.
    static let aboutCicadaSleep =
        "Consolidation is not automatic. Sleep runs when you press Consolidate on the Sleep page, or on the schedule you pick in \(settingsSleep) — nightly, every few hours, or after an import. "
        + "A scheduled cycle never spends your plan quota."

    // MARK: Shared action verbs
    //
    // One verb per action, app-wide. The Sleep page used to say "Run now" /
    // "Running…" while the queue card said "Consolidate now" / "Sleeping…"
    // for the identical POST.

    static let consolidateNow = "Consolidate now"
    static let consolidating = "Consolidating…"

    // MARK: The Sleep hero (G125 v3, R-A4…R-A7)

    /// The noun under the hero's promoted numeral. Pluralised, like every
    /// other count in this file (`clusterCount`, `bracketTail`) — the hero
    /// draws it only when the count is at least 1, and "1 episodes waiting"
    /// is the kind of small wrongness that makes a page look generated.
    static func episodesWaiting(_ count: Int) -> String {
        count == 1 ? "episode waiting" : "episodes waiting"
    }

    /// The hero tiles' nouns (R-A6). Each takes its own count so the singular
    /// is right, and an unknown (`nil`) keeps the plural — the tile shows `—`
    /// beside it, so "— entities in memory" reads correctly and "— entity in
    /// memory" would not.
    static func entitiesInMemory(_ count: Int?) -> String {
        count == 1 ? "entity in memory" : "entities in memory"
    }

    static func sourcesFeeding(_ count: Int?) -> String {
        count == 1 ? "source feeding it" : "sources feeding it"
    }

    /// What `Rested n%` is made of, on hover over the meter's label
    /// (round-2 live check). The backend combines two ratios into one
    /// percentage — how full the queue is by volume, and how far its oldest
    /// unread episode has aged — and this is the only place either is spelled
    /// out now that the duplicate line under the stage strip is gone: the
    /// hero's meter already draws `Rested n%`, and drawing the same number
    /// again two rows below it was the R-A5 violation the live check found.
    /// Both percentages name their noun, as everything on this page must.
    static func restedBreakdown(volumePct: Int, agePct: Int) -> String {
        "Volume \(volumePct)% · age \(agePct)% of the way to a full backlog"
    }

    static let lastCycle = "Last cycle"

    /// R-A14/P18 — every `—` on this page carries a hover reason naming why
    /// the number is unknowable. A cycle's duration is joined from the
    /// `sleep_run` telemetry ledger by commit hash; with telemetry off (or a
    /// cycle older than the ledger) there is no row to join, and G107's
    /// ruling forbids showing a guess in its place.
    static let noTimingRecorded = "No timing was recorded for that cycle."
    static let bankListNotLoaded = "The bank list hasn't loaded yet."
    static let sourceOverviewNotLoaded = "The source overview hasn't loaded yet."

    /// The Feed page's "+" / ⌘N affordance for opening the add-source sheet
    /// (G68 §1 — Capture merged into Feed).
    static let addASource = "Add a source"

    // MARK: Sleep engine (G74(a))

    /// The engine id the backend reports, in the user's words.
    static func engineLabel(_ id: String) -> String {
        switch id {
        case "claude-cli": "Claude Code (your plan)"
        case "codex-cli": "Codex (your ChatGPT plan)"
        case "ollama": "Ollama (on this Mac)"
        case "litellm": "API key"
        default: id
        }
    }

    /// The three honest things about running Sleep on a subscription: what it
    /// spends, who starts it, and what a throttle does. Not "free" — plan
    /// quota is a real budget, just not a dollar one.
    static let sleepEngineExplainer =
        "Sleep runs through the `claude` CLI on your plan: it spends plan quota, not money. "
        + "Only when you start a cycle yourself — never on the nightly schedule — and if the "
        + "plan throttles it stops cleanly with the queue intact."

    // MARK: Engines (Track E — R-E4, R-E13, R-E24, R-E28)

    static let signInWithChatGPT = "Sign in with ChatGPT"
    static let signOut = "Sign out"
    static let tryAgain = "Try again"
    static let copyCode = "Copy"
    static let copied = "Copied"
    static let openSignInPage = "Open the sign-in page"
    static let deviceCodeStarting = "Getting a sign-in code from ChatGPT…"
    static let deviceCodeRawFallback = "No code yet — here's what ChatGPT's sign-in said so far:"
    static let deviceCodeInstructions = "Enter this code on the ChatGPT page that just opened:"
    static let deviceCodeWaiting = "Waiting for you to finish signing in…"
    static let deviceCodeDone = "Signed in."
    static let deviceCodeFailed = "Sign-in didn't finish."
    /// The one owner-side switch the device-code flow can need (R2 §3.1: it
    /// must be enabled in the ChatGPT account's security settings).
    static let deviceCodeFailedHint =
        "If ChatGPT says code sign-in is turned off, turn on device code sign-in in your "
        + "ChatGPT account's security settings, then try again."
    static let chatgptSignOutTitle = "Sign out of ChatGPT in Cicada?"
    static let chatgptSignOutExplainer =
        "Cicada's ChatGPT sign-in is its own. Codex in your terminal stays signed in."
    static let keepGoingOnExtraUsage = "Keep going on extra usage"
    static let keepGoingOnExtraUsageExplainer =
        "Off: when your Claude plan's included usage runs out, Sleep stops and waits. "
        + "On: Sleep keeps going on extra usage, which Anthropic bills separately."
    static let scheduledNeverSpendsPlans =
        "Scheduled cycles never use your Claude or ChatGPT plan — only a cycle you start yourself does."

    // MARK: Sleep control (cancel + episode cap)

    static let cancelSleep = "Cancel"
    static let cancellingSleep = "Cancelling…"

    /// What tapping Cancel actually does — cooperative, not instant, nothing
    /// lost. Shown as both a caption on the Sleep page and the cancel
    /// button's tooltip.
    ///
    /// Review fix L4: the backend's structural tail (logo warm-up, connector
    /// poll, question refresh) still runs after a cancel is acknowledged —
    /// correct (spec: it runs on every exit path, cancel included, no
    /// regressions) but means "Cancelling…" can outlast the cycle itself by
    /// a few seconds. Said plainly rather than left for the user to wonder
    /// why the button didn't clear the instant the cycle stopped.
    static let cancelSleepExplainer =
        "Stops at the next safe point — never mid-write. Nothing is lost: any "
        + "episodes not yet consolidated stay queued for the next cycle. A few "
        + "housekeeping checks (logos, connectors) can still run right after, "
        + "so \"Cancelling…\" may stay up a few seconds longer than expected."

    /// The control row's one-line caption while a cycle runs (Track Z §4.1
    /// sketch B); the long explainer stays the button's tooltip.
    static let cancelCaption = "Stops at the next safe point — nothing is lost."
    /// The whisper line's hover reason when the next run is "—" (R-A14: a dash
    /// is a value with a reason).
    static let nextRunUnknownReason = "Cicada hasn't worked out the next run yet."

    /// Pause/resume the nightly auto-run schedule — the third quick control
    /// on the Sleep page (alongside run + cancel). The full time editor
    /// lives in Settings → Schedule (`settingsSchedule`); this only flips
    /// `enabled`.
    static let pauseAutoRun = "Pause auto-run"
    static let resumeAutoRun = "Resume auto-run"

    // MARK: Liveness (G125 v3 Task 8 — spec R-A12)

    /// Why a page is desaturated one step: the backend stopped answering, and
    /// what is on screen is the last thing it said. Deliberately not an
    /// error — the Store's whole promise is that a view never blanks, and a
    /// disconnect is a fact about the connection, not a failure of the cycle.
    static let notConnectedExplainer = "Not connected — showing the last reading."

    /// The chip that dates a desaturated page. 24-hour, zero-padded, because
    /// it sits inline next to a title and `4:12 PM` is three glyphs wider for
    /// no added meaning. `timeZone` is injectable for the same reason
    /// `SleepHistoryPresentation.timeText` opened that seam: so the assertion
    /// never depends on the test runner's locale.
    static func asOf(_ date: Date, timeZone: TimeZone = .current) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        f.timeZone = timeZone
        f.locale = Locale(identifier: "en_US_POSIX")
        return "as of \(f.string(from: date))"
    }

    // MARK: Observer

    /// The user's own observer label. Never the account holder's first name —
    /// the app is single-user, and "You" reads correctly for anyone.
    static let you = "You"

    // MARK: Page subtitles

    static let clustersSubtitle = "Every entity, grouped by type."
    static let feedSubtitle = "Everything Cicada has read, newest first."
    /// G125 v3 Task 8: "today's episodes" was the one false string on the
    /// page. The queue's oldest item is months old on a real bank — the
    /// queue card's own `oldest <n>d` line says so two cards down — so a subtitle
    /// promising *today* contradicted a number the same screen was drawing.
    /// What a cycle actually does is fold whatever is waiting, however old.
    static let sleepSubtitle = "Fold what's waiting into the graph."
    /// The Sleep page's title, drawn by `PageTitle` like every page's (Z-B4).
    static let sleepPageTitle = "Sleep Cycle"
    /// The Sleep page's one disclosure (Track Z R-Z6): everything past the
    /// room, the sentence, the button and the whisper line lives behind it.
    static let sleepDetails = "Details"
    static let inboxSubtitle = "Questions waiting on you."
    static let agentsSubtitle = "Wire any MCP agent into this Mac's memory."
    static let plansAndKeysSubtitle = "What Cicada bills against, and how it signs in."
    static let sourcesSubtitle = "Where your memory comes from, and who wrote it."
    /// Rewritten off "Schedule" (which said "Sleep" freely) — the title
    /// above this is now literally "Sleep", and `CopyConstantsTests`'s
    /// `testSubtitlesAreShortAndDoNotRepeatTheirTitle` bans a subtitle that
    /// repeats its own title.
    /// G139 (A3): the engine moved to Settings → Engines, so "Who runs…"
    /// stopped being true of this section.
    static let sleepSettingsSubtitle = "When Cicada consolidates what it captured."
    static let generalSubtitle = "Appearance, text size and setup."
    static let integrationsSubtitle = "Every app connected to Cicada, in one place."

    // MARK: Remote connector (G135) — pinned by RemoteConnectorTests
    static let onThisMac = "On this Mac"
    static let fromAnywhere = "From anywhere"
    static let remoteSwitchTitle = "Let AI apps outside this Mac use your memory."
    static let remoteSwitchDetail = "Works while this Mac is awake and online. Everything still lives here."
    static let remoteNeverOpensTunnel = "Cicada never opens a tunnel on its own."
    static let remoteShownOnce = "You won't see this again. Revoke any time."
    static let remoteMachineNameWarning = "Turning on HTTPS in Tailscale writes this Mac's name into a public certificate log. Rename your Mac first if its name is personal."
    static let remoteGeminiApp = "Using the Gemini app? It can't connect to outside memory yet. Use Gemini CLI, or bring your Gemini history in from the Feed."

    // MARK: Pointers

    static let noConnections = "No connections yet — add one in \(settingsPlansAndKeys)."

    // MARK: Derived

    /// The Clusters list count. It counts entities and the type groups they
    /// fall into — the page never detected a "cluster" and must not say it did.
    static func clusterCount(entities: Int, groups: Int) -> String {
        "\(entities) \(entities == 1 ? "entity" : "entities") in \(groups) \(groups == 1 ? "group" : "groups")"
    }

    // MARK: - Export step paths (G71 §4.2)

    /// One breadcrumb line per export platform: exactly the clicks, in the
    /// vendor's own words, so the user never has to guess which of five
    /// "Download your data" screens is the right one. `>` is the separator
    /// because that is how the spec writes it and how the vendors' own
    /// breadcrumbs read.
    static let instagramStepPath =
        "Settings > Accounts Center > Your information and permissions > "
        + "Download your information > Download or transfer > "
        + "Some of your information > Saved > JSON"

    static let takeoutStepPath =
        "Google Takeout > Deselect all > YouTube and YouTube Music > "
        + "All YouTube data included > playlists + history > Next step > Create export"

    static let tiktokStepPath =
        "Profile > Menu > Settings and privacy > Account > Download your data > "
        + "File format: JSON > Request data"

    static let linkedinStepPath =
        "Settings & Privacy > Data privacy > Get a copy of your data > "
        + "Want something in particular > Saved items > Request archive"

    static let redditExportStepPath =
        "Settings > Privacy > Request a copy of your data > Full date range > Request data"

    static let claudeStepPath =
        "Settings > Privacy > Export data > check your email > download the .zip"

    static let chatgptStepPath =
        "Settings > Data controls > Export data > Export > "
        + "check your email > download the .zip"

    static func exportStepPath(_ vendor: WalkthroughVendor) -> String {
        switch vendor {
        case .claude: return claudeStepPath
        case .chatgpt: return chatgptStepPath
        case .takeout: return takeoutStepPath
        case .instagram: return instagramStepPath
        case .tiktok: return tiktokStepPath
        case .linkedin: return linkedinStepPath
        case .redditExport: return redditExportStepPath
        case .gemini: return geminiStepPath
        }
    }

    // MARK: - Connectors (G71 §2)

    /// Shown after the browser is handed the consent URL — the callback lands
    /// back on the local backend, so there is nothing to paste back.
    static let connectorAuthorizeHint =
        "Approve it in the browser tab, then come back — Cicada finishes on its own."

    /// Why a Connect-route tile still offers an export walkthrough.
    static let connectorExportBackfill =
        "The API only reaches your most recent ~1,000 saves. A one-off data "
        + "export backfills everything older."

    // MARK: - Empty states (G117) — `EmptyStateView`'s honest one-sentence copy

    /// Graph's own blank canvas — the G117 row's opening evidence — finally
    /// says why it's empty and names the one thing to do about it.
    static let emptyGraphMessage = "Nothing here yet. Connect a source or import."
    static let emptyInboxMessage = "Questions appear here after a Sleep cycle."
    static let emptyFeedMessage = "Save a link or add a source to get started."
    static let emptySourcesMessage = "Nothing has fed this memory yet."

    /// Settings → Integrations with BOTH domains loaded and both empty —
    /// which on a working install means the backend is not answering, since
    /// `channel_registry` always yields thirteen rows. Never shown while a
    /// fetch is in flight or an error is latched (`IntegrationsView.
    /// loadState`), so it can only ever mean "confirmed nothing".
    static let integrationsEmpty = "No integrations found — is the Cicada backend running?"
}
