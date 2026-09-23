import XCTest
@testable import CicadaApp

/// Track I T6 (design §6.2) — every number appears once: while Getting started
/// shows "Read what came in", TODAY omits its waiting clause.
final class HomeLayoutTests: XCTestCase {
    func testTheWaitingNumberAppearsOnce() {
        XCTAssertFalse(HomeLayout.showsWaitingInToday(gettingStartedVisible: true, hasRunBefore: false))
        XCTAssertTrue(HomeLayout.showsWaitingInToday(gettingStartedVisible: true, hasRunBefore: true))
        XCTAssertTrue(HomeLayout.showsWaitingInToday(gettingStartedVisible: false, hasRunBefore: false))
    }
}
