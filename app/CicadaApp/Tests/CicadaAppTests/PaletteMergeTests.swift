import XCTest
@testable import CicadaApp

/// G136 design §3.2 "the list never jumps" / plan R-SU15 — the merge rule,
/// the counts and the keyboard walk, as pure values.
final class PaletteMergeTests: XCTestCase {
    private func row(_ kind: FindKind, _ id: String, _ group: FindGroupID, score: Double = 1) -> FindRow {
        FindRow(key: FindRowKey(kind: kind, id: id), group: group, title: id, mark: .symbol("circle"),
                score: score, destination: .entity(id: id))
    }

    private func local(_ rows: [FindRow]) -> QuickIndex.Result {
        QuickIndex.Result(rows: rows, counts: Dictionary(grouping: rows, by: \.group).mapValues(\.count))
    }

    func testFreshPutsAskFirstAndLiftsTheTopHitOutOfItsGroup() {
        let results = FindMerge.fresh(query: "al", local: local([row(.entity, "a", .entities, score: 4),
                                                                 row(.entity, "b", .entities, score: 3),
                                                                 row(.media, "m", .sources, score: 4)]))
        XCTAssertEqual(results.ask?.destination, .ask("al"))
        XCTAssertEqual(results.topHit?.key.id, "a", "a tie goes to the earlier group")
        XCTAssertEqual(results.groups[.entities]?.map(\.key.id), ["b"])
        XCTAssertEqual(results.count(for: .entities), .exact(1))
        XCTAssertEqual(results.sections(expanded: []).map(\.group), [.ask, .topHit, .entities, .sources])
        XCTAssertNil(FindMerge.fresh(query: "  ", local: local([])).ask, "nothing typed, no Ask row")
    }

    func testServerRowsAppendDedupeAndNeverReorder() {
        var results = FindMerge.fresh(query: "al", local: local([row(.entity, "a", .entities, score: 4),
                                                                 row(.entity, "b", .entities, score: 3)]))
        results = FindMerge.append([row(.entity, "a", .entities, score: 9), row(.entity, "c", .entities, score: 9),
                                    row(.conversation, "s1", .conversations)],
                                   totals: [.entities: .exact(5), .conversations: .exact(1)], to: results)
        XCTAssertEqual(results.topHit?.key.id, "a", "the top hit is the local tier's and stays")
        XCTAssertEqual(results.groups[.entities]?.map(\.key.id), ["b", "c"], "a not repeated; c after what was shown")
        XCTAssertEqual(results.count(for: .entities), .atLeast, "two tiers fed it — the union is unknown")
        XCTAssertEqual(results.count(for: .conversations), .exact(1))
        let again = FindMerge.append([], totals: [.conversations: .exact(1)], to: results)
        XCTAssertEqual(again.count(for: .conversations), .exact(1), "a second pass replaces, never compounds")
    }

    func testAGroupShowsFiveThenShowAllWithAnHonestNumber() {
        let rows = (0..<7).map { row(.entity, "e\($0)", .entities, score: Double(10 - $0)) }
        let results = FindMerge.fresh(query: "e", local: local(rows))
        let section = results.sections(expanded: []).first { $0.group == .entities }
        XCTAssertEqual(section?.rows.count, 5)
        XCTAssertEqual(section?.more, .exact(6), "e0 is the top hit; six remain")
        XCTAssertEqual(section?.headerCount, "5 of 6")
        XCTAssertNil(results.sections(expanded: [.entities]).first { $0.group == .entities }?.more)
        var merged = results
        merged = FindMerge.append([], totals: [.entities: .exact(40)], to: merged)
        XCTAssertEqual(merged.sections(expanded: []).first { $0.group == .entities }?.more, .atLeast)
        XCTAssertNil(merged.sections(expanded: []).first { $0.group == .entities }?.headerCount,
                     "never a guessed number")
    }

    func testCountsCombine() {
        XCTAssertEqual(FindCount.combine(local: nil, server: .exact(9)), .exact(9))
        XCTAssertEqual(FindCount.combine(local: .exact(0), server: .exact(9)), .exact(9))
        XCTAssertEqual(FindCount.combine(local: .exact(3), server: .exact(0)), .exact(3))
        XCTAssertEqual(FindCount.combine(local: .exact(3), server: .exact(9)), .atLeast)
    }

    func testTheSelectionStartsOnTheTopHitClampsAndJumpsGroups() {
        let results = FindMerge.fresh(query: "x", local: local([row(.entity, "a", .entities, score: 5),
                                                                row(.entity, "b", .entities, score: 4),
                                                                row(.inbox, "i", .inbox, score: 3)]))
        let sections = results.sections(expanded: [])
        let start = FindSelection.initial(sections)
        XCTAssertEqual(start?.id, "a")
        XCTAssertEqual(FindSelection.move(start, .next, in: sections)?.id, "b")
        let top = FindSelection.move(start, .previous, in: sections)
        XCTAssertEqual(top?.kind, .ask)
        XCTAssertEqual(FindSelection.move(top, .previous, in: sections)?.kind, .ask, "no wrap")
        XCTAssertEqual(FindSelection.move(start, .nextGroup, in: sections)?.id, "b")
        XCTAssertEqual(FindSelection.move(FindRowKey(kind: .entity, id: "b"), .nextGroup, in: sections)?.id, "i")
        XCTAssertEqual(FindSelection.move(FindRowKey(kind: .inbox, id: "i"), .previousGroup, in: sections)?.id, "b")
        XCTAssertEqual(FindSelection.move(start, .last, in: sections)?.id, "i")
        XCTAssertEqual(FindSelection.move(start, .first, in: sections)?.kind, .ask)
    }

    func testTheSelectionSurvivesAServerAppend() {
        let results = FindMerge.fresh(query: "x", local: local([row(.entity, "a", .entities, score: 5)]))
        let key = FindSelection.initial(results.sections(expanded: []))
        let merged = FindMerge.append([row(.belief, "c1", .beliefs)], totals: [:], to: results)
        XCTAssertNotNil(key.flatMap { merged.row(for: $0) })
    }

    func testRecentsAreIdsOnlyDedupedCappedAndLocallyResolvable() {
        var list: [FindRowKey] = []
        for i in 0..<8 { list = FindRecents.push(FindRowKey(kind: .entity, id: "e\(i)"), into: list) }
        XCTAssertEqual(list.count, FindRecents.limit)
        XCTAssertEqual(list.first?.id, "e7")
        list = FindRecents.push(FindRowKey(kind: .entity, id: "e5"), into: list)
        XCTAssertEqual(list.first?.id, "e5")
        XCTAssertEqual(list.filter { $0.id == "e5" }.count, 1)
        let unchanged = FindRecents.push(FindRowKey(kind: .conversation, id: "ses_1"), into: list)
        XCTAssertEqual(unchanged, list, "R-SU6: a conversation cannot be drawn again without its text")
    }

    func testRowTextNamesTheKindAndThePosition() {
        let belief = FindRow(key: FindRowKey(kind: .belief, id: "c1"), group: .beliefs, title: "alpha-project uses sqlite-vec",
                             detail: "alpha-project", mark: .symbol("circle"), history: "until 3 Sep",
                             destination: .belief(subjectId: "alpha-project", claimId: "c1"))
        XCTAssertEqual(FindRowText.accessibilityLabel(belief), "Earlier belief, alpha-project uses sqlite-vec, alpha-project, until 3 Sep")
        XCTAssertEqual(FindRowText.announcement(belief, position: 2, of: 7), "Earlier belief, alpha-project uses sqlite-vec, 2 of 7")
        XCTAssertEqual(FindRowText.moreLabel(.exact(12)), "Show all 12")
        XCTAssertEqual(FindRowText.moreLabel(.atLeast), "More…")
    }
}
