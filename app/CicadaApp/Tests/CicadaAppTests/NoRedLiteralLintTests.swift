import XCTest
@testable import CicadaApp

/// Track I part b (design §13, R-IB21) — an error is `CicadaTheme.danger`, a theme
/// token with a light and a dark value; `.red` is one system red in both themes.
/// The three that existed left with the retired first-run sheet; this keeps the
/// next one out. Same walker and comment rule as `MeadowPlacementLintTests`.
final class NoRedLiteralLintTests: XCTestCase {
    static let needles = [".foregroundStyle(.red)", ".foregroundColor(.red)", "Color.red"]

    func testNoViewPaintsTheSystemRed() throws {
        let views = try ThemeTokenTests.swiftSources().filter { $0.path.contains("/Views/") }
        XCTAssertFalse(views.isEmpty, "found no Views sources — the lint would pass vacuously")
        var offenders: [String] = []
        for file in views {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if Self.needles.contains(where: { code.contains($0) }) {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "use CicadaTheme.danger (design §13)")
    }
}
