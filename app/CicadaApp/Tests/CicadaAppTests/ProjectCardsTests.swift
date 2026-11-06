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

    private func planned(_ names: [(String, String, String?)]) throws -> ProjectLine {
        let ms: [[String: Any]] = names.enumerated().map { i, m in
            var o: [String: Any] = ["slug": m.0, "name": "Step \(m.0)", "status": m.1, "source": "milestone"]
            if let t = m.2 { o["target"] = t }
            return o
        }
        let object: [String: Any] = ["id": "p", "name": "Example p", "status": "active", "planned": true,
                                     "lastMomentDay": today.adding(-2).description,
                                     "created": today.adding(-20).description, "milestones": ms]
        let row = try JSONDecoder().decode(ProjectRow.self, from: JSONSerialization.data(withJSONObject: object))
        return try XCTUnwrap(ProjectsModel.entries([row], tab: .current, query: "", today: today)
            .compactMap(\.line).first)
    }

    func testAPlanIsStepsInDateOrderWithTheNextOneMarked() throws {
        let line = try planned([("c", "planned", today.adding(9).description), ("a", "done", today.adding(-5).description),
                                ("b", "planned", today.adding(3).description)])
        XCTAssertEqual(ProjectSteps.steps(line).map(\.state), [.done, .next, .later])
        XCTAssertEqual(ProjectSteps.steps(line).map(\.name), ["Step a", "Step b", "Step c"])
        XCTAssertEqual(ProjectSteps.glyph(line), "diamond")
    }

    func testNoPlanDrawsNoStepsAndTheStandingIsAClock() throws {
        let entries = ProjectsModel.entries([try row("a")], tab: .current, query: "", today: today)
        let line = try XCTUnwrap(entries.compactMap(\.line).first)
        XCTAssertTrue(ProjectSteps.steps(line).isEmpty)   // R-PJ11: no plan, no track
        XCTAssertEqual(ProjectSteps.glyph(line), "clock")
    }

    func testALongPlanDropsItsOldestDoneStepsFirst() throws {
        let line = try planned((0..<8).map { ("m\($0)", $0 < 3 ? "done" : "planned", today.adding($0 - 4).description) })
        let shown = ProjectSteps.visible(ProjectSteps.steps(line))
        XCTAssertEqual(shown.count, ProjectSteps.cap)
        XCTAssertEqual(shown.map(\.name), ["Step m3", "Step m4", "Step m5", "Step m6", "Step m7"])
        XCTAssertEqual(ProjectSteps.visible(Array(ProjectSteps.steps(line).prefix(3))).count, 3)
    }

    func testTheTabsCountCardsNotSubProjects() throws {
        let rows = [try row("a"), try row("b", parent: "a"), try row("c")]
        let c = ProjectsModel.counts(rows, today: today)
        XCTAssertEqual(ProjectsModel.tabs(c).first?.count, 2)
        XCTAssertNil(ProjectsModel.tabs(c).last?.count)   // Past with none carries no 0
    }

    func testAMilestoneASubProjectCarriesByNameIsDrawnOnceOnTheLead() throws {
        let line = try planned([("a", "done", today.adding(-5).description), ("b", "planned", today.adding(3).description)])
        var named = try row("k", parent: "p")
        named.name = "Step b"
        let kid = try XCTUnwrap(ProjectsModel.entries([named], tab: .current, query: "", today: today).compactMap(\.line).first)
        let kids = [kid]
        XCTAssertEqual(ProjectSteps.steps(line, without: kids).map(\.name), ["Step a"])
        XCTAssertEqual(ProjectSteps.steps(line, without: []).count, 2)
    }
}
