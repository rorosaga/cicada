import XCTest
@testable import CicadaApp

/// G125 R6 — `ScheduleConfig.mode` is the source of truth; `enabled` is a
/// derived wire convenience, never a stored property of its own.
final class ScheduleModeTests: XCTestCase {

    func testOlderPayloadWithOnlyEnabledDerivesDailyMode() throws {
        let json = #"{"enabled":true,"hour":3,"minute":0}"#.data(using: .utf8)!
        let cfg = try JSONDecoder().decode(ScheduleConfig.self, from: json)
        XCTAssertEqual(cfg.mode, "daily")
        XCTAssertEqual(cfg.intervalHours, 6, "defaults when the backend predates interval_hours")
        XCTAssertTrue(cfg.enabled)
    }

    func testOlderPayloadWithEnabledFalseDerivesManualMode() throws {
        let json = #"{"enabled":false,"hour":3,"minute":0}"#.data(using: .utf8)!
        let cfg = try JSONDecoder().decode(ScheduleConfig.self, from: json)
        XCTAssertEqual(cfg.mode, "manual")
        XCTAssertFalse(cfg.enabled)
    }

    func testModePresentOnTheWireWinsOverEnabled() throws {
        let json = #"{"mode":"after_import","enabled":true,"hour":3,"minute":0,"intervalHours":6}"#.data(using: .utf8)!
        let cfg = try JSONDecoder().decode(ScheduleConfig.self, from: json)
        XCTAssertEqual(cfg.mode, "after_import")
        XCTAssertTrue(cfg.enabled, "enabled is derived FROM mode, not the other way round")
    }

    func testIntervalModeDecodesItsHours() throws {
        let json = #"{"mode":"interval","hour":3,"minute":0,"intervalHours":12}"#.data(using: .utf8)!
        let cfg = try JSONDecoder().decode(ScheduleConfig.self, from: json)
        XCTAssertEqual(cfg.mode, "interval")
        XCTAssertEqual(cfg.intervalHours, 12)
        XCTAssertTrue(cfg.enabled)
    }

    /// Encoding always writes `enabled` too (R6: "always written for older
    /// readers") — never omitted just because `mode` already carries the
    /// same information for a current reader.
    func testEncodingManualModeAlsoWritesEnabledFalse() throws {
        let cfg = ScheduleConfig(mode: "manual", hour: 3, minute: 0)
        let data = try JSONEncoder().encode(cfg)
        let obj = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        XCTAssertEqual(obj["mode"] as? String, "manual")
        XCTAssertEqual(obj["enabled"] as? Bool, false)
        XCTAssertEqual(obj["intervalHours"] as? Int, 6)
    }

    func testEncodingIntervalModeWritesEnabledTrue() throws {
        let cfg = ScheduleConfig(mode: "interval", hour: 3, minute: 0, intervalHours: 8)
        let data = try JSONEncoder().encode(cfg)
        let obj = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        XCTAssertEqual(obj["mode"] as? String, "interval")
        XCTAssertEqual(obj["enabled"] as? Bool, true)
        XCTAssertEqual(obj["intervalHours"] as? Int, 8)
    }

    func testMemberwiseInitDefaultsIntervalHoursToSix() {
        let cfg = ScheduleConfig(mode: "daily", hour: 4, minute: 30)
        XCTAssertEqual(cfg.intervalHours, 6)
        XCTAssertEqual(cfg.hour, 4)
        XCTAssertEqual(cfg.minute, 30)
    }
}
