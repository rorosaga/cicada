import XCTest
@testable import CicadaApp

/// G246 (ruling 81a, owner 2026-11-25) — Clusters' Media draws each list of saved things as one line, from the same
/// bubbles the graph folds. Pure: the folding, the filter's interplay, the lines and the keys.
final class ClustersListGroupsTests: XCTestCase {
    private func media(_ id: String, day: String = "2026-11-01", kind: String = "video") -> Entity {
        var m = Entity(id: id, name: "name \(id)", type: .media, status: .active, confidence: 0.8, created: "",
                       lastReferenced: day, decayRate: 0, sourceEpisodes: [], tags: [], related: [], version: 0,
                       markdownContent: "", history: [])
        m.mediaKind = kind
        return m
    }

    private func bubble(_ id: String, members: [String], outside: [String] = [], pageId: String? = nil,
                        count: Int? = nil) -> GraphBubble {
        GraphBubble(id: id, key: id, name: "List \(id)", site: "youtube", mark: "youtube", kindNoun: "videos",
                    count: count, pageId: pageId, members: members, outside: outside)
    }

    private let types = Set(EntityType.selectableCases)

    private func groups(_ all: [Entity], _ bubbles: [GraphBubble], kinds: Set<String> = []) -> [ClustersModel.Group] {
        ClustersModel.groups(ClustersModel.filtered(all, types: types, labels: [], mediaKinds: kinds), bubbles: bubbles)
    }

    func testAListsMembersLeaveTheRowsAndAnEarnedOrLoosePageStays() {
        let all = (1...8).map { media("m\($0)") } + [media("earned"), media("loose")]
        let list = bubble("pl", members: (1...8).map { "m\($0)" }, outside: ["earned"])
        let group = groups(all, [list]).first { $0.type == .media }
        XCTAssertEqual(group?.lists.map(\.id), ["pl"])
        XCTAssertEqual(group?.lists.first?.members.count, 8)
        XCTAssertEqual(Set(group?.entities.map(\.id) ?? []), ["earned", "loose"])
        XCTAssertEqual(group?.count, 3, "a list is one entry, beside the two pages")
    }

    func testAListsOwnPageIsItsLineNeverASecondRow() {
        let all = (1...6).map { media("m\($0)") } + [media("listpage", kind: "list")]
        let group = groups(all, [bubble("pl", members: (1...6).map { "m\($0)" }, pageId: "listpage")])
            .first { $0.type == .media }
        XCTAssertEqual(group?.entities.count, 0)
        XCTAssertEqual(group?.lists.first?.pageId, "listpage")
    }

    /// Review of #935: a list the View menu leaves no member of draws no line, so its own page is a row again, never lost.
    func testAnEmptiedListsOwnPageIsARowAgain() {
        let all = (1...6).map { media("v\($0)", kind: "video") } + [media("listpage", kind: "list")]
        let group = groups(all, [bubble("pl", members: (1...6).map { "v\($0)" }, pageId: "listpage")],
                           kinds: ["list"]).first { $0.type == .media }
        XCTAssertTrue(group?.lists.isEmpty ?? false)
        XCTAssertEqual(group?.entities.map(\.id), ["listpage"])
    }

    func testNoBubblesLeavesTheGroupsAsTheyWere() {
        let all = (1...4).map { media("m\($0)") }
        let g = groups(all, [])
        XCTAssertEqual(g.first?.entities.count, 4)
        XCTAssertTrue(g.first?.lists.isEmpty ?? false)
    }

    /// The kind filter narrows a list's members; a list nothing is left of is not drawn, and the count says what is shown.
    func testTheKindFilterNarrowsAListAndDropsAnEmptyOne() {
        let all = (1...6).map { media("v\($0)", kind: "video") } + (1...6).map { media("a\($0)", kind: "article") }
            + (1...6).map { media("x\($0)", kind: "article") }
        let bubbles = [bubble("vids", members: (1...6).map { "v\($0)" } + (1...6).map { "a\($0)" }, count: 40),
                       bubble("reads", members: (1...6).map { "x\($0)" })]
        let none = groups(all, bubbles).first { $0.type == .media }!
        XCTAssertEqual(none.lists.count, 2)
        XCTAssertEqual(none.lists.first { $0.id == "vids" }?.count, 40, "no filter: the list's own count")
        let videos = groups(all, bubbles, kinds: ["video"]).first { $0.type == .media }!
        XCTAssertEqual(videos.lists.map(\.id), ["vids"], "the list with no video left is not drawn")
        XCTAssertEqual(videos.lists.first?.count, 6, "a filtered list says how many are shown")
        XCTAssertNil(groups(all, bubbles, kinds: ["paper"]).first { $0.type == .media })
    }

    func testListsAreOrderedByTheirNewestMember() {
        let all = [media("a1", day: "2026-10-01"), media("b1", day: "2026-11-20")]
        let g = groups(all, [bubble("old", members: ["a1"]), bubble("new", members: ["b1"])])
        XCTAssertEqual(g.first?.lists.map(\.id), ["new", "old"])
    }

    func testAClosedListIsOneLineAndAnOpenOneShowsACappedLazyRun() {
        let ids = (1...80).map { "m\($0)" }
        let g = groups(ids.map { media($0) } + [media("loose")], [bubble("pl", members: ids)])
        let closed = ClustersModel.lines(groups: g, tab: .media, matches: nil, expandAll: false, cap: 5)
        XCTAssertEqual(closed.count, 3, "header, the list's one line, the loose page")
        guard case .list(_, let isOpen) = closed[1] else { return XCTFail("the second line is the list") }
        XCTAssertFalse(isOpen)
        let open = ClustersModel.lines(groups: g, tab: .media, matches: nil, expandAll: false, cap: 5, openLists: ["pl"])
        XCTAssertEqual(open.count, 1 + 1 + ClustersModel.memberCap + 1 + 1, "header, line, 30 members, Show all, loose")
        guard case .moreMembers(let id, let n) = open[2 + ClustersModel.memberCap] else { return XCTFail("Show all") }
        XCTAssertEqual(id, "pl"); XCTAssertEqual(n, 80)
        let full = ClustersModel.lines(groups: g, tab: .media, matches: nil, expandAll: false, cap: 5,
                                       openLists: ["pl"], fullLists: ["pl"])
        XCTAssertEqual(full.count, 1 + 1 + 80 + 1)
        XCTAssertEqual(Set(full.map(\.id)).count, full.count, "every line has its own id")
    }

    func testAllCapsTheListLinesAndSaysShowAll() {
        let all = (1...5).flatMap { l in (1...6).map { media("l\(l)m\($0)", day: "2026-11-0\(l)") } }
        let bubbles = (1...5).map { l in bubble("l\(l)", members: (1...6).map { "l\(l)m\($0)" }) }
        let g = groups(all, bubbles)
        let lines = ClustersModel.lines(groups: g, tab: nil, matches: nil, expandAll: false, cap: 5)
        let listLines = lines.filter { if case .list = $0 { true } else { false } }
        XCTAssertEqual(listLines.count, ClustersModel.listLines)
        guard case .more(.media, let count)? = lines.last else { return XCTFail("a Show all follows") }
        XCTAssertEqual(count, 5, "the tab's count: five lists")
        let expanded = ClustersModel.lines(groups: g, tab: nil, matches: nil, expandAll: true, cap: 5)
        XCTAssertEqual(expanded.filter { if case .list = $0 { true } else { false } }.count, 5)
    }

    /// Find still finds a member by name, as a row, inside a closed list.
    func testFindMatchesAMemberOfAClosedListAsARow() {
        let ids = (1...6).map { "m\($0)" }
        let all = ids.map { media($0) }
        let filtered = ClustersModel.filtered(all, types: types, labels: [])
        let found = ClustersModel.matches(query: "name m3", within: filtered) { _ in all.filter { $0.id == "m3" } }
        let lines = ClustersModel.lines(groups: ClustersModel.groups(filtered, bubbles: [bubble("pl", members: ids)]),
                                        tab: nil, matches: found, expandAll: false, cap: 5)
        XCTAssertEqual(lines.compactMap(\.entity).map(\.id), ["m3"])
    }

    func testTheKeysWalkTheOpenListsMembersBeforeTheLoosePages() {
        let ids = (1...40).map { "m\($0)" }
        let g = groups(ids.map { media($0) } + [media("loose")], [bubble("pl", members: ids)])
        let closed = ClustersGrid.visible(g, tab: .media, expandAll: false)
        XCTAssertEqual(closed.map(\.id), ["loose"])
        var actions = ClusterListActions()
        actions.open = ["pl"]
        let open = ClustersGrid.visible(g, tab: .media, expandAll: false, lists: actions)
        XCTAssertEqual(open.count, ClustersModel.memberCap + 1)
        XCTAssertEqual(open.last?.id, "loose")
        actions.full = ["pl"]
        XCTAssertEqual(ClustersGrid.visible(g, tab: .media, expandAll: false, lists: actions).count, 41)
    }

    func testTabsCountEntriesNotMembers() {
        let ids = (1...50).map { "m\($0)" }
        let g = groups(ids.map { media($0) } + [media("loose")], [bubble("pl", members: ids)])
        XCTAssertEqual(ClustersModel.tabs(g).map(\.count), [2, 2])
    }
}
