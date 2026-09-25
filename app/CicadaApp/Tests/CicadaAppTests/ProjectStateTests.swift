import XCTest
@testable import CicadaApp

/// R-PP4 / R-PJB17 — `ProjectState` and `project_state.timeline_state` run ONE table,
/// `api/tests/fixtures/timeline_state.json`: add a rule on one side only and the other goes red.
final class ProjectStateTests: XCTestCase {
    private struct Case: Decodable {
        let name: String
        let today: String
        let input: ProjectState.Input
        let expected: ProjectState.Output
    }

    private func cases() throws -> [Case] {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/timeline_state.json")
        let cases = try JSONDecoder().decode([Case].self, from: Data(contentsOf: file))
        XCTAssertGreaterThanOrEqual(cases.count, 5, "read \(cases.count) cases from \(file.path) — vacuous below 5")
        return cases
    }

    func testTheSharedFixture() throws {
        for c in try cases() {
            XCTAssertEqual(ProjectState.state(c.input, today: try XCTUnwrap(ISODay(c.today))), c.expected, c.name)
        }
    }

    /// The demo's live wire agrees with §12's expected values after PJ-3.
    func testTheDemoRoverReadsAsTheServerSaysIt() throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let s = ProjectState.state(ProjectState.Input(t), today: ProjectFixtures.today)
        XCTAssertEqual(s.quietThreshold, 20)
        XCTAssertEqual(s.section, .inMotion)
        XCTAssertEqual(s.progress, ProjectProgress(done: 1, total: 4))
        XCTAssertEqual(s.next, "first-grasp")
        let camera = try XCTUnwrap(t.now.threads.first { $0.since == "2026-08-30" })
        XCTAssertEqual(s.thread(camera.claimId)?.quietDays, 24)
        XCTAssertEqual(s.thread(camera.claimId)?.followupEligible, true)
        XCTAssertTrue(s.isQuiet(camera.claimId))
        let garden = ProjectState.state(ProjectState.Input(try ProjectFixtures.timeline("garden-sensor-project")),
                                        today: ProjectFixtures.today)
        XCTAssertFalse(garden.planned)
        XCTAssertEqual(garden.quietThreshold, 43)
    }
}
