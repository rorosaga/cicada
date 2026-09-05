import AppKit

/// The desk scene's own palette — a SEPARATE type on purpose.
/// `BookwormSpriteTests.testPaletteIsExactlyTheNineRoles` fails on a tenth key
/// in `BookwormPalette`, so the scene cannot extend it. Three hues are
/// deliberately the same VALUES as the worm's `o`/`a`/`q` so the room and the
/// character read as one drawing. Checked against
/// `ThemeTokenTests.testNoStateHexOutsideTheTheme`'s banned list: no collision
/// (and `DeskPaletteTests` asserts the values, not just the absent literals).
/// One NIGHT palette, mode-independent, for the same reason the worm palette
/// is (`BookwormSprites.swift:13-19`) and a stronger one here — this is the
/// Sleep page, and a night window is the metaphor, not a theme accident.
///
/// The keys are disjoint from `BookwormPalette`'s so a grid authored for one
/// palette can never be drawn with the other's colours and come out looking
/// almost right; `DeskPaletteTests` pins that.
enum DeskPalette {
    static let transparent: Character = "."
    static let colors: [Character: UInt32] = [
        "d": 0x2B2140,  // deep outline / sill — the worm's `o` hue, on purpose
        "f": 0x4A3C6B,  // window frame + mullions, dusk plum
        "k": 0x1B1B38,  // night sky (glass)
        "m": 0xFFE18A,  // moonlight cream
        "n": 0xE0A93A,  // moon terminator — the worm's accent `a` hue
        "s": 0xFFCB57,  // star — the worm's sparkle `q` hue
        "c": 0x5B4B8A,  // cushion
        "p": 0x3A2F5C,  // cushion shadow
        "t": 0x8A5A3C,  // terracotta pot
        "g": 0x4FA85A,  // plant green
        "h": 0x7ED77F,  // plant highlight
        "i": 0x6E7B8F,  // mug steel / unlit lamp shade
        "u": 0xB8C4D4,  // mug highlight
    ]

    /// Resolved once, through the one hex→sRGB conversion in the app.
    static let ns: [Character: NSColor] = PixelRenderer.nsColors(colors)
}
