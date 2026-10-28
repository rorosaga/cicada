import AppKit
import XCTest
@testable import CicadaApp

/// C11 / R-PE14 — the one avatar's shapes, sizes and D fallback, pure.
final class EntityPictureLayoutTests: XCTestCase {
    func testEveryTypeHasAShapeAndAFrame() {
        XCTAssertEqual(EntityPictureLayout.shape(.person), .circle)
        XCTAssertEqual(EntityPictureLayout.shape(.media), .wide)
        XCTAssertEqual(EntityPictureLayout.shape(.company), .square)
        XCTAssertEqual(EntityPictureLayout.frame(.media, size: 32), CGSize(width: 48, height: 32))
        XCTAssertEqual(EntityPictureLayout.frame(.person, size: 88), CGSize(width: 88, height: 88))
        XCTAssertEqual(EntityPictureLayout.clamp(8), 20)
        XCTAssertEqual(EntityPictureLayout.clamp(200), 88)
        XCTAssertEqual(EntityPictureLayout.clamp(40), 40)
    }

    /// R-08's must-fix and the owner's 2026-10-28 ruling: a person's fallback is a ring of initials; any other page with
    /// no picture draws nothing — never a type glyph, never a made-up monogram — unless the person chose initials.
    func testTheFallbackIsInitialsForAPersonAndNothingElse() {
        XCTAssertEqual(EntityPictureLayout.fallback(.person, name: "Dana Example"), .initials("DE"))
        XCTAssertEqual(EntityPictureLayout.fallback(.company, name: "Acme Example"), .none)
        for type in EntityType.allCases where type != .person {
            XCTAssertEqual(EntityPictureLayout.fallback(type, name: "Alpha Project"), .none, "\(type)")
        }
        XCTAssertEqual(EntityPictureLayout.fallback(.project, name: "Alpha Project", chosenInitials: true), .monogram("AP"),
                       "\"Use initials instead\" draws initials on every type — the person's own choice")
        XCTAssertEqual(EntityPictureLayout.fallback(.person, name: "Dana Example", chosenInitials: true), .initials("DE"))
        XCTAssertTrue(EntityPictureLayout.ringed(.upload, hasImage: true, type: .person))
        XCTAssertFalse(EntityPictureLayout.ringed(.logo, hasImage: true, type: .company), "a logo stands bare (DR-52)")
        XCTAssertFalse(EntityPictureLayout.ringed(nil, hasImage: false, type: .person), "a person's ring is its hue ring")
        XCTAssertFalse(EntityPictureLayout.ringed(nil, hasImage: false, type: .concept), "an empty slot draws no ring")
        XCTAssertTrue(EntityPictureLayout.ringed(.initials, hasImage: false, type: .concept), "a chosen monogram is ringed")
    }

    /// One decision everywhere: empty means "not a person and no picture"; a list keeps its picture column only while
    /// some row draws something.
    func testEmptyAndTheListSlotRule() {
        let logo = EntityPictureRef(url: "/entities/acme/logo", source: .logo)
        XCTAssertFalse(EntityPictureLayout.isEmpty(.person, picture: nil))
        XCTAssertTrue(EntityPictureLayout.isEmpty(.project, picture: nil))
        XCTAssertFalse(EntityPictureLayout.isEmpty(.company, picture: logo))
        XCTAssertTrue(EntityPictureLayout.anyDrawn([(type: .concept, picture: nil), (type: .company, picture: logo)]))
        XCTAssertTrue(EntityPictureLayout.anyDrawn([(type: .tool, picture: nil), (type: .person, picture: nil)]))
        XCTAssertFalse(EntityPictureLayout.anyDrawn([(type: .tool, picture: nil), (type: .concept, picture: nil)]))
        XCTAssertFalse(EntityPictureLayout.anyDrawn([]))
    }
}

/// Owner 2026-10-28 ("remove this npc aahh icons") — no surface draws an entity type's glyph as a stand-in for a picture
/// or beside a type's section label. A source lint: a hue-tinted symbol keyed on an entity type is the pattern removed.
final class NoTypeGlyphLintTests: XCTestCase {
    func testNoTypeGlyphStandsInForAPictureOrLabel() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !file.path.contains("/Theme/") {
            let lines = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            for (i, line) in lines.enumerated() where line.contains("Image(systemName:") {
                let window = lines[i..<min(i + 4, lines.count)].joined(separator: " ")
                // Keyed on a page's type (a variable), not a fixed hue borrowed for an error or a folder row.
                let keyedHue = window.range(of: #"entityColor\(for: [a-z]"#, options: .regularExpression) != nil
                if keyedHue || (line.contains("EntityType") && line.contains(".icon")) {
                    offenders.append("\(file.lastPathComponent):\(i + 1)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "a type glyph stands in for a picture or a label — draw the picture or nothing")
    }
}
