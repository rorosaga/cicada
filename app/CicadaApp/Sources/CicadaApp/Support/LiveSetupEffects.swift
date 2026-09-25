import Foundation

/// The real `SetupEffects` (R-IB14). The owner PUT carries the loaded handle and
/// email back, because `PUT /settings/owner` writes what it is given and clears
/// what is omitted (`api/routers/settings.py`). `markOnboarded` and every
/// per-bank write read `store.bank` at execution — the LIVE bank, the lesson
/// `FirstRunSheet.finish` carried (a demo switch happens mid-plan).
@MainActor
struct LiveSetupEffects: SetupEffects {
    let store: Store
    let deps: FoundTurnOnDeps
    var owner: OwnerSettings? = nil
    /// `@MainActor` so a main-actor method reference (`runner.checklistChanged`)
    /// converts without losing its isolation.
    var onShowHome: @MainActor () -> Void = {}
    var onClose: @MainActor () -> Void = {}
    /// `SetupRunner.checklistChanged` — every record write re-renders Home.
    var onChecklistChanged: @MainActor () -> Void = {}

    /// The route writes what it is given and CLEARS what is omitted, so a Welcome
    /// whose own GET failed re-reads handle and email here rather than wipe them;
    /// if that read fails too, the backend is down and the PUT fails with it.
    func saveOwner(_ name: String) async throws {
        var current = owner
        if current == nil { current = try? await APIClient.shared.fetchOwnerSettings() }
        _ = try await APIClient.shared.updateOwnerSettings(name: name, handle: current?.handle, email: current?.email)
    }

    func markOnboarded() { OnboardingState.markOnboarded(bank: store.bank) }

    func recordGettingStarted(_ ids: [FoundItemID]) {
        GettingStartedState.record(bank: store.bank, enabled: ids)
        onChecklistChanged()
    }

    /// Called by `SetupRunner` for the Welcome's plans only — never from Home's card (R-HO15).
    func armAppearanceTip() { AppearanceTipPolicy.arm() }

    func showHome() { onShowHome() }
    func close() { onClose() }

    func createDemoBank() async throws {
        _ = try await APIClient.shared.createDemoBank()
        await store.refresh([.banks])
    }

    func turnOn(_ id: FoundItemID) async -> FoundTurnOnResult { await FoundTurnOn.run(id, deps: deps) }

    /// R-OB8 — untick through the one turn-on's twin, so a browser, Calendar and Wispr Flow stop the same way from
    /// every host.
    func turnOff(_ id: FoundItemID) async { await FoundTurnOn.stop(id, deps: deps) }

    func forgetRecord(_ id: FoundItemID) {
        GettingStartedState.remove(id, bank: store.bank)
        onChecklistChanged()
    }

    /// Seam 3 — onboarding's Open Cicada asks; T-Demo's Home offer answers once.
    func requestTour() { TourOffer.request() }

    func settle(_ id: FoundItemID) {
        GettingStartedState.settle(id, bank: store.bank)
        onChecklistChanged()
    }
}
