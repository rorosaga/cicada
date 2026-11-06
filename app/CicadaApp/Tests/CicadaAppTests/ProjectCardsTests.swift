import XCTest
@testable import CicadaApp

/// ROR-118 round 1 — Current's cards: a sub-project joins its parent's card, and the thread draws no remainder without a plan (R-PJ11). Synthetic rows only.
@MainActor
final class ProjectCardsTests: XCTestCase {
    private let today = ISODay(year: 2026, month: 9, day: 23)

    private func row(_ id: String, parent: String? = nil, planned: Bool = false) throws -> ProjectRow {
        var object: [String: Any] = ["id": id, "name": "Example \(id)", "status": "active", "planned": planned,
                                     "lastMomentDay": today.adding(-2).description,
                                     "created": today.adding(-20).description]
        if let parent { object["parent"] = parent }
        return try JSONDecoder().decode(ProjectRow.self, from: JSONSerialization.data(withJSONObject: object))
    }

    func testASubProjectJoinsItsParentsCard() throws {
        let rows = [try row("a"), try row("b", parent: "a"), try row("c")]
        let entries = ProjectsModel.entries(rows, tab: .current, query: "", today: today)
        let groups = ProjectCardGroup.groups(entries.compactMap(\.line))
        XCTAssertEqual(groups.map(\.id), ["a", "c"])
        XCTAssertEqual(groups[0].kids.map(\.id), ["b"])
        XCTAssertEqual(ProjectCardGroup.blocks(entries).count, 1)
    }

    func testTheThreadHasOnlyThePlansMilestonesAndNoRemainderWithoutAPlan() throws {
        let open = try row("a")
        XCTAssertFalse(ProjectThread.span(open, today: today).planned)
        XCTAssertTrue(ProjectThread.marks(open).isEmpty)
        XCTAssertTrue(try ProjectThread.span(row("p", planned: true), today: today).planned)
    }

    func testTheStandingHangsFromTodayWhenThereIsNoNextMilestone() throws {
        let entries = ProjectsModel.entries([try row("a")], tab: .current, query: "", today: today)
        let line = try XCTUnwrap(entries.compactMap(\.line).first)
        let caption = try XCTUnwrap(ProjectThread.caption(line, today: today))
        XCTAssertEqual(caption.text, ProjectsModel.standing(line, today: today))
        XCTAssertEqual(caption.fraction, ProjectThread.span(line.row, today: today).fill, accuracy: 0.0001)
    }
}
