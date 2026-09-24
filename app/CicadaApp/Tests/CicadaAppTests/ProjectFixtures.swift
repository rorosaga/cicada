import Foundation
import XCTest
@testable import CicadaApp

/// G141 PJ-5 (R-PP27) — the demo scenario's wire, generated from a fresh `demo_bank.populate(today=2026-09-23)` by
/// `api/tests/test_projects_app_fixture.py`, which also fails on any drift. Synthetic only (spec §12).
enum ProjectFixtures {
    struct Wire: Decodable {
        let today: String
        let projects: ProjectsResponse
        let timelines: [String: ProjectTimeline]
        let followup: InboxItem
    }

    static let today = ISODay(year: 2026, month: 9, day: 23)

    /// Resolved from THIS file's own path (`ThemeTokenTests.swiftSources()`'s rule), never a caller's `#filePath`:
    /// …/Tests/CicadaAppTests/ProjectFixtures.swift → …/Tests/fixtures/projects-demo.json.
    private static let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // CicadaAppTests
        .deletingLastPathComponent()   // Tests
        .appendingPathComponent("fixtures/projects-demo.json")

    static func load(file: StaticString = #filePath, line: UInt = #line) throws -> Wire {
        let wire = try JSONDecoder().decode(Wire.self, from: Data(contentsOf: url))
        XCTAssertGreaterThanOrEqual(wire.projects.projects.count, 3,
                                    "read \(url.path) — a test over no projects passes vacuously", file: file, line: line)
        return wire
    }

    static func timeline(_ id: String) throws -> ProjectTimeline { try XCTUnwrap(load().timelines[id]) }
    static func row(_ id: String) throws -> ProjectRow { try XCTUnwrap(load().projects.projects.first { $0.id == id }) }
}
