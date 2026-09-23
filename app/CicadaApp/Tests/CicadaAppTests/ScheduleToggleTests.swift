import XCTest
@testable import CicadaApp

/// Track Z, Z0 (Z-P27) — the schedule toggle's rule, hoisted out of the
/// onboarding step so the Sleep page's lamp (Z6) and onboarding share ONE
/// definition, and Track I can delete its step without deleting the rule.
final class ScheduleToggleTests: XCTestCase {

    func test_isOn_isEveryModeButManual() {
        XCTAssertFalse(ScheduleToggle.isOn(ScheduleConfig(mode: "manual", hour: 3, minute: 0)))
        for mode in ["daily", "interval", "after_import"] {
            XCTAssertTrue(ScheduleToggle.isOn(ScheduleConfig(mode: mode, hour: 3, minute: 0)), mode)
        }
    }

    /// ON from manual writes exactly `daily 03:00`; OFF from any mode writes
    /// `manual` and keeps hour/minute; ON when already scheduled never
    /// downgrades a rhythm chosen in Settings (Track P R4).
    func test_toggled_writesOnlyManualOrDailyAtThree_andNeverDowngrades() {
        let on = ScheduleToggle.toggled(on: true, current: ScheduleConfig(mode: "manual", hour: 9, minute: 15))
        XCTAssertEqual(on.mode, "daily"); XCTAssertEqual(on.hour, 3); XCTAssertEqual(on.minute, 0)
        let off = ScheduleToggle.toggled(on: false, current: ScheduleConfig(mode: "interval", hour: 9, minute: 15, intervalHours: 4))
        XCTAssertEqual(off.mode, "manual"); XCTAssertEqual(off.hour, 9); XCTAssertEqual(off.minute, 15)
        XCTAssertEqual(off.intervalHours, 4)
        let keep = ScheduleToggle.toggled(on: true, current: ScheduleConfig(mode: "after_import", hour: 3, minute: 0))
        XCTAssertEqual(keep.mode, "after_import")
    }
}
