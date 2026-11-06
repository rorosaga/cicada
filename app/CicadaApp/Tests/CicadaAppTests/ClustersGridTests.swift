import SwiftUI
import XCTest
@testable import CicadaApp

/// F-11 (plan R-PE12) — the All grid, pure: which cards share a row, how many tiles each shows, and the order the keys
/// walk.
final class ClustersGridTests: XCTestCase {
    private func e(_ id: String, _ type: EntityType) -> Entity {
        Entity(id: id, name: id, type: type, status: .active, confidence: 0.8, created: "", lastReferenced: "",
               decayRate: 0, sourceEpisodes: [], tags: [], related: [], version: 0, markdownContent: "", history: [])
    }

    private func group(_ type: EntityType, _ n: Int) -> ClustersModel.Group {
        ClustersModel.Group(type: type, entities: (0..<n).map { e("\(type.rawValue)-\($0)", type) })
    }

    private var groups: [ClustersModel.Group] {
        [group(.person, 18), group(.project, 14), group(.company, 9), group(.tool, 22), group(.concept, 31),
         group(.media, 40), group(.skill, 6), group(.location, 4), group(.directory, 3)]
    }

    func testFacesLeadListsAndMediaThenTheShortRows() {
        XCTAssertEqual(ClustersGrid.rows(groups, expandAll: false), [
            .faces([.person]), .lead([.project]), .trio([.company, .tool, .concept]), .gallery([.media]),
            .short([.skill, .location, .directory]),
        ])
        XCTAssertEqual(ClustersGrid.rows([group(.person, 2), group(.skill, 1)], expandAll: false),
                       [.faces([.person]), .short([.skill])])
        XCTAssertEqual(ClustersGrid.rows([group(.tool, 2), group(.concept, 1)], expandAll: false),
                       [.trio([.tool, .concept])], "a missing list leaves its slot, not a hole in the order")
        XCTAssertEqual(ClustersGrid.rows([group(.person, 2), group(.tool, 1)], expandAll: true),
                       [.pair([.person]), .pair([.tool])], "Expand all: one card per row")
    }

    /// ROR-118 — 8 portraits, 3 project cards, 5 names a list, 6 media, 2 lines in a short card.
    func testTheBudgetIsOneStripOneRowOfCardsAndShortLists() {
        let rows = ClustersGrid.rows(groups, expandAll: false)
        XCTAssertEqual(ClustersGrid.budget(rows[0], index: 0, expandAll: false), 8)
        XCTAssertEqual(ClustersGrid.budget(rows[1], index: 1, expandAll: false), 3)
        XCTAssertEqual(ClustersGrid.budget(rows[2], index: 2, expandAll: false), 5)
        XCTAssertEqual(ClustersGrid.budget(rows[3], index: 3, expandAll: false), 6)
        XCTAssertEqual(ClustersGrid.budget(rows[4], index: 4, expandAll: false), 2)
        XCTAssertNil(ClustersGrid.budget(rows[0], index: 0, expandAll: true))
    }

    /// DR-68 — ↑/↓ walk what is drawn in reading order: row by row, section by section.
    func testTheKeysWalkWhatIsDrawnInReadingOrder() {
        let visible = ClustersGrid.visible(groups, tab: nil, expandAll: false).map(\.id)
        XCTAssertEqual(visible.count, 8 + 3 + 5 + 5 + 5 + 6 + 2 + 2 + 2)
        XCTAssertEqual(Array(visible.prefix(10)), (0..<8).map { "person-\($0)" } + ["project-0", "project-1"])
        XCTAssertEqual(ClustersGrid.visible(groups, tab: .tool, expandAll: false).count, 22, "a tab shows every tile")
    }

    /// ROR-118 round 3 — the strip puts photos first; the name lists and Media put the dimmed ones last.
    func testPhotosLeadTheStripAndDimmedNamesComeLast() {
        let people = (0..<6).map { e("p\($0)", .person) }
        let faces = ClustersGrid.shown(people, type: .person, row: .faces([.person]), budget: 4,
                                       pictured: { ["p1", "p3"].contains($0.id) })
        XCTAssertEqual(faces.map(\.id), ["p1", "p3", "p0", "p2"], "photos first, each part in the model's order")
        var tools = (0..<5).map { e("t\($0)", .tool) }
        tools[0].quiet = true
        tools[2].quiet = true
        let shown = ClustersGrid.shown(tools, type: .tool, row: .trio([.tool]), budget: 4, pictured: { _ in false })
        XCTAssertEqual(shown.map(\.id), ["t1", "t3", "t4", "t0"], "dimmed last, then the budget")
        let walk = ClustersGrid.visible([ClustersModel.Group(type: .tool, entities: tools)], tab: nil, expandAll: false)
        XCTAssertEqual(walk.map(\.id), ["t1", "t3", "t4", "t0", "t2"], "the keys walk what is drawn")
    }

    func testThePortraitsAndCardsRegroupUnderNineHundredUnits() {
        XCTAssertEqual(ClustersGrid.faceColumns(width: 1200, scale: 1.0), 8)
        XCTAssertEqual(ClustersGrid.faceColumns(width: 800, scale: 1.0), 4)
        XCTAssertEqual(ClustersGrid.leadColumns(width: 1200, scale: 1.0), 3)
        XCTAssertEqual(ClustersGrid.leadColumns(width: 1200, scale: 1.4), 1, "857 units")
    }

    func testATabsCardWidensWithTheWindowAndNarrowsWithZoom() {
        XCTAssertEqual(ClustersGrid.tabColumns(width: 800, scale: 1.0), 2)
        XCTAssertEqual(ClustersGrid.tabColumns(width: 1100, scale: 1.0), 3)
        XCTAssertEqual(ClustersGrid.tabColumns(width: 1400, scale: 1.0), 4)
        XCTAssertEqual(ClustersGrid.tabColumns(width: 1400, scale: 1.4), 3, "1000 units")
        XCTAssertEqual(ClustersGrid.tabColumns(width: 1200, scale: 1.4), 2, "857 units")
    }

    /// DR-70 — a tile never wants more than a half card at 0.8×, 1× and 1.4×.
    @MainActor
    func testATileFitsItsHalfCardAtEveryZoom() throws {
        defer { CicadaTheme.uiScale = 1.0 }
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        var entity = e("bob-example", .person)
        entity.name = String(repeating: "Bob Example ", count: 6)
        entity.markdownContent = String(repeating: "Runs the lab cluster. ", count: 8)
        for scale in [0.8, 1.0, 1.4] {
            CicadaTheme.uiScale = scale
            let width = CGFloat(280 * scale)
            let renderer = ImageRenderer(content: ClusterTile(entity: entity) {}.environment(store))
            renderer.proposedSize = ProposedViewSize(width: width, height: nil)
            let size = try XCTUnwrap(renderer.nsImage).size
            XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(scale): \(size.width)")
        }
    }
}
