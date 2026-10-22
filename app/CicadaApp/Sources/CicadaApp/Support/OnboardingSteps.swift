import Foundation

// Onboarding v2 (G217, G92, ruling 36; 2026-10-22) — what each working step shows, decided purely so the views are
// renderers and the rules are tested without a window (`OnboardingStepsTests`).

// MARK: Intelligence

/// Step 2's headline (ruling 36 D1): a signed-in plan pre-selected and said in words with what runs; a chosen engine by
/// its own words; or nothing yet, which shows the plans and the keys side by side as equal options.
enum IntelligenceStepState: Equatable {
    /// Auto resolved to the person's plan: the plan's line ("Using your Claude plan — you're signed in.") and the
    /// harness Cicada runs on their limits.
    case plan(line: String, runs: String, mark: String)
    /// Something else reads (a key the person chose, a stored non-Auto choice): `EngineHeadline`'s own words.
    case chosen(title: String, line: String, mark: String)
    /// No engine can read yet.
    case nothing

    /// The keys onboarding offers (the person's likely providers, one router); every other key waits in Settings →
    /// Intelligence, one link away, so the step stays a choice rather than a catalogue.
    static let featuredKeys: Set<String> = ["byok-anthropic", "byok-openai", "byok-gemini", "byok-openrouter"]

    static func of(_ response: SleepEngineResponse?) -> IntelligenceStepState {
        guard let response else { return .nothing }
        let headline = EngineHeadline.of(response)
        if headline.needsSignIn { return .nothing }
        if headline.isAuto, let engine = response.preview?.manual.engine, ScheduleHonesty.planEngines.contains(engine) {
            return .plan(line: headline.line, runs: Copy.intelRuns(engine == "claude-cli" ? "Claude Code" : "Codex"),
                         mark: engine == "claude-cli" ? "claude" : "openai")
        }
        // A plan chosen outright (or fixed by the environment) reads the same way: it is still the person's plan.
        if ["agent", "codex"].contains(response.selected) {
            let claude = response.selected == "agent"
            let label = response.candidates.first { $0.id == response.selected }?.label ?? headline.title
            return .plan(line: Copy.EngineHeadline.usingPlan(label), runs: Copy.intelRuns(claude ? "Claude Code" : "Codex"),
                         mark: claude ? "claude" : "openai")
        }
        return .chosen(title: headline.title, line: headline.line, mark: EngineStepMark.logo(headline.mark))
    }
}

/// `EngineHeadline.mark` names an engine card; the logo set names the umbrella.
enum EngineStepMark {
    static func logo(_ card: String) -> String {
        switch card {
        case "agent": "claude"
        case "codex": "openai"
        case "openrouter": "openrouter"
        default: card
        }
    }
}

// MARK: Agents

/// What one agent's row offers, in the order Settings' own steps would (`AgentQuickSetup.actions`, `AgentSteps`).
enum AgentRowAction: Equatable {
    /// Already calling Cicada.
    case none
    /// Connect for me: the wire's commands plus Remembers automatically's (R-OB12), shown before the click that runs
    /// them (spec decision 14).
    case connect([AgentWiringStep])
    /// The Claude app: the config merge Settings' *Set up Claude* runs.
    case setUpClaude
    /// Cursor: the app's own catalog link.
    case openCursor
    /// Anything else: the setup prompt the agent carries out itself.
    case copy(String)
    /// Its setup has not arrived yet.
    case preparing
}

struct AgentStepRow: Identifiable, Equatable {
    let entry: AgentCatalogEntry
    let connected: Bool
    let action: AgentRowAction
    var id: String { entry.id }
}

enum AgentStepRows {
    /// The agents found on this machine — the backend's wiring says a harness is installed (config detection), the
    /// Claude app is on this Mac, or `/agents/live` already saw it call — in catalog order. Cloud agents and "another
    /// agent" are not rows here: the step's own two rows below the list cover them.
    static func rows(wiring: AgentWiringResponse?, live: [String: AgentLiveRow], setups: [String: AgentSetupPrompt],
                     claudeAppInstalled: Bool) -> [AgentStepRow] {
        AgentCatalog.all.compactMap { entry -> AgentStepRow? in
            let row = wiring?.agents.first { $0.id == entry.id }
            let connected = live[entry.id]?.connected == true
            switch entry.kind {
            case .remote, .anyAgent: return nil
            case .claude:
                guard claudeAppInstalled || connected else { return nil }
                return AgentStepRow(entry: entry, connected: connected, action: connected ? .none : .setUpClaude)
            case .prompt, .deeplink:
                guard row?.installed == true || connected else { return nil }
                return AgentStepRow(entry: entry, connected: connected,
                                    action: connected ? .none : action(for: entry, wiring: row, setups: setups))
            }
        }
    }

    static func action(for entry: AgentCatalogEntry, wiring: AgentWiring?,
                       setups: [String: AgentSetupPrompt]) -> AgentRowAction {
        let setup = entry.setupHarnesses.first.flatMap { setups[$0] }
        let quick = AgentQuickSetup.actions(catalogId: entry.id, setup: setup, wiring: wiring)
        for action in quick {
            if case .connectForMe(let steps) = action { return .connect(steps + AgentSteps.recallSteps(for: wiring)) }
        }
        if quick.contains(.openCursor) { return .openCursor }
        for action in quick {
            if case .copyPrompt(let text) = action { return .copy(text) }
        }
        return .preparing
    }

    /// The row's dot and word: green once Cicada saw it call; Waiting after this step connected it; Found before.
    static func status(_ row: AgentStepRow, started: Bool) -> (word: String, on: Bool) {
        if row.connected { return (Copy.Status.connected, true) }
        return (started ? Copy.Status.waiting : Copy.agentsFound, false)
    }
}

// MARK: Sources

/// One tile of step 4's grid, and what its tick does — exactly what that source's row on the Sources page does.
enum SourceTileKind: Equatable {
    /// Calendar, Contacts, a browser: the one turn-on (`FoundTurnOn`) through `SetupRunner`, as the old Import page
    /// and Home's Getting started run it; its consent is the macOS prompt the entry's own words name.
    case tick(ImportEntry)
    /// Messages and the accounts read through the person's browser: the Sources page's own detail for that entry,
    /// opened over onboarding (`SourceCatalogDetail`), so its consents and switches are the page's.
    case open(SourceCatalogEntry)
    /// A chat export: the window's one drop target, or the file panel.
    case chats
}

struct SourceTile: Identifiable, Equatable {
    let id: String
    let title: String
    let origin: String
    let kind: SourceTileKind
}

enum SourceTiles {
    /// The Sources page's entries the grid opens, in the grid's order.
    static let openIds = ["imessage", "youtube", "x", "instagram"]

    /// The popular ones: Calendar, Contacts, each supported browser on this Mac, Messages, YouTube, X, Instagram,
    /// and chat history. Apple Notes, Wispr Flow, tab groups and the rest stay one click away on the Sources page.
    static func tiles(imports: [ImportEntry]) -> [SourceTile] {
        var out: [SourceTile] = []
        let calendar = imports.first { $0.id == .app(AppSourceDrivers.calendar) }
        let contacts = imports.first { $0.id == .app(AppSourceDrivers.contacts) }
        for entry in [calendar, contacts].compactMap({ $0 }) {
            out.append(SourceTile(id: entry.id.key, title: entry.title, origin: entry.origin, kind: .tick(entry)))
        }
        for entry in imports where entry.category == .browsers && entry.parent == nil {
            out.append(SourceTile(id: entry.id.key, title: entry.title, origin: entry.origin, kind: .tick(entry)))
        }
        for id in openIds {
            guard let entry = SourceCatalog.fixed.first(where: { $0.id == id }) else { continue }
            out.append(SourceTile(id: "open:" + id, title: entry.title, origin: entry.origin, kind: .open(entry)))
        }
        out.append(SourceTile(id: "chats", title: Copy.sourcesChats, origin: "claude-export", kind: .chats))
        return out
    }

    /// A ticked source's dot and word (`SetupProgress`'s phase).
    static func status(phase: SetupRowPhase?) -> (word: String, tone: StatusWord.Tone) {
        switch phase {
        case .comingIn?: (Copy.sourcesComingIn, .on)
        case .done?: (Copy.sourcesOn, .on)
        case .needsYou?: (Copy.sourcesNeedsYou, .attention)
        case .off?, nil: (Copy.sourcesOff, .off)
        }
    }

    /// An opened source's dot and word (the Sources page's own status).
    static func status(catalog: SourceCatalogStatus) -> (word: String, tone: StatusWord.Tone) {
        switch catalog {
        case .connected: (Copy.sourcesOn, .on)
        case .needsSignIn: (Copy.sourcesNeedsYou, .attention)
        case .off: (Copy.sourcesOff, .off)
        }
    }

    /// Chat history's word: what the dropped exports are doing, else what to do.
    static func chatsStatus(phases: [SetupRowPhase]) -> (word: String, tone: StatusWord.Tone) {
        if phases.contains(.comingIn) { return (Copy.sourcesComingIn, .on) }
        if phases.contains(.needsYou) { return (Copy.sourcesNeedsYou, .attention) }
        if phases.contains(.done) { return (Copy.sourcesOn, .on) }
        return (Copy.sourcesDropFile, .off)
    }

    /// Whether a tick tile reads as ticked: running or keeping up (`ImportRows.control`).
    static func isTicked(_ entry: ImportEntry, phase: SetupRowPhase?) -> Bool {
        switch ImportRows.control(entry, phase: phase) {
        case .tick(let on): on
        case .locked, .done: true
        }
    }
}

// MARK: Done

/// Step 5's one line: "Talk to your agent; Cicada remembers." and what happens next, from real state — imports coming
/// in now, the schedule's own time, or Read now on Home. Never "tonight" on a manual schedule (`OnboardingScheduleLine`'s
/// lesson: a first run is told only what is true).
enum DoneLine {
    static func line(importsComingIn: Bool, scheduleLoaded: Bool, honesty: HonestyInputs) -> String {
        Copy.doneLead + (tail(importsComingIn: importsComingIn, scheduleLoaded: scheduleLoaded, honesty: honesty)
            .map { " " + $0 } ?? "")
    }

    static func tail(importsComingIn: Bool, scheduleLoaded: Bool, honesty: HonestyInputs) -> String? {
        if importsComingIn { return Copy.doneImportsNow }
        guard scheduleLoaded else { return nil }
        if ScheduleHonesty.scheduledCanRead(honesty), let when = ScheduleHonesty.whenPhrase(honesty.schedule) {
            return Copy.doneScheduled(when)
        }
        return Copy.doneReadNow
    }
}
