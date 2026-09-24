import Foundation

/// A calendar day as the Projects wire sends it — `YYYY-MM-DD` (G141 R-PJ6: absolute only). Arithmetic is whole days
/// in the proleptic Gregorian calendar with no time zone in it (Hinnant's days-from-civil), so "24 days" is 24 across
/// a DST change and the numbers match Python's `date` arithmetic, which `ProjectState` needs to run the shared fixture.
/// A zone enters only when today is read — the viewer's calendar (R-PP5); the server never sends today (R-PJ7).
struct ISODay: Hashable, Comparable, Sendable, CustomStringConvertible {
    /// Days since 1970-01-01.
    let ordinal: Int

    init(ordinal: Int) { self.ordinal = ordinal }

    init(year: Int, month: Int, day: Int) { ordinal = Self.daysFromCivil(year, month, day) }

    /// The first ten characters as `YYYY-MM-DD` (an instant's day part parses too); anything else is nil.
    init?(_ raw: String?) {
        guard let raw, raw.count >= 10 else { return nil }
        let parts = raw.prefix(10).split(separator: "-")
        guard parts.count == 3, let y = Int(parts[0]), let m = Int(parts[1]), let d = Int(parts[2]),
              (1...12).contains(m), (1...31).contains(d) else { return nil }
        self.init(year: y, month: m, day: d)
    }

    static func today(now: Date = Date(), calendar: Calendar = .autoupdatingCurrent) -> ISODay {
        let c = calendar.dateComponents([.year, .month, .day], from: now)
        return ISODay(year: c.year ?? 1970, month: c.month ?? 1, day: c.day ?? 1)
    }

    func adding(_ days: Int) -> ISODay { ISODay(ordinal: ordinal + days) }

    static func - (lhs: ISODay, rhs: ISODay) -> Int { lhs.ordinal - rhs.ordinal }
    static func < (lhs: ISODay, rhs: ISODay) -> Bool { lhs.ordinal < rhs.ordinal }

    var civil: (year: Int, month: Int, day: Int) { Self.civilFromDays(ordinal) }

    var description: String {
        let c = civil
        return String(format: "%04d-%02d-%02d", c.year, c.month, c.day)
    }

    /// Noon on this day in `calendar`'s zone — what a formatter needs to print it without a zone shift.
    func date(in calendar: Calendar) -> Date {
        let c = civil
        return calendar.date(from: DateComponents(year: c.year, month: c.month, day: c.day, hour: 12)) ?? Date()
    }

    private static func daysFromCivil(_ year: Int, _ m: Int, _ d: Int) -> Int {
        let y = m <= 2 ? year - 1 : year
        let era = (y >= 0 ? y : y - 399) / 400
        let yoe = y - era * 400
        let doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1
        let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy
        return era * 146_097 + doe - 719_468
    }

    private static func civilFromDays(_ days: Int) -> (year: Int, month: Int, day: Int) {
        let z = days + 719_468
        let era = (z >= 0 ? z : z - 146_096) / 146_097
        let doe = z - era * 146_097
        let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
        let mp = (5 * doy + 2) / 153
        let d = doy - (153 * mp + 2) / 5 + 1
        let m = mp < 10 ? mp + 3 : mp - 9
        return (yoe + era * 400 + (m <= 2 ? 1 : 0), m, d)
    }
}

/// DR-58 / G141 §8 — every relative word on the Projects page, computed at read from an absolute day and the viewer's
/// today; nothing relative is stored or sent (R-PJ6). The ONLY place the day words are spelled
/// (`RelativeDayTests.testRelativeWordsAreSpelledOnlyByRelativeDay`), so a second, drifting spelling cannot appear.
enum RelativeDay {
    /// Lately's headers (R-PP14).
    enum Group: Hashable, CaseIterable, Sendable { case today, yesterday, thisWeek, earlier }

    /// "Today" · "Yesterday" · "Tomorrow" · a weekday within the last six days · "Sep 9" · "Sep 9, 2025".
    static func phrase(_ day: ISODay, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        switch day - today {
        case 0: "Today"
        case -1: "Yesterday"
        case 1: "Tomorrow"
        case -6 ... -2: weekday(day, locale: locale)
        default: absolute(day, today: today, locale: locale)
        }
    }

    /// "Sep 9", with the year only when it is not this one — a row's date (DR-58: the full date is its `.help`).
    static func absolute(_ day: ISODay, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: day.civil.year == today.civil.year ? "MMMd" : "yMMMd", locale: locale)
    }

    /// "September 23" — what VoiceOver says ("You are here, today, September 23").
    static func spoken(_ day: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: "MMMMd", locale: locale)
    }

    /// "Tuesday, September 22, 2026" — a date's `.help`.
    static func full(_ day: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: "EEEEyMMMMd", locale: locale)
    }

    static func weekday(_ day: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: "EEEE", locale: locale)
    }

    /// "Sep" — the band's month labels.
    static func month(_ day: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        format(day, template: "MMM", locale: locale)
    }

    /// "today" · "tomorrow" · "in 8 days" · "yesterday" · "24 days ago" — the lower-case clause after a date
    /// ("Oct 1 · in 8 days").
    static func distance(_ day: ISODay, today: ISODay) -> String {
        let n = day - today
        switch n {
        case 0: return "today"
        case 1: return "tomorrow"
        case -1: return "yesterday"
        case 2...: return "in \(UsageFormat.count(n)) days"
        default: return "\(UsageFormat.count(-n)) days ago"
        }
    }

    /// DR-58 — a row's compact age: "today" · "9d" · "4w" · "4mo"; "—" with no day (its reason is the row's `.help`).
    static func compactAge(_ day: ISODay?, today: ISODay) -> String {
        guard let day else { return "—" }
        let n = today - day
        if n <= 0 { return "today" }
        if n < 14 { return "\(UsageFormat.count(n))d" }
        if n < 60 { return "\(UsageFormat.count(n / 7))w" }
        return "\(UsageFormat.count(n / 30))mo"
    }

    /// R-PP14 — This week is 2–6 days back, a rolling week, so a Monday's is never empty. A day ahead of today (a
    /// clock that moved) reads as Today rather than vanishing.
    static func group(_ day: ISODay, today: ISODay) -> Group {
        switch today - day {
        case ...0: .today
        case 1: .yesterday
        case 2...6: .thisWeek
        default: .earlier
        }
    }

    static func title(_ group: Group) -> String {
        switch group {
        case .today: "Today"
        case .yesterday: "Yesterday"
        case .thisWeek: "This week"
        case .earlier: "Earlier"
        }
    }

    /// The band's words near the marker (R-PP10): two weeks either side, or a month back on a window past 180 days.
    static func bandWords(spanDays: Int) -> [(offset: Int, text: String)] {
        spanDays > 180 ? [(-30, "a month ago")] : [(-14, "2 weeks ago"), (14, "in 2 weeks")]
    }

    private static func format(_ day: ISODay, template: String, locale: Locale) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .current
        let f = DateFormatter()
        f.locale = locale
        f.calendar = calendar
        f.timeZone = calendar.timeZone
        f.setLocalizedDateFormatFromTemplate(template)
        return f.string(from: day.date(in: calendar))
    }
}
