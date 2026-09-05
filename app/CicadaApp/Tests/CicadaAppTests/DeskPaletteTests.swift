import AppKit
import XCTest
@testable import CicadaApp

/// G125 v3 Task 2: the study room's palette is a SEPARATE type from the
/// mascot's, and these tests are why it has to be.
///
/// `BookwormSpriteTests.testPaletteIsExactlyTheNineRoles` fails the build on a
/// tenth key in `BookwormPalette`, so the scene literally cannot extend it —
/// and it should not, because a room and a character are different drawings
/// that happen to share three hues. What must hold instead: the key sets are
/// disjoint (so a grid authored for one palette can never be silently drawn
/// with the other's colours), and none of the values collides with the nine
/// state hexes `ThemeTokenTests.testNoStateHexOutsideTheTheme` reserves for
/// the mode-aware theme accessors. That grep test would catch a collision in
/// the source file; asserting the values here says WHY they were chosen.
final class DeskPaletteTests: XCTestCase {

    func testKeySetIsExactlyTheDocumentedThirteen() {
        XCTAssertEqual(Set(DeskPalette.colors.keys),
                       ["d", "f", "k", "m", "n", "s", "c", "p", "t", "g", "h", "i", "u"])
        XCTAssertEqual(DeskPalette.transparent, ".")
        XCTAssertEqual(DeskPalette.transparent, BookwormPalette.transparent,
                       "one transparent character across every grid in the app")
    }

    /// Disjoint keys, so a prop grid can never be rendered with the mascot's
    /// palette (or vice versa) and come out looking almost right.
    func testKeysAreDisjointFromTheMascotPalette() {
        let overlap = Set(DeskPalette.colors.keys).intersection(BookwormPalette.colors.keys)
        XCTAssertTrue(overlap.isEmpty, "shared characters: \(overlap.sorted())")
    }

    /// Asserted directly rather than leaning on `ThemeTokenTests`' grep: that
    /// test proves the literal is absent from the file, this one proves the
    /// VALUE is absent from the palette, which is the property the room's art
    /// actually depends on (G68 §2.7 reserves those hues for state).
    func testNoValueIsAReservedStateHex() {
        let banned: Set<UInt32> = [0x22C55E, 0xEF4444, 0xF59E0B, 0x3B82F6,
                                   0x4A9EFF, 0x8B5CF6, 0x3BD97A, 0x6B7280, 0x999999]
        for (key, hex) in DeskPalette.colors {
            XCTAssertFalse(banned.contains(hex),
                           "'\(key)' = \(String(format: "0x%06X", hex)) is a reserved state hue")
        }
    }

    /// Three hues are deliberately the same VALUES as the worm's `o`/`a`/`q`
    /// so the room and the character read as one drawing. Pinned so a later
    /// palette tweak on either side is a conscious choice, not a drift.
    func testThreeHuesAreShakenHandsWithTheMascot() {
        XCTAssertEqual(DeskPalette.colors["d"], BookwormPalette.colors["o"], "outline / sill")
        XCTAssertEqual(DeskPalette.colors["n"], BookwormPalette.colors["a"], "moon terminator / accent")
        XCTAssertEqual(DeskPalette.colors["s"], BookwormPalette.colors["q"], "star / sparkle")
    }

    func testNsMirrorsEveryKey() {
        XCTAssertEqual(Set(DeskPalette.ns.keys), Set(DeskPalette.colors.keys))
        XCTAssertNil(DeskPalette.ns[DeskPalette.transparent], "'.' is never a colour")
    }
}
