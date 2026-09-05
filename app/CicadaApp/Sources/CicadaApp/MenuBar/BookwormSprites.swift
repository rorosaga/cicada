import Foundation

/// A sprite frame: 24 rows of 24 characters, one character per palette index
/// (`BookwormPalette.colors`) or `.` for transparent. Grids are authored as
/// strings in code — no image pipeline, no asset catalog — so the mascot is
/// as portable as the rest of the bank (CLAUDE.md: portability is the point).
typealias PixelGrid = [String]

/// The mascot's nine colours (ruling R1 of the 2026-09-02 mascot plan). The
/// brief named eight roles; `error` red is the ninth because it cannot be
/// borrowed from blush or amber without losing one of them. Pupils reuse `o`.
///
/// These are ART hues, deliberately mode-independent: the menu bar has no app
/// colour mode, and the same image must read on both light and dark bars, so
/// none of them is a `CicadaTheme` token. `e` in particular is NOT the
/// `CicadaTheme.danger` literal — G68 §2.7 reserves the state hexes for the
/// mode-aware theme accessors (`ThemeTokenTests.testNoStateHexOutsideTheTheme`
/// greps every source file for them), and the theme's own rule is that an
/// identity hue "stays literal at its call site — identity, not state".
enum BookwormPalette {
    static let transparent: Character = "."
    static let colors: [Character: UInt32] = [
        "o": 0x2B2140,  // outline + pupils — dark plum, survives light AND dark menu bars
        "b": 0x6FCF6A,  // body green
        "l": 0xB8EBA6,  // belly / reading-light stripe
        "w": 0xFFFFFF,  // lens white
        "r": 0xF28BAE,  // blush
        "a": 0xE0A93A,  // accent: glasses rim, book cover (= CicadaTheme hub gold)
        "z": 0x8896FF,  // zZ + sweat drop (= CicadaTheme dark accent)
        "q": 0xFFCB57,  // ? mark, sparkle, badge pill (= CicadaTheme pendingPulse)
        "e": 0xE5484D,  // error red pupils — an art red, not the `danger` state token (see above)
    ]
}

/// Code-defined 24×24 pixel bookworm — G107's "real art". One character,
/// eight moods, every mood ≥ 2 frames so it is always moving (the owner's
/// 2026-09-02 ask). Frames are COMPOSED from shared fragments (head top,
/// glasses, mouth, body) plus small overlay glyphs, so the silhouette is
/// identical across states by construction and the head/glasses row is
/// asserted equal in `BookwormSpriteTests`.
///
/// `frames(for:)` bakes the `.curious` count badge and the `.sleeping` stage
/// dots into the frames it returns (ruling R2): consumers never merge
/// overlays themselves, which is what lets the menu bar show ONE image with
/// the count inside it instead of an icon plus a text title.
enum BookwormSprites {
    static let size = 24
    private static let transparent = BookwormPalette.transparent

    // MARK: - Grid helpers (pure; tested)

    static func blank() -> PixelGrid {
        Array(repeating: String(repeating: transparent, count: size), count: size)
    }

    /// Row `r` of `grid`, padded/truncated to exactly `size` characters —
    /// ragged authoring (trailing spaces stripped by an editor) must never
    /// crash indexing, the same rule the 16×16 renderer had.
    private static func padded(_ grid: PixelGrid, _ r: Int) -> String {
        guard r < grid.count else { return String(repeating: transparent, count: size) }
        let row = grid[r]
        if row.count == size { return row }
        if row.count > size { return String(row.prefix(size)) }
        return row + String(repeating: transparent, count: size - row.count)
    }

    /// Paints every non-transparent cell of `overlay` onto `base`.
    static func merge(_ base: PixelGrid, _ overlay: PixelGrid) -> PixelGrid {
        (0..<size).map { r in
            var row = Array(padded(base, r))
            let over = Array(padded(overlay, r))
            for c in 0..<size where over[c] != transparent { row[c] = over[c] }
            return String(row)
        }
    }

    private static func shiftRow(_ row: String, _ dx: Int) -> String {
        if dx > 0 { return String(repeating: transparent, count: dx) + String(row.prefix(size - dx)) }
        if dx < 0 { return String(row.dropFirst(-dx)) + String(repeating: transparent, count: -dx) }
        return row
    }

    /// Whole-sprite translation (a bob is `dy: 1`, a bounce `dy: -1`). Cells
    /// pushed off the edge are dropped.
    static func shift(_ grid: PixelGrid, dx: Int = 0, dy: Int = 0) -> PixelGrid {
        var out = blank()
        for r in 0..<size {
            let rr = r + dy
            guard rr >= 0, rr < size else { continue }
            out[rr] = shiftRow(padded(grid, r), dx)
        }
        return out
    }

    /// Horizontal shift of a band of rows only — a head tilt keeps the body
    /// still.
    static func shiftRows(_ grid: PixelGrid, _ rows: Range<Int>, dx: Int) -> PixelGrid {
        var out = (0..<size).map { padded(grid, $0) }
        for r in rows { out[r] = shiftRow(padded(grid, r), dx) }
        return out
    }

    static func replaceRows(_ grid: PixelGrid, at start: Int, with rows: PixelGrid) -> PixelGrid {
        var out = grid
        for (i, row) in rows.enumerated() { out[start + i] = row }
        return out
    }

    /// A small glyph placed at (`top`, `left`) on an otherwise blank grid,
    /// clipped at the edges.
    static func glyph(_ shape: [String], top: Int, left: Int) -> PixelGrid {
        var out = blank()
        for (i, row) in shape.enumerated() {
            let r = top + i
            guard r >= 0, r < size else { continue }
            var line = Array(out[r])
            for (j, ch) in row.enumerated() where ch != transparent {
                let c = left + j
                if c >= 0, c < size { line[c] = ch }
            }
            out[r] = String(line)
        }
        return out
    }

    // MARK: - Fragments (rows 2–4 head top, 5–9 glasses, 10–12 mouth, 13–22 body)

    private static let headTop: PixelGrid = [
        "........oooooooo........",  // 2
        "......oobbbbbbbboo......",  // 3
        ".....obbbbbbbbbbbbo.....",  // 4
    ]

    enum Lid { case open, closed, half }

    /// Rows 5–9: two closed rims joined by a bridge on the top row, lenses
    /// four cells wide. `pupil` is `o` normally and `e` for the error state.
    static func eyes(pupil: Character = "o", lid: Lid = .open) -> PixelGrid {
        func lens(_ inside: String) -> String { "a" + inside + "a" }
        func row(_ l: String, _ r: String) -> String { "....ob" + l + "b" + r + "bo..." }
        let white = lens("wwww")
        let shut = lens("oooo")
        let look = lens("w" + String(pupil) + String(pupil) + "w")
        let rimTop = "....ob" + "aaaaaa" + "a" + "aaaaaa" + "bo..."     // 5 — the bridge joins the rims
        let rimBottom = "....ob" + "aaaaaa" + "b" + "aaaaaa" + "bo..."  // 9
        let middle: [String]
        switch lid {
        case .open:   middle = [row(white, white), row(look, look), row(look, look)]
        case .closed: middle = [row(white, white), row(white, white), row(shut, shut)]
        case .half:   middle = [row(shut, shut), row(look, look), row(white, white)]
        }
        return [rimTop] + middle + [rimBottom]
    }

    private static let mouthSmile: PixelGrid = [
        "....obbrrbbbbbbbbrrbo...",  // 10 blush
        ".....obbbobbbbbbobbo....",  // 11 smile corners
        "......obbboooooobbo.....",  // 12 smile + chin
    ]
    private static let mouthGrin: PixelGrid = [
        "....obbrrbbbbbbbbrrbo...",
        ".....obbboooooooobbo....",  // 11 wide grin
        "......obbbowwwwobbo.....",  // 12 teeth
    ]
    private static let mouthNeutral: PixelGrid = [
        "....obbbbbbbbbbbbbbbo...",
        ".....obbbbbbbbbbbbbo....",
        "......obbbooooobbbo.....",  // 12 flat line
    ]
    private static let mouthFrown: PixelGrid = [
        "....obbbbbbbbbbbbbbbo...",
        ".....obbbboooooobbbo....",  // 11 bowl
        "......obbobbbbbbobbo....",  // 12 corners down
    ]
    private static let mouthOpen: PixelGrid = [
        "....obbrrbbbbbbbbrrbo...",
        ".....obbbboooooobbbo....",  // 11 open
        "......obbboaaaaobbo.....",  // 12 book cover between the lips
    ]
    private static let mouthChew: PixelGrid = [
        "....obbrrbbbbbbbbrrbo...",
        ".....obbbbooooooobbo....",  // 11 closed on the book
        "......obbbboaaaobbo.....",  // 12 a bite taken
    ]

    private static let body: PixelGrid = [
        ".......obbbbbbbbbbo.....",  // 13 neck
        "........obbllbbbbo......",  // 14
        "........obbllbbbbo......",  // 15
        ".......obbbllbbbbo......",  // 16
        "......obbbllbbbbo.......",  // 17
        ".....obbbllbbbbo........",  // 18
        "....obbbllbbbbo.........",  // 19
        "...obbbbbbbbbo..........",  // 20 tail
        "..obbbbbbbboo...........",  // 21
        "...ooooooo..............",  // 22
    ]
    /// Chest rise: the belly stripe one cell wider on rows 14–16.
    private static let bodyBreath: PixelGrid = [
        ".......obbbbbbbbbbo.....",
        "........oblllbbbbo......",
        "........oblllbbbbo......",
        ".......obblllbbbbo......",
        "......obbbllbbbbo.......",
        ".....obbbllbbbbo........",
        "....obbbllbbbbo.........",
        "...obbbbbbbbbo..........",
        "..obbbbbbbboo...........",
        "...ooooooo..............",
    ]

    private static func compose(_ eyeRows: PixelGrid, _ mouth: PixelGrid, body: PixelGrid = body) -> PixelGrid {
        var g = blank()
        g = replaceRows(g, at: 2, with: headTop)
        g = replaceRows(g, at: 5, with: eyeRows)
        g = replaceRows(g, at: 10, with: mouth)
        g = replaceRows(g, at: 13, with: body)
        return g
    }

    // MARK: - Overlay glyphs

    private static let zSmall = ["zzz", "..z", ".z.", "zzz"]
    private static let zBig = ["zzzzz", "...z.", "..z..", ".z...", "zzzzz"]
    private static let questionMark = [".qqq.", "q...q", "....q", "...q.", "..q..", ".....", "..q.."]
    private static let sparkle = ["..q..", ".qqq.", "qqqqq", ".qqq.", "..q.."]
    private static let sparkleSmall = ["..q..", ".q.q.", "..q.."]
    private static let drop = [".z.", "zzz", "zzz"]
    private static let dropSmall = [".z.", "zzz"]
    private static let book = ["aaaaa", "awwwa", "awwwa", "aaaaa"]
    private static let bookBitten = ["aaaa.", "awwa.", "awwa.", "aaaa."]

    /// 3×5 mini-font for the badge count, drawn in outline colour on the
    /// amber pill.
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

    /// The inbox count as a pixel numeral INSIDE the sprite: an amber pill in
    /// the bottom-right corner (right edge col 22, rows 16–22 — the body curls
    /// left, so nothing else lives there), clamped to 1…99. This is what
    /// replaced the menu bar's duplicate `button.title` text badge.
    static func badgeOverlay(_ count: Int) -> PixelGrid {
        let text = String(max(1, min(99, count)))
        let width = 3 * text.count + (text.count - 1) + 2   // digits + 1px gaps + 1px pad each side
        let left = 23 - width
        var out = glyph(Array(repeating: String(repeating: "q", count: width), count: 7), top: 16, left: left)
        var x = left + 1
        for ch in text {
            out = merge(out, glyph(digits[ch] ?? [], top: 17, left: x))
            x += 4
        }
        return out
    }

    /// Sleep-stage progress: five dots on the bottom row, `stage` of them lit
    /// in accent, the rest in outline so the row reads as a track.
    static func stageDots(_ stage: Int) -> PixelGrid {
        let filled = max(0, min(5, stage))
        var row = Array(String(repeating: transparent, count: size))
        for (i, c) in [3, 7, 11, 15, 19].enumerated() { row[c] = i < filled ? "a" : "o" }
        var out = blank()
        out[23] = String(row)
        return out
    }

    // MARK: - Base frames

    /// Awake idle, eyes open, smile. The canonical frame (see the plan's reference grid).
    static let awakeBase: PixelGrid = compose(eyes(), mouthSmile)
    private static let awakeBlink: PixelGrid = compose(eyes(lid: .closed), mouthSmile)
    private static let sleepBase: PixelGrid = compose(eyes(lid: .closed), mouthNeutral)
    private static let sleepBreath: PixelGrid = compose(eyes(lid: .closed), mouthNeutral, body: bodyBreath)
    private static let happyBase: PixelGrid = compose(eyes(), mouthGrin)
    private static let curiousBase: PixelGrid = compose(eyes(), mouthNeutral)
    private static let curiousTilt: PixelGrid = shiftRows(curiousBase, 2..<13, dx: 1)
    private static let hungryBase: PixelGrid = compose(eyes(lid: .half), mouthFrown)
    private static let errorBase: PixelGrid = compose(eyes(pupil: "e"), mouthNeutral)
    /// Static: glasses nudged right, body nudged left — a one-cell tear.
    private static let errorGlitch: PixelGrid = shiftRows(shiftRows(errorBase, 5..<10, dx: 1), 13..<23, dx: -1)

    // MARK: - Animation lookup

    /// Ordered frames + per-frame interval for a state, overlays baked in
    /// (R2). Every state returns ≥ 2 frames that differ, so a consumer's
    /// timer always has something to show; intervals sit in 250–800 ms (R8).
    static func frames(for state: BookwormState) -> (frames: [PixelGrid], interval: TimeInterval) {
        switch state {
        case .awake:
            // Idle bob (one cell down) and a blink.
            return ([awakeBase, shift(awakeBase, dy: 1), awakeBase, awakeBlink], 0.5)
        case .sleeping(let stage):
            // Eyes shut; a z drifts up-right and grows; the belly rises on the middle frame.
            let dots = stageDots(stage)
            return ([
                merge(merge(sleepBase, glyph(zSmall, top: 2, left: 21)), dots),
                merge(merge(sleepBreath, glyph(zSmall, top: 1, left: 20)), dots),
                merge(merge(sleepBase, glyph(zBig, top: 0, left: 19)), dots),
            ], 0.6)
        case .digesting:
            // Chewing on a book held at the right cheek; the book loses a corner.
            return ([
                merge(compose(eyes(), mouthOpen), glyph(book, top: 10, left: 17)),
                merge(compose(eyes(), mouthChew), glyph(book, top: 10, left: 17)),
                merge(compose(eyes(lid: .closed), mouthChew), glyph(bookBitten, top: 10, left: 17)),
                merge(compose(eyes(), mouthOpen), glyph(bookBitten, top: 10, left: 17)),
            ], 0.3)
        case .happy:
            // Bounce (one cell up) with sparkles trading corners.
            return ([
                merge(happyBase, glyph(sparkleSmall, top: 2, left: 1)),
                merge(shift(happyBase, dy: -1), merge(glyph(sparkle, top: 0, left: 18), glyph(sparkleSmall, top: 5, left: 1))),
                merge(happyBase, glyph(sparkleSmall, top: 1, left: 19)),
                shift(happyBase, dy: -1),
            ], 0.4)
        case .curious(let count):
            // Head tilt with a ? that lifts; the count rides in the pill on every frame.
            let badge = badgeOverlay(count)
            return ([
                merge(merge(curiousBase, glyph(questionMark, top: 0, left: 19)), badge),
                merge(merge(curiousTilt, glyph(questionMark, top: 0, left: 19)), badge),
                merge(merge(curiousTilt, glyph(questionMark, top: 1, left: 19)), badge),
            ], 0.6)
        case .hungry:
            // Half-lidded droop (one cell down) with a sweat drop sliding down the temple.
            return ([
                merge(hungryBase, glyph(dropSmall, top: 3, left: 21)),
                merge(shift(hungryBase, dy: 1), glyph(drop, top: 5, left: 21)),
                merge(shift(hungryBase, dy: 1), glyph(drop, top: 8, left: 21)),
            ], 0.7)
        case .reading:
            // An open book held low in front of the belly (rows 15–18, cols 8–16);
            // the eyes track left, centre, right; the third frame flicks the
            // right-hand page. Reduce Motion holding frame 0 is `BookwormView`'s
            // OWN general rule (its doc comment cites "ruling R7" from the
            // ORIGINAL 2026-09-02 mascot plan — a different plan's R7 than this
            // one's; do not confuse it with G125 R7, "after imports"). Nothing
            // state-specific needed here — it applies to every state already.
            //
            // `glyph` requires each row of `shape` to be the same width (a
            // ragged row still renders, just non-rectangular) — both grids
            // below are 9 columns per row:
            let bookOpen  = ["aaaaaaaaa", "awwwawwwa", "awwwawwwa", "aaaaaaaaa"]
            let bookFlick = ["aaaaaaaaa", "awwwaww.a", "awwwaw..a", "aaaaaaaaa"]
            let base = compose(eyes(), mouthSmile)
            return ([
                merge(shiftRows(base, 6..<9, dx: -1), glyph(bookOpen, top: 15, left: 8)),
                merge(base, glyph(bookOpen, top: 15, left: 8)),
                merge(shiftRows(base, 6..<9, dx: 1), glyph(bookFlick, top: 15, left: 8)),
                merge(base, glyph(bookOpen, top: 15, left: 8)),
            ], 0.5)
        case .error:
            // Red pupils, flat mouth; the second frame is a one-cell tear
            // between glasses and body — a glitch, not a bob.
            return ([errorBase, errorGlitch], 0.5)
        }
    }
}
