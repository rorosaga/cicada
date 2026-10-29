import XCTest
@testable import CicadaApp

/// G227 — same name, different things. The backend derives a short qualifier when two pages share a title
/// (`same_name`); the app decodes it, shows `<name> (<qualifier>)` on every list, and a bare `[[<name>]]` link that two
/// pages answer to asks which one instead of picking. Placeholders: `Alpha` is `<name-a>`.
final class SameNameTests: XCTestCase {

    func test_graphNode_decodesTheQualifier_andShowsTheQualifiedName() throws {
        let json = #"""
        {"id": "alpha", "name": "Alpha", "type": "tool", "status": "active", "confidence": 0.8,
         "qualifier": "IDE", "displayName": "Alpha (IDE)"}
        """#
        let node = try JSONDecoder().decode(GraphNode.self, from: Data(json.utf8))
        XCTAssertEqual(node.qualifier, "IDE")
        XCTAssertEqual(node.shownName, "Alpha (IDE)")
        XCTAssertEqual(node.name, "Alpha", "the stored title stays clean")
    }

    func test_aTitleOfItsOwn_showsTheBareName_andAnOlderPayloadStillDecodes() throws {
        let json = #"{"id": "beta", "name": "Beta", "type": "tool", "status": "active", "confidence": 0.8}"#
        let node = try JSONDecoder().decode(GraphNode.self, from: Data(json.utf8))
        XCTAssertNil(node.qualifier)
        XCTAssertEqual(node.shownName, "Beta")
    }

    func test_theCardDecodesTheQualifiedName() throws {
        let json = #"""
        {"id": "alpha-program", "name": "Alpha", "type": "project", "status": "active", "confidence": 0.8,
         "created": "", "lastReferenced": "", "decayRate": 0, "markdownContent": "",
         "qualifier": "program", "displayName": "Alpha (program)"}
        """#
        let entity = try JSONDecoder().decode(Entity.self, from: Data(json.utf8))
        XCTAssertEqual(entity.shownName, "Alpha (program)")
        let roundTrip = try JSONDecoder().decode(Entity.self, from: JSONEncoder().encode(entity))
        XCTAssertEqual(roundTrip.displayName, "Alpha (program)", "a held card keeps it")
    }

    func test_inboxOptionsAndMergeTilesNameAPageByItsQualifiedName() {
        let names = EntityNames(nodes: [
            GraphNode(id: "alpha", name: "Alpha", type: .tool, qualifier: "IDE", displayName: "Alpha (IDE)"),
            GraphNode(id: "beta", name: "Beta", type: .tool),
        ])
        XCTAssertEqual(names.display("alpha"), "Alpha (IDE)")
        XCTAssertEqual(names.display("beta"), "Beta")
    }

    func test_aLinkToASharedNameNamesEveryPage_neverPicksOne() {
        let nodes = [
            GraphNode(id: "alpha", name: "Alpha", type: .tool, qualifier: "IDE", displayName: "Alpha (IDE)"),
            GraphNode(id: "alpha-program", name: "Alpha", type: .project, qualifier: "program",
                      displayName: "Alpha (program)"),
            GraphNode(id: "beta", name: "Beta", type: .tool),
        ]
        XCTAssertEqual(Set(MarkdownBody.entityIDs("Alpha", in: nodes)), ["alpha", "alpha-program"])
        XCTAssertEqual(MarkdownBody.entityIDs("alpha-program", in: nodes), ["alpha-program"], "an id is one page")
        XCTAssertEqual(MarkdownBody.entityIDs("Beta", in: nodes), ["beta"])
        XCTAssertEqual(MarkdownBody.entityIDs("Gamma Delta", in: nodes), ["gamma-delta"], "the old fallback holds")
    }

    func test_serverSearchRowsAndProjectRowsTakeTheQualifiedName() throws {
        let hit = try JSONDecoder().decode(MemorySearchHit.self, from: Data(#"""
        {"id": "alpha", "name": "Alpha", "type": "tool", "status": "active", "kind": "entity",
         "qualifier": "IDE", "displayName": "Alpha (IDE)"}
        """#.utf8))
        XCTAssertEqual(hit.shownName, "Alpha (IDE)")
        let row = try JSONDecoder().decode(ProjectPageRow.self, from: Data(#"""
        {"id": "alpha", "name": "Alpha", "displayName": "Alpha (IDE)"}
        """#.utf8))
        XCTAssertEqual(row.shownName, "Alpha (IDE)")
        let page = try JSONDecoder().decode(SleepConsolidated.Page.self, from: Data(#"""
        {"id": "alpha", "name": "Alpha", "displayName": "Alpha (IDE)"}
        """#.utf8))
        XCTAssertEqual(RunItemGroups.pageLabel(page, names: EntityNames.empty), "Alpha (IDE)")
    }

    func test_anInboxItemDecodesItsDisplayNames() throws {
        let item = try JSONDecoder().decode(InboxItem.self, from: Data(#"""
        {"id": "c-1", "kind": "clarification", "requiredInput": "freetext", "title": "Who is Alpha?",
         "entityId": "alpha", "entityName": "Alpha", "entityDisplayName": "Alpha (IDE)",
         "sameTitle": ["alpha", "alpha-program"]}
        """#.utf8))
        XCTAssertEqual(item.displayName, "Alpha (IDE)")
        XCTAssertEqual(item.sameTitle, ["alpha", "alpha-program"])
    }

    // MARK: - the qualifier as a tag, and pick the page (owner 2026-10-29)

    func test_paletteRowsShowThePlainName_withTheQualifierBesideIt() throws {
        let response = try JSONDecoder().decode(MemorySearchResponse.self, from: Data(#"""
        {"results": [{"id": "alpha", "name": "Alpha", "type": "tool", "status": "active", "kind": "entity",
                      "qualifier": "IDE", "displayName": "Alpha (IDE)"},
                     {"id": "alpha-program", "name": "Alpha", "type": "project", "status": "active", "kind": "entity",
                      "qualifier": "program", "displayName": "Alpha (program)"}],
         "totals": {}, "mode": "lexical", "indexState": "ready"}
        """#.utf8))
        let rows = FindServerRows.rows(response, query: "Alpha", context: .init())
        XCTAssertEqual(rows.map(\.title), ["Alpha", "Alpha"], "searching the bare name finds both, titled plainly")
        XCTAssertEqual(rows.map(\.qualifier), ["IDE", "program"])
        XCTAssertTrue(FindRowText.accessibilityLabel(rows[0]).contains("IDE"), "VoiceOver hears which one")
    }

    func test_theRunCardSaysTheQualifierInsideThePagesTag() {
        let page = SleepConsolidated.Page(id: "alpha", name: "Alpha", displayName: "Alpha (IDE)", qualifier: "IDE")
        XCTAssertEqual(RunItemGroups.pageLabel(page, names: EntityNames.empty), "Alpha · IDE")
    }

    func test_aPickThePageOptionDecodesItsPage_andTheCatchUpAnswersWithItsKey() throws {
        let item = try JSONDecoder().decode(InboxItem.self, from: Data(#"""
        {"id": "inbox-002", "kind": "merge_suggestion", "requiredInput": "merge", "title": "Which Alpha is this?",
         "entityId": "alpha", "entityName": "Alpha", "mergeTargetHint": "alpha", "sameTitle": ["alpha", "alpha-program"],
         "options": [{"key": "page:alpha", "label": "Alpha (IDE)", "pageId": "alpha", "pageName": "Alpha",
                      "qualifier": "IDE"},
                     {"key": "page:alpha-program", "label": "Alpha (program)", "pageId": "alpha-program",
                      "pageName": "Alpha", "qualifier": "program"},
                     {"key": "another", "label": "Another one"}]}
        """#.utf8))
        XCTAssertEqual(item.options.map(\.pageName), ["Alpha", "Alpha", nil])
        XCTAssertEqual(item.options.map(\.qualifier), ["IDE", "program", nil])
        XCTAssertEqual(FocusCardVariant.of(item), .options, "one tap per page, never same/different")
        let reading = CatchupTurnReply.Reading(optionKey: "page:alpha-program", answer: nil, quote: "the program one",
                                               confirm: false)
        let resolution = try XCTUnwrap(CatchupAnswers.resolution(item, reading))
        XCTAssertEqual(resolution.action, "resolve")
        XCTAssertEqual(resolution.optionKey, "page:alpha-program")
    }
}
