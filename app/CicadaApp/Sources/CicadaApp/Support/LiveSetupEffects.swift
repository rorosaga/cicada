import Foundation

enum SetupError: LocalizedError {
    case engine(String)
    var errorDescription: String? { if case .engine(let why) = self { return why }; return nil }
}

/// The real `SetupEffects` (R-IB14). The owner PUT carries the loaded handle and
/// email back, because `PUT /settings/owner` writes what it is given and clears
/// what is omitted (`api/routers/settings.py`). `markOnboarded` and every
/// per-bank write read `store.bank` at execution — the LIVE bank, the lesson
/// `FirstRunSheet.finish` carried (a demo switch happens mid-plan).
@MainActor
struct LiveSetupEffects: SetupEffects {
    let store: Store
    let engineVM: SleepEngineViewModel
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

    /// `SleepEngineViewModel.set` never throws — it sets `errorMessage` — so the
    /// failure is read back from there and becomes one line on the *Who reads*
    /// row rather than stopping Start (R-IB14).
    func saveEngine(_ candidateId: String) async throws {
        let model = engineVM.response?.candidates.first { $0.id == candidateId }?.models.first
        engineVM.errorMessage = nil
        await engineVM.set(mode: candidateId, model: model, disambiguationModel: nil)
        if let why = engineVM.errorMessage { throw SetupError.engine(why) }
        await store.refresh([.connections])
    }

    func markOnboarded() { OnboardingState.markOnboarded(bank: store.bank) }

    func recordGettingStarted(_ ids: [FoundItemID]) {
        GettingStartedState.record(bank: store.bank, enabled: ids)
        // R-HO15 — the Welcome's Start arms *Make it yours*; the demo plan never records Getting started.
        AppearanceTipPolicy.arm()
        onChecklistChanged()
    }

    func showHome() { onShowHome() }
    func close() { onClose() }

    func createDemoBank() async throws {
        _ = try await APIClient.shared.createDemoBank()
        await store.refresh([.banks])
    }

    func turnOn(_ id: FoundItemID) async -> FoundTurnOnResult { await FoundTurnOn.run(id, deps: deps) }

    func settle(_ id: FoundItemID) {
        GettingStartedState.settle(id, bank: store.bank)
        onChecklistChanged()
    }
}
