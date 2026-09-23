import Foundation

/// The one rule behind every "Read on a schedule" switch in the app (Track Z
/// Z0, Z-P27) — hoisted from `OnboardingSchedule` so the Sleep page's lamp
/// popover (Z6) and onboarding share it, and a later onboarding redesign
/// (Track I) can delete its step without deleting the rule.
///
/// The toggle moves between exactly two states (Track P R4): ON from manual
/// writes `daily` at 03:00 (`sleep_scheduler._DEFAULT`'s hour), and never
/// downgrades an `interval` or `after_import` rhythm chosen in Settings → Sleep;
/// OFF writes `manual` and keeps hour and minute, so re-enabling restores them.
enum ScheduleToggle {
    static func isOn(_ schedule: ScheduleConfig) -> Bool { schedule.mode != "manual" }

    static func toggled(on: Bool, current: ScheduleConfig) -> ScheduleConfig {
        if !on {
            var next = current; next.mode = "manual"; return next
        }
        if isOn(current) { return current }
        var next = current; next.mode = "daily"; next.hour = 3; next.minute = 0
        return next
    }
}
