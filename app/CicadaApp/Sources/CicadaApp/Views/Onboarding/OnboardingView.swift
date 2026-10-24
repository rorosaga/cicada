import AppKit
import SwiftUI

/// Onboarding v2 (G217, G92, ruling 36; 2026-10-22; built on round 4 phase B, G145) — one full-window layer over the
/// shell (R-IB11's placement kept), six steps of one verb each: Welcome and Done are the study room over a card, and
/// *Meet your bookworm* (owner 2026-10-23) the menu-bar worm over a card (`MenuBarStep`); the
/// three working steps (Intelligence, Agents, Sources) are the split frame — the room in its pane (`OnboardingRoom`,
/// the one illustration, DR-13), then the column: the topbar ("Step n of 5 · k still coming in", Set up later), the
/// step, the foot (Back, a visible Skip, the one primary Continue with ⏎). It decides nothing itself: steps are
/// `OnboardingPage`, what each shows `OnboardingSteps`, geometry `OnboardingLayout`, button plans `OnboardingFlow` run
/// by `SetupRunner`, every source row and count `SetupProgress` (R-OB4). Continue on Welcome is the owner PUT alone
/// (R-OB2); after it a tick or a drop starts at once. The step reached is kept per bank (`OnboardingState.saveStep`),
/// so quitting mid-way resumes there. Esc closes See how, then — on a rerun only — the flow (R-OB19).
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
    /// Seam 4 — the Contacts row and Chrome's open tab-group sub-row start through their readers; optional like the
    /// calendar, so a host without them registers no driver and the row finishes in Integrations.
    @Environment(ContactsReader.self) private var contacts: ContactsReader?
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(SleepViewModel.self) private var sleepVM
    /// The menu-bar worm, introduced by *Meet your bookworm* (`MenuBarIntro`); optional, so a host without it (a test,
    /// a preview) still draws the step.
    @Environment(MenuBarManager.self) private var menuBar: MenuBarManager?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var page: OnboardingPage = .welcome
    @State private var furthest: OnboardingPage = .welcome
    @State private var ownerSaved = false
    @State private var name = ""
    @State private var owner: OwnerSettings?
    @State private var editingName = false
    @State private var busy = false
    @State private var failure: String?
    @State private var seeHow: ChatVendor?
    /// Held here, not by the Agents step, so Open Cicada records the agents it saw connect (R-OB13).
    @State private var live = AgentLiveProbe()
    @State private var browsers = BrowserInventory.empty
    @State private var allowRequested: Set<FoundItemID> = []
    @State private var pageShownAt = Date()
    @FocusState private var rootFocused: Bool

    private var apps: [String: AppSourceDriver] {
        AppSourceDrivers.live(calendar: calendar, local: local, store: store, contacts: contacts, tabGroups: tabGroups)
    }

    private var entries: [ImportEntry] {
        ImportCatalog.entries(ImportContext(browsers: browsers, wisprInstalled: local.wisprInstalled,
                                            wisprDictation: local.wisprSettings.includeDictation))
    }

    private var effects: LiveSetupEffects {
        LiveSetupEffects(store: store,
                         deps: .live(inventory: inventory, watcher: watcher, intake: intake, calendar: calendar,
                                     local: local, store: store, contacts: contacts, tabGroups: tabGroups,
                                     permissionPlace: { .onboarding(browser: $0) }),
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
                if page.isSplit, paneWidth > 0 {
                    pane(width: paneWidth, height: geo.size.height)
                }
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
        .onChange(of: intake.welcomeChooseRequest) { _, _ in Task { @MainActor in SourcesStep.chooseFile(intake) } }
        // R-OB7 — a Full Disk Access grant lands while Cicada is in the background.
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task { await inventory.refresh() }
        }
        .onChange(of: inventory.items) { _, items in startGranted(items) }
        .onChange(of: page) { _, next in
            furthest = max(furthest, next)
            pageShownAt = Date()
            // v3 — staged against the real app: while the step talks about the worm, the real one (already up there on
            // a rerun) says hello. A first run's worm says it on landing instead (`MenuBarManager.introduce`).
            if next == .menuBar { menuBar?.greet() }
            if next == .done { Task { await refreshReveal() } }
            // Resume where the person was if they quit mid-way — only once the name is saved (R-OB2).
            if ownerSaved, next != .welcome { OnboardingState.saveStep(next, bank: store.bank) }
        }
        // The name field took focus and gave it back on ⏎: return it to the root, so the next ⏎ is Get started.
        .onChange(of: editingName) { _, editing in if !editing { rootFocused = true } }
    }

    // MARK: The split frame

    /// The room in the working pages' pane, centred on a `bgPane` ground (one lightness step from the column, P-b).
    /// Art only: it rests while See how covers it, and no word sits on it (DR-13).
    private func pane(width: CGFloat, height: CGFloat) -> some View {
        OnboardingRoom(mood: page.roomMood, cell: OnboardingRoomLayout.paneCell(paneWidth: width))
            .frame(width: width, height: height)
            .background(CicadaTheme.bgPane.ignoresSafeArea())
            .environment(\.scenePaused, seeHow != nil)
    }

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
            // One scroll per step: the frame's single ScrollView kept the last step's offset, so the next step (and
            // Back) opened part-way down with its headline cut off under the topbar (QA 2026-10-16).
            .id(page)
            // Pinned outside the scroll (the G130 lesson): the way forward is never the first thing to clip.
            foot
                .padding(.horizontal, CicadaTheme.scaled(OnboardingLayout.columnPadding))
                .padding(.bottom, CicadaTheme.scaled(OnboardingLayout.footBottom))
        }
    }

    @ViewBuilder
    private func pageContent(width: CGFloat, snapshots s: [SetupRowSnapshot]) -> some View {
        switch page {
        case .intelligence: IntelligenceStep()
        case .agents: AgentsStep(live: live)
        case .sources:
            SourcesStep(imports: entries, snapshots: Dictionary(uniqueKeysWithValues: s.map { ($0.id, $0) }),
                        dropTargeted: dropTargeted,
                        needsAccess: Set(inventory.items.filter { $0.readiness == .needsPermission }.map(\.id)),
                        denied: deniedByMacOS,
                        onTick: tick, onSeeHow: { seeHow = $0 })
        case .welcome, .menuBar, .done: EmptyView()
        }
    }

    /// Back, a visible Skip on the working steps (design-refs pattern 12), and the one primary. Skip and Continue both
    /// move on and write nothing of their own: what a step changed, a click inside it already wrote.
    private var foot: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            TextButton(title: Copy.onboardingBack, flushLeading: true) {
                if let previous = page.previous { go(previous, .pointer) }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if page.skippable {
                TextButton(title: Copy.onboardingSkip) { advance(.pointer) }
            }
            PrimaryActionButton(title: Copy.onboardingContinue) { advance(.pointer) }
            KeyHint("⏎")
        }
    }

    /// Calendar and Contacts refused in macOS's own prompt (read from their readers' status — never asked again here).
    private var deniedByMacOS: Set<FoundItemID> {
        var out: Set<FoundItemID> = []
        if case .denied? = calendar?.status { out.insert(.app(AppSourceDrivers.calendar)) }
        if case .denied? = contacts?.status { out.insert(.app(AppSourceDrivers.contacts)) }
        return out
    }

    /// Done's reveal: the pages this memory already holds and the conversations waiting to be read, from the Store's
    /// live graph and the Sleep page's own queue — the person's own, never an example.
    private var reveal: DoneReveal {
        DoneReveal.of(pages: DoneReveal.pages(store.graph.value?.nodes ?? []),
                      waiting: sleepVM.queuedEpisodes.map { DoneReveal.Conversation(id: $0.id, title: $0.title,
                                                                                    origin: $0.origin) },
                      reading: sleepVM.isRunning)
    }

    /// Done shows what is there now: one read of the graph, the status and the queue. It starts nothing.
    private func refreshReveal() async {
        await store.refresh([.graph, .status])
        await sleepVM.load()
    }

    /// Done's one line (`DoneLine`) from the real schedule, both previews and what is still coming in — a rerun after
    /// a schedule was chosen reads that schedule, and a first run is never told "tonight" on a manual schedule.
    private func doneLine(_ snapshots: [SetupRowSnapshot]) -> String {
        let honesty = HonestyInputs.from(schedule: sleepVM.schedule, response: engineVM.response,
                                         connections: store.connections.value ?? [])
        return DoneLine.line(brought: DoneLine.brought(snapshots), canReadNow: DoneLine.canReadNow(engineVM.response),
                             scheduleLoaded: sleepVM.scheduleLoaded, honesty: honesty,
                             nowKey: DoneLine.nowKey(engineVM.response))
    }

    // MARK: Welcome and Done

    private func card(size: CGSize) -> some View {
        let width = OnboardingLayout.cardWidth(windowWidth: size.width, scale: CGFloat(CicadaTheme.uiScale))
        let content = Group {
            if page == .welcome {
                WelcomePage(mode: mode, name: $name, editingName: $editingName, busy: busy, failure: failure,
                            waitingDrops: ownerSaved ? 0 : intake.welcomeDrops.count,
                            onGetStarted: { advance(.pointer) }, onSetUpLater: mode == .rerun ? closeRerun : setUpLater,
                            onTryDemo: tryDemo)
            } else if page == .menuBar {
                MenuBarStep(waiting: store.status.value?.waitingForSleep,
                            shownInMenuBar: menuBar?.introPhase == .done && menuBar?.isVisible == true, busy: busy,
                            onBack: { go(.sources, .pointer) },
                            onSkip: { go(.done, .pointer) },
                            onContinue: { go(.done, .pointer) })
            } else {
                DonePage(line: doneLine(snapshots), reveal: reveal, waiting: store.status.value?.waitingForSleep,
                         busy: busy, onBack: { go(.menuBar, .pointer) },
                         onOpen: { frame in openCicada(.openCicadaByPointer, from: frame) })
            }
        }
        .frame(width: width)
        // The room over the card (owner 2026-10-16), as wide as the card allows; a whole number of points per cell.
        let room = OnboardingRoom(mood: page.roomMood, cell: OnboardingRoomLayout.cardCell(cardWidth: width))
            .environment(\.scenePaused, seeHow != nil)
        return VStack {
            Spacer(minLength: CicadaTheme.spacingLG)
            // A short window first drops the room (art only, DR-13), then scrolls the card with its actions inside it —
            // never clipped (G130).
            if page == .menuBar || page == .done {
                // The big menu-bar worm stands where the room stands (`MenuBarStep` and, since v3, `DonePage` draw it
                // over their own card): no room on these steps, so the worm is never one picture among two.
                ViewThatFits(in: .vertical) {
                    content
                    ScrollView { content }.scrollBounceBehavior(.basedOnSize)
                }
            } else {
                ViewThatFits(in: .vertical) {
                    VStack(spacing: CicadaTheme.scaled(OnboardingRoomLayout.cardGap)) { room; content }
                    content
                    ScrollView { content }.scrollBounceBehavior(.basedOnSize)
                }
            }
            Spacer(minLength: CicadaTheme.spacingLG)
        }
        .frame(maxWidth: .infinity)
        .padding(.bottom, CicadaTheme.scaled(OnboardingLayout.cardBottom))
    }

    // MARK: What the buttons do

    private func advance(_ input: OnboardingInput) {
        guard !busy, seeHow == nil else { return }
        switch page {
        case .welcome: getStarted(input)
        // ⏎ on Done: the worm is simply there, never flown (DR-60).
        case .done: openCicada(input == .keyboard ? .openCicadaByKey : .openCicadaByPointer, from: nil)
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
            go(.intelligence, input)
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

    /// R-OB15 — mark, record the agents Cicada saw connect, offer the tour (seam 3), Home. v3: the worm goes into the
    /// menu bar first — flown from Done by a pointer's Open Cicada, faded under Reduce Motion, simply there on ⏎
    /// (`OnboardingExit`); the window's close then finds it already introduced.
    private func openCicada(_ exit: OnboardingExit, from frame: CGRect?) {
        guard !busy else { return }
        menuBar?.introduce(exit.reveal(from: frame, reduceMotion: reduceMotion))
        // Owner 2026-10-22: once right after onboarding when the person brought something in — a run they started.
        if DoneLine.readsNow(brought: DoneLine.brought(snapshots), canReadNow: DoneLine.canReadNow(engineVM.response)) {
            let vm = sleepVM
            Task { await vm.triggerManually() }
        }
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
        // The schedule line (`OnboardingScheduleLine`) shows nothing until the schedule is known — Home's guard.
        if !sleepVM.scheduleLoaded { Task { await sleepVM.load() } }
        // A person who quit mid-way resumes on the step they reached, once their name is saved (Hyrum mode B:
        // `OnboardingPage(stored:)` maps every name a build stored). Welcome is never a resume point.
        if mode != .rerun, let saved = OnboardingState.savedStep(bank: store.bank),
           let savedName = owner?.name, OnboardingFlow.canStart(name: savedName) {
            ownerSaved = true
            furthest = saved
            page = saved
        }
        browsers = await Task.detached(priority: .userInitiated) { BrowserInventory.live() }.value
        await inventory.refresh()
        if page == .done { await refreshReveal() }
        resumePermissionTick()
    }

    /// v3 — Cicada was reopened from the drag helper (Full Disk Access waits for a fresh process): back on Sources,
    /// the browser whose tick asked is ticked again — it starts if the grant took, or shows the helper again.
    private func resumePermissionTick() {
        guard ownerSaved, let marker = PermissionResume.take(matching: \.isOnboarding) else { return }
        go(.sources, .keyboard)
        guard case .onboarding(let browser?) = marker.place,
              let entry = entries.first(where: { $0.id == .browser(browser) }) else { return }
        tick(entry, true)
    }
}

/// "Step n of 5 · k still coming in" and Set up later (R-OB1). The segments link to any page already reached, never
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
                // DR-43 (round 3, 2026-10-20): what is still arriving is said in words alone, never a spinner beside them.
                Text("·").font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
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
