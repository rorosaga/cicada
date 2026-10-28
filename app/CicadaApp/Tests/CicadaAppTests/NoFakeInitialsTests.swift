import XCTest
@testable import CicadaApp

/// Owner 2026-10-28, the #512 rule applied to provenance: a conversation or saved page with no image of its own draws
/// the real mark of the source it came from, else nothing — never made-up initials on a hue.
final class NoFakeInitialsTests: XCTestCase {
    func testFallbackIsTheSourcesRealMarkOrNothing() {
        XCTAssertEqual(LogoImage.entityFallback(origin: "claude-code"), .origin("claude-code"), "a bundled mark exists")
        XCTAssertEqual(LogoImage.entityFallback(origin: "rss"), .origin("rss"))
        XCTAssertEqual(LogoImage.entityFallback(origin: nil), .none)
        XCTAssertEqual(LogoImage.entityFallback(origin: "no-such-origin-example"), .none,
                       "a source with only a generic symbol draws nothing, not the symbol")
    }

    /// The lint: provenance views and the logo view never draw initials as a stand-in for a source's picture.
    func testNoMonogramIsDrawnForAConversationOrPage() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources()
        where file.path.contains("/Views/Provenance/") || file.lastPathComponent == "LogoImage.swift" {
            let lines = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            for (i, line) in lines.enumerated() where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                if line.contains("Text(Self.monogram(") || line.contains("Text(LogoImage.monogram(") {
                    offenders.append("\(file.lastPathComponent):\(i + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "made-up initials stand in for a source — draw its real mark or nothing")
    }
}
