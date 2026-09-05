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
    /// The study list's pointer to where the schedule itself is edited —
    /// built from `settingsSleep` so a rename can't desync the two halves.
    static let changeInSettingsSleep = "Change in \(settingsSleep)"

    // MARK: Shared action verbs
    //
    // One verb per action, app-wide. The Sleep page used to say "Run now" /
    // "Running…" while the queue card said "Consolidate now" / "Sleeping…"
    // for the identical POST.

    static let consolidateNow = "Consolidate now"
    static let consolidating = "Consolidating…"

    /// The Feed page's "+" / ⌘N affordance for opening the add-source sheet
    /// (G68 §1 — Capture merged into Feed).
    static let addASource = "Add a source"

    // MARK: Sleep engine (G74(a))

    /// The engine id the backend reports, in the user's words.
    static func engineLabel(_ id: String) -> String {
        switch id {
        case "claude-cli": "Claude Code (your plan)"
        case "ollama": "Ollama (on this Mac)"
        case "litellm": "API key"
        default: id
        }
    }

    static let sleepEngineTitle = "Use for Sleep"

    /// The three honest things about running Sleep on a subscription: what it
    /// spends, who starts it, and what a throttle does. Not "free" — plan
    /// quota is a real budget, just not a dollar one.
    static let sleepEngineExplainer =
        "Sleep runs through the `claude` CLI on your plan: it spends plan quota, not money. "
        + "Only when you start a cycle yourself — never on the nightly schedule — and if the "
        + "plan throttles it stops cleanly with the queue intact."

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

    /// Pause/resume the nightly auto-run schedule — the third quick control
    /// on the Sleep page (alongside run + cancel). The full time editor
    /// lives in Settings → Schedule (`settingsSchedule`); this only flips
    /// `enabled`.
    static let pauseAutoRun = "Pause auto-run"
    static let resumeAutoRun = "Resume auto-run"

    // MARK: Observer

    /// The user's own observer label. Never the account holder's first name —
    /// the app is single-user, and "You" reads correctly for anyone.
    static let you = "You"

    // MARK: Page subtitles

    static let clustersSubtitle = "Every entity, grouped by type."
    static let feedSubtitle = "Everything Cicada has read, newest first."
    static let sleepSubtitle = "Fold today's episodes into the graph."
    static let inboxSubtitle = "Questions waiting on you."
    static let agentsSubtitle = "Wire any MCP agent into this Mac's memory."
    static let plansAndKeysSubtitle = "What Cicada bills against, and how it signs in."
    static let sourcesSubtitle = "Where your memory comes from, and who wrote it."
    /// Rewritten off "Schedule" (which said "Sleep" freely) — the title
    /// above this is now literally "Sleep", and `CopyConstantsTests`'s
    /// `testSubtitlesAreShortAndDoNotRepeatTheirTitle` bans a subtitle that
    /// repeats its own title.
    static let sleepSettingsSubtitle = "Who runs the nightly cycle, and when."
    static let generalSubtitle = "Appearance and text size."
    static let integrationsSubtitle = "Every app connected to Cicada, in one place."

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

    // MARK: - First-run sheet (G117)

    /// Step 2's caption above the embedded `IntegrationsView` — R4's
    /// justification made visible: the whole Integrations page is shown, not
    /// a hand-picked subset, and this line is what tells the reader they
    /// only need to pick ONE row here, not connect everything before moving
    /// on.
    static let onboardingChannelCaption =
        "Connect one thing to get started — add the rest anytime in Settings → Integrations."

    /// One title per `OnboardingStep`, shown in the sheet's header.
    static func onboardingStepTitle(_ step: OnboardingStep) -> String {
        switch step {
        case .identity: return "Who's using Cicada?"
        case .engine: return "Choose a Sleep engine"
        case .channel: return "Connect a source"
        case .sleep: return "Run your first Sleep cycle"
        }
    }
}
