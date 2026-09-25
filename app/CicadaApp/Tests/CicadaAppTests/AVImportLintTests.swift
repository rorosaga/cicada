import XCTest
@testable import CicadaApp

/// R-V6 / plan R8: `AVPlaybackController.swift` is the ONLY new file that may
/// import AVFoundation, so the rest of the app stays testable without one.
/// A source lint, not a behaviour test — the defect is "an import exists in
/// the diff", which nothing a rendered view produces would reveal.
/// `WalkthroughPanel.swift` is grandfathered: its muted looping walkthrough
/// player predates this seam and is not a media surface.
///
/// The match is per-line and anchored at an `import` STATEMENT, not a
/// substring of the whole file. A whole-file `contains` reads a docstring that
/// merely cites this rule ("the only file allowed to import AVFoundation") as
/// a violation — which it did, on the first run, against `VideoPlayerView`'s
/// own explanation of the seam. In a repo whose docstrings are required to
/// explain WHY and cite the ruling, a lint that punishes naming the ruling is
/// a lint that teaches people not to write the docstring.
final class AVImportLintTests: XCTestCase {
    private static let allowed = [
        "Views/Common/AVPlaybackController.swift",
        "Views/Capture/Sheets/WalkthroughPanel.swift",
    ]

    private static let needles = ["import AVKit", "import AVFoundation"]

    /// …/Tests/CicadaAppTests/<this file> → …/Sources/CicadaApp
    private var sourcesRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .appendingPathComponent("Sources/CicadaApp")
    }

    private func isAVImport(_ line: String) -> Bool {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        return Self.needles.contains { trimmed == $0 || trimmed.hasPrefix($0 + " ") }
    }

    func testOnlyTheControllerImportsAVFoundation() throws {
        let sources = sourcesRoot
        let all = FileManager.default.enumerator(at: sources, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL }
            .filter { $0.pathExtension == "swift" }
            .filter { url in !Self.allowed.contains(where: { url.path.hasSuffix($0) }) } ?? []
        XCTAssertFalse(all.isEmpty, "found no sources under \(sources.path) — the lint would pass vacuously")
        for file in all {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() where isAVImport(line) {
                XCTFail("\(file.lastPathComponent):\(index + 1) has `\(line.trimmingCharacters(in: .whitespaces))` — "
                        + "route playback through VideoPlaybackController instead (R-V6).")
            }
        }
    }

    /// The non-vacuity guard above only proves the walk found FILES. This one
    /// proves the needle still matches a real import statement: the
    /// grandfathered `WalkthroughPanel.swift` has had `import AVKit` since it
    /// shipped, so if this goes green-by-silence the lint above is dead too.
    func testTheNeedleStillMatchesARealImport() throws {
        let panel = sourcesRoot.appendingPathComponent("Views/Capture/Sheets/WalkthroughPanel.swift")
        let text = try String(contentsOf: panel, encoding: .utf8)
        XCTAssertTrue(
            text.components(separatedBy: .newlines).contains(where: isAVImport),
            "WalkthroughPanel.swift no longer has an AV import — either it moved (update `allowed`) "
            + "or the matcher stopped matching, in which case the lint passes vacuously."
        )
    }
}
