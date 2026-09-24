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

    func testFullCardsPairUpAndTheRestShareShortRows() {
        XCTAssertEqual(ClustersGrid.rows(groups, expandAll: false), [
            .pair([.person, .project]), .pair([.company, .tool]), .pair([.concept, .media]),
            .short([.skill, .location, .directory]),
        ])
        XCTAssertEqual(ClustersGrid.rows([group(.person, 2), group(.skill, 1)], expandAll: false),
                       [.pair([.person]), .short([.skill])])
        XCTAssertEqual(ClustersGrid.rows([group(.person, 2), group(.tool, 1)], expandAll: true),
                       [.pair([.person]), .pair([.tool])], "Expand all: one card per row")
    }

    /// F-11's own counts: 6 tiles in the first row of cards, 4 after, 2 lines in a short card.
    func testTheTileBudgetIsF11s() {
        let rows = ClustersGrid.rows(groups, expandAll: false)
        XCTAssertEqual(ClustersGrid.budget(rows[0], index: 0, expandAll: false), 6)
        XCTAssertEqual(ClustersGrid.budget(rows[1], index: 1, expandAll: false), 4)
        XCTAssertEqual(ClustersGrid.budget(rows[3], index: 3, expandAll: false), 2)
        XCTAssertNil(ClustersGrid.budget(rows[0], index: 0, expandAll: true))
    }

    /// DR-68 — ↑/↓ walk the tiles in reading order: row by row, card by card.
    func testTheKeysWalkWhatIsDrawnInReadingOrder() {
        let visible = ClustersGrid.visible(groups, tab: nil, expandAll: false).map(\.id)
        XCTAssertEqual(visible.count, 6 + 6 + 4 + 4 + 4 + 4 + 2 + 2 + 2)
        XCTAssertEqual(Array(visible.prefix(7)), ["person-0", "person-1", "person-2", "person-3", "person-4", "person-5",
                                                  "project-0"])
        XCTAssertEqual(ClustersGrid.visible(groups, tab: .tool, expandAll: false).count, 22, "a tab shows every tile")
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
