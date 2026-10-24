import Foundation
import Observation

/// R-AG15 — polls `GET /agents/live` while the page that owns it is visible (its `.task` runs `run()` and SwiftUI
/// cancels it when the page leaves). Never blank: a failed poll keeps the last answer. `justConnected` holds the
/// pills that flipped to connected while this page was open, so their ✓ scales in once — the first answer never
/// animates.
@MainActor
@Observable
final class AgentLiveProbe {
    private(set) var rows: [String: AgentLiveRow] = [:]
    private(set) var justConnected: Set<String> = []
    /// Onboarding v3 — the first agent that called Cicada after this probe's first answer (`FirstAgentCall`): its id,
    /// once, and then it stays (the Agents step's moment of confirmation).
    private(set) var firstCall: String?
    @ObservationIgnored private var baselineSeen: [String: String] = [:]
    private var loaded = false

    @ObservationIgnored private let fetch: @Sendable () async throws -> AgentLiveResponse
    @ObservationIgnored private let interval: Duration

    init(fetch: @escaping @Sendable () async throws -> AgentLiveResponse = { try await APIClient.shared.fetchAgentLive() },
         interval: Duration = .seconds(3)) {
        self.fetch = fetch
        self.interval = interval
    }

    var connected: Set<String> { Set(rows.values.filter(\.connected).map(\.id)) }
    var connectedCount: Int { connected.count }

    func apply(_ response: AgentLiveResponse) {
        let before = connected
        rows = Dictionary(response.agents.map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })
        if loaded {
            justConnected.formUnion(connected.subtracting(before))
            if firstCall == nil { firstCall = FirstAgentCall.detect(baseline: baselineSeen, rows: response.agents) }
        } else {
            baselineSeen = FirstAgentCall.baseline(response.agents)
        }
        loaded = true
    }

    func run() async {
        while !Task.isCancelled {
            if let fresh = try? await fetch() { apply(fresh) }
            try? await Task.sleep(for: interval)
        }
    }
}

/// Onboarding v3 (2026-10-24, after HeyClicky's mic check) — the Agents step's one live check: did an agent call
/// Cicada since the step started? `GET /agents/live` already carries each agent's `lastSeenAt`, stamped on every
/// call (`agent_seen`) and every remote request; a time that moved past the step's first answer is a new call. Ids and
/// times only, nothing persisted.
enum FirstAgentCall {
    /// What each agent's last call was when the step started.
    static func baseline(_ rows: [AgentLiveRow]) -> [String: String] {
        Dictionary(rows.compactMap { row in row.lastSeenAt.map { (row.id, $0) } }, uniquingKeysWith: { _, last in last })
    }

    /// The first agent, in the answer's order, whose last call is newer than the baseline — a time it had not shown
    /// before (a call only ever moves it forward). A wired agent that has never called (`via: config`, no time) is
    /// not a call.
    static func detect(baseline: [String: String], rows: [AgentLiveRow]) -> String? {
        rows.first { row in
            guard let seen = row.lastSeenAt, !seen.isEmpty else { return false }
            return baseline[row.id] != seen
        }?.id
    }
}
