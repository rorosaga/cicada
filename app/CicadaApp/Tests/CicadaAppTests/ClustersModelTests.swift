import XCTest
@testable import CicadaApp

/// R-DL9 / R-DL11 / R-DL12 — what Clusters lists, pure.
final class ClustersModelTests: XCTestCase {
    private func e(_ id: String, _ name: String, _ type: EntityType, tags: [String] = [],
                   status: EntityStatus = .active, confidence: Double = 0.85) -> Entity {
        Entity(id: id, name: name, type: type, status: status, confidence: confidence, created: "", lastReferenced: "",
               decayRate: 0, sourceEpisodes: [], tags: tags, related: [], version: 0, markdownContent: "", history: [])
    }

    private lazy var all: [Entity] = [
        e("alpha-project", "Alpha Project", .project, tags: ["side-project"]),
        e("beta-project", "beta project", .project),
        e("tool-example-a", "Tool Example A", .tool, tags: ["side-project", "cli"]),
        e("bob-example", "Bob Example", .person, status: .decaying, confidence: 0.4),
    ]

    func testTheViewMenuIsTheOneFilterAndSortsAToZ() {
        XCTAssertEqual(ClustersModel.filtered(all, types: [.project, .tool], labels: []).map(\.id),
                       ["alpha-project", "beta-project", "tool-example-a"])
        XCTAssertEqual(ClustersModel.filtered(all, types: Set(EntityType.selectableCases), labels: ["cli"]).map(\.id),
                       ["tool-example-a"])
    }

    func testGroupsFollowTheTypeOrderAndTabsCarryCounts() {
        let groups = ClustersModel.groups(ClustersModel.filtered(all, types: Set(EntityType.selectableCases), labels: []))
        XCTAssertEqual(groups.map(\.type), EntityType.selectableCases.filter { [.project, .tool, .person].contains($0) })
        let tabs = ClustersModel.tabs(groups)
        XCTAssertEqual(tabs.first?.label, Copy.Lists.all)
        XCTAssertEqual(tabs.first?.count, 4)
        XCTAssertEqual(tabs.first { $0.id == .project }?.count, 2)
    }

    func testAllCapsEachGroupAndOffersShowAll() {
        let groups = ClustersModel.groups(ClustersModel.filtered(all, types: Set(EntityType.selectableCases), labels: []))
        let lines = ClustersModel.lines(groups: groups, tab: nil, matches: nil, expandAll: false, cap: 1)
        let project = lines.drop { $0.id != "header:project" }.prefix(3).map(\.id)
        XCTAssertEqual(project, ["header:project", "alpha-project", "more:project"])
        let expanded = ClustersModel.lines(groups: groups, tab: nil, matches: nil, expandAll: true, cap: 1)
        XCTAssertFalse(expanded.contains { $0.id == "more:project" }, "Expand all shows every row")
        XCTAssertEqual(ClustersModel.cap(for: .wide), 5)
        XCTAssertEqual(ClustersModel.cap(for: .triage), 3)
    }

    func testATabListsItsGroupFlatAndFindRanksAcrossGroups() {
        let groups = ClustersModel.groups(all)
        XCTAssertEqual(ClustersModel.lines(groups: groups, tab: .project, matches: nil, expandAll: false, cap: 1).map(\.id),
                       ["alpha-project", "beta-project"])
        let found = ClustersModel.matches(query: "exa", within: all) { _ in [self.all[2], self.all[3]] }
        XCTAssertEqual(found?.map(\.id), ["tool-example-a", "bob-example"])
        XCTAssertNil(ClustersModel.matches(query: "   ", within: all) { _ in self.all }, "spaces are not a search")
        let hidden = ClustersModel.matches(query: "exa", within: [all[2]]) { _ in [self.all[2], self.all[3]] }
        XCTAssertEqual(hidden?.map(\.id), ["tool-example-a"], "find never shows what the View menu hides")
    }

    func testTheEyebrowSaysWhereYouAre() {
        let groups = ClustersModel.groups(all)
        XCTAssertEqual(ClustersModel.eyebrow(groups: groups, tab: nil, matches: nil, openId: nil),
                       "Clusters · 4 entities in 3 groups")
        XCTAssertEqual(ClustersModel.eyebrow(groups: groups, tab: .project, matches: nil, openId: nil),
                       "Clusters · Project · 2 entities")
        XCTAssertEqual(ClustersModel.eyebrow(groups: groups, tab: .project, matches: nil, openId: "beta-project"),
                       "Clusters · Project · 2 of 2")
        XCTAssertEqual(ClustersModel.eyebrow(groups: groups, tab: nil, matches: [all[0]], openId: nil),
                       "Clusters · 1 match")
        XCTAssertEqual(ClustersModel.eyebrow(groups: [], tab: nil, matches: nil, openId: nil), "Clusters")
    }

    func testTheTriageLineNamesTheTypeOnlyWhereTypesMix() {
        XCTAssertEqual(ClustersModel.detail(all[2], showsType: false), "85% · side-project, cli")
        XCTAssertEqual(ClustersModel.detail(all[3], showsType: true), "Person · 40% · decaying")
    }

    func testLabelCountsAreAToZ() {
        XCTAssertEqual(ClustersModel.labelCounts(all).map(\.label), ["cli", "side-project"])
        XCTAssertEqual(ClustersModel.labelCounts(all).last?.count, 2)
    }
}
