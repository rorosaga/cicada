import Foundation
import Observation

/// R-OB13 — F-04's fetches: the one `/agents/wiring` answer (Connect for me's steps and the binaries its policy
/// checks, R-FA15), each pill's `/agents/setup` once, From anywhere's status (a cloud agent's link needs a tunnel)
/// and the live memory root (so a registered server points at the bank the backend really uses, G88). Never blank:
/// a failed fetch keeps the last answer. Settings → Agents keeps its own fetches (`ConnectView`, with the backoff
/// its always-open page needs); onboarding asks once per appearance.
@MainActor
@Observable
final class AgentsSetupModel {
    struct Deps {
        var wiring: @MainActor () async -> AgentWiringResponse?
        var setup: @MainActor (String) async -> AgentSetupPrompt?
        var remote: @MainActor () async -> RemoteStatus?
        var memoryRoot: @MainActor () async -> String?

        @MainActor static var live: Deps {
            Deps(wiring: { try? await APIClient.shared.fetchAgentWiring() },
                 setup: { try? await APIClient.shared.fetchAgentSetup(harness: $0) },
                 remote: { try? await APIClient.shared.fetchRemoteStatus() },
                 memoryRoot: { (try? await APIClient.shared.fetchHealth())?.memoryRoot })
        }
    }

    private(set) var wiring: AgentWiringResponse?
    private(set) var setups: [String: AgentSetupPrompt] = [:]
    private(set) var remote: RemoteStatus?
    private(set) var memoryRoot: String?
    @ObservationIgnored private var asked: Set<String> = []
    @ObservationIgnored private let deps: Deps

    init(deps: Deps) { self.deps = deps }
    /// `AutoRecallModel`'s reason for a convenience init: `Deps.live` is main-actor state (SE-0411 is off here).
    convenience init() { self.init(deps: .live) }

    func load() async {
        await refreshWiring()
        if let fresh = await deps.remote() { remote = fresh }
        if let root = await deps.memoryRoot() { memoryRoot = root }
    }

    func refreshWiring() async {
        if let fresh = await deps.wiring() { wiring = fresh }
    }

    /// Each harness a pill reads is asked once per model; a failed ask is asked again the next time the page
    /// appears, because the page recreates the model.
    func select(_ entry: AgentCatalogEntry) async {
        for harness in entry.setupHarnesses where !asked.contains(harness) {
            asked.insert(harness)
            if let prompt = await deps.setup(harness) { setups[harness] = prompt }
        }
    }
}
