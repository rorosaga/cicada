import SwiftUI
import XCTest
@testable import CicadaApp

/// §10 Graph / R-DG3 … R-DG8 — the Graph's chrome, pure, plus one fit test for the group's floor. The views in
/// `Views/Graph/` render these and decide nothing.
final class GraphChromeTests: XCTestCase {
    /// R-DG4 — "filtered" whenever a filter differs from the defaults; the observer lens (the tabs) and
    /// Show logos (paint) never count.
    func testTheLegendSaysFilteredOnlyWhenAFilterMoved() {
        XCTAssertEqual(GraphChrome.legendLabel(GraphFilter()), "Legend")
        var f = GraphFilter(); f.observers = ["agent"]; f.showLogos = true
        XCTAssertEqual(GraphChrome.legendLabel(f), "Legend", "the tabs and the logos are not filters")
        let changes: [(inout GraphFilter) -> Void] = [
            { $0.toggleType(.person) },
            { $0.toggleStatus(.archived) },
            { $0.minConfidence = 0.3 },
            { $0.contexts = ["engineering"] },
        ]
        for change in changes {
            var g = GraphFilter(); change(&g)
            XCTAssertEqual(GraphChrome.legendLabel(g), "Legend · filtered")
        }
    }

    /// R-DG4 — pages only (a hub or a satellite is a view), busiest first, and a type switched off stays
    /// listed at 0 so it can come back.
    func testTypeRowsCountPagesBusiestFirst() {
        let nodes = [GraphNode(id: "a", name: "A", type: .person), GraphNode(id: "b", name: "B", type: .person),
                     GraphNode(id: "c", name: "C", type: .tool), GraphNode(id: "h", name: "H", type: .concept, isHub: true),
                     GraphNode(id: "a#x", name: "A", type: .person, isFacet: true, parentId: "a", context: "x")]
        var filter = GraphFilter(); filter.toggleType(.skill)
        let rows = GraphChrome.typeRows(nodes: nodes, filter: filter)
        XCTAssertEqual(rows.map(\.type), [.person, .tool, .skill])
        XCTAssertEqual(rows.map(\.count), [2, 1, 0])
        XCTAssertEqual(rows.map(\.isOn), [true, true, false])
    }

    /// R-DG4 — today's context semantics: none chosen is every context; a click shows only that one.
    func testContextRowsKeepTheOneTapSubgraph() {
        let edges = [GraphEdge(source: "a", target: "b", label: "uses", context: "engineering"),
                     GraphEdge(source: "a", target: "c", label: "knows", context: "career"),
                     GraphEdge(source: "b", target: "c", label: "uses", context: "engineering")]
        var filter = GraphFilter()
        XCTAssertEqual(GraphChrome.contextRows(roster: ["career", "engineering"], edges: edges, filter: filter).map(\.isOn), [true, true])
        filter.toggleContext("engineering")
        let rows = GraphChrome.contextRows(roster: ["career", "engineering"], edges: edges, filter: filter)
        XCTAssertEqual(rows.map(\.links), [1, 2])
        XCTAssertEqual(rows.map(\.isOn), [false, true])
        XCTAssertEqual(GraphChrome.linksLabel(1), "1 link")
        XCTAssertEqual(GraphChrome.linksLabel(2), "2 links")
    }

    func testStatusRowsAreWordsWithTheirHints() {
        let rows = GraphChrome.statusRows(GraphFilter())
        XCTAssertEqual(rows.map(\.label), ["Active", "Fading", "Archived", "Dropped"])
        XCTAssertEqual(rows.map(\.isOn), [true, true, false, false])
        XCTAssertEqual(rows.map(\.hint), [nil, "dashed", "hidden by default", "hidden by default"])
    }

    /// DR-59 — no bare "%".
    func testMinimumConfidenceIsWords() {
        XCTAssertEqual(GraphChrome.minConfidenceLabel(0), "Any")
        XCTAssertEqual(GraphChrome.minConfidenceLabel(0.004), "Any")
        XCTAssertEqual(GraphChrome.minConfidenceLabel(0.5), "50 or more")
        XCTAssertFalse(GraphChrome.minConfidenceLabel(0.85).contains("%"))
    }

    /// The wires are `GraphViewModel.setObserver`'s; nil is All (DR-45: tapping the active tab returns to it).
    func testObserverTabsAreTheWiresSetObserverKnows() {
        XCTAssertEqual(GraphChrome.observerTabs.map(\.id), [nil, "agent", "__owner__", "external"])
        XCTAssertEqual(GraphChrome.observerTabs.map(\.label), ["All", "Cicada", "You", "External"])
    }

    /// R-DG3 — the mock's 640 breakpoint, and a group that hides when the canvas is narrower than it.
    func testTheGroupMovesTheTabsThenHides() {
        XCTAssertEqual(GraphChromeLayout.group(canvasWidth: 824, scale: 1, hasObserverTabs: true), .full)
        XCTAssertEqual(GraphChromeLayout.group(canvasWidth: 484, scale: 1, hasObserverTabs: true), .compact)
        XCTAssertEqual(GraphChromeLayout.group(canvasWidth: 824, scale: 1.4, hasObserverTabs: true), .compact, "units, not points")
        XCTAssertEqual(GraphChromeLayout.group(canvasWidth: 1200, scale: 1, hasObserverTabs: false), .compact)
        XCTAssertEqual(GraphChromeLayout.group(canvasWidth: 344, scale: 1, hasObserverTabs: true), .compact,
                       "the rail + Reader + column at 1200 pt keeps its group")
        XCTAssertEqual(GraphChromeLayout.group(canvasWidth: 300, scale: 1, hasObserverTabs: true), .hidden, "never clipped")
        XCTAssertEqual(GraphChromeLayout.group(canvasWidth: 192, scale: 1, hasObserverTabs: true), .hidden)
        XCTAssertTrue(GraphChromeLayout.tabsInPanel(.compact, hasObserverTabs: true))
        XCTAssertFalse(GraphChromeLayout.tabsInPanel(.full, hasObserverTabs: true))
        XCTAssertFalse(GraphChromeLayout.tabsInPanel(.compact, hasObserverTabs: false))
    }

    /// R-DG3 — `groupMinWidth` is the widest group the page draws ("Legend · filtered" with three context hues,
    /// − + fit and pan) plus its inset on each side, at every zoom: under it the group hides rather than clip.
    @MainActor
    func testTheWidestGroupFitsItsFloor() throws {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        store.graph.value = GraphResponse(links: [
            GraphEdge(source: "a", target: "b", label: "uses", context: "engineering"),
            GraphEdge(source: "a", target: "c", label: "knows", context: "career"),
            GraphEdge(source: "b", target: "c", label: "uses", context: "family"),
        ])
        store.graph.loadedAt = Date()
        let vm = GraphViewModel(store: store)   // `init` syncs the snapshot above synchronously
        vm.filter.minConfidence = 0.3
        XCTAssertEqual(vm.contextRoster.count, 3, "three hues on the Legend button")
        XCTAssertEqual(GraphChrome.legendLabel(vm.filter), "Legend · filtered")
        defer { CicadaTheme.uiScale = 1.0 }
        for scale in [1.0, 1.4] {
            CicadaTheme.uiScale = scale
            let renderer = ImageRenderer(content: GraphControlGroup(showsObserverTabs: false, legendOpen: false,
                                                                    onToggleLegend: {}).environment(vm))
            let width = try XCTUnwrap(renderer.nsImage).size.width
            XCTAssertLessThanOrEqual(width + 2 * CicadaTheme.spacingLG, GraphChromeLayout.groupMinWidth * CGFloat(scale) + 0.5,
                                     "\(scale): the widest group is \(width) wide")
        }
    }

    /// DR-28 / R-DG7 — Esc closes one thing per press, the topmost first.
    func testEscapeClosesTheTopmostThingFirst() {
        typealias S = GraphDismiss.State
        XCTAssertEqual(GraphDismiss.escape(S(findOpen: true, legendOpen: true, readerOpen: true, entityOpen: true)), .closeFind)
        XCTAssertEqual(GraphDismiss.escape(S(legendOpen: true, readerOpen: true, entityOpen: true)), .closeLegend)
        XCTAssertEqual(GraphDismiss.escape(S(readerOpen: true, entityOpen: true)), .closeReader)
        XCTAssertEqual(GraphDismiss.escape(S(entityOpen: true)), .closeEntity)
        XCTAssertEqual(GraphDismiss.escape(S()), .none)
    }

    /// R-DG8 — an outside click dismisses a panel first; then it closes the column and its Reader (R-DG7).
    func testABackgroundClickDismissesAPanelBeforeTheColumn() {
        typealias S = GraphDismiss.State
        XCTAssertEqual(GraphDismiss.backgroundClick(S(legendOpen: true, entityOpen: true)), .closePanels)
        XCTAssertEqual(GraphDismiss.backgroundClick(S(findOpen: true)), .closePanels)
        XCTAssertEqual(GraphDismiss.backgroundClick(S(readerOpen: true, entityOpen: true)), .closeEntityAndReader)
        XCTAssertEqual(GraphDismiss.backgroundClick(S(entityOpen: true)), .closeEntity)
        XCTAssertEqual(GraphDismiss.backgroundClick(S(readerOpen: true)), .none, "a Reader opened elsewhere stays (R-DI8)")
        XCTAssertEqual(GraphDismiss.close(S(readerOpen: true, entityOpen: true)), .closeEntityAndReader)
        XCTAssertEqual(GraphDismiss.close(S(entityOpen: true)), .closeEntity)
    }

    /// R-DG5 — Esc in the find field clears, then closes.
    func testFindEscapeClearsThenCloses() {
        XCTAssertEqual(GraphFind.escape(textIsEmpty: false), .clear)
        XCTAssertEqual(GraphFind.escape(textIsEmpty: true), .close)
    }

    /// The tabs' selection lives in the view model now (it was the retired bar's own `@State`).
    @MainActor
    func testSetObserverRecordsTheSelection() {
        let vm = GraphViewModel(store: Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI()))
        vm.setObserver("agent")
        XCTAssertEqual(vm.observerSelection, "agent")
        XCTAssertEqual(vm.filter.observers, ["agent"])
        vm.setObserver(nil)
        XCTAssertNil(vm.observerSelection)
        XCTAssertTrue(vm.filter.observers.isEmpty)
    }
}
