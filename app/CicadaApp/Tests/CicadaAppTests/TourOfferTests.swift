import XCTest
@testable import CicadaApp

final class TourOfferTests: XCTestCase {
    private var defaults: UserDefaults!
    private let suite = "com.cicada.tests.TourOffer"

    override func setUp() {
        super.setUp()
        defaults = TestDefaults.suite(suite)
        defaults.removePersistentDomain(forName: TestDefaults.path(suite))
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: TestDefaults.path(suite))
        super.tearDown()
    }

    func testNothingRequestedMeansNoOffer() {
        XCTAssertFalse(TourOffer.consume(defaults: defaults))
    }

    func testARequestIsAnsweredExactlyOnce() {
        TourOffer.request(defaults: defaults)
        XCTAssertTrue(TourOffer.consume(defaults: defaults))
        XCTAssertFalse(TourOffer.consume(defaults: defaults), "a relaunch must not offer the tour twice")
    }
}
