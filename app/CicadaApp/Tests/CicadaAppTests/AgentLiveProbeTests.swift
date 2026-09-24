import XCTest
@testable import CicadaApp

/// R-AG15 — the poller keeps its last answer, and only a flip seen while the page is open animates.
@MainActor
final class AgentLiveProbeTests: XCTestCase {
    private func response(_ connected: [String]) -> AgentLiveResponse {
        AgentLiveResponse(agents: AgentCatalog.all.map { AgentLiveRow(id: $0.id, connected: connected.contains($0.id)) })
    }

    func testTheFirstAnswerNeverAnimatesAndAFlipDoesOnce() {
        let probe = AgentLiveProbe(fetch: { AgentLiveResponse() }, interval: .seconds(3))
        probe.apply(response(["codex"]))
        XCTAssertEqual(probe.justConnected, [])
        XCTAssertEqual(probe.connectedCount, 1)
        probe.apply(response(["codex", "grok"]))
        XCTAssertEqual(probe.justConnected, ["grok"])
        probe.apply(response(["codex", "grok"]))
        XCTAssertEqual(probe.justConnected, ["grok"], "a pill stays marked as just-connected for this page's life")
    }

    /// A lock-guarded counter, so the @Sendable fetch closure mutates nothing it captured by value (Swift 6) —
    /// the `ResumeOnce` device from `AgentConnect.swift`.
    private final class Counter: @unchecked Sendable {
        private let lock = NSLock()
        private var n = 0
        func next() -> Int { lock.lock(); defer { lock.unlock() }; n += 1; return n }
    }

    func testAFailedPollKeepsTheLastAnswer() async {
        let counter = Counter()
        let probe = AgentLiveProbe(fetch: {
            if counter.next() == 1 { return AgentLiveResponse(agents: [AgentLiveRow(id: "codex", connected: true)]) }
            throw URLError(.cannotConnectToHost)
        }, interval: .milliseconds(1))
        let task = Task { await probe.run() }
        try? await Task.sleep(for: .milliseconds(50))
        task.cancel()
        XCTAssertEqual(probe.rows["codex"]?.connected, true)
    }
}
