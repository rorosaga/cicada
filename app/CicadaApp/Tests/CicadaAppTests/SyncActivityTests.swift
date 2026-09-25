import XCTest
@testable import CicadaApp

/// R-SR11 / R-SR17 — the one registry a row asks "is this running, how far, can I stop it".
@MainActor
final class SyncActivityTests: XCTestCase {
    func testARunIsVisibleUntilItEndsAndCancelCallsTheReaderOnce() {
        let activity = SyncActivity()
        var cancels = 0
        activity.began("chrome-tab-groups", detail: "Reading 3 open groups", cancel: { cancels += 1 })
        XCTAssertEqual(activity.run(for: "chrome-tab-groups")?.cancellable, true)
        activity.progressed("chrome-tab-groups", detail: "Sending 3 groups", fraction: 1.4)
        XCTAssertEqual(activity.run(for: "chrome-tab-groups")?.fraction, 1, "a fraction is clamped to 0…1")
        activity.cancel("chrome-tab-groups")
        activity.cancel("chrome-tab-groups")
        XCTAssertEqual(cancels, 1)
        XCTAssertNil(activity.run(for: "chrome-tab-groups"))
        activity.began("contacts-local", cancel: nil)
        XCTAssertEqual(activity.run(for: "contacts-local")?.cancellable, false)
        activity.ended("contacts-local")
        XCTAssertNil(activity.run(for: "contacts-local"))
    }

    func testOnlyACancellationReadsAsOne() {
        XCTAssertTrue(SyncCancellation.isCancellation(CancellationError()))
        XCTAssertTrue(SyncCancellation.isCancellation(URLError(.cancelled)))
        XCTAssertFalse(SyncCancellation.isCancellation(URLError(.timedOut)))
        XCTAssertFalse(SyncCancellation.isCancellation(APIError.httpError(409, "{}")))
    }
}
