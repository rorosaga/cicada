import XCTest
@testable import CicadaApp

/// G124 — the per-contributor calendar and the read/write stats, and the
/// rule that nothing on this page prices anything.
final class ContributorCalendarTests: XCTestCase {

    func testContributorCalendarDecodesAndTolerates() throws {
        let json = #"{"author":"gpt-5.4-mini","days":[{"date":"2026-08-28","memoryWrites":2,"level":4}],"weeks":4}"#.data(using: .utf8)!
        let cal = try JSONDecoder().decode(ContributorCalendar.self, from: json)
        XCTAssertEqual(cal.author, "gpt-5.4-mini"); XCTAssertEqual(cal.weeks, 4)
        XCTAssertEqual(cal.days[0].cell, CalendarCell(date: "2026-08-28", level: 4, memoryWrites: 2, events: 0, tokens: 0))
        let sparse = try JSONDecoder().decode(ContributorCalendar.self, from: #"{"author":"user"}"#.data(using: .utf8)!)
        XCTAssertEqual(sparse.days.map(\.date), []); XCTAssertEqual(sparse.weeks, 53)
    }

    func testTopEntitiesDecodesAndTolerates() throws {
        let json = #"{"written":[{"entityId":"alpha-project","commits":3,"lastWritten":"2026-08-03"}],"read":[{"entityId":"bob-example","reads":2,"lastRead":"2026-09-01T10:00:00Z"}],"commitsScanned":5,"range":"all"}"#.data(using: .utf8)!
        let top = try JSONDecoder().decode(TopEntities.self, from: json)
        XCTAssertEqual(top.written.map(\.entityId), ["alpha-project"]); XCTAssertEqual(top.written[0].commits, 3)
        XCTAssertEqual(top.read[0].reads, 2); XCTAssertEqual(top.commitsScanned, 5)
        let empty = try JSONDecoder().decode(TopEntities.self, from: "{}".data(using: .utf8)!)
        XCTAssertEqual(empty.written, []); XCTAssertEqual(empty.read, []); XCTAssertEqual(empty.commitsScanned, 0)
    }

    func testHeatmapTooltipNeverMentionsTokens() {
        let writesOnly = CalendarCell(date: "2026-08-28", level: 4, memoryWrites: 1, events: 0, tokens: 99_000)
        XCTAssertEqual(HeatmapView.tooltip(writesOnly), "2026-08-28 · 1 memory write")
        let both = CalendarCell(date: "2026-08-29", level: 2, memoryWrites: 2, events: 3, tokens: 99_000)
        XCTAssertEqual(HeatmapView.tooltip(both), "2026-08-29 · 2 memory writes · 3 events")
        XCTAssertFalse(HeatmapView.tooltip(both).lowercased().contains("token"))
    }

    func testAdvancedTilesAreCountsOnly() {
        var s = ConsumptionSummary()
        s.memoryWrites = 12; s.sleepRuns = 3; s.agenticWrites = 4; s.streakCurrent = 2; s.streakBest = 9; s.costUsd = 42
        let tiles = AdvancedStatsView.tiles(for: s)
        XCTAssertEqual(tiles.map(\.title), ["Memory writes", "Sleep runs", "In-session writes", "Streak"])
        XCTAssertEqual(tiles.map(\.value), ["12", "3", "4", "2d"])
        XCTAssertFalse(tiles.contains { $0.value.contains("$") || ($0.footnote ?? "").contains("$") })
    }

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    /// Same harness `ConversationsTests` uses (`MockURLProtocol` lives in
    /// `EntitySourceTests.swift`; `APIClient(session:)` is the test-only
    /// init). A URLProtocol sees a POST body as a stream, so the assertion
    /// reads `httpBodyStream` — `httpBody` is nil there.
    func testRecordEntityReadPostsIdsOnly() async throws {
        var captured: (method: String?, path: String?, body: Data?)?
        MockURLProtocol.handler = { request in
            var data = Data()
            if let stream = request.httpBodyStream {
                stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 1024)
                while stream.hasBytesAvailable {
                    let n = stream.read(&buffer, maxLength: buffer.count)
                    if n <= 0 { break }
                    data.append(buffer, count: n)
                }
            } else if let body = request.httpBody { data = body }
            captured = (request.httpMethod, request.url?.path, data)
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!,
                    #"{"recorded":true}"#.data(using: .utf8)!)
        }
        await APIClient(session: MockURLProtocol.makeSession()).recordEntityRead(id: "alpha-project")
        XCTAssertEqual(captured?.method, "POST")
        XCTAssertEqual(captured?.path, "/entities/alpha-project/read")
        let body = try XCTUnwrap(captured?.body)
        XCTAssertEqual(try JSONSerialization.jsonObject(with: body) as? [String: String], ["surface": "app"])
    }

    /// A 404 (page gone) or an old backend must never surface: the call
    /// returns normally.
    func testRecordEntityReadSwallowsErrors() async {
        MockURLProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 404, httpVersion: nil, headerFields: nil)!, Data())
        }
        await APIClient(session: MockURLProtocol.makeSession()).recordEntityRead(id: "gone")
    }
}
