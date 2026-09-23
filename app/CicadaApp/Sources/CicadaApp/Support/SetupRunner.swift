import Foundation
import Observation

/// What a Start step does in the world — injected so the order and the
/// failure rules are tested without a window (SetupRunnerTests).
@MainActor
protocol SetupEffects {
    func saveOwner(_ name: String) async throws
    func saveEngine(_ candidateId: String) async throws
    func markOnboarded()
    func recordGettingStarted(_ ids: [FoundItemID])
    func showHome()
    func close()
    func createDemoBank() async throws
    func turnOn(_ id: FoundItemID) async -> FoundTurnOnResult
    func settle(_ id: FoundItemID)
}

/// Track I part b (design §4.1.7, R-IB14) — executes part a's `OnboardingFlow`
/// plan. The owner PUT runs alone and first: it is the observer every later
/// write carries (G117 R1), so its failure stops everything. The sequential
/// steps end on Home before any row runs (Start costs one round trip); the rows
/// then run side by side, each reporting here, and a failure stays on its row.
/// App-lifetime, so a Welcome that has faded out keeps reporting to Home's
/// Getting started card.
@MainActor
@Observable
final class SetupRunner {
    enum Phase: Equatable { case idle, starting, failed(String), started }

    static let demoPlan: [StartStep] = OnboardingFlow.demoSteps + [.showHome]

    private(set) var phase: Phase = .idle
    private(set) var rows: [FoundItemID: FoundRowState] = [:]
    private(set) var refused: [FoundItemID: [String]] = [:]
    private(set) var detail: [FoundItemID: String] = [:]
    /// A dropped export's title ("ChatGPT history") and origin ("chatgpt-export",
    /// for its real mark), captured at Start — the router forgets the drop once
    /// it is committed.
    private(set) var titles: [FoundItemID: String] = [:]
    private(set) var origins: [FoundItemID: String] = [:]
    private(set) var engineError: String?
    /// "You're set up." shows for the rest of the session once, then the card hides.
    var sawDoneThisSession = false
    /// W14: after Start, VoiceOver focus moves to the Getting started heading —
    /// once. Held here, not in the card, because Home is rebuilt on every tab
    /// switch (R-IB3) and a view's own flag would move focus on every ⌘1.
    var movedFocusToChecklist = false
    /// Bumped after every `GettingStartedState` write, so Home and the card —
    /// which read the record straight from defaults in `body` (four keys) —
    /// re-render when it changes. Defaults are not observable; this is.
    private(set) var checklistRevision = 0

    func checklistChanged() { checklistRevision &+= 1 }

    /// ✕ on a dropped export's row: it lives only in this session's state, so
    /// dismissing it is forgetting it (R-IB17 — a drop is never persisted).
    func forget(_ id: FoundItemID) {
        rows[id] = nil
        refused[id] = nil
        detail[id] = nil
    }

    func run(_ plan: [StartStep], titles: [FoundItemID: String] = [:], origins: [FoundItemID: String] = [:],
             effects: SetupEffects) async {
        phase = .starting
        engineError = nil
        self.titles.merge(titles) { _, new in new }
        self.origins.merge(origins) { _, new in new }
        var turnOns: [FoundItemID] = []
        for step in plan {
            switch step {
            case .saveOwner(let name):
                do { try await effects.saveOwner(name) } catch { phase = .failed(Self.describe(error)); return }
            case .saveEngine(let id):
                do { try await effects.saveEngine(id) } catch { engineError = Copy.gsEngineFailed }
            case .markOnboarded:
                effects.markOnboarded()
            case .recordGettingStarted(let ids):
                effects.recordGettingStarted(ids)
            case .showHome:
                effects.showHome()
            case .close:
                effects.close()
            case .createDemoBank:
                do { try await effects.createDemoBank() } catch {
                    phase = .failed(Copy.welcomeDemoFailed(Self.describe(error)))
                    return
                }
            case .turnOn(let id):
                turnOns.append(id)
            }
        }
        for id in turnOns { rows[id] = .working(Self.workingText(id)) }
        phase = .started
        let tasks = turnOns.map { id in Task { @MainActor in await self.turnOn(id, effects: effects) } }
        for task in tasks { await task.value }
    }

    /// One row — Start's children and Getting started's Turn on / Retry alike.
    func turnOn(_ id: FoundItemID, effects: SetupEffects) async {
        rows[id] = .working(Self.workingText(id))
        refused[id] = nil
        switch await effects.turnOn(id) {
        case .on(let line):
            rows[id] = .on
            if let line { detail[id] = line }
        case .refused(let lines):
            rows[id] = nil
            refused[id] = lines
        case .failed(let why):
            rows[id] = .failed(why)
        case .needsPermission:
            rows[id] = .needsAction(Copy.foundAllow)
        case .openedApp:
            rows[id] = .on
            effects.settle(id)
        case .finishInSettings, .rechecked:
            rows[id] = nil
        }
    }

    static func workingText(_ id: FoundItemID) -> String {
        switch id {
        case .browser: Copy.foundSavingBookmarks
        case .dropped: Copy.gsBringingIn
        default: Copy.foundConnecting
        }
    }

    static func describe(_ error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}
