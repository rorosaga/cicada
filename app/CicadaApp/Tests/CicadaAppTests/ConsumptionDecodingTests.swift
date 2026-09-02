import XCTest
@testable import CicadaApp

final class ConsumptionDecodingTests: XCTestCase {
    func testSummaryDecodesWithMissingFields() throws {
        let json = #"{"costUsd": 1.5, "range": "30d"}"#.data(using: .utf8)!
        let s = try JSONDecoder().decode(ConsumptionSummary.self, from: json)
        XCTAssertEqual(s.costUsd, 1.5); XCTAssertEqual(s.invocations, 0); XCTAssertEqual(s.streakCurrent, 0)
    }

    func testCalendarDayToCell() throws {
        let json = #"{"days":[{"date":"2026-08-28","memoryWrites":2,"events":3,"tokens":100,"level":4}],"weeks":1}"#.data(using: .utf8)!
        let c = try JSONDecoder().decode(ConsumptionCalendar.self, from: json)
        XCTAssertEqual(c.days[0].cell, CalendarCell(date: "2026-08-28", level: 4, memoryWrites: 2, events: 3, tokens: 100))
    }

    func testStatsRowsDecodeLooseDicts() throws {
        let json = #"{"byModel":[{"model":"gpt-5.4-mini","tokens":10,"costUsd":null,"invocations":1}],"byStage":[],"byConnection":[],"byBank":[],"hourHistogram":[0],"series":[],"range":"all"}"#.data(using: .utf8)!
        let s = try JSONDecoder().decode(ConsumptionStats.self, from: json)
        XCTAssertEqual(s.byModel[0].name, "gpt-5.4-mini"); XCTAssertNil(s.byModel[0].costUsd); XCTAssertEqual(s.byModel[0].tokens, 10)
    }

    /// A row with none of `model`/`stage`/`connection`/`bank` (shouldn't happen,
    /// but the backend sends loose dicts) must still decode to something
    /// rather than throwing and losing the whole table.
    func testStatsRowFallsBackToUnknownName() throws {
        let json = #"{"tokens":5}"#.data(using: .utf8)!
        let row = try JSONDecoder().decode(StatsRow.self, from: json)
        XCTAssertEqual(row.name, "unknown")
        XCTAssertEqual(row.tokens, 5)
    }

    func testConnectionConsumptionToleratesMissingOptionalFields() throws {
        let json = #"{"id":"anthropic"}"#.data(using: .utf8)!
        let c = try JSONDecoder().decode(ConnectionConsumption.self, from: json)
        XCTAssertEqual(c.label, "anthropic")
        XCTAssertEqual(c.billing, "usage")
        XCTAssertFalse(c.connected)
        XCTAssertNil(c.priceUsdMonth)
        XCTAssertTrue(c.byModel.isEmpty)
    }

    func testLooseValueDecodesStringNumberAndNull() throws {
        let json = #"{"a":"x","b":1.5,"c":null}"#.data(using: .utf8)!
        let dict = try JSONDecoder().decode([String: LooseValue].self, from: json)
        XCTAssertEqual(dict["a"]?.text, "x")
        XCTAssertEqual(dict["b"]?.number, 1.5)
        XCTAssertEqual(dict["c"]?.text, "—")
    }

    /// Everything the dashboard needs, folded into one bundle (see
    /// `ConsumptionBundle`) — a plain round trip through the same
    /// `JSONEncoder`/`JSONDecoder` pair `SnapshotCache` uses.
    func testConsumptionBundleRoundTripsThroughCodable() throws {
        let json = """
        {"summary":{"costUsd":2.5,"range":"month"},
         "calendar":{"days":[],"weeks":53},
         "stats":{"byModel":[],"byStage":[],"byConnection":[],"byBank":[],"hourHistogram":[0],"series":[],"range":"month"},
         "connections":{"connections":[],"range":"month"},
         "harness":{}}
        """.data(using: .utf8)!
        let bundle = try JSONDecoder().decode(ConsumptionBundle.self, from: json)
        let reencoded = try JSONEncoder().encode(bundle)
        let roundTripped = try JSONDecoder().decode(ConsumptionBundle.self, from: reencoded)
        XCTAssertEqual(roundTripped.summary.costUsd, 2.5)
        XCTAssertEqual(roundTripped.connections.connections.count, 0)
    }

    func testHeatRampCoversTheFullRangeAndClampsOutOfBounds() {
        CicadaTheme.mode = .dark
        XCTAssertEqual(CicadaTheme.heatRamp(level: 0), CicadaTheme.surfaceElevated)
        XCTAssertEqual(CicadaTheme.heatRamp(level: 4), CicadaTheme.accent)
        XCTAssertEqual(CicadaTheme.heatRamp(level: -1), CicadaTheme.heatRamp(level: 0), "clamps below 0")
        XCTAssertEqual(CicadaTheme.heatRamp(level: 9), CicadaTheme.heatRamp(level: 4), "clamps above 4")
    }
}

