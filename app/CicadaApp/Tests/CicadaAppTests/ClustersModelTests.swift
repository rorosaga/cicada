import XCTest
@testable import CicadaApp

/// R-DL9 / R-DL11 / R-DL12 — what Clusters lists, pure.
final class ClustersModelTests: XCTestCase {
    private func e(_ id: String, _ name: String, _ type: EntityType, tags: [String] = [],
                   status: EntityStatus = .active, confidence: Double = 0.85, lastReferenced: String = "",
                   summary: String = "") -> Entity {
        Entity(id: id, name: name, type: type, status: status, confidence: confidence, created: "",
               lastReferenced: lastReferenced, decayRate: 0, sourceEpisodes: [], tags: tags, related: [], version: 0,
               markdownContent: summary, history: [])
    }

    private lazy var all: [Entity] = [
        e("alpha-project", "Alpha Project", .project, tags: ["side-project"]),
        e("beta-project", "beta project", .project),
        e("tool-example-a", "Tool Example A", .tool, tags: ["side-project", "cli"]),
        e("bob-example", "Bob Example", .person, status: .decaying, confidence: 0.4),
    ]

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

    /// R-PE13 — F-12's "recently mentioned first"; A→Z breaks a tie.
    func testTheViewMenuIsTheOneFilterAndSortsRecentFirst() {
        let recent = [e("alpha-project", "Alpha Project", .project, lastReferenced: "2026-09-01"),
                      e("gamma-project", "Gamma Project", .project, lastReferenced: "2026-09-20"),
                      e("beta-project", "beta project", .project, lastReferenced: "2026-09-20")]
        XCTAssertEqual(ClustersModel.filtered(recent, types: [.project], labels: []).map(\.id),
                       ["beta-project", "gamma-project", "alpha-project"])
        XCTAssertEqual(ClustersModel.filtered(all, types: Set(EntityType.selectableCases), labels: ["cli"]).map(\.id),
                       ["tool-example-a"])
    }

    func testATabListsItsGroupUnderItsHeaderAndFindRanksAcrossGroups() {
        let groups = ClustersModel.groups(all)
        XCTAssertEqual(ClustersModel.lines(groups: groups, tab: .project, matches: nil, expandAll: false, cap: 1).map(\.id),
                       ["header:project", "alpha-project", "beta-project"])
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
                       "Clusters · Projects · 2 entities")
        XCTAssertEqual(ClustersModel.eyebrow(groups: groups, tab: .project, matches: nil, openId: "beta-project"),
                       "Clusters · Projects · 2 of 2")
        XCTAssertEqual(ClustersModel.eyebrow(groups: groups, tab: nil, matches: [all[0]], openId: nil),
                       "Clusters · 1 match")
        XCTAssertEqual(ClustersModel.eyebrow(groups: [], tab: nil, matches: nil, openId: nil), "Clusters")
    }

    /// F-11 — a tile's line is words, never tags, a percentage or a confidence.
    func testALineIsWordsNeverTagsOrAPercentage() {
        let bob = e("bob-example", "Bob Example", .person, tags: ["lab"], summary: "Runs the Northwind lab cluster.")
        XCTAssertEqual(ClustersModel.line(bob), "Runs the Northwind lab cluster.")
        XCTAssertEqual(ClustersModel.detail(bob, showsType: true), "Person · Runs the Northwind lab cluster.")
        XCTAssertEqual(ClustersModel.detail(bob, showsType: false), "Runs the Northwind lab cluster.")
        XCTAssertNil(ClustersModel.detail(all[0], showsType: false), "no summary, no line")
        XCTAssertEqual(ClustersModel.age(e("x", "X", .concept, lastReferenced: "2026-09-14"),
                                         today: ISODay(year: 2026, month: 9, day: 23)), "9d")
    }

    /// R-PE13 — plural, person-friendly group names; the primary six lead.
    func testGroupsArePluralAndThePrimarySixLead() {
        XCTAssertEqual(EntityType.person.groupLabel, "People")
        XCTAssertEqual(EntityType.location.groupLabel, "Places")
        XCTAssertEqual(EntityType.directory.groupLabel, "Folders")
        XCTAssertEqual(Array(ClustersModel.typeOrder.prefix(6)), ClustersGrid.primary)
        XCTAssertEqual(Set(ClustersModel.typeOrder), Set(EntityType.selectableCases))
        let groups = ClustersModel.groups(ClustersModel.filtered(all, types: Set(EntityType.selectableCases), labels: []))
        XCTAssertEqual(ClustersModel.tabs(groups).first { $0.id == .project }?.label, "Projects")
    }

    func testLabelCountsAreAToZ() {
        XCTAssertEqual(ClustersModel.labelCounts(all).map(\.label), ["cli", "side-project"])
        XCTAssertEqual(ClustersModel.labelCounts(all).last?.count, 2)
    }
}
