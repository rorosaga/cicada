import AppKit
import SwiftUI

/// Track I part b (design §4.1, spec decision 14, G117) — the Welcome: one
/// screen, replacing the four-step first-run sheet. A painted meadow band
/// (`WelcomeHero`), a card that rises into its grass carrying every word — the
/// greeting, what was found, the chat drop zone and who reads — and a footer
/// pinned outside the card's scroll view with the one action, *Start
/// remembering*, and the line that says exactly what Start will do.
///
/// It decides nothing itself. The name rule is `WelcomeName`, the ticks
/// `WelcomeTicks`, the geometry `WelcomeLayout`, the start line
/// `FoundPolicy.startSummary` over exactly the ticked set, and Start is
/// `SetupRunner` executing `OnboardingFlow.plan` (R-IB14) — all tested without a
/// window. Nothing is written and nothing is read before Start (R-IB12): the
/// only side effects before it are the re-probe and System Settings opening for
/// an Allow… the person clicked.
///
/// `mode` is `.firstRun` or `.rerun` (Settings → General → Run setup again,
/// R-IB16): a rerun reads *Save changes*, hides the demo, and Close and Esc
/// dismiss it; on first run Esc does nothing, so a stray key never skips setup.
struct WelcomeView: View {
    let mode: OnboardingMode
    let dropTargeted: Bool
    let onShowHome: () -> Void
    let onClose: () -> Void

    @Environment(Store.self) private var store
    @Environment(SetupRunner.self) private var runner
    @Environment(LocalInventory.self) private var inventory
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(IntakeRouter.self) private var intake
    @Environment(SleepEngineViewModel.self) private var engineVM

    @State private var name = ""
    /// The loaded owner — its handle and email ride back on the PUT, because
    /// the route clears what is omitted (R-IB14).
    @State private var owner: OwnerSettings?
    @State private var editingName = false
    @FocusState private var nameFocused: Bool
    @AccessibilityFocusState private var headlineFocused: Bool
    @State private var ticked: Set<FoundItemID> = []
    @State private var touched: Set<FoundItemID> = []
    @State private var allowRequested: Set<FoundItemID> = []
    @State private var droppedTicked: Set<String> = []
    @State private var pick: String?
    @State private var starting = false
    @State private var ownerError: String?
    @State private var revealed = false

    var body: some View {
        GeometryReader { geo in
            let scale = CGFloat(CicadaTheme.uiScale)
            let band = WelcomeLayout.bandHeight(windowHeight: geo.size.height, scale: scale)
            let cardTop = WelcomeLayout.cardTop(windowHeight: geo.size.height, scale: scale)
            let cardWidth = WelcomeLayout.cardWidth(windowWidth: geo.size.width, scale: scale)
            let gutter = WelcomeLayout.gutter * scale
            ZStack(alignment: .top) {
                CicadaTheme.background.ignoresSafeArea()
                WelcomeHero().frame(height: band)
                VStack(spacing: 0) {
                    Color.clear.frame(height: cardTop)
                    // The card scrolls inside itself; the gutter inside the
                    // scroll view keeps the card's shadow from being clipped
                    // and never widens past the window (`cardWidth` already
                    // leaves a gutter each side).
                    ScrollView {
                        card
                            .padding(.horizontal, gutter)
                            .padding(.bottom, gutter)
                    }
                    .scrollBounceBehavior(.basedOnSize)
                    .frame(width: min(cardWidth + 2 * gutter, geo.size.width))
                    // Pinned OUTSIDE the scroll view (R-IB11, the G130 lesson):
                    // the one way forward is never the first thing to clip.
                    footer
                        .frame(maxWidth: .infinity)
                        .frame(height: CicadaTheme.scaled(WelcomeLayout.footerHeight))
                        .background(CicadaTheme.background)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .onExitCommand { if mode == .rerun { onClose() } }
        .task { await load() }
        // W5 — a Full Disk Access grant lands while Cicada is in the background:
        // re-probe on return so the Allow… row ticks itself.
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task { await inventory.refresh() }
        }
        .onChange(of: inventory.items) { old, new in
            ticked = WelcomeTicks.reconcile(items: new, current: ticked, touched: touched,
                                            allowRequested: allowRequested)
            announceGrants(old: old, new: new)
        }
        // W11 — the drop was the act: a newly staged export arrives ticked.
        .onChange(of: intake.welcomeDrops.map(\.id)) { old, new in
            for id in new where !old.contains(id) { droppedTicked.insert(id) }
            droppedTicked.formIntersection(new)
        }
        // ⌘⇧I and the menu bar's *Import a file…* while the Welcome shows (R-IB15).
        // Deferred a turn: a modal panel must not run inside a view update.
        .onChange(of: intake.welcomeChooseRequest) { _, _ in
            Task { @MainActor in WelcomeChecklist.chooseFile(intake) }
        }
        .onChange(of: editingName) { _, editing in
            // The field exists only once this update lands, so focus it after.
            if editing { Task { @MainActor in nameFocused = true } }
        }
    }

    // MARK: The card

    private var card: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            headline
            WelcomeChecklist(ticked: $ticked, touched: $touched, allowRequested: $allowRequested,
                             droppedTicked: $droppedTicked, pick: $pick, revealed: revealed,
                             dropTargeted: dropTargeted)
        }
        .padding(CicadaTheme.spacingXL)
        .frame(maxWidth: .infinity, alignment: .leading)
        // Content, not chrome: `surface`, never glass (R-M5). The toast's soft
        // shadow (`ContentView.toastBanner`) so the card reads as lifted off
        // the painting without a border.
        .background(CicadaTheme.surface,
                    in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous))
        .shadow(color: .black.opacity(0.25), radius: 10, y: 3)
    }

    /// The headline block is the card's own first section, so no word ever
    /// sits on paint (R-IB11). Display type only through `displayFont`, so the
    /// Track F1 face switch lands here with no edit.
    private var headline: some View {
        let first = WelcomeName.firstWord(name)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if editingName {
                TextField(Copy.welcomeYourName, text: $name)
                    .textFieldStyle(.roundedBorder)
                    .font(CicadaTheme.font(size: 22))
                    .focused($nameFocused)
                    .onSubmit { if OnboardingFlow.canStart(name: name) { editingName = false } }
                    .accessibilityLabel(Copy.welcomeYourName)
            } else {
                Text(first.isEmpty ? Copy.welcomeHelloNoName : Copy.welcomeHello(first))
                    .font(CicadaTheme.displayFont(size: 40))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityFocused($headlineFocused)
            }
            Text(Copy.welcomeFound)
                .font(CicadaTheme.displayFont(size: 28, italic: true))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.welcomeSubline)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            // W7 — the prefill came from the Mac account; one click corrects it.
            if !first.isEmpty && !editingName {
                Button(Copy.welcomeNotYou(first)) { beginEditingName() }
                    .buttonStyle(.link)
                    .font(CicadaTheme.captionFont)
            }
            // W15 — the owner save failed: nothing ran, and it says why here.
            if let ownerError {
                Text(ownerError)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // MARK: The footer

    /// On plain `background`, never the grass: the pixel worm stands on ground
    /// (R9 §5.3), and the start line is Start's text twin.
    private var footer: some View {
        let canStart = OnboardingFlow.canStart(name: name)
        return HStack(spacing: CicadaTheme.spacingMD) {
            BookwormView(state: store.intakeInFlight ? .reading : .awake, pointSize: 48)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                MeadowPill(title: starting ? Copy.welcomeStarting
                               : (mode == .rerun ? Copy.welcomeSaveChanges : Copy.welcomeStart),
                           isBusy: starting, action: start)
                    // Return starts — except while the name is being typed, where
                    // it only confirms the name: the checklist is the consent, and
                    // a Return meant for the field must not accept it unseen.
                    .keyboardShortcut(editingName ? nil : KeyboardShortcut.defaultAction)
                    .disabled(!canStart)
                Text(canStart ? FoundPolicy.startSummary(tickedItems) : Copy.welcomeAddName)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: CicadaTheme.spacingMD) {
                    if mode == .rerun {
                        secondary(Copy.welcomeClose, action: onClose)
                    } else {
                        secondary(Copy.welcomeTryDemo, action: tryDemo)
                        secondary(canStart ? Copy.welcomeSetUpLater : Copy.welcomeSetUpLaterNeedsName,
                                  action: setUpLater)
                    }
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
    }

    private func secondary(_ title: String, action: @escaping () -> Void) -> some View {
        Button(title, action: action)
            .buttonStyle(.cicadaPlain)
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .disabled(starting)
    }

    // MARK: What Start runs

    /// Exactly the set Start runs, in the order it runs it — so the line never
    /// promises a row Start skips.
    private var tickedItems: [FoundItem] {
        FoundPolicy.order(inventory.items).filter { ticked.contains($0.id) }
            + tickedDrops.map(WelcomeChecklist.foundItem)
    }

    private var tickedDrops: [WelcomeDrop] { intake.welcomeDrops.filter { droppedTicked.contains($0.id) } }

    private var effects: LiveSetupEffects {
        LiveSetupEffects(store: store, engineVM: engineVM,
                         deps: .live(inventory: inventory, watcher: watcher, intake: intake),
                         owner: owner, onShowHome: onShowHome, onClose: onClose,
                         onChecklistChanged: runner.checklistChanged)
    }

    /// W14 — Start: the owner first and alone, then the engine if one was
    /// clicked, the record, Home; the ticked rows then run side by side and
    /// report to Getting started (R-IB14). A dropped export's title and origin
    /// are captured now — the router forgets the drop once it is committed.
    private func start() {
        guard OnboardingFlow.canStart(name: name), !starting else { return }
        let drops = tickedDrops
        let startIDs = FoundPolicy.order(inventory.items).map(\.id).filter(ticked.contains)
            + drops.map { FoundItemID.dropped($0.id) }
        var titles: [FoundItemID: String] = [:]
        var origins: [FoundItemID: String] = [:]
        for drop in drops {
            titles[.dropped(drop.id)] = IntakeSummary.previewTitle(drop.preview)
            origins[.dropped(drop.id)] = drop.preview.origin ?? ""
        }
        let plan = OnboardingFlow.plan(name: name, pickedEngine: pick, ticked: startIDs, mode: mode)
        if !startIDs.isEmpty {
            AccessibilityNotification.Announcement(Copy.welcomeSettingUp(startIDs.count)).post()
        }
        run(plan, titles: titles, origins: origins)
    }

    /// R-IB16 — saves the name (G117 R1: it is the observer), marks the bank,
    /// records an empty checklist and lands on Home, where Getting started lists
    /// what was found under *Also found*. Without a name it asks for one.
    private func setUpLater() {
        guard OnboardingFlow.canStart(name: name) else { beginEditingName(); return }
        guard !starting else { return }
        run(OnboardingFlow.plan(name: name, pickedEngine: nil, ticked: [], mode: .setUpLater))
    }

    /// The demo, then Home — the front door is the same for everyone. A failure
    /// keeps the Welcome up with its reason.
    private func tryDemo() {
        guard !starting else { return }
        run(SetupRunner.demoPlan)
    }

    /// The runner is app-lifetime: once Home shows, this view is gone but the
    /// rows keep reporting to Getting started. Only a failure before Home (the
    /// owner PUT, the demo) comes back here.
    private func run(_ plan: [StartStep], titles: [FoundItemID: String] = [:],
                     origins: [FoundItemID: String] = [:]) {
        ownerError = nil
        starting = true
        let effects = self.effects
        Task {
            await runner.run(plan, titles: titles, origins: origins, effects: effects)
            starting = false
            if case .failed(let why) = runner.phase { ownerError = why }
        }
    }

    /// Opens the name field and focuses it; already open, it only focuses —
    /// `onChange(of: editingName)` would not fire for a value that did not move.
    private func beginEditingName() {
        if editingName { nameFocused = true } else { editingName = true }
    }

    // MARK: Load

    private func load() async {
        owner = try? await APIClient.shared.fetchOwnerSettings()
        // A name typed while the GET was in flight wins over the prefill.
        if name.isEmpty {
            name = WelcomeName.initial(saved: owner?.name, fullUserName: NSFullUserName())
        }
        editingName = !OnboardingFlow.canStart(name: name)
        // W1 — focus lands on the greeting (or the name field when there is none).
        if !editingName { headlineFocused = true }
        if engineVM.response == nil { Task { await engineVM.load() } }
        // The shared inventory may already know this Mac (Getting started and
        // the `+` strip probe it too): show that at once, then re-probe — the
        // wiring check can take seconds, and `onChange(of: items)` re-ticks.
        ticked = WelcomeTicks.reconcile(items: inventory.items, current: ticked, touched: touched,
                                        allowRequested: allowRequested)
        revealed = true
        await inventory.refresh()
    }

    /// W5 — a row whose Allow… the person clicked says so when the grant lands.
    private func announceGrants(old: [FoundItem], new: [FoundItem]) {
        let granted = new.contains { item in
            allowRequested.contains(item.id) && item.readiness == .ready
                && old.first { $0.id == item.id }?.readiness != .ready
        }
        if granted { AccessibilityNotification.Announcement(Copy.welcomeAllowed).post() }
    }
}
