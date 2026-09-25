import XCTest
@testable import CicadaApp

/// R-DL4 / R-DL5 — the owner's live check of #94: the list ignored ↑/↓/⏎ until clicked, and an option read
/// "tool-example-a" where the page is "Tool Example A".
final class InboxKeysAndNamesTests: XCTestCase {
    // MARK: R-DL4 — where the keys land

    func testArrivalAndAnAnswerGiveTheListTheKeys() {
        XCTAssertEqual(InboxFocusPolicy.afterArrivalOrAnswer(listHidden: false, questionOpen: true), .list)
        XCTAssertEqual(InboxFocusPolicy.afterArrivalOrAnswer(listHidden: false, questionOpen: false), .list)
        XCTAssertEqual(InboxFocusPolicy.afterArrivalOrAnswer(listHidden: true, questionOpen: true), .question,
                       "DR-27 hid the list: the question takes the keys, never nothing")
        XCTAssertNil(InboxFocusPolicy.afterArrivalOrAnswer(listHidden: true, questionOpen: false))
    }

    /// Source pin: the page asks the policy at both moments (a hosted-window test cannot run headless).
    func testThePageAsksThePolicyOnArrivalAndAfterAnAnswer() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Inbox/InboxPage.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertGreaterThanOrEqual(text.components(separatedBy: "InboxFocusPolicy.afterArrivalOrAnswer(").count - 1, 2)
    }

    // MARK: R-DL5 — an id reads as its page's name

    private let names = EntityNames(byId: ["tool-example-a": "Tool Example A", "alpha-project": "Alpha Project"])

    func testAnIdTheGraphHoldsReadsAsItsName() {
        XCTAssertEqual(names.display("tool-example-a"), "Tool Example A")
        XCTAssertEqual(names.display(" alpha-project "), "Alpha Project")
        XCTAssertEqual(names.name(for: "alpha-project"), "Alpha Project")
    }

    func testAnythingElseStaysExactlyAsWritten() {
        XCTAssertEqual(names.display("Tool Example A"), "Tool Example A")
        XCTAssertEqual(names.display("tool-example-z"), "tool-example-z", "never humanise an id the graph lacks")
        XCTAssertEqual(names.display(""), "")
        XCTAssertNil(names.name(for: "tool-example-z"))
        XCTAssertEqual(EntityNames.empty.display("tool-example-a"), "tool-example-a")
    }

    func testFacetsAreNotPages() {
        let n = EntityNames(nodes: [GraphNode(id: "tool-example-a", name: "Tool Example A", type: .tool),
                                    GraphNode(id: "bob-example#work", name: "work", type: .person, isFacet: true)])
        XCTAssertEqual(n.display("tool-example-a"), "Tool Example A")
        XCTAssertEqual(n.display("bob-example#work"), "bob-example#work")
    }

    @MainActor
    func testTheStoreRereadsTheGraphWhenItChanges() {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        XCTAssertEqual(store.entityNames.display("tool-example-a"), "tool-example-a")
        store.graph.value = GraphResponse(nodes: [GraphNode(id: "tool-example-a", name: "Tool Example A", type: .tool)])
        store.graph.loadedAt = Date()
        XCTAssertEqual(store.entityNames.display("tool-example-a"), "Tool Example A")
        store.graph.value = GraphResponse(nodes: [GraphNode(id: "tool-example-a", name: "Tool A (renamed)", type: .tool)])
        store.graph.loadedAt = Date().addingTimeInterval(1)
        XCTAssertEqual(store.entityNames.display("tool-example-a"), "Tool A (renamed)")
    }

    /// The Undo row names the answer the way the card did.
    func testTheUndoRowSaysTheName() throws {
        let json = #"{"id":"1","kind":"conflict","requiredInput":"choice","title":"t","options":[{"key":"a","label":"tool-example-a"}]}"#
        let item = try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
        let words = UndoLabel.of(QuestionResolution(action: "resolve", optionKey: "a"), item: item, names: names)
        XCTAssertEqual(words.full, "Answered · Tool Example A")
        XCTAssertEqual(UndoLabel.of(QuestionResolution(action: "resolve", optionKey: "a"), item: item).full,
                       "Answered · tool-example-a", "no names, no change")
    }
}
