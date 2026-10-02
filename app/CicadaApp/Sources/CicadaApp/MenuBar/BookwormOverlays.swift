import Foundation

/// The overlay palette remains the authority for code-drawn badges, dots and stage icons.
enum BookwormPalette {
    static let transparent: Character = "."
    static let colors: [Character: UInt32] = [
        "o": 0x2B2140,  // outline + pupils — dark plum, survives light AND dark menu bars
        "b": 0x6FCF6A,  // body green
        "l": 0xB8EBA6,  // belly / reading-light stripe
        "w": 0xFFFFFF,  // lens white
        "r": 0xF28BAE,  // blush
        "a": 0xE0A93A,  // accent: glasses rim, book cover (= CicadaTheme hub gold)
        "z": 0x8896FF,  // zZ + sweat drop (the pre-G137 dark accent — the mascot's palette is its own and did not move)
        "q": 0xFFCB57,  // ? mark, sparkle, badge pill (= CicadaTheme pendingPulse)
    ]
}


/// Only count and stage are code-drawn; all character ink comes from the sheets.
enum BookwormOverlays {
    static let size = 18
    static func blank() -> PixelGrid { Array(repeating: String(repeating: ".", count: size), count: size) }

    static func merge(_ base: PixelGrid, _ overlay: PixelGrid) -> PixelGrid {
        (0..<size).map { r in
            var line = Array(base[r])
            for (c, ch) in overlay[r].enumerated() where ch != "." { line[c] = ch }
            return String(line)
        }
    }

    static func glyph(_ shape: PixelGrid, top: Int, left: Int) -> PixelGrid {
        var out = blank().map(Array.init)
        for (r, row) in shape.enumerated() where (0..<size).contains(top + r) {
            for (c, ch) in row.enumerated() where (0..<size).contains(left + c) && ch != "." { out[top + r][left + c] = ch }
        }
        return out.map { String($0) }
    }

    static let digits: [Character: [String]] = [
        "0": ["ooo", "o.o", "o.o", "o.o", "ooo"],
        "1": [".o.", "oo.", ".o.", ".o.", "ooo"],
        "2": ["ooo", "..o", "ooo", "o..", "ooo"],
        "3": ["ooo", "..o", "ooo", "..o", "ooo"],
        "4": ["o.o", "o.o", "ooo", "..o", "..o"],
        "5": ["ooo", "o..", "ooo", "..o", "ooo"],
        "6": ["ooo", "o..", "ooo", "o.o", "ooo"],
        "7": ["ooo", "..o", "..o", "..o", "..o"],
        "8": ["ooo", "o.o", "ooo", "o.o", "ooo"],
        "9": ["ooo", "o.o", "ooo", "..o", "ooo"],
    ]


    static func badgeOverlay(_ count: Int) -> PixelGrid {
        let text = String(max(1, min(99, count)))
        let width = text.count * 4 + 1
        let left = size - width
        var out = glyph(Array(repeating: String(repeating: "q", count: width), count: 7), top: 11, left: left)
        for (i, ch) in text.enumerated() { out = merge(out, glyph(digits[ch] ?? [], top: 12, left: left + 1 + i * 4)) }
        return out
    }

    static func stageDots(_ stage: Int) -> PixelGrid {
        var out = blank()
        var row = Array(out[17])
        for (i, col) in [1, 5, 9, 13, 17].enumerated() { row[col] = i < max(0, min(5, stage)) ? "a" : "o" }
        out[17] = String(row)
        return out
    }

    static func grid(for state: BookwormState) -> PixelGrid {
        switch state {
        case .curious(let count): badgeOverlay(count)
        case .sleeping(let stage): stageDots(stage)
        default: blank()
        }
    }
}
