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
        XCTAssertTrue(ScheduleToggle.isOn(ScheduleConfig(mode: "interval", hour: 3, minute: 0, intervalHours: 6)))
        XCTAssertTrue(OnboardingSchedule.line(ScheduleConfig(mode: "interval", hour: 3, minute: 0, intervalHours: 6)).contains("6 hours"))
        XCTAssertTrue(ScheduleToggle.isOn(ScheduleConfig(mode: "after_import", hour: 3, minute: 0)))
        XCTAssertFalse(ScheduleToggle.isOn(ScheduleConfig(mode: "manual", hour: 3, minute: 0)))
    }

    // The toggle's own rule (`toggled(on:current:)`) moved to
    // `ScheduleToggleTests` with the rule itself (Track Z Z0, Z-P27).
}
