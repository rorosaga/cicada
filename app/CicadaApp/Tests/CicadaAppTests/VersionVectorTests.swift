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
}
