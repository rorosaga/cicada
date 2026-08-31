import XCTest
@testable import CicadaApp

/// PR15 triage finding #3: a 304 on the ledger-backed `/consumption/*`
/// sections used to discard the WHOLE `fetchConsumption` response —
/// including `/connections` and `/harness`, which carry no ETag and are
/// always freshly refetched. Pinned against the real
/// `APIClient.fetchConsumption`, not `FakeSyncAPI`, via the injected-session
/// `MockURLProtocol` pattern (see `EntitySourceTests.swift`).
final class ConsumptionFetchTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    private func ok(_ url: URL, _ body: String) -> (HTTPURLResponse, Data) {
        (HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: ["ETag": "\"fresh\""])!,
         Data(body.utf8))
    }

    private func notModified(_ url: URL) -> (HTTPURLResponse, Data) {
        (HTTPURLResponse(url: url, statusCode: 304, httpVersion: nil, headerFields: nil)!, Data())
    }

    private func emptyStats() throws -> ConsumptionStats {
        try JSONDecoder().decode(ConsumptionStats.self, from: Data("""
        {"byModel":[],"byStage":[],"byConnection":[],"byBank":[],"hourHistogram":[0],"series":[],"range":"month"}
        """.utf8))
    }

    /// The bug, pinned: `/summary`, `/calendar` and `/stats` all 304 (nothing
    /// changed there since the caller's cached etag), but `/connections` and
    /// `/harness` answer fresh — the merged bundle must carry the fresh
    /// sections through and reuse the cached ones for the 304'd sections,
    /// never report `notModified` (which would make `Store.refreshOne` drop
    /// the whole response, fresh sections included), and never blank the
    /// 304'd sections down to empty placeholders.
    func testA304OnTheLedgerSectionsStillMergesFreshConnectionsAndHarness() async throws {
        var cachedSummary = ConsumptionSummary()
        cachedSummary.tokens = 111
        let current = ConsumptionBundle(
            summary: cachedSummary,
            calendar: ConsumptionCalendar(days: [], weeks: 53),
            stats: try emptyStats(),
            connections: ConsumptionConnections(connections: [], range: "month"),
            harness: HarnessStats(claudeCode: nil, codex: nil)
        )

        MockURLProtocol.handler = { request in
            switch request.url!.path {
            case "/consumption/summary", "/consumption/calendar", "/consumption/stats":
                return self.notModified(request.url!)
            case "/consumption/connections":
                return self.ok(request.url!, #"{"connections":[{"id":"anthropic","label":"Anthropic","tokens":42}],"range":"month"}"#)
            case "/consumption/harness":
                return self.ok(request.url!, #"{"claudeCode":{"total_sessions":7}}"#)
            default:
                XCTFail("unexpected path \(request.url!.path)")
                throw URLError(.badURL)
            }
        }

        let result = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchConsumption(etag: "\"s\"|\"c\"|\"st\"", current: current)

        XCTAssertFalse(result.notModified, "connections/harness are always fresh, so this must never report no-change")
        XCTAssertEqual(result.value?.summary.tokens, 111, "a 304'd section must fall back to the caller's cached bundle, not an empty one")
        XCTAssertEqual(result.value?.connections.connections.first?.id, "anthropic", "freshly fetched connections must not be dropped")
        XCTAssertEqual(result.value?.harness.claudeCode?["total_sessions"]?.value?.number, 7, "freshly fetched harness must not be dropped")
    }

    /// The ordinary all-fresh path still builds a complete bundle (no
    /// regression from threading `current` through).
    func testAllFreshResponsesStillBuildACompleteBundle() async throws {
        MockURLProtocol.handler = { request in
            switch request.url!.path {
            case "/consumption/summary": return self.ok(request.url!, #"{"costUsd":1.5,"range":"month"}"#)
            case "/consumption/calendar": return self.ok(request.url!, #"{"days":[],"weeks":53}"#)
            case "/consumption/stats": return self.ok(request.url!, #"{"byModel":[],"byStage":[],"byConnection":[],"byBank":[],"hourHistogram":[0],"series":[],"range":"month"}"#)
            case "/consumption/connections": return self.ok(request.url!, #"{"connections":[],"range":"month"}"#)
            case "/consumption/harness": return self.ok(request.url!, "{}")
            default:
                XCTFail("unexpected path \(request.url!.path)")
                throw URLError(.badURL)
            }
        }

        let result = try await APIClient(session: MockURLProtocol.makeSession()).fetchConsumption(etag: nil, current: nil)
        XCTAssertFalse(result.notModified)
        XCTAssertEqual(result.value?.summary.costUsd, 1.5)
    }
}
