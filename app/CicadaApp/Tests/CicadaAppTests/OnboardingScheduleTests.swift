import XCTest
@testable import CicadaApp

/// Track P (recent-work #2, test gap 7) — the first-run sheet used to tell a
/// brand-new install that Sleep "also runs on its own schedule". It does not:
/// `api/services/sleep_scheduler.py::_DEFAULT` is `mode="manual"`, and
/// `register_job` registers NOTHING for manual — so the one sentence a new
/// person reads about automation was false, on the very first screen, which
/// inverts the "transparency over magic" principle.
///
/// The fix is a toggle, not softer copy (R3): the step writes the schedule it
/// describes. These tests pin the half that no UI is needed to exercise — the
/// line is a pure function of the mode the backend reports, so the copy can
/// never drift from the behaviour again.
final class OnboardingScheduleTests: XCTestCase {

    func testManualNeverClaimsASchedule() {
        let line = OnboardingSchedule.line(ScheduleConfig(mode: "manual", hour: 3, minute: 0))
        XCTAssertFalse(line.lowercased().contains("own schedule"))
        XCTAssertFalse(line.lowercased().contains("automatically"))
        XCTAssertTrue(line.lowercased().contains("only when you ask"))
    }

    func testDailyNamesTheHourItActuallyWrote() {
        XCTAssertTrue(OnboardingSchedule.line(ScheduleConfig(mode: "daily", hour: 3, minute: 0)).contains("3:00"))
        XCTAssertTrue(OnboardingSchedule.line(ScheduleConfig(mode: "daily", hour: 22, minute: 30)).contains("22:30"))
    }

    /// R4 — a schedule chosen in Settings is never silently downgraded to
    /// "nightly at 3": the toggle reads ON and the line names the real mode.
    func testIntervalAndAfterImportKeepTheirOwnWords() {
        XCTAssertTrue(OnboardingSchedule.isOn(ScheduleConfig(mode: "interval", hour: 3, minute: 0, intervalHours: 6)))
        XCTAssertTrue(OnboardingSchedule.line(ScheduleConfig(mode: "interval", hour: 3, minute: 0, intervalHours: 6)).contains("6 hours"))
        XCTAssertTrue(OnboardingSchedule.isOn(ScheduleConfig(mode: "after_import", hour: 3, minute: 0)))
        XCTAssertFalse(OnboardingSchedule.isOn(ScheduleConfig(mode: "manual", hour: 3, minute: 0)))
    }

    /// Turning it ON from a manual bank writes exactly `daily 03:00`; turning
    /// it OFF from ANY scheduled mode writes `manual` — the toggle only ever
    /// moves between those two, it never invents a third (R4).
    func testTogglingWritesOnlyManualOrDailyAtThree() {
        let on = OnboardingSchedule.toggled(on: true, current: ScheduleConfig(mode: "manual", hour: 3, minute: 0))
        XCTAssertEqual(on.mode, "daily"); XCTAssertEqual(on.hour, 3); XCTAssertEqual(on.minute, 0)
        let off = OnboardingSchedule.toggled(on: false, current: ScheduleConfig(mode: "interval", hour: 9, minute: 15, intervalHours: 4))
        XCTAssertEqual(off.mode, "manual")
        // The hour/minute a person set elsewhere survive an OFF write, so
        // re-enabling in Settings restores what they chose.
        XCTAssertEqual(off.hour, 9); XCTAssertEqual(off.minute, 15)
        // Already scheduled + toggled on again = unchanged, never rewritten
        // to 03:00 (R4).
        let keep = OnboardingSchedule.toggled(on: true, current: ScheduleConfig(mode: "after_import", hour: 3, minute: 0))
        XCTAssertEqual(keep.mode, "after_import")
    }
}
