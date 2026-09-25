import XCTest
@testable import CicadaApp

/// Test gap 3 — the merge-reject contract was tested on the server
/// (`api/tests/test_merge_rejections.py:116-120` proves an explicit
/// `merge_target` works) and untested on the client, so a "Keep separate"
/// that sent NO target passed both suites while 400ing in the app.
///
/// `inbox_service.resolve` resolves the other side of the pair as
/// `merge_target_hint` OR `request.merge_target` and raises 400 when both are
/// empty — and the hint is absent exactly when the extractor wrote "Possible
/// duplicate" with no candidate (`clarification_manager.py:155-169` returns
/// None) or when the item was migrated (`inbox_migration.py:154-157` only sets
/// the key `if hint`). The name is sitting in the field two rows above the
/// button; the view just never sent it.
final class InboxMergeRejectTests: XCTestCase {

    func testRejectCarriesTheExistingEntityAsItsMergeTarget() {
        let r = MergeReject.resolution(existingName: "alpha-project")
        XCTAssertEqual(r?.action, "reject")
        XCTAssertEqual(r?.mergeTarget, "alpha-project")
        XCTAssertNil(r?.mergeSurvivor, "a reject decides nothing about which name survives")
    }

    func testWhitespaceIsTrimmedAndAnEmptyTargetProducesNoRequest() {
        XCTAssertEqual(MergeReject.resolution(existingName: "  alpha-project  ")?.mergeTarget, "alpha-project")
        XCTAssertNil(MergeReject.resolution(existingName: "   "),
                     "with no hint and nothing typed there is no pair to remember — disable, never 400")
        XCTAssertNil(MergeReject.resolution(existingName: ""))
    }
}
