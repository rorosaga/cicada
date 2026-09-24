import AppKit
import SwiftUI

/// Round-4 phase B (G145) — the paged onboarding, one full-window layer over the shell (R-IB11's placement kept):
/// Welcome and You're set on the whole painting with a card; the four working pages in the split frame — the page's
/// painting (`OnboardingPane`), then the column: the topbar ("Step n of 6 · k still coming in", Set up later), the page,
/// the foot (Back, the page's line, its one primary with ⏎). It decides nothing itself: pages are `OnboardingPage`,
/// geometry `OnboardingLayout`, steps `OnboardingFlow` run by `SetupRunner`, every row and count `SetupProgress`
/// (R-OB4). Get started is the owner PUT alone (R-OB2); after it a tick or a drop starts at once. Esc closes See how,
/// then — on a rerun only — the flow (R-OB19).
struct OnboardingView: View {
    let mode: OnboardingMode
    let dropTargeted: Bool
    let onShowHome: () -> Void
    let onClose: () -> Void

    @Environment(Store.self) private var store
    @Environment(SetupRunner.self) private var runner
    @Environment(LocalInventory.self) private var inventory
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(IntakeRouter.self) private var intake
    @Environment(SyncActivity.self) private var activity
    @Environment(LocalSourceWatcher.self) private var local
    @Environment(CalendarReader.self) private var calendar: CalendarReader?
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(LoginItemService.self) private var loginItems
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @AppStorage(MenuBarPreference.defaultsKey) private var showsMenuBar = true

    @State private var page: OnboardingPage = .welcome
    @State private var furthest: OnboardingPage = .welcome
    @State private var ownerSaved = false
    @State private var name = ""
    @State private var owner: OwnerSettings?
    @State private var editingName = false
    @State private var busy = false
    @State private var failure: String?
    @State private var seeHow: ChatVendor?
    /// Held here, not by F-04, so You're set reads the last answer (R-OB13).
    @State private var live = AgentLiveProbe()
    @State private var browsers = BrowserInventory.empty
    @State private var memoryRoot: String?
    @State private var allowRequested: Set<FoundItemID> = []
    @State private var pageShownAt = Date()
    @FocusState private var rootFocused: Bool

    private var apps: [String: AppSourceDriver] { AppSourceDrivers.live(calendar: calendar, local: local, store: store) }

    private var entries: [ImportEntry] {
        ImportCatalog.entries(ImportContext(browsers: browsers, wisprInstalled: local.wisprInstalled))
    }

    private var effects: LiveSetupEffects {
        LiveSetupEffects(store: store,
                         deps: .live(inventory: inventory, watcher: watcher, intake: intake, calendar: calendar,
                                     local: local, store: store),
                         owner: owner, onShowHome: onShowHome, onClose: onClose,
                         onChecklistChanged: runner.checklistChanged)
    }

    /// Every Import row and every drop, through the one projection (R-OB4).
    private var snapshots: [SetupRowSnapshot] {
        let inputs = GettingStartedInputs.live(record: GettingStartedRecord(enabled: entries.map(\.id)),
                                               inventory: inventory, runner: runner, watcher: watcher, apps: apps)
        let channels = store.channels.value ?? []
        let ids = Set(channels.map(\.id) + entries.compactMap { GettingStartedSourceRows.channelId($0.id) })
        let facts = SetupFacts(channels: channels,
                               watches: Dictionary(uniqueKeysWithValues: ids.compactMap { id in
                                   watcher.state(for: id).map { (id, $0) } }),
                               runs: activity.runs, origins: runner.origins, finishedAt: runner.finishedAt)
        return SetupProgress.snapshots(GettingStartedProgress.rows(inputs), facts: facts)
    }

    var body: some View {
        GeometryReader { geo in
            let scale = CGFloat(CicadaTheme.uiScale)
            let paneWidth = page.isSplit ? OnboardingLayout.paneWidth(windowWidth: geo.size.width, scale: scale)
                                         : geo.size.width
            ZStack(alignment: .topLeading) {
                CicadaTheme.bgBase.ignoresSafeArea()
                OnboardingPane(pane: page.pane, paused: seeHow != nil)
                    .frame(width: paneWidth, height: geo.size.height)
                if page.isSplit {
                    column(width: geo.size.width - paneWidth)
                        .frame(width: geo.size.width - paneWidth, height: geo.size.height)
                        .background(CicadaTheme.bgBase)
                        .offset(x: paneWidth)
                } else {
                    card(size: geo.size)
                }
                if let vendor = seeHow {
                    ExportWalkthroughSheet(vendor: vendor) { seeHow = nil }
                }
            }
        }
        .focusable()
        .focusEffectDisabled()
        .focused($rootFocused)
        .defaultFocus($rootFocused, true)
        .onAppear { Task { @MainActor in if !editingName { rootFocused = true } } }
        // DR-60 — ⏎ advances with no animation. A text field (the name, a key) takes its own Return first.
        .onKeyPress(.return) {
            guard seeHow == nil, !busy else { return .ignored }
            advance(.keyboard)
            return .handled
        }
        .onExitCommand(perform: exit)
        .task { await load() }
        // R-OB2 — a drop starts at once once the owner is saved; before that it waits, staged.
        .onChange(of: intake.welcomeDrops.map(\.id)) { old, new in startDrops(new.filter { !old.contains($0) }) }
        // ⌘⇧I and the menu bar's Import a file… while onboarding shows (R-IB15), a turn later: a modal panel must
        // not run inside a view update.
        .onChange(of: intake.welcomeChooseRequest) { _, _ in Task { @MainActor in ImportPage.chooseFile(intake) } }
        // R-OB7 — a Full Disk Access grant lands while Cicada is in the background.
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task { await inventory.refresh() }
        }
        .onChange(of: inventory.items) { _, items in startGranted(items) }
        .onChange(of: page) { _, next in
            furthest = max(furthest, next)
            pageShownAt = Date()
        }
        // The name field took focus and gave it back on ⏎: return it to the root, so the next ⏎ is Get started.
        .onChange(of: editingName) { _, editing in if !editing { rootFocused = true } }
    }

    // MARK: The split frame

    private func column(width: CGFloat) -> some View {
        let s = snapshots
        return VStack(spacing: 0) {
            OnboardingTopbar(page: page, furthest: furthest, ownerSaved: ownerSaved,
                             comingIn: SetupProgress.stillComingIn(s),
                             trailing: mode == .rerun ? Copy.welcomeClose : Copy.welcomeSetUpLater,
                             onJump: { go($0, .pointer) }, onTrailing: mode == .rerun ? closeRerun : setUpLater)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    // The newest arrival, with its source's own mark (DR-52) — the design's "2,104 bookmarks in".
                    if let arrival = SetupProgress.arrival(s, finishedAt: runner.finishedAt, since: pageShownAt) {
                        HStack(spacing: CicadaTheme.spacingXS) {
                            OriginMark(origin: arrival.model.origin, size: CicadaTheme.scaled(14))
                            Text(Copy.onboardingArrival(title: arrival.model.title, line: arrival.model.line))
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textSecondary)
                        }
                    }
                    pageContent(width: width, snapshots: s)
                }
                .padding(.horizontal, CicadaTheme.scaled(OnboardingLayout.columnPadding))
                .padding(.vertical, CicadaTheme.spacingLG)
            }
            .scrollBounceBehavior(.basedOnSize)
            // Pinned outside the scroll (the G130 lesson): the way forward is never the first thing to clip.
            foot
                .padding(.horizontal, CicadaTheme.scaled(OnboardingLayout.columnPadding))
                .padding(.bottom, CicadaTheme.scaled(OnboardingLayout.footBottom))
        }
    }

    @ViewBuilder
    private func pageContent(width: CGFloat, snapshots s: [SetupRowSnapshot]) -> some View {
        switch page {
        case .import:
            ImportPage(entries: entries, snapshots: Dictionary(uniqueKeysWithValues: s.map { ($0.id, $0) }),
                       browsers: browsers, memoryRoot: memoryRoot,
                       columnWidth: width - 2 * CicadaTheme.scaled(OnboardingLayout.columnPadding),
                       dropTargeted: dropTargeted, onTick: tick, onSeeHow: { seeHow = $0 })
        case .agents: AgentsPage(live: live)
        case .whoReads: WhoReadsPage()
        case .keepRunning: KeepRunningPage()
        case .welcome, .ready: EmptyView()
        }
    }

    private var foot: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            TextButton(title: Copy.onboardingBack) { if let previous = page.previous { go(previous, .pointer) } }
            footLine
            Spacer(minLength: CicadaTheme.spacingSM)
            PrimaryActionButton(title: Copy.onboardingContinue) { advance(.pointer) }
            KeyHint("⏎")
        }
    }

    @ViewBuilder
    private var footLine: some View {
        switch page {
        case .import:
            OnboardingPointerLine(lead: Copy.importMoreSources, section: .integrations,
                                  label: Copy.onboardingSettingsIntegrations)
        case .agents:
            OnboardingPointerLine(lead: Copy.agentsFoot, section: .agents, label: Copy.onboardingSettingsAgents)
        case .whoReads, .keepRunning:
            // R-OB17 — "Everything stays on this Mac" only when nothing is read off it; F-06 says the same as F-05.
            Label(WhoReadsPage.footLine(engineVM.response), systemImage: "lock")
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
        case .welcome, .ready:
            EmptyView()
        }
    }

    // MARK: Welcome and You're set

    private func card(size: CGSize) -> some View {
        let width = OnboardingLayout.cardWidth(windowWidth: size.width, scale: CGFloat(CicadaTheme.uiScale))
        let content = Group {
            if page == .welcome {
                WelcomePage(mode: mode, name: $name, editingName: $editingName, busy: busy, failure: failure,
                            waitingDrops: ownerSaved ? 0 : intake.welcomeDrops.count,
                            onGetStarted: { advance(.pointer) }, onSetUpLater: mode == .rerun ? closeRerun : setUpLater,
                            onTryDemo: tryDemo)
            } else {
                ReadyPage(summary: SetupProgress.summary(snapshots, keepsUp: { SetupProgress.keepsUp($0, apps: apps) }),
                          agents: ReadySummary.agents(connected: live.connected),
                          agentMarks: AgentCatalog.featured.filter { live.connected.contains($0.id) },
                          startup: ReadySummary.startup(opensAtLogin: loginItems.state == .on, menuBar: showsMenuBar),
                          busy: busy, onBack: { go(.keepRunning, .pointer) }, onOpen: { advance(.pointer) })
            }
        }
        .frame(width: width)
        return VStack {
            Spacer(minLength: CicadaTheme.spacingLG)
            // A short window scrolls the card with its actions inside it — never clipped (G130).
            ViewThatFits(in: .vertical) {
                content
                ScrollView { content }.scrollBounceBehavior(.basedOnSize)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.bottom, CicadaTheme.scaled(OnboardingLayout.cardBottom))
    }

    // MARK: What the buttons do

    private func advance(_ input: OnboardingInput) {
        guard !busy, seeHow == nil else { return }
        switch page {
        case .welcome: getStarted(input)
        case .ready: openCicada()
        default: if let next = page.next { go(next, input) }
        }
    }

    private func go(_ target: OnboardingPage, _ input: OnboardingInput) {
        if let animation = OnboardingNav.animation(input, reduceMotion: reduceMotion) {
            withAnimation(animation) { page = target }
        } else {
            page = target
        }
    }

    /// R-OB2 — the owner PUT alone and first; its failure keeps Welcome up with the reason (G117 R1). A file dropped on
    /// Welcome waited for this and starts now.
    private func getStarted(_ input: OnboardingInput) {
        guard OnboardingFlow.canStart(name: name) else { editingName = true; return }
        busy = true
        failure = nil
        let effects = self.effects
        Task {
            await runner.run(OnboardingFlow.beginSteps(name: name), effects: effects)
            busy = false
            if case .failed(let why) = runner.phase { failure = why; return }
            ownerSaved = true
            startDrops(intake.welcomeDrops.map(\.id))
            go(.import, input)
        }
    }

    /// A tick starts that source now; an untick stops it keeping up (R-OB8). A blocked browser's tick opens System
    /// Settings and is remembered, so the grant starts it (R-OB7).
    private func tick(_ entry: ImportEntry, _ on: Bool) {
        guard ownerSaved else { return }
        let effects = self.effects
        if on {
            if inventory.items.first(where: { $0.id == entry.id })?.readiness == .needsPermission {
                allowRequested.insert(entry.id)
            }
            Task { await runner.start(entry.id, effects: effects) }
        } else {
            allowRequested.remove(entry.id)
            Task { await runner.stop(entry.id, effects: effects) }
        }
    }

    private func startDrops(_ ids: [String]) {
        guard ownerSaved else { return }
        let effects = self.effects
        for id in ids {
            guard let drop = intake.welcomeDrops.first(where: { $0.id == id }) else { continue }
            Task {
                await runner.start(.dropped(id), title: IntakeSummary.previewTitle(drop.preview),
                                   origin: drop.preview.origin ?? "", effects: effects)
            }
        }
    }

    private func startGranted(_ items: [FoundItem]) {
        let running = Set(runner.rows.filter { row in
            switch row.value {
            case .working, .on: true
            case .off, .needsAction, .failed: false
            }
        }.keys)
        for id in ImportTicks.startsAfterGrant(items: items, allowRequested: allowRequested, started: running) {
            if let entry = entries.first(where: { $0.id == id }) { tick(entry, true) }
            allowRequested.remove(id)
        }
    }

    private func setUpLater() {
        guard ownerSaved || OnboardingFlow.canStart(name: name) else { editingName = true; return }
        run(OnboardingFlow.laterSteps(name: name, ownerSaved: ownerSaved))
    }

    /// Seam 2 — the demo is `SetupRunner.demoPlan`, unchanged; T-Demo makes it richer.
    private func tryDemo() { run(SetupRunner.demoPlan) }

    /// R-OB15 — mark, record the agents Cicada saw connect, offer the tour (seam 3), Home.
    private func openCicada() {
        run(OnboardingFlow.finishSteps(recorded: OnboardingFlow.recordedAgents(connected: live.connected)))
    }

    private func run(_ plan: [StartStep]) {
        guard !busy else { return }
        busy = true
        failure = nil
        let effects = self.effects
        Task {
            await runner.run(plan, effects: effects)
            busy = false
            if case .failed(let why) = runner.phase { failure = why }
        }
    }

    private func exit() {
        if seeHow != nil { seeHow = nil; return }
        if mode == .rerun { closeRerun() }
    }

    /// R-OB19 — a rerun's Close marks the bank again once something changed (`OnboardingFlow.closeSteps`).
    private func closeRerun() { run(OnboardingFlow.closeSteps(ownerSaved: ownerSaved)) }

    private func load() async {
        owner = try? await APIClient.shared.fetchOwnerSettings()
        // A name typed while the GET was in flight wins over the prefill.
        if name.isEmpty { name = WelcomeName.initial(saved: owner?.name, fullUserName: NSFullUserName()) }
        editingName = !OnboardingFlow.canStart(name: name)
        if engineVM.response == nil { Task { await engineVM.load() } }
        browsers = await Task.detached(priority: .userInitiated) { BrowserInventory.live() }.value
        memoryRoot = (try? await APIClient.shared.fetchHealth())?.memoryRoot
        await inventory.refresh()
    }
}

/// "Step n of 6 · k still coming in" and Set up later (R-OB1). The segments link to any page already reached, never
/// past Get started (`OnboardingNav.canJump`). Below the titlebar band, never in it (R-OB23).
private struct OnboardingTopbar: View {
    let page: OnboardingPage
    let furthest: OnboardingPage
    let ownerSaved: Bool
    let comingIn: Int
    let trailing: String
    let onJump: (OnboardingPage) -> Void
    let onTrailing: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.scaled(4)) {
                ForEach(OnboardingPage.allCases, id: \.self) { p in
                    Button { onJump(p) } label: {
                        Capsule()
                            .fill(p == page ? CicadaTheme.textPrimary
                                  : (p <= furthest ? CicadaTheme.textTertiary : CicadaTheme.bgSelected))
                            .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(3))
                            .frame(height: CicadaTheme.scaled(20))
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.cicadaPlain)
                    .disabled(!OnboardingNav.canJump(to: p, furthest: furthest, ownerSaved: ownerSaved))
                    .accessibilityLabel(Copy.onboardingStepOf(p.step))
                }
            }
            Text(Copy.onboardingStepOf(page.step)).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            if comingIn > 0 {
                Text("·").font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                ProgressView().controlSize(.mini)
                Text(Copy.onboardingComingIn(comingIn)).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary).monospacedDigit()
            }
            Spacer()
            TextButton(title: trailing, action: onTrailing)
        }
        .frame(height: CicadaTheme.scaled(OnboardingLayout.topbarHeight))
        .padding(.leading, CicadaTheme.scaled(OnboardingLayout.columnPadding))
        .padding(.trailing, CicadaTheme.spacingLG)
        .accessibilityElement(children: .contain)
    }
}
