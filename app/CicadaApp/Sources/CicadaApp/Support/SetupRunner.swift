import Foundation
import Observation

/// What a Start step does in the world — injected so the order and the
/// failure rules are tested without a window (SetupRunnerTests).
@MainActor
protocol SetupEffects {
    func saveOwner(_ name: String) async throws
    func markOnboarded()
    func recordGettingStarted(_ ids: [FoundItemID])
    /// R-HO15 — *Make it yours* is armed by the Welcome's Start alone. A requirement of its own, not a side effect of
    /// `recordGettingStarted`, because Home's Getting started card calls that effect directly for an *Also found* row:
    /// folded in there, an install onboarded before round 4 got the first-time tip on its first Also-found click
    /// (r4-home final review).
    func armAppearanceTip()
    func showHome()
    func close()
    func createDemoBank() async throws
    func turnOn(_ id: FoundItemID) async -> FoundTurnOnResult
    func settle(_ id: FoundItemID)
    /// R-OB8 — an untick: stop keeping up (a browser's watch, Calendar, Wispr Flow); what came in stays.
    func turnOff(_ id: FoundItemID) async
    /// R-OB8 — the unticked row leaves Getting started rather than staying there as Off.
    func forgetRecord(_ id: FoundItemID)
    /// Seam 3 — onboarding's Open Cicada asks for the tour (`TourOffer.request()`); T-Demo's Home offer answers.
    func requestTour()
}

/// Track I part b (design §4.1.7, R-IB14) — executes part a's `OnboardingFlow`
/// plan. The owner PUT runs alone and first: it is the observer every later
/// write carries (G117 R1), so its failure stops everything. Since round 4 phase B a
/// row runs on its tick (`start`, R-OB2 — the owner: "do not wait for continue") and stops on its untick (`stop`,
/// R-OB8); each reports here, and a failure stays on its row. App-lifetime, so onboarding that has faded out keeps
/// reporting to Home's Getting started card.
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
    /// When a row last came on — a finished import's "Imported …" (R-SR12) reads it, since an import is not a sync
    /// and has no channel to say when.
    private(set) var finishedAt: [FoundItemID: Date] = [:]
    @ObservationIgnored var now: () -> Date = Date.init
    /// R-OB8 — each row's run generation. `stop` bumps it, so a run it retired (an untick mid-read cancels the read,
    /// and the cancelled read still answers `.on(Copy.syncStopped)`) lands nowhere instead of re-ticking the row.
    @ObservationIgnored private var runs: [FoundItemID: Int] = [:]
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
        self.titles.merge(titles) { _, new in new }
        self.origins.merge(origins) { _, new in new }
        var turnOns: [FoundItemID] = []
        for step in plan {
            switch step {
            case .saveOwner(let name):
                do { try await effects.saveOwner(name) } catch { phase = .failed(Self.describe(error)); return }
            case .markOnboarded:
                effects.markOnboarded()
            case .recordGettingStarted(let ids):
                effects.recordGettingStarted(ids)
                // Only onboarding's Open Cicada and Set up later carry this step; the demo plan does not,
                // so a demo never arms the tip (R-HO15).
                effects.armAppearanceTip()
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
            case .offerTour:
                effects.requestTour()
            }
        }
        for id in turnOns { rows[id] = .working(Self.workingText(id)) }
        phase = .started
        let tasks = turnOns.map { id in Task { @MainActor in await self.turnOn(id, effects: effects) } }
        for task in tasks { await task.value }
    }

    /// One row — Start's children and Getting started's Turn on / Retry alike.
    func turnOn(_ id: FoundItemID, effects: SetupEffects) async {
        runs[id, default: 0] &+= 1
        let run = runs[id]
        rows[id] = .working(Self.workingText(id))
        refused[id] = nil
        let result = await effects.turnOn(id)
        guard runs[id] == run else { return }
        switch result {
        case .on(let line):
            rows[id] = .on
            finishedAt[id] = now()
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

    /// Round-4 phase B — a tick on the Import page (owner: "start syncing as soon as connected … do not wait for
    /// continue"). Recorded for Getting started at once, so leaving setup halfway loses nothing, then run. The owner
    /// PUT already ran at Get started (R-OB2). A drop's title and mark are kept here because the router forgets the
    /// drop once it is committed (R-IB14's reason).
    func start(_ id: FoundItemID, title: String? = nil, origin: String? = nil, effects: SetupEffects) async {
        if let title { titles[id] = title }
        if let origin { origins[id] = origin }
        effects.recordGettingStarted([id])
        await turnOn(id, effects: effects)
    }

    /// R-OB8 — an untick: stop keeping up, keep what came in, and take the row off Getting started. The run in
    /// flight (if any) is retired FIRST, before the await: Wispr Flow's stop awaits a network write, and a run that
    /// resumed inside that await must already land nowhere.
    func stop(_ id: FoundItemID, effects: SetupEffects) async {
        runs[id, default: 0] &+= 1
        await effects.turnOff(id)
        rows[id] = nil
        detail[id] = nil
        refused[id] = nil
        finishedAt[id] = nil
        effects.forgetRecord(id)
    }

    static func workingText(_ id: FoundItemID) -> String {
        switch id {
        case .browser: Copy.foundSavingBookmarks
        case .dropped, .app: Copy.gsBringingIn
        default: Copy.foundConnecting
        }
    }

    static func describe(_ error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}
