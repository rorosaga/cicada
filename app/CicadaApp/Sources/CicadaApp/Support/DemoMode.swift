import Foundation

/// G117 round 4 (T-Demo, F-08) — the demo is a bank like any other. It is entered through `SetupRunner.demoPlan`
/// (seam 2: the Welcome's *Try the demo* and Settings → General run the same plan) and left through the banner's
/// *Finish setting up*. Which bank is the demo is the server's answer — `/banks` rows carry `demo`, read from
/// `demo_guard.is_demo`, never from the name (a person may call a real bank "demo", R-CS10).
enum DemoMode {
    /// True while the active bank is a demo. Unknown (no roster yet) is never the demo, so a cold launch never
    /// flashes the banner over a real bank.
    static func isActive(_ roster: BanksResponse?) -> Bool {
        guard let roster, let active = roster.active else { return false }
        return roster.banks.first { $0.name == active }?.demo == true
    }

    /// True once the demo is the bank the whole app SHOWS: the roster names it active AND `Store.bank` has caught up.
    /// `Store.refresh([.banks])` assigns the roster, then awaits `hydrate(bank:)` before it moves `Store.bank`; in that
    /// gap the roster already says "demo" while every page still shows the bank being left. A tour auto-started there
    /// was stamped with the old bank, interrupted a beat later by the very switch it started for, and had already spent
    /// `cicada.tour.demoStarted` — so the demo's one automatic tour never showed (plan critic, 2026-09-24).
    static func isShowing(_ roster: BanksResponse?, bank: String) -> Bool {
        isActive(roster) && roster?.active == bank
    }

    /// The name of the demo bank on this Mac, if one exists.
    static func demoBank(in roster: BanksResponse?) -> String? {
        roster?.banks.first { $0.demo }?.name
    }

    /// What leaving does in the world — injected so the order is tested without a window (`SetupEffects`' precedent).
    struct ExitEffects {
        var flushHeld: @MainActor () async -> Void
        var leaveDemo: @MainActor () async throws -> BanksResponse
        var refreshBanks: @MainActor () async -> Void
        var resetOnboarding: @MainActor (String) -> Void
        var openOnboarding: @MainActor () -> Void
    }

    enum ExitOutcome: Equatable {
        case left(String)
        case stayed
        case failed(String)
    }

    /// *Finish setting up* (F-08). A held Inbox answer is sent first — it belongs to the demo (R-DI3, every switch
    /// path does this). The server switches to the real bank left most recently, or makes one; the roster is re-read
    /// so every domain hydrates that bank; then onboarding opens through the ONE door, seam 1 —
    /// `OnboardingState.reset(bank:)` + `AppRouter.requestFirstRun()` — for the bank the server landed on, never the
    /// demo's name (the flag is per bank, and resetting the demo's would reopen nothing).
    ///
    /// `openSetup: false` is Settings → General's *Back to your memory*: the same switch, but it neither clears the
    /// landing bank's `cicada.hasOnboarded` flag nor opens the Welcome. That door is reached from a set-up install, and
    /// sending it into setup broke the label's promise — and a quit partway through reopened the person's own bank on
    /// the Welcome (r4-demo final review, finding 2). A bank that was never set up still meets `FirstRunGate`.
    @MainActor
    static func leave(_ fx: ExitEffects, openSetup: Bool = true) async -> ExitOutcome {
        await fx.flushHeld()
        let roster: BanksResponse
        do {
            roster = try await fx.leaveDemo()
        } catch {
            return .failed(SetupRunner.describe(error))
        }
        guard let bank = roster.active, !isActive(roster) else { return .stayed }
        await fx.refreshBanks()
        if openSetup {
            fx.resetOnboarding(bank)
            fx.openOnboarding()
        }
        return .left(bank)
    }

    @MainActor
    static func liveExit(store: Store, router: AppRouter, graph: GraphViewModel) -> ExitEffects {
        ExitEffects(
            flushHeld: { await store.flushHeld() },
            leaveDemo: { try await APIClient.shared.leaveDemo() },
            // `BankSwitcher.switchTo`'s pair: the roster, then the graph's own reload.
            refreshBanks: { await store.refresh([.banks]); await graph.loadGraph() },
            resetOnboarding: { OnboardingState.reset(bank: $0) },
            openOnboarding: { router.requestFirstRun() })
    }

    /// Settings → General's *Explore the demo*: seam 2's plan, unchanged — the same `SetupRunner.demoPlan` the
    /// Welcome runs (`POST /banks/demo` re-opens a demo that already exists). A held answer is sent first, like every
    /// switch. Returns the failure's sentence, or nil.
    @MainActor
    static func enter(runner: SetupRunner, effects: SetupEffects, flushHeld: @MainActor () async -> Void) async -> String? {
        await flushHeld()
        await runner.run(SetupRunner.demoPlan, effects: effects)
        if case .failed(let why) = runner.phase { return why }
        return nil
    }
}

/// G117 round 4 — the demo's known ids: the ones the guided tour opens inside the demo, and nowhere else (in a real
/// bank the tour never picks a person or a project for the person, ruling R-DT7). Pinned to the generator by
/// `api/tests/fixtures/demo_showcase.json` (`DemoModeTests`, `test_demo_showcase.py`).
enum DemoShowcase {
    static let person = "leo-example"
    static let project = "rover-arm-project"
}
