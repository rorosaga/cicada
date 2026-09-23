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
/// checklist* in Settings → General, R-IB17). Its one trigger — *Read now*,
/// *Read the next N*, *Try again*, all through `read()` — is G125 R10's second
/// narrow amendment (R-IB19): a user act, subtitled with the manual engine like
/// Consolidate, and the only trigger anywhere on Home. Home's steady state is a
/// link to the Sleep page.
struct GettingStartedCard: View {
    @Binding var selectedTab: AppTab

    @Environment(Store.self) private var store
    @Environment(SetupRunner.self) private var runner
    @Environment(LocalInventory.self) private var inventory
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(IntakeRouter.self) private var intake
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(ExportWaitStore.self) private var waits
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @AccessibilityFocusState private var headingFocused: Bool
    @State private var showsEngineAfterFailure = false

    var body: some View {
        // Defaults are not observable; the revision is (every record write bumps it).
        let _ = runner.checklistRevision
        let record = GettingStartedState.load(bank: store.bank)
        if GettingStartedProgress.visible(record: record) || runner.sawDoneThisSession {
            card(record ?? GettingStartedRecord())
        }
    }

    // MARK: The card

    @ViewBuilder
    private func card(_ record: GettingStartedRecord) -> some View {
        let connections = store.connections.value ?? []
        let readiness = EngineReadiness.resolve(candidates: engineVM.response?.candidates ?? [],
                                                connections: connections, preview: engineVM.response?.preview)
        let honesty = HonestyInputs.from(schedule: sleepVM.schedule, response: engineVM.response,
                                         connections: connections)
        let inputs = GettingStartedInputs(
            record: record, items: inventory.items, runnerRows: runner.rows, runnerDetail: runner.detail,
            titles: runner.titles,
            browserOn: Set(BrowserWatchPolicy.watched.map(\.channel).filter(watcher.isEnabled)),
            wiringLoaded: inventory.wiring != nil)
        let rows = GettingStartedProgress.rows(inputs)
        let asksSchedule = hasRunBefore && sleepVM.scheduleLoaded && !record.scheduleAsked
            && ScheduleChoice.asks(sleepVM.schedule)
        // R-IB20: unknown is never an answer — a placeholder `manual` is not "asked".
        let scheduleAnswered = record.scheduleAsked
            || (sleepVM.scheduleLoaded && !ScheduleChoice.asks(sleepVM.schedule))
        let alsoFound = GettingStartedProgress.alsoFound(inputs)
        let done = GettingStartedProgress.isDone(rows: rows, hasRunBefore: hasRunBefore,
                                                 scheduleAnswered: scheduleAnswered,
                                                 alsoFoundIsEmpty: alsoFound.isEmpty,
                                                 inventoryLoaded: inventory.hasChecked)
        let hasDrop = rows.contains { if case .dropped = $0.id { return true }; return false }

        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            header
            if done || runner.sawDoneThisSession {
                Text(Copy.gsDone)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .transition(.opacity)
            } else {
                rowList(rows)
                if !hasDrop { chatHistoryRow.transition(.opacity) }
                if readiness == .needsChoice { EngineChoice().transition(.opacity) }
                Divider()
                firstRead(readiness: readiness)
                if asksSchedule { scheduleQuestion(honesty).transition(.opacity) }
                if !alsoFound.isEmpty { alsoFoundList(alsoFound).transition(.opacity) }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingLG)
        .background(CicadaTheme.surface, in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge))
        .animation(CicadaMotion.settle(reduceMotion: reduceMotion),
                   value: [done, hasDrop, readiness == .needsChoice, asksSchedule, alsoFound.isEmpty])
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

    private var effects: LiveSetupEffects {
        LiveSetupEffects(store: store, engineVM: engineVM,
                         deps: .live(inventory: inventory, watcher: watcher, intake: intake),
                         onChecklistChanged: runner.checklistChanged)
    }

    private var header: some View {
        HStack {
            Text(Copy.gsTitle)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
                .accessibilityFocused($headingFocused)
            Spacer(minLength: CicadaTheme.spacingSM)
            Button(Copy.gsHide) {
                GettingStartedState.setHidden(true, bank: store.bank)
                // Hide also ends this session's "You're set up." (R-IB18).
                runner.sawDoneThisSession = false
                runner.checklistChanged()
            }
            .buttonStyle(.cicadaPlain)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textSecondary)
        }
    }

    // MARK: Rows

    @ViewBuilder
    private func rowList(_ rows: [GettingStartedRow]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            ForEach(rows) { row in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        FoundRow(mark: mark(row.id), title: row.title, detail: row.detail, state: row.state,
                                 action: { Task { await runner.turnOn(row.id, effects: effects) } },
                                 settingsLink: row.settingsLink)
                        dismissButton(row)
                    }
                    refusedLines(row.id)
                }
            }
            if let engineError = runner.engineError {
                Text(engineError)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// ✕ settles a row (R-IB18); a dropped export lives only in this session,
    /// so its ✕ forgets it instead (R-IB17 — a drop is never recorded).
    private func dismissButton(_ row: GettingStartedRow) -> some View {
        Button {
            if case .dropped = row.id { runner.forget(row.id) } else { effects.settle(row.id) }
        } label: {
            Image(systemName: "xmark")
                .font(CicadaTheme.font(size: 10, weight: .semibold))
                .foregroundStyle(CicadaTheme.textTertiary)
                .iconHover()
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.gsDismiss)
        .accessibilityLabel("\(Copy.gsDismiss), \(row.title)")
    }

    /// The export's real mark for a dropped row (an unknown origin falls to the
    /// SF fallback); every other row wears the `+` strip's mark.
    private func mark(_ id: FoundItemID) -> FoundMark {
        if case .dropped = id {
            return .logo(OriginIconography.logoName(for: runner.origins[id] ?? "") ?? "")
        }
        return OnThisMacStrip.mark(id)
    }

    /// Exactly as `OnThisMacStrip` renders them: to inspect, never to run — no copy button.
    @ViewBuilder
    private func refusedLines(_ id: FoundItemID) -> some View {
        if let lines = runner.refused[id] {
            Text(Copy.foundRefused).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(lines, id: \.self) {
                Text($0).font(CicadaTheme.monoFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// An invitation, not a connection with a state — so a plain row, not a
    /// `FoundRow`. It opens the one intake (design §5.1), never a picker of its own.
    /// Under it (R-IB22): each export the person is waiting on, with when it was
    /// asked and when the reminder comes — the text twin that needs no
    /// notification permission — or, while nothing is awaited, how to ask for one.
    private var chatHistoryRow: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            chatDropLine
            let active = waits.active(bank: store.bank)
            if active.isEmpty {
                ForEach(ChatVendor.allCases) { ExportAskRow(vendor: $0, startsOpen: false) }
                    .padding(.horizontal, CicadaTheme.spacingSM)
            } else {
                TimelineView(.periodic(from: .now, by: ExportWaits.refreshInterval)) { context in
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        ForEach(active) { waitRow($0, now: context.date) }
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingSM)
            }
        }
    }

    private func waitRow(_ wait: ExportWait, now: Date) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            VendorMark(origin: ChatVendor(rawValue: wait.vendor)?.origin, size: CicadaTheme.scaled(18))
            Text(ExportWaits.rowLine(wait, now: now))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            Spacer(minLength: CicadaTheme.spacingSM)
            Button(Copy.intakeChooseFile) { intake.present(from: wait.intakeOrigin(fallback: .onboardingRow)) }
                .buttonStyle(.bordered)
            Button { waits.remove(wait) } label: {
                Image(systemName: "xmark")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .iconHover()
            }
            .buttonStyle(.cicadaPlain)
            .help(Copy.reminderDismiss)
            .accessibilityLabel("\(Copy.reminderDismiss), \(ExportWaits.vendorTitle(wait.vendor))")
        }
    }

    private var chatDropLine: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            HStack(spacing: -CicadaTheme.scaled(6)) {
                ForEach(ChatVendor.allCases) { VendorMark(vendor: $0, size: CicadaTheme.scaled(20)) }
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(Copy.gsChatHistory)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.gsChatDrop)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            Button(Copy.intakeChooseFile) { intake.present(from: .onboardingRow) }
                .buttonStyle(.bordered)
        }
        .padding(.vertical, CicadaTheme.spacingXS)
        .padding(.horizontal, CicadaTheme.spacingSM)
    }

    // MARK: The first read (R-IB19)

    @ViewBuilder
    private func firstRead(readiness: EngineReadiness) -> some View {
        let status = sleepVM.status
        let step = FirstReadStep.of(FirstReadInputs(
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
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                BookwormView(state: step.worm, pointSize: 24)
                    .accessibilityHidden(true)   // the line beside it is its text twin
                Text(step.line())
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            switch step.action {
            case .readNow?:
                trigger(Copy.intakeReadNow, readiness: readiness)
            case .readNext(let n)?:
                trigger(Copy.gsReadNext(n), readiness: readiness)
            case .tryAgain?:
                trigger(Copy.gsTryAgain, readiness: readiness)
                // The needs-choice case already shows the chooser above.
                if readiness != .needsChoice {
                    DisclosureGroup(isExpanded: $showsEngineAfterFailure) {
                        EngineChoice().padding(.top, CicadaTheme.spacingXS)
                    } label: {
                        Text(Copy.gsWhoReads).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
            case .watchSleep?:
                VStack(alignment: .leading, spacing: 2) {
                    Button(Copy.gsWatchOnSleep) { selectedTab = .sleep }.buttonStyle(.link)
                    Text(Copy.gsLeaveWhileReading)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            case .openGraph?:
                Button(Copy.gsOpenGraph) { selectedTab = .graph }.buttonStyle(.link)
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
                .font(CicadaTheme.font(size: 13, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            HStack(spacing: CicadaTheme.spacingMD) {
                ForEach(options, id: \.0) { mode, label in
                    let current = sleepVM.schedule.mode == mode.rawValue
                    Button { answer(mode) } label: {
                        Label(label, systemImage: current ? "largecircle.fill.circle" : "circle")
                            .font(CicadaTheme.captionFont)
                    }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .disabled(!enabled.contains(mode))
                    .opacity(enabled.contains(mode) ? 1 : 0.45)
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
            Button(Copy.gsNotNow) {
                GettingStartedState.setScheduleAsked(bank: store.bank)
                runner.checklistChanged()
            }
            .buttonStyle(.link)
            .font(CicadaTheme.captionFont)
        }
    }

    /// The one writer is `updateSchedule`; the question is answered only when
    /// the write landed, so a failure asks again rather than pretend.
    private func answer(_ mode: ScheduleMode) {
        Task {
            if await sleepVM.updateSchedule(ScheduleChoice.config(for: mode, current: sleepVM.schedule)) {
                GettingStartedState.setScheduleAsked(bank: store.bank)
                runner.checklistChanged()
            }
        }
    }

    // MARK: Also found

    private func alsoFoundList(_ items: [FoundItem]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.gsAlsoFound)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
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
