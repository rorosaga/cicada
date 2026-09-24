import XCTest
@testable import CicadaApp

/// G152's constraint, as a lint: the tour never acts for the person — "no click on a callout answers an inbox item,
/// starts a cycle or connects anything". `TourNavigation` already has no case that could; this keeps the tour's own
/// files from growing a side door (a behaviour test cannot see a new call arrive in a diff — `FontLiteralLintTests`'
/// reasoning).
final class TourLintTests: XCTestCase {
    static let files = ["/Support/Tour.swift", "/Views/Tour/"]
    static let needles = ["APIClient", ".perform(", "triggerManually", "resolve(", "createDemoBank", "turnOn(",
                          "requestFirstRun", "openSettings("]

    func testTheTourOnlyNavigates() throws {
        let sources = try ThemeTokenTests.swiftSources().filter { f in Self.files.contains { f.path.contains($0) } }
        XCTAssertGreaterThanOrEqual(sources.count, 5, "the lint would pass vacuously")
        var offenders: [String] = []
        for file in sources {
            for (n, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), !code.hasPrefix("///") else { continue }
                if Self.needles.contains(where: code.contains) { offenders.append("\(file.lastPathComponent):\(n + 1)") }
            }
        }
        XCTAssertEqual(offenders, [], "the tour navigates through AppRouter and never acts (G152)")
    }
}
