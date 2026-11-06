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

    func testASavedPagesSummaryThatOnlyRepeatsItsTitleIsNoLine() {
        let repeated = e("m1", "Why local-first software matters", .media, summary: "## Summary\nSaved url — Why local-first software matters.")
        XCTAssertNil(ClustersModel.line(repeated), "the row already says the title")
        let feed = e("m2", "A gripper teardown", .media, summary: "## Summary\nFrom a feed — A gripper teardown.")
        XCTAssertNil(ClustersModel.line(feed))
        let adds = e("m3", "Lab walkthrough", .media, summary: "## Summary\nSaved video — A tour of the lab bench.")
        XCTAssertEqual(ClustersModel.line(adds), "Saved video — A tour of the lab bench.", "a line that adds something stays")
        let person = e("p1", "Leo", .person, summary: "## Summary\nSaved url — Leo.")
        XCTAssertNotNil(ClustersModel.line(person), "only media pages are judged")
    }

    /// ROR-138 — a media tile says what follows "Saved <kind> —", never the lead its slot and chip already say; its slot
    /// draws a source's mark only for a known origin.
    func testAMediaTileDropsTheSavedLeadAndDrawsOnlyAKnownOriginsMark() {
        let paper = e("m1", "Diffusion Policy", .media, summary: "## Summary\nSaved paper — arXiv 2303.04137.")
        XCTAssertEqual(ClustersModel.tileLine(paper), "arXiv 2303.04137.")
        let again = e("m2", "Gripper grasp demo", .media, summary: "## Summary\nSaved video — Gripper grasp demo.")
        XCTAssertNil(ClustersModel.tileLine(again))
        let plain = e("m3", "Lab Cluster Onboarding Guide", .media, summary: "## Summary\nA PDF that walks through connecting.")
        XCTAssertEqual(ClustersModel.tileLine(plain), "A PDF that walks through connecting.")
        var saved = plain
        XCTAssertNil(MediaLeadingSlot.markOrigin(saved), "no origin, no mark")
        saved.origin = "chrome-bookmark"
        XCTAssertEqual(MediaLeadingSlot.markOrigin(saved), "chrome-bookmark")
        saved.origin = "unknown"
        XCTAssertNil(MediaLeadingSlot.markOrigin(saved), "an unknown origin draws nothing, never a stand-in")
        var person = e("p1", "Leo", .person)
        person.origin = "chrome-bookmark"
        XCTAssertNil(MediaLeadingSlot.markOrigin(person), "only media pages")
    }

    /// Owner 2026-10-20 — "we can filter looks inside the entities page": only the pages that show a look.
    func testTheViewMenuNarrowsToThePagesWithLooks() {
        let types = Set(EntityType.selectableCases)
        XCTAssertEqual(ClustersModel.filtered(all, types: types, labels: []).count, 4)
        XCTAssertEqual(ClustersModel.filtered(all, types: types, labels: [], withLooks: ["alpha-project"]).map(\.id),
                       ["alpha-project"])
        XCTAssertTrue(ClustersModel.filtered(all, types: types, labels: [], withLooks: []).isEmpty)
        XCTAssertEqual(ClustersModel.filtered(all, types: [.project], labels: [],
                                              withLooks: ["alpha-project", "tool-example-a"]).map(\.id),
                       ["alpha-project"], "the looks filter and the type filter both hold")
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
        // Say it once (2026-10-19): the tabs carry the counts and the card says what is open.
        XCTAssertEqual(ClustersModel.eyebrow(groups: groups, tab: nil, matches: nil, openId: nil), "Clusters")
        XCTAssertEqual(ClustersModel.eyebrow(groups: groups, tab: .project, matches: nil, openId: nil), "Clusters")
        XCTAssertEqual(ClustersModel.eyebrow(groups: groups, tab: .project, matches: nil, openId: "beta-project"),
                       "Clusters")
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
