import Foundation

/// One row of the Getting started card: a connection the person turned on at
/// the Welcome (or later), or an export dropped this session.
struct GettingStartedRow: Equatable, Identifiable {
    let id: FoundItemID
    let title: String
    let detail: String
    let state: FoundRowState
    /// The one thing left to do lives in Settings (Claude Desktop, an app) —
    /// the row shows a link instead of a button (`FoundRow.settingsLink`).
    var settingsLink: SettingsSection? = nil
}

/// Everything the card's rows depend on, gathered by the view so the rules
/// below stay pure (GettingStartedProgressTests).
struct GettingStartedInputs {
    var record: GettingStartedRecord
    var items: [FoundItem] = []
    var runnerRows: [FoundItemID: FoundRowState] = [:]
    var runnerDetail: [FoundItemID: String] = [:]
    var titles: [FoundItemID: String] = [:]
    var browserOn: Set<String> = []
    /// `/agents/wiring` answered at least once — an agent missing from a real
    /// answer is gone, one missing because nothing answered is waiting.
    var wiringLoaded = false
    /// R-OB9 — the app-side sources that are on now (`AppSourceDriver.isOn`), and every one that has a driver. A
    /// known source that is not on reads Off; an unknown one still finishes in Integrations.
    var appsOn: Set<String> = []
    var appsKnown: Set<String> = []
}

/// Track I part b (design §4.2, R-IB18) — the card's rows: this session's
/// runner state first, else what the machine says now (never a remembered
/// "on" that is no longer true). After a relaunch the runner is empty, so a
/// row's state is re-derived from `LocalInventory` and the browser watch — a
/// hook someone removed by hand reads as off, not as a stale tick.
enum GettingStartedProgress {
    /// A row whose item the probe no longer lists (an agent uninstalled, a
    /// browser absent) still needs a name; these are the names the Welcome used.
    /// Round 4 (C9): every supported browser's name comes from `BrowserInventory.catalog`.
    static let fallbackTitles: [String: String] = ["agent:claude-code": "Claude Code", "agent:codex": "Codex",
                                                   "agent:cursor": "Cursor", "agent:claude-desktop": "Claude"]
        .merging(Dictionary(uniqueKeysWithValues: BrowserInventory.catalog.compactMap { spec in
            spec.bookmarksChannel.map { ("browser:\($0)", spec.name) }
        })) { first, _ in first }
        // R-OB9 — the app-side sources onboarding can start (`AppSourceDrivers`).
        .merging(["app:calendar-local": "Calendar", "app:notes": "Apple Notes", "app:wispr-flow": "Wispr Flow"]) { first, _ in first }

    static func rows(_ i: GettingStartedInputs) -> [GettingStartedRow] {
        // A dropped export lives only in this session's runner (R-IB17), after
        // the recorded rows, in a stable order so the card never reshuffles.
        let dropped = i.runnerRows.keys.filter { if case .dropped = $0 { return true }; return false }
            .sorted { $0.key < $1.key }
        return (i.record.enabled + dropped).map { id in
            let item = i.items.first { $0.id == id }
            let derived = derivedState(id, item: item, i)
            // R-IB18: ✕ settles a row even over this session's runner state, or a
            // row that failed a minute ago could never let the card finish.
            let runner = i.record.settled.contains(id) ? nil : i.runnerRows[id]
            let state = runner ?? derived.state
            return GettingStartedRow(id: id, title: item?.title ?? i.titles[id] ?? fallbackTitles[id.key] ?? id.key,
                                     detail: i.runnerDetail[id] ?? detail(id, state: state),
                                     state: state, settingsLink: runner == nil ? derived.link : nil)
        }
    }

    /// What the machine says about a row when this session has nothing newer.
    /// Claude Desktop is On only when its config names Cicada; Cursor owns its
    /// own config, so its opened confirm (a settle) is all Cicada can know.
    static func derivedState(_ id: FoundItemID, item: FoundItem?,
                             _ i: GettingStartedInputs) -> (state: FoundRowState, link: SettingsSection?) {
        if i.record.settled.contains(id) { return (.on, nil) }
        switch id {
        case .agent("claude-desktop"):
            return item?.readiness == .alreadyOn ? (.on, nil) : (.needsAction(Copy.foundClaudeDesktopDetail), .agents)
        case .agent("cursor"):
            return (.off, nil)
        case .agent:
            guard let item else { return i.wiringLoaded ? (.failed(Copy.gsAgentGone), nil) : (.working(Copy.foundBackendDown), nil) }
            switch item.readiness {
            case .alreadyOn: return (.on, nil)
            case .failed(let why): return (.failed(why), nil)
            default: return (.off, nil)
            }
        case .browser(let channel):
            if i.browserOn.contains(channel) { return (.on, nil) }
            return item?.readiness == .needsPermission ? (.needsAction(Copy.foundAllow), nil) : (.off, nil)
        case .dropped:
            return (.on, nil)
        case .app(let app):
            // R-OB9 — a registered source says its real state; anything else still finishes in Integrations.
            if i.appsOn.contains(app) { return (.on, nil) }
            if i.appsKnown.contains(app) { return (.off, nil) }
            return (.needsAction(Copy.gsFinishInIntegrations), .integrations)
        }
    }

    static func detail(_ id: FoundItemID, state: FoundRowState) -> String {
        switch id {
        case .agent("cursor"): Copy.foundCursorDetail
        case .agent("claude-desktop"): Copy.foundClaudeDesktopDetail
        case .agent: state == .on ? Copy.gsAgentOn : Copy.foundAgentDetail
        case .browser: Copy.foundBrowserDetail
        case .dropped, .app: ""
        }
    }

    /// Present, not turned on, not already on — offered with Turn on (design §4.2 "Also found").
    static func alsoFound(_ i: GettingStartedInputs) -> [FoundItem] {
        let enabled = Set(i.record.enabled)
        return i.items.filter { !enabled.contains($0.id) && $0.readiness != .alreadyOn && !i.record.settled.contains($0.id) }
    }

    /// R-IB18: done is every row On (or settled), a first read that happened,
    /// and a schedule answer — the three things the card exists to see through.
    ///
    /// An EMPTY checklist is not "every row On" while Also found still offers
    /// something: *Show setup checklist* records no rows, and on an established
    /// bank the vacuous `allSatisfy` made the card say only "You're set up." and
    /// hide itself — never listing what was found, the one thing that button is
    /// for (R-IB17; I-b final review, finding 4).
    ///
    /// And an empty Also found is an answer only once the inventory has given
    /// one (`inventoryLoaded`, `LocalInventory.hasChecked`). Before its first
    /// scan lands, `items` is `[]`, so Also found is empty too; the card's
    /// `onChange(initial:)` read that first render as done and persisted the
    /// hide, undoing the button a second before the scan said otherwise. Unknown
    /// is never empty — the default is "not loaded" (I-b final re-review,
    /// finding 4).
    static func isDone(rows: [GettingStartedRow], hasRunBefore: Bool, scheduleAnswered: Bool,
                       alsoFoundIsEmpty: Bool = true, inventoryLoaded: Bool = false) -> Bool {
        guard !rows.isEmpty || (inventoryLoaded && alsoFoundIsEmpty) else { return false }
        return rows.allSatisfy { $0.state == .on } && hasRunBefore && scheduleAnswered
    }

    /// R-IB17: only a bank the Welcome ran on (or *Show setup checklist*
    /// recorded) has a card; an install onboarded before this track never sees one.
    static func visible(record: GettingStartedRecord?) -> Bool {
        guard let record else { return false }
        return !record.hidden
    }
}

/// The status facts the first read's row is drawn from, flattened so the table
/// test can build any of them without a `SleepStatusResponse`.
struct FirstReadInputs: Equatable {
    var running = false
    /// The wire's `stage` counts COMPLETED stages (R-Z14); `of` turns it into
    /// the active one through `activeStage(completed:)`, as every surface does.
    var stage = 0
    var error: String? = nil
    var unprocessed: Int? = nil
    var read = 0
    var total = 0
    var episodesTotal = 0
    var episodesQueued = 0
    var hasRunBefore = false
    var pages: Int? = nil
}

enum FirstReadAction: Equatable { case readNow, watchSleep, openGraph, readNext(Int), tryAgain }

/// Track I part b (design §4.2 "the first read: the payoff", R-IB19) — one total
/// function over the status: each state has one line (the text twin), one worm
/// and at most one action. Never a duration (G107); a meter only with its noun.
enum FirstReadStep: Equatable {
    case nothingYet
    case waiting(Int)
    case running(read: Int, total: Int, stage: Int)
    case finished(pages: Int?)
    case capped(read: Int, left: Int)
    case failed(String)

    static func of(_ i: FirstReadInputs) -> FirstReadStep {
        if i.running { return .running(read: i.read, total: i.total, stage: activeStage(completed: i.stage)) }
        if let e = i.error?.trimmingCharacters(in: .whitespacesAndNewlines), !e.isEmpty { return .failed(firstSentence(e)) }
        if i.hasRunBefore {
            // The cycle hit its episode cap: more was queued than it took.
            if i.episodesQueued > i.episodesTotal, let left = i.unprocessed, left > 0 {
                return .capped(read: i.episodesTotal, left: left)
            }
            return .finished(pages: i.pages)
        }
        // Unknown is never a number: a missing count reads as "nothing yet".
        guard let n = i.unprocessed, n > 0 else { return .nothingYet }
        return .waiting(n)
    }

    /// A failure's first sentence only — the row is one line, and the rest of
    /// the server's message is on the Sleep page.
    static func firstSentence(_ s: String) -> String {
        guard let r = s.range(of: ". ") else { return s }
        return String(s[..<r.lowerBound]) + "."
    }

    var worm: BookwormState {
        switch self {
        case .nothingYet: .awake
        case .waiting: .reading
        case .running(_, _, let stage): .sleeping(stage: stage)
        case .finished, .capped: .happy
        case .failed: .error
        }
    }

    var action: FirstReadAction? {
        switch self {
        case .nothingYet: nil
        case .waiting: .readNow
        case .running: .watchSleep
        case .finished: .openGraph
        case .capped(let read, _): .readNext(read)
        case .failed: .tryAgain
        }
    }

    func line(locale: Locale = .autoupdatingCurrent) -> String {
        switch self {
        case .nothingYet: Copy.gsNothingYet
        case .waiting(let n): Copy.gsWaiting(n, locale: locale)
        // Past Stage 1 there is no per-item count (the wire's by-origin maps
        // empty out): say "reading", never "Read 0 of 0".
        case .running(let read, let total, _): total > 0 ? Copy.gsRunning(read: read, total: total, locale: locale) : Copy.gsReading
        case .finished(let pages): pages.map { Copy.gsFinished(pages: $0, locale: locale) } ?? Copy.gsFinishedNoCount
        case .capped(let read, let left): Copy.gsCapped(read: read, left: left, locale: locale)
        case .failed(let why): why
        }
    }
}

/// R-IB20 — the schedule question, asked only of a person still on `manual`;
/// every answer writes exactly what it says, keeping everything else. A mode
/// set in Settings is already an answer, so an `interval` is never downgraded
/// (Track P R4).
enum ScheduleChoice {
    static func asks(_ schedule: ScheduleConfig) -> Bool { schedule.mode == ScheduleMode.manual.rawValue }

    static func config(for mode: ScheduleMode, current: ScheduleConfig) -> ScheduleConfig {
        var next = current
        next.mode = mode.rawValue
        if mode == .daily { next.hour = 3; next.minute = 0 }
        return next
    }
}

/// Round 4 (T-Sources, decision 3; the plan's coordination note: T-Home owns the card) — a Getting started row as a `SourceRow`: a
/// browser row says when it last synced and can be stopped while it runs; every other row keeps its own words and
/// state. Pure, so the card only renders it.
enum GettingStartedSourceRows {
    /// A browser's or an app source's channel (R-OB9: an app row says "Last synced" too); an agent and a drop have
    /// none.
    static func channelId(_ id: FoundItemID) -> String? {
        switch id {
        case .browser(let channel), .app(let channel): channel
        case .agent, .dropped: nil
        }
    }

    /// Where a row's live run sits in `SyncActivity`: its channel, or a drop's import key (R-OB10).
    static func runKey(_ id: FoundItemID) -> String? {
        if case .dropped(let drop) = id { return IntakeRouter.runKey(drop) }
        return channelId(id)
    }

    /// `finishedAt` is `SetupRunner.finishedAt[row.id]` — a finished drop says "Imported …", never "Last synced".
    static func model(_ row: GettingStartedRow, origin: String, channel: SourceChannel?, watch: BrowserWatchState?,
                      run: SyncActivity.Run?, finishedAt: Date? = nil) -> SourceRowModel {
        let status: SourceRowStatus
        switch row.state {
        case .working(let text) where channelId(row.id) == nil && run == nil:
            // An agent being connected is not a sync: its own words ("Connecting Codex…") are the line, and
            // `GettingStartedRowAction` draws the spinner — never "Syncing now".
            return SourceRowModel(id: row.id.key, origin: origin, title: row.title, line: text, status: .idle)
        case .working(let text):
            status = .syncing(detail: run?.detail ?? text, fraction: run?.fraction, cancellable: run?.cancellable ?? false)
        case .failed(let why):
            status = .problem(why)
        case .off, .needsAction:
            status = run.map { .syncing(detail: $0.detail, fraction: $0.fraction, cancellable: $0.cancellable) } ?? .idle
        case .on:
            if case .dropped = row.id, let finishedAt {
                status = .imported(finishedAt)          // an import is not a sync (R-SR12)
            } else {
                status = channelId(row.id) == nil ? .idle : SourceRowText.status(channel: channel, watch: watch, run: run)
            }
        }
        let line = channel.flatMap { SourceRowText.countLine($0) } ?? (row.detail.isEmpty ? nil : row.detail)
        return SourceRowModel(id: row.id.key, origin: origin, title: row.title, line: line, status: status)
    }
}

extension GettingStartedInputs {
    /// Home's card and onboarding build their inputs here and nowhere else, so a row can never read differently on
    /// the two (R-OB4).
    @MainActor
    static func live(record: GettingStartedRecord, inventory: LocalInventory, runner: SetupRunner,
                     watcher: BrowserWatcher, apps: [String: AppSourceDriver]) -> GettingStartedInputs {
        GettingStartedInputs(record: record, items: inventory.items, runnerRows: runner.rows,
                             runnerDetail: runner.detail, titles: runner.titles,
                             browserOn: Set(BrowserWatchPolicy.watched.map(\.channel).filter(watcher.isEnabled)),
                             wiringLoaded: inventory.wiring != nil,
                             appsOn: Set(apps.filter { $0.value.isOn() }.keys), appsKnown: Set(apps.keys))
    }
}
