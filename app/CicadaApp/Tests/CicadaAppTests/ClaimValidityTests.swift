import XCTest
@testable import CicadaApp

final class ClaimValidityTests: XCTestCase {
    func testSuccessorOnlyHistoryNeverReadsAsCurrentInTheTimelineOrChip() throws {
        let data = Data(#"{"id":"clm_old","text":"Earlier calibration method","subject":"alpha-project","predicate":"uses","object":"amber","supersededBy":"clm_new"}"#.utf8)
        let claim = try JSONDecoder().decode(Claim.self, from: data)
        XCTAssertNil(claim.validTo)
        XCTAssertFalse(claim.isValid)
    }
}
