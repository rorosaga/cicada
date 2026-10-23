import AppKit
import SwiftUI

/// Track I part b (design §4.2, T9b) — Getting started: the Welcome continued on
/// Home. It renders three things and decides none of them: `SetupRunner`'s
/// rows (this session), the per-bank `GettingStartedState` record (what the
/// person turned on, settled, hid, answered), and the machine's own state
/// (`LocalInventory`, the browser watch) — every rule is a pure function in
/// `GettingStartedProgress`, table-tested.
///
/// Dormant until a bank has a record (the Welcome's Start, or *Show setup
/// checklist* in Settings → General, R-IB17).
///
/// **Owner ruling 2026-10-14, "Graduate + Needs you first"** (amends R-IB17/R-IB18): once the person has chats in
/// memory (`HomeSetup.hasChatsInMemory`, a fact of the bank) the card graduates — it shrinks to one line,
/// "Setup · N things left · Show ›", at the foot of Home, and leaves entirely when nothing is left
/// (`GettingStartedPresentation`). Its viewer's open/closed choice is remembered per bank (DR-39), and *Show setup
/// checklist* opens it whole. Inside, three labelled groups (review #7, DR-20/DR-35): Connected, Your past chats (one
/// 36 pt row per vendor still to ask, opening the drawn walkthrough — review #1) and First read; *Also on this Mac* is
/// an offer under them, never a blocker.
///
/// Its one trigger — *Read now*,
/// *Read the next N*, all through `read()` — is G125 R10's second
/// narrow amendment (R-IB19): a user act, subtitled with the manual engine like
/// Consolidate, and the only trigger anywhere on Home. Home's steady state is a
/// link to the Sleep page.
struct GettingStartedCard: View {
    @Binding var selectedTab: AppTab
    /// The export walkthrough Home presents over itself (`HomeWalkthroughLayer`).
    @Binding var seeHow: ChatVendor?
    /// The person has chats in memory: the card graduates (owner 2026-10-14).
    var graduated = false

    @Environment(Store.self) private var store
    @Environment(SetupRunner.self) private var runner
    @Environment(LocalInventory.self) private var inventory
    @Environment(BrowserWatcher.self) private var watcher
    /// Round 4 (R-SR17) — a browser row's running sync and its ×.
    @Environment(SyncActivity.self) private var activity
    @Environment(IntakeRouter.self) private var intake
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(AppRouter.self) private var appRouter
    @Environment(ExportWaitStore.self) private var waits
    /// R-OB9 — the app-side sources (Calendar, Apple Notes, Wispr Flow, Contacts, Chrome's open tab groups) turn on
    /// through their registered drivers, so their rows start here exactly as they do on the Import page. Optional: a
    /// host without a reader registers no driver for it and its row still finishes in Integrations.
    @Environment(CalendarReader.self) private var calendar: CalendarReader?
    @Environment(ContactsReader.self) private var contacts: ContactsReader?
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?
    @Environment(LocalSourceWatcher.self) private var local
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @AccessibilityFocusState private var headingFocused: Bool
    /// A refused row's commands, shown on request (DR-39): the sentence above them leads with the fix.
    @State private var showsCommands: Set<FoundItemID> = []

    /// Review #7 — the groups inside the card sit 20 pt apart (DR-35: blocks inside the focus card are 20–24 pt).
    static let groupGap: CGFloat = 20
    static let labelGap: CGFloat = 6

    var body: some View {
        // Defaults are not observable; the revision is (every record write bumps it).
        let _ = runner.checklistRevision
        let record = GettingStartedState.load(bank: store.bank)
        let visible = GettingStartedProgress.visible(record: record) || runner.sawDoneThisSession
        let current = record ?? GettingStartedRecord()
        let rows = visible ? GettingStartedProgress.rows(inputs(current)) : []
        switch GettingStartedPresentation.of(visible: visible, graduated: graduated, expanded: current.expanded,
                                             left: HomeSetup.thingsLeft(rows)) {
        case .none:
            EmptyView()
        case .line(let left):
            setupLine(left)
        case .card:
            card(current, rows: rows)
        }
    }

    /// R-OB4 — built through the one `.live` builder onboarding also uses, so a row never reads differently.
    private func inputs(_ record: GettingStartedRecord) -> GettingStartedInputs {
        GettingStartedInputs.live(record: record, inventory: inventory, runner: runner, watcher: watcher, apps: apps)
    }

    /// The graduated card, closed: one line, no card of its own (DR-37), the whole line a button (review #5).
    private func setupLine(_ left: Int) -> some View {
        HomeRowButton(help: Copy.homeSetupShowHelp, trailingLabel: Copy.homeSetupShow, action: {
            GettingStartedState.setExpanded(true, bank: store.bank)
            runner.checklistChanged()
        }) {
            Text(Copy.homeSetupLine(left: left))
                .font(CicadaTheme.rowFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .task { await inventory.refresh() }
    }

    // MARK: The card

    @ViewBuilder
    private func card(_ record: GettingStartedRecord, rows: [GettingStartedRow]) -> some View {
        let connections = store.connections.value ?? []
        let readiness = EngineReadiness.resolve(candidates: engineVM.response?.candidates ?? [],
                                                connections: connections, preview: engineVM.response?.preview)
        let honesty = HonestyInputs.from(schedule: sleepVM.schedule, response: engineVM.response,
                                         connections: connections)
        let asksSchedule = hasRunBefore && sleepVM.scheduleLoaded && !record.scheduleAsked
            && ScheduleChoice.asks(sleepVM.schedule)
        // R-IB20: unknown is never an answer — a placeholder `manual` is not "asked".
        let scheduleAnswered = record.scheduleAsked
            || (sleepVM.scheduleLoaded && !ScheduleChoice.asks(sleepVM.schedule))
        let alsoFound = GettingStartedProgress.alsoFound(inputs(record))
        let done = GettingStartedProgress.isDone(rows: rows, hasRunBefore: hasRunBefore,
                                                 scheduleAnswered: scheduleAnswered,
                                                 // After onboarding its Agents/Sources offers are not asked again.
                                                 alsoFoundIsEmpty: alsoFound.isEmpty
                                                     || OnboardingState.isOnboarded(bank: store.bank),
                                                 inventoryLoaded: inventory.hasChecked)
        let hasDrop = rows.contains { if case .dropped = $0.id { return true }; return false }
        let waiting = waits.active(bank: store.bank)
        let toAsk = HomeSetup.vendorsToAsk(store.sourcesOverview.value)
            .filter { vendor in !waiting.contains { $0.vendor == vendor.rawValue } }
        let showsPastChats = !hasDrop && (!toAsk.isEmpty || !waiting.isEmpty)

        VStack(alignment: .leading, spacing: CicadaTheme.scaled(Self.groupGap)) {
            header
            if done || runner.sawDoneThisSession {
                Text(Copy.gsDone)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .transition(.opacity)
            } else {
                // After onboarding (owner fix round, 2026-10-22): what it covered folds into one line, only open
                // rows stay, and its Sources/Agents offers are not asked again (`GettingStartedFold`).
                let fold = GettingStartedFold.of(rows: rows, onboarded: OnboardingState.isOnboarded(bank: store.bank),
                                                 showsPastChats: showsPastChats, showsAlsoFound: !alsoFound.isEmpty)
                if fold.covered > 0 || !fold.openRows.isEmpty {
                    group(Copy.gsConnected) {
                        if fold.covered > 0 {
                            Text(Copy.gsCoveredInSetup(fold.covered))
                                .font(CicadaTheme.bodyFont).monospacedDigit()
                                .foregroundStyle(CicadaTheme.textSecondary)
                        }
                        if !fold.openRows.isEmpty { rowList(fold.openRows) }
                    }
                }
                if fold.showsPastChats {
                    group(Copy.gsPastChats) { chatHistory(waiting: waiting, toAsk: toAsk) }.transition(.opacity)
                }
                // Review #2 — "Your memory has N pages now" is the first week's payoff; on a graduated card Last read and
                // the graph own that number (DR-38), so a finished first read leaves the group.
                let step = firstReadStep
                let showsRead = !(graduated && step.action == .openGraph)
                if showsRead || readiness == .needsChoice || asksSchedule {
                    group(Copy.gsFirstRead) {
                        if readiness == .needsChoice { EngineChoice().transition(.opacity) }
                        if showsRead { firstRead(step, readiness: readiness) }
                        if asksSchedule { scheduleQuestion(honesty).transition(.opacity) }
                    }
                }
                if fold.showsAlsoFound { group(Copy.gsAlsoFound) { alsoFoundList(alsoFound) }.transition(.opacity) }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        // Looks pass (2026-10-23, §9) — one Home card: the same grouped block, 12 pt inset and 13 pt title as the tour
        // offer, the empty block and Make it yours beside it (`glassCard`: `bgFocus`, `cornerRadius`, the resting
        // ring). It was the focus card (R-HS5: `radiusLarge`, 24/28 inset, a 17 pt heading), so three stacked cards
        // on a first Home drew three paddings and three title sizes.
        .padding(CicadaTheme.spacingMD)
        .glassCard()
        .animation(CicadaMotion.settle(reduceMotion: reduceMotion),
                   value: [done, showsPastChats, readiness == .needsChoice, asksSchedule, alsoFound.isEmpty])
        // The first time it is done: "You're set up." for this session, and the
        // card is gone next launch (R-IB18). Never inside `body` — a state write
        // during evaluation would loop.
        .onChange(of: done, initial: true) { _, isDone in
            guard isDone, !runner.sawDoneThisSession else { return }
            runner.sawDoneThisSession = true
            GettingStartedState.setHidden(true, bank: store.bank)
            runner.checklistChanged()
        }
        .onAppear {
            // W14 — focus moves to the heading once, right after Start.
            guard runner.phase == .started, !runner.movedFocusToChecklist else { return }
            runner.movedFocusToChecklist = true
            headingFocused = true
        }
        .task {
            if engineVM.response == nil { await engineVM.load() }
            await inventory.refresh()
        }
        // A Full Disk Access grant lands while Cicada is in the background (W5):
        // re-probe on return so an Allow… row ticks itself.
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task { await inventory.refresh() }
        }
    }

    /// The first read is what this card waits for; before its status lands, a
    /// recorded last Sleep is the same fact from `/status` (as `TodaySection`).
    private var hasRunBefore: Bool {
        sleepVM.status?.debt.hasRunBefore ?? (store.status.value?.lastSleepAt != nil)
    }

    /// The live app-source registrations (R-OB9) — read for the rows' on/known state and handed to the turn-on.
    private var apps: [String: AppSourceDriver] {
        AppSourceDrivers.live(calendar: calendar, local: local, store: store, contacts: contacts, tabGroups: tabGroups)
    }

    private var effects: LiveSetupEffects {
        LiveSetupEffects(store: store,
                         deps: .live(inventory: inventory, watcher: watcher, intake: intake,
                                     calendar: calendar, local: local, store: store, contacts: contacts,
                                     tabGroups: tabGroups),
                         onChecklistChanged: runner.checklistChanged)
    }

    /// Review #7 — one labelled group inside the card (DR-20, DR-47: every section label is a `SectionLabel`).
    private func group<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(Self.labelGap)) {
            SectionLabel(title)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) { content() }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text(Copy.gsTitle)
                .font(CicadaTheme.rowFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
                .accessibilityFocused($headingFocused)
            Spacer(minLength: CicadaTheme.spacingSM)
            if graduated {
                // A graduated card closes back to its line, remembered (DR-39).
                TextButton(title: Copy.homeSetupShowLess) {
                    GettingStartedState.setExpanded(false, bank: store.bank)
                    runner.checklistChanged()
                }
            }
            // DR-40 — the text button (R-HS5).
            TextButton(title: Copy.gsHide) {
                GettingStartedState.setHidden(true, bank: store.bank)
                // Hide also ends this session's "You're set up." (R-IB18).
                runner.sawDoneThisSession = false
                runner.checklistChanged()
            }
        }
    }

    // MARK: Rows

    /// R-OB4 — the rows are `SetupProgress.snapshots`, the one projection the Import page, the onboarding topbar and
    /// F-07 read too, so "Last synced", "Reading 9 of 17" and the × can never differ between Home and onboarding.
    @ViewBuilder
    private func rowList(_ rows: [GettingStartedRow]) -> some View {
        let snapshots = SetupProgress.snapshots(rows, facts: facts(for: rows))
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            VStack(alignment: .leading, spacing: 0) {   // DR-35 — no gap between one-line rows
                ForEach(snapshots) { snapshot in
                    let row = snapshot.row
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        // The × reads the run key, not the channel: a drop's run sits under its import key and is
                        // never cancellable (R-OB10), so `SourceRow` draws no × for it.
                        SourceRow(model: snapshot.model, now: context.date,
                                  onCancel: GettingStartedSourceRows.runKey(row.id)
                                      .map { key -> () -> Void in { activity.cancel(key) } }) {
                            // An app row now has a channel, so it says "Last synced …" like a browser; an agent or a
                            // drop keeps the ✓ On label.
                            GettingStartedRowAction(row: row, showsOn: GettingStartedSourceRows.channelId(row.id) == nil) {
                                Task { await runner.turnOn(row.id, effects: effects) }
                            }
                            // While a run can be stopped, its × is the row's one ×.
                            if !snapshot.model.status.isSyncing { dismissButton(row) }
                        }
                        refusedLines(row.id)
                    }
                }
            }
        }
    }

    /// What a row is drawn from beyond its runner state (R-OB4): the Store's channels, each channel's watch light,
    /// the live runs, a drop's vendor mark and when each row finished. The marks themselves are
    /// `SetupProgress.origin` — an app row wears its channel's mark (Apple Notes → `apple-notes`), not its bare id.
    /// The watch light is read per row's channel (as before), not per Store channel: a browser whose channel the
    /// Store has not listed yet still shows its syncing light.
    private func facts(for rows: [GettingStartedRow]) -> SetupFacts {
        var facts = SetupFacts()
        facts.channels = store.channels.value ?? []
        for id in rows.compactMap({ GettingStartedSourceRows.channelId($0.id) }) {
            if let state = watcher.state(for: id) { facts.watches[id] = state }
        }
        facts.runs = activity.runs
        facts.origins = runner.origins
        facts.finishedAt = runner.finishedAt
        return facts
    }

    /// ✕ settles a row (R-IB18); a dropped export lives only in this session,
    /// so its ✕ forgets it instead (R-IB17 — a drop is never recorded).
    /// The one icon-only button (DR-40, R-HS5).
    private func dismissButton(_ row: GettingStartedRow) -> some View {
        IconButton(systemName: "xmark", help: Copy.gsDismiss,
                   accessibilityLabel: "\(Copy.gsDismiss), \(row.title)") {
            if case .dropped = row.id { runner.forget(row.id) } else { effects.settle(row.id) }
        }
    }

    /// As `OnThisMacStrip` renders them — to inspect, never to run, no copy button — but behind *Show the commands*
    /// (review #6, DR-39): the sentence leads with the fix, and the commands are detail.
    @ViewBuilder
    private func refusedLines(_ id: FoundItemID) -> some View {
        if let lines = runner.refused[id] {
            let open = showsCommands.contains(id)
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.foundRefused).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: CicadaTheme.spacingSM)
                TextButton(title: open ? Copy.gsHideCommands : Copy.gsShowCommands) {
                    if open { showsCommands.remove(id) } else { showsCommands.insert(id) }
                }
            }
            if open {
                ForEach(lines, id: \.self) {
                    Text($0).font(CicadaTheme.monoFont).foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    /// An invitation, not a connection with a state — so a plain row, not a
    /// `FoundRow`. It opens the one intake (design §5.1), never a picker of its own.
    /// Under it (R-IB22, review #11): each export the person is waiting on, leading with what to look for, ABOVE the
    /// vendors still to ask — one 36 pt "See how ›" row each (review #1), which opens the drawn walkthrough. A vendor
    /// whose export is already in this bank is not asked again (`HomeSetup.vendorsToAsk`).
    private func chatHistory(waiting: [ExportWait], toAsk: [ChatVendor]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            chatDropLine
            if !waiting.isEmpty {
                TimelineView(.periodic(from: .now, by: ExportWaits.refreshInterval)) { context in
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(waiting) { wait in
                            ExportWaitRow(wait: wait, now: context.date,
                                          onChoose: { intake.present(from: wait.intakeOrigin(fallback: .onboardingRow)) },
                                          onStop: { waits.remove(wait) })
                        }
                    }
                }
            }
            ForEach(toAsk) { vendor in
                ExportVendorRow(vendor: vendor) { seeHow = $0 }
            }
        }
    }

    private var chatDropLine: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            HStack(spacing: -CicadaTheme.scaled(6)) {
                ForEach(ChatVendor.allCases) { VendorMark(vendor: $0, size: CicadaTheme.scaled(20)) }
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(Copy.gsChatHistory)
                    .font(CicadaTheme.rowFont)   // DR-16 reserves semibold
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.gsChatDrop)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.intakeChooseFile, size: .compact) { intake.present(from: .onboardingRow) }
        }
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(RowMetrics.twoLine), alignment: .leading)
    }

    // MARK: The first read (R-IB19)

    private var firstReadStep: FirstReadStep {
        let status = sleepVM.status
        return FirstReadStep.of(FirstReadInputs(
            running: sleepVM.isRunning || store.status.value?.sleep.status == "running",
            stage: status?.stage ?? 0,
            error: status?.error,
            unprocessed: store.status.value?.episodes.unprocessed ?? status?.debt.unprocessedCount,
            read: (status?.readByOrigin ?? [:]).values.reduce(0, +),
            total: (status?.queueByOrigin ?? [:]).values.reduce(0, +),
            episodesTotal: status?.episodesTotal ?? 0,
            episodesQueued: status?.episodesQueued ?? 0,
            hasRunBefore: hasRunBefore,
            pages: store.graph.value.map { $0.nodes.filter { !$0.isHub && !$0.isFacet }.count }))
    }

    @ViewBuilder
    private func firstRead(_ step: FirstReadStep, readiness: EngineReadiness) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                // The worm stays in the study room (DR-13: never on a row); Sleep's own glyph says what this waits on.
                Image(systemName: "moon")
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)   // the line beside it is its text twin
                Text(step.line())
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            switch step.action {
            case .readNow?:
                trigger(Copy.intakeReadNow, readiness: readiness)
            case .keepReading?:
                trigger(Copy.gsKeepReading, readiness: readiness)
            case .seeDetails?:
                // DR-40/59 — one calm fix action; the raw diagnosis lives in Sleep Details.
                TextButton(title: Copy.sleepDetails) { appRouter.routeToSleepDetails(.lastCycle) }
            case .watchSleep?:
                VStack(alignment: .leading, spacing: 2) {
                    TextButton(title: Copy.gsWatchOnSleep) { selectedTab = .sleep }
                    Text(Copy.gsLeaveWhileReading)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            case .openGraph?:
                TextButton(title: Copy.gsOpenGraph) { selectedTab = .graph }
            case nil:
                EmptyView()
            }
        }
    }

    /// The same action wears the same pill the intake done card's *Read now*
    /// wears (R-IA16, R-IB19), subtitled with the engine a manual read uses —
    /// and disabled, saying why, until someone can read (`EngineReadiness`).
    @ViewBuilder
    private func trigger(_ title: String, readiness: EngineReadiness) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            triggerRow(title, readiness: readiness)
            // Sleep page v5 — the same caption as the intake card's Read now: it reads everything waiting, saving as it
            // goes, or (while a run is paused) it opens the Sleep page, where Continue is.
            if readiness != .needsChoice, let caption = sleepVM.door.readNowCaption {
                Text(caption)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func triggerRow(_ title: String, readiness: EngineReadiness) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            MeadowPill(title: title) { read() }
                .disabled(readiness == .needsChoice)
            if readiness == .needsChoice {
                Text(Copy.intakeChooseWhoReads)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            } else if let preview = engineVM.response?.preview {
                Text(Copy.engineLabel(preview.manual.engine))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
    }

    /// The card's one trigger (G125 R10's second narrow amendment): the
    /// person's own click, never a schedule and never outside this card.
    private func read() {
        Task { await sleepVM.triggerManually(); await store.refresh([.status, .channels]) }
    }

    // MARK: The schedule question (R-IB20)

    @ViewBuilder
    private func scheduleQuestion(_ honesty: HonestyInputs) -> some View {
        let enabled = ScheduleHonesty.enabledModes(honesty)
        let options: [(ScheduleMode, String)] = [(.manual, Copy.gsWhenIAsk), (.afterImport, Copy.gsAfterImports),
                                                  (.daily, Copy.gsNightly)]
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.gsScheduleQuestion)
                .font(CicadaTheme.rowFont)   // DR-16 reserves semibold
                .foregroundStyle(CicadaTheme.textPrimary)
            // Review #5/#7 — three 28 pt neutral buttons (DR-40), the current one ticked; never 11 pt hand-rolled radios.
            HStack(spacing: CicadaTheme.spacingSM) {
                ForEach(options, id: \.0) { mode, label in
                    let current = sleepVM.schedule.mode == mode.rawValue
                    NeutralButton(title: label, systemImage: current ? "checkmark" : nil, size: .compact,
                                  isDisabled: !enabled.contains(mode),
                                  disabledHelp: ScheduleHonesty.engineLine(honesty)) { answer(mode) }
                        .accessibilityAddTraits(current ? .isSelected : [])
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel(Copy.gsScheduleQuestion)
            // Ruling 4, shown: with plans only and no key, only "When I ask" is on.
            Text(ScheduleHonesty.engineLine(honesty))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            TextButton(title: Copy.gsNotNow) {
                GettingStartedState.setScheduleAsked(bank: store.bank)
                runner.checklistChanged()
            }
        }
    }

    /// The one writer is `updateSchedule`; the question is answered only when
    /// the write landed, so a failure asks again rather than pretend.
    private func answer(_ mode: ScheduleMode) {
        store.bankTask {
            if await sleepVM.updateSchedule(ScheduleChoice.config(for: mode, current: sleepVM.schedule)) {
                GettingStartedState.setScheduleAsked(bank: store.bank)
                runner.checklistChanged()
            }
        }
    }

    // MARK: Also found

    /// An offer, never a blocker (owner 2026-10-14): what else is on this Mac, under its own group label.
    private func alsoFoundList(_ items: [FoundItem]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(items) { item in
                FoundRow(mark: OnThisMacStrip.mark(item.id), title: item.title,
                         detail: OnThisMacStrip.detail(item.id),
                         state: item.readiness == .needsPermission ? .needsAction(Copy.foundAllow) : .off,
                         action: {
                             // Recorded first, so the row moves up into the list
                             // and keeps its state after a relaunch (R-IB17).
                             effects.recordGettingStarted([item.id])
                             Task { await runner.turnOn(item.id, effects: effects) }
                         })
            }
        }
    }
}

/// The one thing a Getting started row can still do — `FoundRow`'s trailing rule, as DR-40 buttons. `showsOn`: a row
/// with no channel (an agent, an app, a dropped export) has no "Last synced" to say, so it keeps `FoundRow`'s
/// "On ✓" — without it an On row would say nothing on its right at all; a browser row says "Last synced …" instead.
private struct GettingStartedRowAction: View {
    let row: GettingStartedRow
    let showsOn: Bool
    let action: () -> Void

    var body: some View {
        switch row.state {
        case .off, .needsAction, .failed:
            if let section = row.settingsLink {
                // The state's own words ("Finish on the Agents page", "Finish in Integrations"), as `FoundRow`
                // would with an `actionTitle`; the Claude-desktop sentence is only the fallback.
                SettingsSectionLink(home: section,
                                    label: FoundRow.defaultActionTitle(row.state) ?? Copy.foundClaudeDesktopDetail)
            } else if let title = FoundRow.defaultActionTitle(row.state) {
                NeutralButton(title: title, size: .compact, action: action)
            }
        case .on:
            if showsOn {
                Label(Copy.foundOn, systemImage: "checkmark.circle.fill")
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.success)
            }
        case .working:
            if showsOn { ProgressView().controlSize(.small) }   // a syncing browser row's spinner is `SourceRow`'s own
        }
    }
}
