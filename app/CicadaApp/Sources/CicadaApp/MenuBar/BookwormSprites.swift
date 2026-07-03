import Foundation

/// Code-defined pixel sprites for the menu-bar bookworm, transcribed from
/// `app/assets/book_worm.png`. Each grid is 16 rows x 16 cols; `#` is a lit
/// pixel, any other character (space) is transparent. ``BookwormRenderer``
/// rasterizes them into template `NSImage`s so the menu bar tints them for
/// dark + light appearance. The renderer pads/truncates ragged rows, so trailing
/// spaces stripped by an editor never crash indexing.
///
/// Authoring rule (per spec §1.2): the head + twin round-lens glasses silhouette
/// is identical across `awakeOpen`, `happy`, `curious`, `hungry`, `digesting` so
/// the character stays recognizable; only the eyes (pupils/lids), mouth, body
/// wiggle, and overlays differ between states. Each lens is a closed rounded box
/// with a centered pupil; the two lenses share a bridge; a smile sits under it.
enum BookwormSprites {

    // MARK: - Head fragments (kept constant so the worm reads the same)

    /// Open-eyed glasses: two lenses, each a closed box with a centered pupil.
    private static let headOpen = [
        "   ####   ####  ",
        "  #    # #    # ",
        "  # ## # # ## # ",
        "  # ## # # ## # ",
        "  #    # #    # ",
        "   ####   ####  ",
    ]

    /// Closed-eye glasses: same frames, pupils replaced by a flat lid line.
    private static let headClosed = [
        "   ####   ####  ",
        "  #    # #    # ",
        "  #    # #    # ",
        "  # #### # #### ",
        "  #    # #    # ",
        "   ####   ####  ",
    ]

    /// Body curling down-left into a segmented worm tail. Same across states.
    private static let bodyCurl = [
        "     ##         ",
        "   ###  ###     ",
        "  ##  ##   ##   ",
        " ##         #   ",
        " ###           ",
        "               ",
    ]

    private static func compose(_ head: [String], mouth: [String], _ body: [String] = bodyCurl) -> [String] {
        // 1 blank + 6 head + 3 mouth + 6 body = 16 rows.
        (["               "] + head + mouth + body)
    }

    // MARK: - Base frames

    /// Awake idle, eyes open, slight smile. The canonical frame.
    static let awakeOpen: [String] = compose(headOpen, mouth: [
        "    #     #     ",
        "    ## # ##     ",
        "     #####      ",
    ])

    /// Same head, eyes blinked shut for a single frame.
    static let awakeBlink: [String] = compose(headClosed, mouth: [
        "    #     #     ",
        "    ## # ##     ",
        "     #####      ",
    ])

    /// Closed eyes, neutral mouth. Used while sleeping.
    static let sleepEyes: [String] = compose(headClosed, mouth: [
        "    #     #     ",
        "    #     #     ",
        "     #####      ",
    ])

    /// OR-merges an overlay grid onto a base grid (row/col-wise `#` union).
    /// Used to bake the zZz overlay into the sleeping-state frames themselves
    /// so any consumer that just plays `frames(for:)` — not only the menu-bar
    /// renderer's explicit `overlays:` path — shows the rising zZz.
    private static func merged(_ base: [String], _ overlay: [String]) -> [String] {
        base.enumerated().map { r, baseLine in
            guard r < overlay.count else { return baseLine }
            let overlayLine = Array(overlay[r])
            return String(Array(baseLine).enumerated().map { c, ch -> Character in
                if c < overlayLine.count, overlayLine[c] == "#" { return "#" }
                return ch
            })
        }
    }

    // MARK: - zZz overlay frames (drawn on top of sleepEyes)
    //
    // A `z` climbing up-right above the head over three frames. Overlay-only:
    // lit cells are OR-ed onto the base by the renderer.

    static let zzzFrame1: [String] = [
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "          ###  ",
        "           #   ",
        "          ###  ",
        "               ",
        "               ",
    ]

    static let zzzFrame2: [String] = [
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "          ###  ",
        "           #   ",
        "          ###  ",
        "               ",
        "            ## ",
        "             # ",
        "            ## ",
        "               ",
        "               ",
    ]

    static let zzzFrame3: [String] = [
        "               ",
        "               ",
        "        ###    ",
        "         #     ",
        "        ###    ",
        "               ",
        "           ##  ",
        "            #  ",
        "           ##  ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
        "               ",
    ]

    /// The full sleeping-state frame sequence: `sleepEyes` with the rising zZz
    /// overlay baked in, one `z` growing to three across the loop. This is what
    /// ``frames(for:)`` hands back for `.sleeping`, so both ``BookwormView``
    /// (plain frame playback, no overlay support) and the menu-bar status item
    /// (which additionally OR-s in the same `zzzFrames` via its own `overlays:`
    /// path — harmless, since OR-merge is idempotent) show the worm visibly
    /// dozing off.
    static let sleepFrame1: [String] = merged(sleepEyes, zzzFrame1)
    static let sleepFrame2: [String] = merged(sleepEyes, zzzFrame2)
    static let sleepFrame3: [String] = merged(sleepEyes, zzzFrame3)

    // MARK: - Digesting (chewing mouth open/closed)

    /// Chewing — mouth open (round jaw).
    static let chew1: [String] = compose(headOpen, mouth: [
        "    #     #     ",
        "    #######     ",
        "     #   #      ",
    ])

    /// Chewing — mouth closed. Reuses the idle smile.
    static let chew2: [String] = awakeOpen

    // MARK: - Happy / sparkle

    /// Big smile (wider mouth than idle).
    static let happy: [String] = compose(headOpen, mouth: [
        "    #     #     ",
        "    ##   ##     ",
        "     #####      ",
    ])

    /// Happy + a sparkle pixel cluster top-right (alternates with `happy`).
    static let sparkle: [String] = {
        var g = happy
        // Light a small sparkle in the top-right corner (rows 0-1).
        g[0] = "            # # "
        g[1] = "   ####   #### #"
        return g
    }()

    // MARK: - Curious (raised brow + slight tilt, 2-frame loop)

    static let curiousTilt1: [String] = {
        var g = awakeOpen
        // Raise a brow pixel over the left lens.
        g[0] = "   #           "
        return g
    }()

    static let curiousTilt2: [String] = {
        // Shift the whole worm one column right for a subtle head-tilt loop.
        awakeOpen.map { line in
            " " + String(line.dropLast())
        }
    }()

    // MARK: - Hungry (half-lidded eyes, downturned mouth, slow sway)

    static let hungryDroop: [String] = compose(headClosed, mouth: [
        "    #     #     ",
        "     #####      ",
        "    ##   ##     ",
    ])

    /// Hungry sway frame — body shifted one column for a slow 2-frame sway.
    static let hungryDroop2: [String] = {
        var g = hungryDroop
        for i in 10..<16 {   // shift the body rows right by one column
            g[i] = " " + String(g[i].dropLast())
        }
        return g
    }()

    // MARK: - Animation lookup

    /// Ordered frames + interval for a state. Overlays (zZz, badge, stage dots)
    /// are merged separately by the renderer from the live snapshot.
    static func frames(for state: BookwormState) -> (frames: [[String]], interval: TimeInterval) {
        switch state {
        case .awake:
            // Mostly static; a quick blink. ~0.5 fps keeps CPU negligible.
            return ([awakeOpen, awakeOpen, awakeOpen, awakeOpen, awakeOpen,
                     awakeOpen, awakeOpen, awakeOpen, awakeOpen, awakeBlink], 0.5)
        case .sleeping:
            // zZz rises over three frames (one z, then two, then three,
            // looping); base eyes stay shut throughout.
            return ([sleepFrame1, sleepFrame2, sleepFrame3], 0.6)
        case .digesting:
            return ([chew1, chew2, chew1, chew2, chew1, chew2], 0.18)
        case .happy:
            return ([happy, happy, happy, happy, happy, sparkle], 0.5)
        case .curious:
            return ([curiousTilt1, curiousTilt2], 0.6)
        case .hungry:
            return ([hungryDroop, hungryDroop2], 0.8)
        }
    }

    /// The three rising `zZz` overlay frames, cycled in lockstep with the
    /// sleeping animation. Returned separately because they are OR-ed onto the
    /// base sleep frame by the renderer.
    static let zzzFrames: [[String]] = [zzzFrame1, zzzFrame2, zzzFrame3]

    // MARK: - Badge digits (3x5 mini-font), drawn bottom-right for `curious`.

    static let digits: [Character: [String]] = [
        "0": ["###", "# #", "# #", "# #", "###"],
        "1": ["  #", "  #", "  #", "  #", "  #"],
        "2": ["###", "  #", "###", "#  ", "###"],
        "3": ["###", "  #", "###", "  #", "###"],
        "4": ["# #", "# #", "###", "  #", "  #"],
        "5": ["###", "#  ", "###", "  #", "###"],
        "6": ["###", "#  ", "###", "# #", "###"],
        "7": ["###", "  #", "  #", "  #", "  #"],
        "8": ["###", "# #", "###", "# #", "###"],
        "9": ["###", "# #", "###", "  #", "###"],
    ]

    /// Render the badge count (1..2 digits, `min(count, 99)`) as a 16x16 overlay
    /// grid lit in the bottom-right corner.
    static func badgeOverlay(_ count: Int) -> [String] {
        let n = max(0, min(99, count))
        let str = String(n)
        var grid = Array(repeating: Array(repeating: Character(" "), count: 16), count: 16)
        // Lay digits right-to-left along rows 11..15, 3 px wide + 1 px gap.
        var col = 15
        let rowTop = 11
        for ch in str.reversed() {
            guard let glyph = digits[ch] else { continue }
            let left = col - 3
            if left < 0 { break }
            for (r, line) in glyph.enumerated() {
                for (c, cell) in Array(line).enumerated() where cell == "#" {
                    let gr = rowTop + r, gc = left + c
                    if gr >= 0, gr < 16, gc >= 0, gc < 16 { grid[gr][gc] = "#" }
                }
            }
            col = left - 1  // 1 px gap before the next digit
        }
        return grid.map { String($0) }
    }

    /// A 16x16 overlay lighting `stage` of 5 dots along the bottom row, used for
    /// the sleep-stage progress indicator. Dots are 1 px each, evenly spaced.
    static func stageDots(_ stage: Int) -> [String] {
        let filled = max(0, min(5, stage))
        var row = Array(repeating: Character(" "), count: 16)
        let cols = [2, 5, 8, 11, 14]
        for i in 0..<filled { row[cols[i]] = "#" }
        var grid = Array(repeating: String(repeating: " ", count: 16), count: 16)
        grid[15] = String(row)
        return grid
    }
}
