import XCTest
@testable import CicadaApp

final class ClaimValidityTests: XCTestCase {
    func testSuccessorOnlyHistoryNeverReadsAsCurrentInTheTimelineOrChip() throws {
        let data = Data(#"{"id":"clm_old","text":"Earlier calibration method","subject":"alpha-project","predicate":"uses","object":"amber","supersededBy":"clm_new"}"#.utf8)
        let claim = try JSONDecoder().decode(Claim.self, from: data)
        XCTAssertNil(claim.validTo)
        XCTAssertFalse(claim.isValid)
    }
    func testFutureStartAndElapsedEndsMatchTheServerRule() throws {
        for json in [
            #"{"id":"clm_future","validFrom":"2099-01-01"}"#,
            #"{"id":"clm_elapsed","expectedEnd":"2000-01-01"}"#,
            #"{"id":"clm_due","predicate":"due","object":"2000-01-01"}"#
        ] {
            let claim = try JSONDecoder().decode(Claim.self, from: Data(json.utf8))
            XCTAssertFalse(claim.isValid, json)
        }
    }
    func testStatedEndIsInclusiveAndTodayUsesTheLocalCalendar() throws {
        let claim = try JSONDecoder().decode(Claim.self, from: Data(
            #"{"id":"clm_test","validFrom":"2026-10-08","expectedEnd":"2026-10-08"}"#.utf8))
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Madrid")!
        let instant = ISO8601DateFormatter().date(from: "2026-10-07T22:30:00Z")!
        let today = ISODay.today(now: instant, calendar: calendar)
        XCTAssertTrue(claim.isCurrent(on: today))
        XCTAssertFalse(claim.isCurrent(on: today.adding(-1)))
        XCTAssertFalse(claim.isCurrent(on: today.adding(1)))
    }

    func testInvalidDatesStayOpenAndMilestoneTargetIsNotAnEnd() throws {
        for json in [
            #"{"id":"clm_bad","validFrom":"2026-02-31","expectedEnd":"undated"}"#,
            #"{"id":"clm_milestone","predicate":"milestone","target":"2000-01-01"}"#
        ] {
            let claim = try JSONDecoder().decode(Claim.self, from: Data(json.utf8))
            XCTAssertTrue(claim.isValid)
        }
    }
}
