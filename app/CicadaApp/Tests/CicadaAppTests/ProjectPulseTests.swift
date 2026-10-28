import XCTest
@testable import CicadaApp

/// Decision 9 (owner 2026-10-28) — `ProjectPulse` and `project_pulse.pulse` run ONE table,
/// `api/tests/fixtures/project_pulse.json`: add a rule on one side only and the other goes red. And the Projects page
/// draws no fold (decision 17, DR-81 as proposed): a source lint over `Views/Projects`.
final class ProjectPulseTests: XCTestCase {
    private struct Case: Decodable {
        let name: String
        let today: String
        let input: ProjectPulse.Input
        let expected: ProjectPulse.Output
    }

    private var repoRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
    }

    func testTheSharedFixture() throws {
        let file = repoRoot.appendingPathComponent("api/tests/fixtures/project_pulse.json")
        let cases = try JSONDecoder().decode([Case].self, from: Data(contentsOf: file))
        XCTAssertGreaterThanOrEqual(cases.count, 4, "read \(cases.count) cases from \(file.path) — vacuous below 4")
        for c in cases {
            XCTAssertEqual(ProjectPulse.pulse(c.input, today: try XCTUnwrap(ISODay(c.today))), c.expected, c.name)
        }
    }

    /// The demo's live wire: the pulse reads its own tied-conversation days and done items, never a model.
    func testTheDemoRoverHasAPulse() throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let p = ProjectPulse.pulse(ProjectPulse.Input(t), today: ProjectFixtures.today)
        XCTAssertEqual(p.weeks.count, 4)
        XCTAssertEqual(p.conversations, p.weeks.reduce(0, +))
        XCTAssertFalse(p.empty)
    }

    /// Decision 17 — the Projects page draws no fold: no disclosure header, chevron or button, anywhere in it.
    func testTheProjectsPageHasNoFolds() throws {
        let dir = repoRoot.appendingPathComponent("app/CicadaApp/Sources/CicadaApp/Views/Projects")
        let files = try FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "swift" }
        XCTAssertGreaterThan(files.count, 10)
        var offenders: [String] = []
        for file in files {
            let lines = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            for (n, line) in lines.enumerated() where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                if ["DisclosureHeader(", "DisclosureChevron(", "DisclosureButton(", "CardDisclosure("]
                    .contains(where: line.contains) {
                    offenders.append("\(file.lastPathComponent):\(n + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "Projects draws open sections capped with \"All N\" (decision 17), never a fold")
    }
}
