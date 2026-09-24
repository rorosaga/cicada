import SwiftUI

/// Settings → General's *Getting to know Cicada* (G152, G117 round 4): the guided tour's replay, and the demo's door —
/// *Explore the demo* runs seam 2's `SetupRunner.demoPlan` (the Welcome's own plan; the server re-opens a demo that
/// exists), and inside the demo the row says so and offers the banner's way back. Its own view so the General page
/// gains one line (the onboarding track edits that page in parallel). Text buttons (DR-40): Settings has no primary.
struct SettingsDemoTourGroup: View {
    @Environment(AppRouter.self) private var router
    @Environment(Store.self) private var store
    @Environment(TourController.self) private var tour
    @Environment(SetupRunner.self) private var runner
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(LocalInventory.self) private var inventory
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(IntakeRouter.self) private var intake
    @Environment(GraphViewModel.self) private var graphVM
    @State private var busy = false

    private var inDemo: Bool { DemoMode.isActive(store.banks.value) }

    var body: some View {
        SettingsGroupCard(header: Copy.Demo.settingsGroup) {
            SettingsRow(.guidedTour, title: Copy.Tour.settingsTitle, detail: Copy.Tour.settingsDetail) {
                TextButton(title: Copy.Tour.offerTake) {
                    router.closeSettings()
                    tour.requestStart()
                }
            }
            SettingsDivider()
            SettingsRow(.demoMemory, title: Copy.Demo.demoTitle,
                        detail: inDemo ? Copy.Demo.demoActiveDetail : Copy.Demo.demoDetail) {
                TextButton(title: inDemo ? Copy.Demo.leaveDemo : Copy.Demo.exploreDemo) {
                    inDemo ? leave() : enter()
                }
                .disabled(busy)
            }
        }
    }

    /// `GettingStartedCard`'s effects, with Home as the landing — the demo plan ends on `.showHome`.
    private var effects: LiveSetupEffects {
        LiveSetupEffects(store: store, engineVM: engineVM,
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
            if case .failed = outcome { store.toast = Copy.Demo.leaveFailed }
            busy = false
        }
    }
}
