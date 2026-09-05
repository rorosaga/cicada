import XCTest
@testable import CicadaApp

/// G113 slice 3: `divergence` and `normalization` decode as real `InboxKind`
/// cases instead of failing the whole inbox array — Sleep has written both
/// kinds for months (`inbox_generator.py`'s `divergence_nudge`/
/// `normalization_audit` branches); the API only just started accepting them.
final class InboxKindDecodingTests: XCTestCase {
    func testDecodesNewKinds() throws {
        let json = #"""
        [{"id":"inbox-010","kind":"divergence","requiredInput":"choice","status":"pending","priority":0.5,
          "entityId":"bob-example","entityName":"Bob Example","title":"t","createdDate":"2026-08-02",
          "options":[{"key":"0","label":"Keep"},{"key":"1","label":"Update"},{"key":"2","label":"Both"}]},
         {"id":"inbox-011","kind":"normalization","requiredInput":"choice","status":"pending","priority":0.3,
          "entityId":"bob-example","entityName":"Bob Example","title":"t","createdDate":"2026-08-02",
          "options":[{"key":"0","label":"Correct fold"},{"key":"1","label":"Wrong fold"}]}]
        """#
        let items = try JSONDecoder().decode([InboxItem].self, from: Data(json.utf8))
        XCTAssertEqual(items.map(\.kind), [.divergence, .normalization])
        XCTAssertEqual(InboxKind.divergence.label, "Divergence")
        XCTAssertEqual(InboxKind.normalization.label, "Predicate fold")
    }
}
