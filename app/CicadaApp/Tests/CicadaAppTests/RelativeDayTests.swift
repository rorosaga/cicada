import XCTest
@testable import CicadaApp

/// R-PP5 / DR-58 — every relative word on the Projects page is computed at read, here, from an absolute day.
final class RelativeDayTests: XCTestCase {
    private let us = Locale(identifier: "en_US")
    private let t = ISODay(year: 2026, month: 9, day: 23)   // a Wednesday

    func testISODayIsWholeDays() {
        XCTAssertEqual(ISODay("1970-01-01")?.ordinal, 0)
        XCTAssertEqual(ISODay("2026-09-23"), t)
        XCTAssertEqual(ISODay("2026-09-23T16:04:00Z"), t, "an instant's day part parses")
        XCTAssertEqual(t - ISODay(year: 2026, month: 8, day: 30), 24)
        XCTAssertEqual(t.adding(8).description, "2026-10-01")
        XCTAssertEqual(ISODay("2024-02-29")?.adding(365).description, "2025-02-28")
        XCTAssertEqual(ISODay("1969-12-31")?.ordinal, -1)
        XCTAssertNil(ISODay("Sep 23"))
        XCTAssertNil(ISODay(nil))
        XCTAssertNil(ISODay("2026-13-01"))
    }

    /// Today is the viewer's: the same instant is the 24th in Tokyo and the 23rd in Los Angeles.
    func testTodayIsReadInTheViewersCalendar() throws {
        var tokyo = Calendar(identifier: .gregorian)
        tokyo.timeZone = try XCTUnwrap(TimeZone(identifier: "Asia/Tokyo"))
        var la = Calendar(identifier: .gregorian)
        la.timeZone = try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))
        let instant = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-09-23T20:00:00Z"))
        XCTAssertEqual(ISODay.today(now: instant, calendar: tokyo).description, "2026-09-24")
        XCTAssertEqual(ISODay.today(now: instant, calendar: la).description, "2026-09-23")
    }

    func testThePhraseLadder() {
        XCTAssertEqual(RelativeDay.phrase(t, today: t, locale: us), "Today")
        XCTAssertEqual(RelativeDay.phrase(t.adding(-1), today: t, locale: us), "Yesterday")
        XCTAssertEqual(RelativeDay.phrase(t.adding(1), today: t, locale: us), "Tomorrow")
        XCTAssertEqual(RelativeDay.phrase(t.adding(-2), today: t, locale: us), "Monday")
        XCTAssertEqual(RelativeDay.phrase(t.adding(-14), today: t, locale: us), "Sep 9")
        XCTAssertEqual(RelativeDay.phrase(ISODay(year: 2025, month: 9, day: 9), today: t, locale: us), "Sep 9, 2025")
        XCTAssertEqual(RelativeDay.spoken(t, locale: us), "September 23")
        XCTAssertEqual(RelativeDay.month(t, locale: us), "Sep")
    }

    /// Midnight moves every word with no network: yesterday's "Today" is today's "Yesterday".
    func testMidnightRollsTheWordsOver() {
        XCTAssertEqual(RelativeDay.phrase(t, today: t.adding(1), locale: us), "Yesterday")
        XCTAssertEqual(RelativeDay.distance(t.adding(8), today: t.adding(1)), "in 7 days")
    }

    func testDistancesAgesAndGroups() {
        XCTAssertEqual(RelativeDay.distance(t, today: t), "today")
        XCTAssertEqual(RelativeDay.distance(t.adding(1), today: t), "tomorrow")
        XCTAssertEqual(RelativeDay.distance(t.adding(8), today: t), "in 8 days")
        XCTAssertEqual(RelativeDay.distance(t.adding(-1), today: t), "yesterday")
        XCTAssertEqual(RelativeDay.distance(t.adding(-24), today: t), "24 days ago")
        XCTAssertEqual(RelativeDay.compactAge(t, today: t), "today")
        XCTAssertEqual(RelativeDay.compactAge(t.adding(-9), today: t), "9d")
        XCTAssertEqual(RelativeDay.compactAge(t.adding(-29), today: t), "4w")
        XCTAssertEqual(RelativeDay.compactAge(t.adding(-120), today: t), "4mo")
        XCTAssertEqual(RelativeDay.compactAge(nil, today: t), "—")
        XCTAssertEqual(RelativeDay.group(t, today: t), .today)
        XCTAssertEqual(RelativeDay.group(t.adding(-1), today: t), .yesterday)
        XCTAssertEqual(RelativeDay.group(t.adding(-6), today: t), .thisWeek)
        XCTAssertEqual(RelativeDay.group(t.adding(-7), today: t), .earlier)
        XCTAssertEqual(RelativeDay.group(t.adding(2), today: t), .today, "a day ahead (a clock that moved) is today")
        XCTAssertEqual(RelativeDay.bandWords(spanDays: 110).map(\.text), ["2 weeks ago", "in 2 weeks"])
        XCTAssertEqual(RelativeDay.bandWords(spanDays: 200).map(\.text), ["a month ago"])
    }

    /// DR-58 — "Today"/"Yesterday"/"Tomorrow" are spelled once, in `RelativeDay`; the Projects files never spell them.
    func testRelativeWordsAreSpelledOnlyByRelativeDay() throws {
        let scope = ["/Views/Projects/", "/Models/Project", "/Theme/Copy+Projects.swift", "/Views/People/", "/Models/PersonCard.swift",
                     "/Theme/Copy+People.swift"]
        let needles = [#""Today""#, #""Yesterday""#, #""Tomorrow""#, #""today""#, #""yesterday""#, #""tomorrow""#]
        var offenders: [String] = []
        var scanned = 0
        for file in try ThemeTokenTests.swiftSources() where scope.contains(where: file.path.contains) {
            scanned += 1
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && needles.contains(where: line.contains) {
                offenders.append("\(file.lastPathComponent):\(i + 1)")
            }
        }
        XCTAssertGreaterThan(scanned, 0, "the lint scanned nothing — its scope no longer matches a file")
        XCTAssertEqual(offenders, [], "DR-58: relative day words come from RelativeDay only")
    }
}
