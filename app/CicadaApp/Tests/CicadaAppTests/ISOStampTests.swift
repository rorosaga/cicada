import XCTest
@testable import CicadaApp

/// Inbox lag (2026-10-17): `ReaderTime` and `InboxAge` parse through formatters built once and keep each stamp's
/// answer. The answers must be the ones a freshly built formatter gives, for every shape a bank holds.
final class ISOStampTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!
    private let lima = TimeZone(identifier: "America/Lima")!

    private func fresh(_ raw: String, timeZone: TimeZone) -> Date? {
        let aware = ISO8601DateFormatter()
        aware.formatOptions = [.withInternetDateTime]
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = aware.date(from: raw) ?? fractional.date(from: raw) { return d }
        let naive = DateFormatter()
        naive.locale = Locale(identifier: "en_US_POSIX")
        naive.timeZone = timeZone
        for format in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd"] {
            naive.dateFormat = format
            if let d = naive.date(from: raw) { return d }
        }
        return nil
    }

    func testInstantMatchesAFreshFormatterForEveryShapeTwice() {
        let shapes = ["2026-08-25T10:00:00Z", "2026-08-25T10:00:00+00:00", "2026-08-25T10:00:00.123456+02:00",
                      "2026-08-25T10:00:00.123456", "2026-08-25T10:00:00", "2026-08-25", "not a date", ""]
        for zone in [utc, lima] {
            for raw in shapes {
                let expected = fresh(raw, timeZone: zone)
                XCTAssertEqual(ReaderTime.instant(raw, timeZone: zone), expected, "\(raw) in \(zone.identifier)")
                XCTAssertEqual(ReaderTime.instant(raw, timeZone: zone), expected, "remembered: \(raw)")
            }
        }
    }

    func testANaiveStampIsReadInTheZoneAskedEvenAfterAnotherZoneReadIt() {
        let raw = "2026-08-25T10:00:00"
        let inUTC = ReaderTime.instant(raw, timeZone: utc)
        let inLima = ReaderTime.instant(raw, timeZone: lima)
        XCTAssertNotNil(inUTC)
        XCTAssertEqual(inLima.map { $0.timeIntervalSince(inUTC!) }, 5 * 3600)
    }

    func testEpisodeDatesAndInboxAgeDatesAreUnchanged() {
        XCTAssertEqual(ReaderTime.episodeDate("ep_2026-08-25_001", timeZone: utc), fresh("2026-08-25", timeZone: utc))
        XCTAssertNil(ReaderTime.episodeDate("alpha-project", timeZone: utc))
        XCTAssertEqual(InboxAge.date("2026-08-25"), fresh("2026-08-25", timeZone: utc))
        XCTAssertEqual(InboxAge.date("2026-08-25T10:00:00.5Z"), fresh("2026-08-25T10:00:00.5Z", timeZone: utc))
        XCTAssertNil(InboxAge.date(nil))
        XCTAssertNil(InboxAge.date("soon"))
    }

    func testTheMemoStartsOverInsteadOfGrowing() {
        for n in 0..<(ISOStamp.memoLimit + 10) {
            _ = ReaderTime.instant("2020-01-01T00:00:\(n % 60)Z-\(n)", timeZone: utc)
        }
        XCTAssertEqual(ReaderTime.instant("2026-08-25T10:00:00Z", timeZone: utc), fresh("2026-08-25T10:00:00Z", timeZone: utc))
    }
}
