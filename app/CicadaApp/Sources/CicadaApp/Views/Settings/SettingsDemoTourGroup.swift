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

    private var inDemo: Bool { DemoMode.isActive(store.banks.value) }

    /// Round 1 (ROR-118): four action tiles in one strip, each a glyph over its own words, instead of three rows of
    /// plain text (the row titles repeated their buttons). Each tile is its row's landing anchor.
    var body: some View {
        // Round 2 (ROR-118): one card of four cells divided by hairlines, not four floating tiles of equal weight.
        HStack(spacing: 0) {
            // DR-40 — neutral, no primary.
            SetupTile(systemImage: "arrow.counterclockwise", title: Copy.runSetupAgain) {
                OnboardingState.reset(bank: store.bank)
                router.requestFirstRun()
            }
            .settingsRow(.runSetup)
            // R-IB17 — the checklist is re-openable, beside Run setup again so G139's index lands on both.
            SetupTile(systemImage: "checklist", title: Copy.gsShowChecklist) {
                GettingStartedState.showChecklist(bank: store.bank)
                // A card already seen done this session would otherwise reopen as "You're set up."
                runner.sawDoneThisSession = false
                runner.checklistChanged()
                router.pendingTab = .home
                router.activateMainWindow()
            }
            .columnEdge()
            SetupTile(systemImage: "map", title: Copy.Tour.offerTake) {
                router.closeSettings()
                tour.requestStart()
            }
            .columnEdge()
            .settingsRow(.guidedTour)
            SetupTile(systemImage: "sparkles", title: inDemo ? Copy.Demo.leaveDemo : Copy.Demo.exploreDemo,
                      isDisabled: busy) {
                inDemo ? leave() : enter()
            }
            .columnEdge()
            .settingsRow(.demoMemory)
        }
        .settingsCardSurface()
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

/// One cell of the Getting started card: a glyph over its words; the pointer lights its own cell (DR-48); neutral like
/// every Settings button (DR-40).
private struct SetupTile: View {
    let systemImage: String
    let title: String
    var isDisabled = false
    let action: () -> Void
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            VStack(spacing: CicadaTheme.scaled(10)) {
                Image(systemName: systemImage)
                    .font(CicadaTheme.font(size: 22, weight: .medium))
                    .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                Text(title)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(108))
            .rowHoverFill(hovering: hovering, cornerRadius: CicadaTheme.cornerRadius)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .disabled(isDisabled)
        .opacity(isDisabled ? NeutralButton.disabledOpacity : 1)
    }
}
