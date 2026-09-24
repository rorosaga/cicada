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
        if loaded { justConnected.formUnion(connected.subtracting(before)) }
        loaded = true
    }

    func run() async {
        while !Task.isCancelled {
            if let fresh = try? await fetch() { apply(fresh) }
            try? await Task.sleep(for: interval)
        }
    }
}
