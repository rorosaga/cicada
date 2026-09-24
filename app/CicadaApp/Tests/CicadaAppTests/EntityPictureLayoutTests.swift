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

    /// R-08's must-fix: the fallback is a ring, a monogram or a glyph — never a solid hue fill.
    func testTheFallbackIsNeverAFill() {
        XCTAssertEqual(EntityPictureLayout.fallback(.person, name: "Dana Example"), .initials("DE"))
        XCTAssertEqual(EntityPictureLayout.fallback(.company, name: "Acme Example"), .monogram("AE"))
        XCTAssertEqual(EntityPictureLayout.fallback(.project, name: "Alpha Project"), .glyph("flag"))
        XCTAssertEqual(EntityPictureLayout.fallback(.project, name: "Alpha Project", chosenInitials: true), .monogram("AP"),
                       "\"Use initials instead\" draws initials on every type, never the glyph it replaced")
        XCTAssertEqual(EntityPictureLayout.fallback(.person, name: "Dana Example", chosenInitials: true), .initials("DE"))
        XCTAssertTrue(EntityPictureLayout.ringed(.upload, hasImage: true, type: .person))
        XCTAssertFalse(EntityPictureLayout.ringed(.logo, hasImage: true, type: .company), "a logo stands bare (DR-52)")
        XCTAssertFalse(EntityPictureLayout.ringed(nil, hasImage: false, type: .person), "a person's ring is its hue ring")
        XCTAssertTrue(EntityPictureLayout.ringed(nil, hasImage: false, type: .concept))
    }

    /// DR-53 — outline symbols that exist on this macOS.
    func testEveryTypeGlyphIsAnOutlineSymbolThatExists() {
        for type in EntityType.allCases {
            let glyph = EntityPictureLayout.glyph(type)
            XCTAssertFalse(glyph.hasSuffix(".fill"), "\(type): \(glyph)")
            XCTAssertNotNil(NSImage(systemSymbolName: glyph, accessibilityDescription: nil), "\(type): \(glyph)")
        }
    }
}
