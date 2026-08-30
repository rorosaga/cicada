import XCTest
@testable import CicadaApp

/// Task 8 review Medium: the two container types must degrade like their
/// siblings when the payload is missing top-level keys, not throw.
final class ConsumptionModelTests: XCTestCase {
    func testCalendarAndConnectionsTolerateEmptyPayloads() throws {
        let cal = try JSONDecoder().decode(ConsumptionCalendar.self, from: Data("{}".utf8))
        XCTAssertEqual(cal.days.count, 0)
        XCTAssertEqual(cal.weeks, 53)
        let conns = try JSONDecoder().decode(ConsumptionConnections.self, from: Data("{}".utf8))
        XCTAssertEqual(conns.connections.count, 0)
        XCTAssertEqual(conns.range, "month")
    }
}
