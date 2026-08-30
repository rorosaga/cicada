import XCTest
@testable import CicadaApp

final class VersionVectorTests: XCTestCase {
    func testNilOldMeansEverything() {
        let v = VersionVector(version: "1", components: ["entities": "a"])
        XCTAssertEqual(v.changedDomains(since: nil), Set(SyncDomain.allCases))
    }
    func testMapsComponents() {
        let old = VersionVector(version: "1", components: ["entities": "a", "inbox": "1", "bank": "x", "sleep": "idle:"])
        let new = VersionVector(version: "2", components: ["entities": "b", "inbox": "1", "bank": "x", "sleep": "idle:"])
        XCTAssertEqual(new.changedDomains(since: old), [.graph, .contributors, .origins])
        let bank = VersionVector(version: "3", components: ["entities": "b", "inbox": "1", "bank": "y", "sleep": "idle:"])
        XCTAssertEqual(bank.changedDomains(since: new), Set(SyncDomain.allCases))
        XCTAssertEqual(new.changedDomains(since: new), [])
    }

    /// `sync_service.components` folds `feeds.yaml` and `calendars.yaml` into
    /// the `sources` component, so a `sources` bump must refresh the calendar
    /// list too — subscribing to an ICS feed changes nothing else.
    func testSourcesComponentAlsoRefreshesFeedsAndCalendars() {
        let base = ["sources": "a", "bank": "x"]
        let old = VersionVector(version: "1", components: base)
        let new = VersionVector(version: "2", components: ["sources": "b", "bank": "x"])
        XCTAssertEqual(new.changedDomains(since: old), [.sources, .feeds, .calendars])
    }
}
