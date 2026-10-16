import XCTest
@testable import CicadaApp

/// Painted art is retired (owner 2026-10-16: "I would remove the painted grass actually. Remove it from everywhere").
/// The study room — pixel art on the Sleep page and in onboarding — is the app's one illustration. This keeps paint
/// from coming back by accident: no painted component is named anywhere, and no painting ships in the bundle. A new
/// painting is a design decision that needs a dated ruling (DESIGN_RULES §9), not a quiet re-add.
final class MeadowPlacementLintTests: XCTestCase {
    static let needles = ["MeadowBackdrop(", "DriftingCloud(", "GrassCorners(", "GrassEdge(",
                          "MeadowSky(", "ArtImage(", "MeadowArt", "PaintedScene", "WelcomeHero(",
                          "HomeHeroBand(", "OnboardingPane("]

    func testNoPaintedArtIsDrawnAnywhere() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (index, line) in text.components(separatedBy: .newlines).enumerated() {
                let code = line.trimmingCharacters(in: .whitespaces)
                guard !code.hasPrefix("//") else { continue }
                if Self.needles.contains(where: { code.contains($0) }) {
                    offenders.append("\(file.lastPathComponent):\(index + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "painted art is retired (owner 2026-10-16)")
    }

    func testNoPaintingShipsInTheBundle() {
        let resources = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/Resources")
        XCTAssertFalse(FileManager.default.fileExists(atPath: resources.appendingPathComponent("art").path),
                       "Resources/art held the paintings; they retired with the ruling")
        XCTAssertTrue(FileManager.default.fileExists(atPath: resources.appendingPathComponent("sprites").path),
                      "the room's sprites stay")
    }
}
