import XCTest
@testable import CicadaApp

/// G137 R-M4 / plan R-M12 — `SleepNumbersLintTests`' motion guard, app-wide.
/// 47 literal durations in 13 files each skipped Reduce Motion; routed
/// through `CicadaMotion` they cannot. A source lint, because "a literal
/// exists in the diff" is not something a rendered view can tell you.
final class MotionLiteralLintTests: XCTestCase {
    /// The two files allowed to spell a duration.
    static let exempt = ["Theme/CicadaMotion.swift", "Views/Sleep/SleepMotion.swift"]
    /// For a `duration:` that is not an animation (a model's argument label):
    /// append `// motion-lint:ok — <reason>` to that line.
    static let escapeHatch = "// motion-lint:ok"

    func testNoDurationIsSpelledOutsideTheMotionVocabulary() throws {
        let files = try ThemeTokenTests.swiftSources()
        XCTAssertFalse(files.isEmpty, "found no sources — this lint would pass vacuously")
        var offenders: [String] = []
        for file in files where !Self.exempt.contains(where: { file.path.hasSuffix($0) }) {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//"), code.contains("duration:"), !code.contains(Self.escapeHatch) else { continue }
                offenders.append("\(file.lastPathComponent):\(index + 1)")
            }
        }
        XCTAssertEqual(offenders, [], "these spell a duration outside CicadaMotion and so skip Reduce Motion (G137 R-M4)")
    }
}
