import XCTest
@testable import CicadaApp

/// G67 — the pure diff model behind the shared `DiffView`. Everything the view
/// renders (order, gutter glyphs, coloring bucket, the truncation notice) is
/// decided here so it can be tested without a view hierarchy.
final class DiffModelTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Parsing

    func testRemovedLinesComeFirstThenAddedLines() {
        let model = DiffModel(EntityDiff(added: "new one\nnew two", removed: "old one"))

        XCTAssertEqual(model.lines.map(\.kind), [.removed, .added, .added])
        XCTAssertEqual(model.lines.map(\.text), ["old one", "new one", "new two"])
    }

    func testGutterGlyphsAreMinusAndPlus() {
        let model = DiffModel(EntityDiff(added: "a", removed: "r"))

        XCTAssertEqual(model.lines[0].gutter, "\u{2212}")  // real minus sign, not a hyphen
        XCTAssertEqual(model.lines[1].gutter, "+")
    }

    func testAnEmptyDiffProducesNoLines() {
        let model = DiffModel(EntityDiff(added: "", removed: ""))

        XCTAssertTrue(model.lines.isEmpty)
        XCTAssertTrue(model.isEmpty)
    }

    func testAOneSidedDiffIsNotEmpty() {
        XCTAssertFalse(DiffModel(EntityDiff(added: "only additions", removed: "")).isEmpty)
        XCTAssertFalse(DiffModel(EntityDiff(added: "", removed: "only removals")).isEmpty)
    }

    func testBlankLinesInsideAHunkArePreservedAsContent() {
        let model = DiffModel(EntityDiff(added: "first\n\nthird", removed: ""))

        XCTAssertEqual(model.lines.count, 3)
        XCTAssertEqual(model.lines[1].text, "")
    }

    func testATrailingNewlineDoesNotProduceAPhantomLine() {
        let model = DiffModel(EntityDiff(added: "one\ntwo\n", removed: ""))

        XCTAssertEqual(model.lines.map(\.text), ["one", "two"])
    }

    func testLineIdentityIsStableAndUniqueAcrossSides() {
        // Both sides can carry the exact same text (a line moved within the
        // file); ForEach must not collapse them into one row.
        let model = DiffModel(EntityDiff(added: "same", removed: "same"))

        XCTAssertEqual(model.lines.count, 2)
        XCTAssertNotEqual(model.lines[0].id, model.lines[1].id)
    }

    // MARK: - Truncation

    func testTheBackendTruncationMarkerBecomesItsOwnKindNotAContentLine() {
        let model = DiffModel(EntityDiff(
            added: "kept\n\(DiffModel.truncationMarker)",
            removed: "",
            truncated: true
        ))

        XCTAssertEqual(model.lines.map(\.kind), [.added, .truncation])
        XCTAssertTrue(model.truncated)
    }

    func testTheTruncationMarkerHasNoGutterGlyph() {
        let model = DiffModel(EntityDiff(added: DiffModel.truncationMarker, removed: "",
                                         truncated: true))

        XCTAssertEqual(model.lines[0].gutter, "")
    }

    func testTruncatedFlagIsCarriedEvenWhenNoMarkerLineIsPresent() {
        // The backend only appends the marker to a NON-EMPTY side, so a diff can
        // be flagged truncated with the marker on the other side only.
        let model = DiffModel(EntityDiff(added: "kept", removed: "", truncated: true))

        XCTAssertTrue(model.truncated)
        XCTAssertEqual(model.lines.map(\.kind), [.added])
    }

    func testTheMarkerStringMatchesTheBackendConstant() {
        // git_service._DIFF_TRUNCATION_MARKER — keep these two in lockstep.
        XCTAssertEqual(DiffModel.truncationMarker, "... [diff truncated]")
    }

    // MARK: - APIClient.fetchEntityCommitDiff

    func testFetchEntityCommitDiffGETsTheCommitPathAndDecodes() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(
                request.url?.path,
                "/entities/mongodb/history/abc1234/diff"
            )
            let body = """
            {"added": "line b", "removed": "line a", "truncated": false}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                            httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let diff = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchEntityCommitDiff(id: "mongodb", commitHash: "abc1234")

        XCTAssertEqual(DiffModel(diff).lines.map(\.text), ["line a", "line b"])
    }
}
