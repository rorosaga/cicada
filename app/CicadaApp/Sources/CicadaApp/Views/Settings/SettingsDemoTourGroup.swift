import SwiftUI

/// Settings → General's *Getting to know Cicada* (G152, G117 round 4): the guided tour's replay, and the demo's door —
/// *Explore the demo* runs seam 2's `SetupRunner.demoPlan` (the Welcome's own plan; the server re-opens a demo that
/// exists), and inside the demo the row says so and offers the banner's way back. Its own view so the General page
/// gains one line (the onboarding track edits that page in parallel). Text buttons (DR-40): Settings has no primary.
///
/// Hyrum audit B12 (2026-10-22): *Run setup again* and *Show setup checklist* joined it from General's Setup card, under
/// one header, *Getting started* (DR-37: one job, one card).
struct SettingsDemoTourGroup: View {
    @Environment(AppRouter.self) private var router
    @Environment(Store.self) private var store
    @Environment(TourController.self) private var tour
    @Environment(SetupRunner.self) private var runner
    @Environment(LocalInventory.self) private var inventory
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(IntakeRouter.self) private var intake
    @Environment(GraphViewModel.self) private var graphVM
    @State private var busy = false
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var inDemo: Bool { DemoMode.isActive(store.banks.value) }

    /// Round 5 (ROR-118): the four actions are one row, *Getting started*, whose whole width opens a menu (a chevron at its
    /// trailing edge, as a value row has). Rounds 1-4 drew them as tiles, a strip, loose buttons and a bar; judges read
    /// every one as onboarding clutter on a settings page, and a rarely used action needs no standing control. Each
    /// item is the old button, unchanged, and the row keeps all three landing anchors. Neutral, no primary (DR-40).
    var body: some View {
        Menu {
            Button { rerunSetup() } label: { Label(Copy.runSetupAgain, systemImage: "arrow.counterclockwise") }
            // R-IB17 — the checklist is re-openable, beside Run setup again so G139's index lands on both.
            Button { showChecklist() } label: { Label(Copy.gsShowChecklist, systemImage: "checklist") }
            Button { router.closeSettings(); tour.requestStart() } label: { Label(Copy.Tour.offerTake, systemImage: "map") }
            Button { inDemo ? leave() : enter() } label: {
                Label(inDemo ? Copy.Demo.leaveDemo : Copy.Demo.exploreDemo, systemImage: "play.circle")
            }
            .disabled(busy)
        } label: {
            HStack(spacing: CicadaTheme.spacingMD) {
                Text(Copy.Demo.settingsGroup)
                    .font(CicadaTheme.font(size: 15, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer(minLength: CicadaTheme.scaled(16))
                Image(systemName: "chevron.up.chevron.down")
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.trailing, CicadaTheme.scaled(6))
            }
            .padding(.vertical, CicadaTheme.spacingSM + CicadaTheme.scaled(2))
            .padding(.horizontal, CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(48), alignment: .leading)
            .background(hovering ? CicadaTheme.bgButtonHover : Color.clear)
            .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.cicadaPlain)
        .menuIndicator(.hidden)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .settingsRow(.runSetup)
        .settingsRow(.guidedTour)
        .settingsRow(.demoMemory)
    }

    private func rerunSetup() {
        OnboardingState.reset(bank: store.bank)
        router.requestFirstRun()
    }

    private func showChecklist() {
        GettingStartedState.showChecklist(bank: store.bank)
        // A card already seen done this session would otherwise reopen as "You're set up."
        runner.sawDoneThisSession = false
        runner.checklistChanged()
        router.pendingTab = .home
        router.activateMainWindow()
    }

    /// `GettingStartedCard`'s effects, with Home as the landing — the demo plan ends on `.showHome`.
    private var effects: LiveSetupEffects {
        LiveSetupEffects(store: store,
                         deps: .live(inventory: inventory, watcher: watcher, intake: intake),
                         onShowHome: { router.pendingTab = .home },
                         onChecklistChanged: runner.checklistChanged)
    }

    private func enter() {
        busy = true
        router.closeSettings()
        let effects = self.effects
        Task {
            if let why = await DemoMode.enter(runner: runner, effects: effects, flushHeld: { await store.flushHeld() }) {
                store.toast = why
            }
            busy = false
        }
    }

    /// The tour belongs to the demo it was showing, so it ends first — the banner's *Finish setting up* rule. Unlike
    /// the banner, this door does what its label says — back to the person's memory, never into setup (`openSetup:
    /// false`; r4-demo final review, finding 2).
    private func leave() {
        busy = true
        tour.interrupt()
        Task {
            let outcome = await DemoMode.leave(DemoMode.liveExit(store: store, router: router, graph: graphVM),
                                               openSetup: false)
            if let why = DemoMode.leaveToast(outcome) { store.toast = why }
            busy = false
        }
    }
}
