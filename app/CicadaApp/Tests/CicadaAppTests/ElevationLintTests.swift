import XCTest
@testable import CicadaApp

/// DR-9 / DR-10 — depth is a ring; dark mode has no shadows; a light floating surface gets one
/// soft shadow, and only through `floatingSurface` in `Theme/`. The border-stroke half of the
/// rule's lint is a page-track sweep (37 sites, R-DS28); this is the shadow half.
final class ElevationLintTests: XCTestCase {
    /// Each entry names why it is still allowed. Dropping one is the goal, not a chore.
    static let allowlist: [String: String] = [
        "Views/Common/MediaPreview.swift": "a legibility shadow under a play glyph over a video still — imagery, not elevation",
        "Views/Common/HeroPreview.swift": "the same play glyph on the entity hero",
    ]

    func testShadowsLiveInTheTheme() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources()
        where !file.path.contains("/Theme/") && !Self.allowlist.keys.contains(where: { file.path.hasSuffix($0) }) {
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && line.contains(".shadow(") {
                offenders.append("\(file.lastPathComponent):\(i + 1)")
            }
        }
        XCTAssertEqual(offenders, [], "DR-10: a shadow outside Theme/ — use floatingSurface(in:) or a ring")
    }

    func testTheAllowlistStillNeedsEachEntry() throws {
        let files = try ThemeTokenTests.swiftSources()
        for path in Self.allowlist.keys {
            let file = try XCTUnwrap(files.first { $0.path.hasSuffix(path) }, "\(path) is gone — drop it")
            XCTAssertTrue(try String(contentsOf: file, encoding: .utf8).contains(".shadow("), "\(path) no longer shadows — drop it")
        }
    }
}
