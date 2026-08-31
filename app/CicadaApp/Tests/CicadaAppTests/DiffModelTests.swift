import XCTest
@testable import CicadaApp

/// G67 — the pure diff model behind the shared `DiffView`. Everything the view
/// renders (order, gutter glyphs, coloring bucket, the truncation notice) is
/// decided here so it can be tested without a view hierarchy.
final class DiffModelTests: XCTestCase {

    override func tearDown() {
        MockURLProtocol.handler = nil
        // CicadaTheme.mode is process-global mutable state (see CicadaTheme.swift);
        // restore its default so a light-mode assertion here can't bleed into
        // another test file that runs after this one.
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    // MARK: - G69: the ordered unified-diff shape
    //
    // The backend now sends `lines` — a real `git show -U4` diff with context
    // rows and git's own old/new line numbers. `DiffModel` must render it in
    // order, with the numbers intact, and must still fall back to the pre-G69
    // two-block shape when `lines` is absent (older backend, or a payload
    // cached before the upgrade).

    /// A one-line edit in the middle of a file, exactly as the backend emits it.
    private var unifiedDiff: EntityDiff {
        EntityDiff(
            added: "CHANGED",
            removed: "l5",
            truncated: false,
            lines: [
                EntityDiffLine(kind: "hunk", text: "@@ -1,10 +1,10 @@"),
                EntityDiffLine(kind: "context", oldLine: 4, newLine: 4, text: "l4"),
                EntityDiffLine(kind: "remove", oldLine: 5, newLine: nil, text: "l5"),
                EntityDiffLine(kind: "add", oldLine: nil, newLine: 5, text: "CHANGED"),
                EntityDiffLine(kind: "context", oldLine: 6, newLine: 6, text: "l6"),
            ]
        )
    }

    func testOrderedLinesArePreferredOverTheFlatBlocks() {
        let model = DiffModel(unifiedDiff)

        XCTAssertTrue(model.hasLineNumbers)
        XCTAssertEqual(model.lines.map(\.kind), [.hunk, .context, .removed, .added, .context])
        XCTAssertEqual(model.lines.map(\.text), ["@@ -1,10 +1,10 @@", "l4", "l5", "CHANGED", "l6"])
    }

    func testLineNumbersSurviveTheProjection() {
        let model = DiffModel(unifiedDiff)

        XCTAssertEqual(model.lines[0].oldLine, nil)      // hunk header: neither
        XCTAssertEqual(model.lines[0].newLine, nil)
        XCTAssertEqual(model.lines[1].oldLine, 4)        // context: both
        XCTAssertEqual(model.lines[1].newLine, 4)
        XCTAssertEqual(model.lines[2].oldLine, 5)        // removal: old only
        XCTAssertNil(model.lines[2].newLine)
        XCTAssertNil(model.lines[3].oldLine)             // addition: new only
        XCTAssertEqual(model.lines[3].newLine, 5)
    }

    func testContextRowsGetASpaceMarkerSoTextStaysColumnAligned() {
        let model = DiffModel(unifiedDiff)

        XCTAssertEqual(model.lines[1].gutter, " ")
        XCTAssertEqual(model.lines[2].gutter, "\u{2212}")
        XCTAssertEqual(model.lines[3].gutter, "+")
        XCTAssertEqual(model.lines[0].gutter, "")  // hunk header has no marker
    }

    func testAnUnknownWireKindDegradesToContextRatherThanBeingDropped() {
        let model = DiffModel(EntityDiff(
            added: "", removed: "",
            lines: [EntityDiffLine(kind: "meta-from-the-future", oldLine: 1, newLine: 1,
                                   text: "still shown")]
        ))

        XCTAssertEqual(model.lines.map(\.kind), [.context])
        XCTAssertEqual(model.lines[0].text, "still shown")
    }

    func testGutterWidthTracksTheWidestLineNumber() {
        let wide = DiffModel(EntityDiff(added: "", removed: "", lines: [
            EntityDiffLine(kind: "context", oldLine: 998, newLine: 1024, text: "x"),
        ]))
        XCTAssertEqual(wide.lineNumberDigits, 4)

        // Floor of 2 so a one-line file doesn't produce a hairline column.
        let narrow = DiffModel(EntityDiff(added: "", removed: "", lines: [
            EntityDiffLine(kind: "add", oldLine: nil, newLine: 1, text: "x"),
        ]))
        XCTAssertEqual(narrow.lineNumberDigits, 2)
    }

    func testRowIdsAreUniqueAcrossIdenticalRepeatedContextText() {
        // A page with repeated blank/boilerplate lines must not collapse rows.
        let model = DiffModel(EntityDiff(added: "", removed: "", lines: [
            EntityDiffLine(kind: "context", oldLine: 1, newLine: 1, text: ""),
            EntityDiffLine(kind: "context", oldLine: 2, newLine: 2, text: ""),
            EntityDiffLine(kind: "context", oldLine: 3, newLine: 3, text: ""),
        ]))

        XCTAssertEqual(Set(model.lines.map(\.id)).count, 3)
    }

    func testTruncationFlagStillSurfacesOnTheOrderedShape() {
        let model = DiffModel(EntityDiff(added: "a", removed: "", truncated: true, lines: [
            EntityDiffLine(kind: "add", oldLine: nil, newLine: 1, text: "a"),
        ]))

        XCTAssertTrue(model.truncated)
    }

    // MARK: - G69: decoding both wire shapes

    func testDecodingTheNewShapeKeepsOrderAndCamelCaseLineNumbers() throws {
        let json = """
        {"added": "CHANGED", "removed": "l5", "truncated": false, "lines": [
          {"kind": "hunk", "oldLine": null, "newLine": null, "text": "@@ -1,10 +1,10 @@"},
          {"kind": "context", "oldLine": 4, "newLine": 4, "text": "l4"},
          {"kind": "remove", "oldLine": 5, "newLine": null, "text": "l5"},
          {"kind": "add", "oldLine": null, "newLine": 5, "text": "CHANGED"}
        ]}
        """.data(using: .utf8)!

        let diff = try JSONDecoder().decode(EntityDiff.self, from: json)

        XCTAssertEqual(diff.lines.count, 4)
        XCTAssertEqual(diff.lines[1].oldLine, 4)
        XCTAssertEqual(diff.lines[3].newLine, 5)
        XCTAssertEqual(DiffModel(diff).lines.map(\.kind), [.hunk, .context, .removed, .added])
    }

    func testDecodingTheOldShapeWithoutLinesFallsBackToTwoBlocks() throws {
        // Exactly what a pre-G69 backend (or a payload cached before the
        // upgrade) sends: no `lines` key at all.
        let json = """
        {"added": "new one\\nnew two", "removed": "old one", "truncated": false}
        """.data(using: .utf8)!

        let model = DiffModel(try JSONDecoder().decode(EntityDiff.self, from: json))

        XCTAssertFalse(model.hasLineNumbers)
        XCTAssertEqual(model.lines.map(\.kind), [.removed, .added, .added])
        XCTAssertEqual(model.lines.map(\.text), ["old one", "new one", "new two"])
        XCTAssertTrue(model.lines.allSatisfy { $0.oldLine == nil && $0.newLine == nil })
        XCTAssertEqual(model.lineNumberDigits, 0)  // no gutters drawn
    }

    func testAnEmptyLinesArrayIsTreatedAsTheOldShapeNotAnEmptyDiff() throws {
        // The backend sends `lines: []` for a diff it couldn't produce; the
        // flat blocks (if any) must still render.
        let json = """
        {"added": "only add", "removed": "", "truncated": false, "lines": []}
        """.data(using: .utf8)!

        let model = DiffModel(try JSONDecoder().decode(EntityDiff.self, from: json))

        XCTAssertFalse(model.hasLineNumbers)
        XCTAssertEqual(model.lines.map(\.text), ["only add"])
    }

    func testAWireLineMissingOptionalFieldsStillDecodes() throws {
        let json = """
        {"lines": [{"kind": "add", "text": "x"}, {"text": "y"}]}
        """.data(using: .utf8)!

        let diff = try JSONDecoder().decode(EntityDiff.self, from: json)

        XCTAssertEqual(diff.lines.map(\.kind), ["add", "context"])
        XCTAssertNil(diff.lines[0].oldLine)
        XCTAssertEqual(DiffModel(diff).lines.map(\.kind), [.added, .context])
    }

    // MARK: - Parsing (legacy two-block shape)

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

    // MARK: - DiffCacheKey (G67 fix round 1)
    //
    // A per-commit diff cache keyed by commit hash alone lets one entity's
    // cached diff leak into another entity's row for a shared commit — one
    // Sleep-cycle commit routinely touches several entity files, so the same
    // hash commonly appears in more than one entity's history. `DiffCacheKey`
    // is the shared (entityId, commitHash) composite key both `EntityDetailCard`
    // and `ContributorsSection` cache their diff state under; this is the pure,
    // testable seam that composition rule lives in.

    func testTheSameCommitHashInTwoDifferentEntitiesProducesDistinctKeys() {
        let mongo = DiffCacheKey(entityId: "mongodb", commitHash: "abc1234")
        let postgres = DiffCacheKey(entityId: "postgres", commitHash: "abc1234")

        XCTAssertNotEqual(mongo, postgres)
    }

    func testTheSameEntityAndCommitProduceEqualKeys() {
        XCTAssertEqual(
            DiffCacheKey(entityId: "mongodb", commitHash: "abc1234"),
            DiffCacheKey(entityId: "mongodb", commitHash: "abc1234")
        )
    }

    func testASetOfKeysDeduplicatesOnlyExactEntityCommitPairs() {
        let keys: Set<DiffCacheKey> = [
            DiffCacheKey(entityId: "mongodb", commitHash: "abc1234"),
            DiffCacheKey(entityId: "postgres", commitHash: "abc1234"),
            DiffCacheKey(entityId: "mongodb", commitHash: "abc1234"),  // duplicate
        ]

        XCTAssertEqual(keys.count, 2)
    }

    func testADictionaryKeyedByDiffCacheKeyKeepsBothEntitiesDiffsSeparate() {
        // The concrete bug this guards against: entity B rendering entity A's
        // cached diff content for a commit hash the two share.
        var cache: [DiffCacheKey: EntityDiff] = [:]
        cache[DiffCacheKey(entityId: "mongodb", commitHash: "abc1234")] =
            EntityDiff(added: "mongodb's line", removed: "")
        cache[DiffCacheKey(entityId: "postgres", commitHash: "abc1234")] =
            EntityDiff(added: "postgres's line", removed: "")

        XCTAssertEqual(
            cache[DiffCacheKey(entityId: "mongodb", commitHash: "abc1234")]?.added,
            "mongodb's line"
        )
        XCTAssertEqual(
            cache[DiffCacheKey(entityId: "postgres", commitHash: "abc1234")]?.added,
            "postgres's line"
        )
    }

    // MARK: - CicadaTheme.diffAdded / diffRemoved (G67 fix round 1)
    //
    // DiffView must route through CicadaTheme rather than raw hex literals so
    // light mode gets its own deepened-for-contrast variant instead of the
    // dark-tuned value rendering unchanged in both themes.

    func testDiffColorsDifferBetweenLightAndDarkMode() {
        CicadaTheme.mode = .dark
        let darkAdded = CicadaTheme.diffAdded
        let darkRemoved = CicadaTheme.diffRemoved

        CicadaTheme.mode = .light
        let lightAdded = CicadaTheme.diffAdded
        let lightRemoved = CicadaTheme.diffRemoved

        XCTAssertNotEqual(darkAdded, lightAdded)
        XCTAssertNotEqual(darkRemoved, lightRemoved)
    }

    func testDiffAddedAndDiffRemovedAreDistinctInEachMode() {
        CicadaTheme.mode = .dark
        XCTAssertNotEqual(CicadaTheme.diffAdded, CicadaTheme.diffRemoved)

        CicadaTheme.mode = .light
        XCTAssertNotEqual(CicadaTheme.diffAdded, CicadaTheme.diffRemoved)
    }
}
