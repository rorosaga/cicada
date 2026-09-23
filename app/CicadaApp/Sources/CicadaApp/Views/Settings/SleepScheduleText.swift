import Foundation

/// The Sleep page's schedule words (G139, R-O10), pure so they are tested.
/// "Next run" is the server's `nextSleepAt` — computed per request by
/// `sleep_scheduler.next_run_at`, calibrated to the mode — never the local
/// picker's date, which was wrong in interval and after-import modes.
enum SleepScheduleText {
    static let modes: [PillOption<String>] = [
        PillOption(value: "manual", label: "Manual"),
        PillOption(value: "daily", label: "Daily"),
        PillOption(value: "interval", label: "Every few hours"),
        PillOption(value: "after_import", label: "After imports"),
    ]

    static func everyHours(_ n: Int) -> String { n == 1 ? "Every hour" : "Every \(n) hours" }

    static func detail(mode: String, nextSleepAt: String?, now: Date = Date(),
                       calendar: Calendar = .current, locale: Locale = .autoupdatingCurrent) -> String {
        if mode == "manual" { return "Only when you press Consolidate now." }
        if let next = StatusSnapshot.parseDate(nextSleepAt) {
            return "Next run: \(relative(next, now: now, calendar: calendar, locale: locale))"
        }
        if mode == "after_import" {
            return "Starts about 10 minutes after the last import lands, if nothing is running."
        }
        return "Next run: not scheduled yet."
    }

    static func relative(_ date: Date, now: Date, calendar: Calendar, locale: Locale) -> String {
        let time = date.formatted(Date.FormatStyle(date: .omitted, time: .shortened, locale: locale,
                                                   calendar: calendar, timeZone: calendar.timeZone))
        if calendar.isDate(date, inSameDayAs: now) { return "today at \(time)" }
        if let tomorrow = calendar.date(byAdding: .day, value: 1, to: now),
           calendar.isDate(date, inSameDayAs: tomorrow) { return "tomorrow at \(time)" }
        let weekday = date.formatted(Date.FormatStyle(locale: locale, calendar: calendar,
                                                      timeZone: calendar.timeZone).weekday(.wide))
        return "\(weekday) at \(time)"
    }
}
