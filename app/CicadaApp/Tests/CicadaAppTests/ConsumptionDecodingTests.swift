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

    /// G113: the feedback section is optional on the wire (an older backend
    /// has no `/consumption/feedback`) and in the disk cache (a bundle
    /// written before this build has no `feedback` key) — both must decode.
    func testBundleWithoutFeedbackDecodesToNil() throws {
        let json = """
        {"summary":{"costUsd":2.5,"range":"month"},
         "calendar":{"days":[],"weeks":53},
         "stats":{"byModel":[],"byStage":[],"byConnection":[],"byBank":[],"hourHistogram":[0],"series":[],"range":"month"},
         "connections":{"connections":[],"range":"month"},
         "harness":{}}
        """.data(using: .utf8)!
        let bundle = try JSONDecoder().decode(ConsumptionBundle.self, from: json)
        XCTAssertNil(bundle.feedback)
    }

    func testFeedbackDecodesWithMissingFieldsAndRoundTrips() throws {
        let sparse = try JSONDecoder().decode(ConsumptionFeedback.self, from: Data(#"{"range":"month"}"#.utf8))
        XCTAssertEqual(sparse.resolutions, 0)
        XCTAssertNil(sparse.rate)
        let full = try JSONDecoder().decode(ConsumptionFeedback.self, from: Data("""
        {"range":"month","since":"2026-09-01","resolutions":12,"corrections":3,"rate":0.7,
         "agreement":[{"kind":"conflict","total":5,"agreed":3,"overruled":1,"rate":0.75}],
         "calibration":[{"bucket":"<0.5","n":0,"agreedRate":null}],
         "byAction":[{"action":"pick:1","n":4}],
         "audits":{"supersede":7,"rejected":2},
         "dedup":{"same":1,"different":3,"unsure":1,"merged":1}}
        """.utf8))
        XCTAssertEqual(full.resolutions, 12)
        XCTAssertEqual(full.corrections, 3)
        XCTAssertEqual(full.rate, 0.7)
        XCTAssertEqual(full.agreement.count, 1)
        let back = try JSONDecoder().decode(ConsumptionFeedback.self, from: JSONEncoder().encode(full))
        XCTAssertEqual(back.rate, 0.7)
        XCTAssertEqual(back.audits["supersede"], 7)
    }
}

