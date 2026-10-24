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

/// Onboarding v3 (2026-10-24, after HeyClicky's mic check) — the Agents step's one live check: did the person's agent
/// ask Cicada something since the step started? It reads `lastCalledAt` — a `tools/call`, stamped apart from the
/// `initialize` every connect writes (`agent_seen` `via: call`) — never `lastSeenAt`: Cicada's own wiring check
/// (`GET /agents/wiring` runs `claude mcp get`, which spawns the server and initializes as Claude Code) and an agent
/// merely starting a session move `lastSeenAt` without asking anything. A call newer than the step's first answer is
/// the first call. Ids and times only, nothing persisted.
enum FirstAgentCall {
    /// Each agent's last tool call when the step started.
    static func baseline(_ rows: [AgentLiveRow]) -> [String: String] {
        Dictionary(rows.compactMap { row in row.lastCalledAt.map { (row.id, $0) } },
                   uniquingKeysWith: { _, last in last })
    }

    /// The first agent, in the answer's order, whose last tool call is later than the baseline's (or its first ever).
    /// A connect alone (`lastSeenAt` moving, no `lastCalledAt`) and a wired agent that never called are not calls; a
    /// time that went backwards is not one either.
    static func detect(baseline: [String: String], rows: [AgentLiveRow]) -> String? {
        rows.first { row in
            guard let called = row.lastCalledAt, let now = instant(called) else { return false }
            guard let before = baseline[row.id] else { return true }
            guard let then = instant(before) else { return called > before }
            return now > then
        }?.id
    }

    /// The backend's ISO-8601 UTC time (`2026-10-24T09:00:00Z`, fractional seconds tolerated).
    static func instant(_ iso: String) -> Date? {
        let plain = ISO8601DateFormatter()
        if let date = plain.date(from: iso) { return date }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: iso)
    }
}
