import Foundation

/// The five things in the room (G125 v3 Task 3), and the window's weather
/// pane, which sits behind the frame (Track Z §7.3). There is deliberately no
/// `shelfBooks` case: the page's ONE volume encoding is the real
/// `BookPileView`, and a painted spine stack at the same pixel scale
/// eighteen points away would ask the reader to tell a chart from wallpaper
/// by taste (P10). `deskSceneLayout` reserves a column for the real pile
/// instead, and `DeskSceneLayoutTests` proves no prop reaches into it.
enum DeskProp: String, CaseIterable, Hashable {
    case pane, window, lamp, plant, cushion, mug
}

/// The study room's art: five 24×24 grids in the same `PixelGrid` encoding
/// the mascot uses (`MenuBar/BookwormSprites.swift`), drawn through the same
/// `PixelRenderer`, in `DeskPalette`.
///
/// **One grid size, one point size (P12).** A prop that should look smaller
/// is authored smaller INSIDE its 24×24 grid — never rendered at a second
/// point size. Two pixel scales in one picture read as a bug at any zoom, and
/// a second `snappedPointSize` call would break G130 R6's single snap.
///
/// **Ink is authored flush to column 0.** That is what lets `deskSceneLayout`
/// read as a floor plan: a layer's `cellX` IS the scene column its paint
/// starts at, with no per-prop column arithmetic anywhere. The vertical
/// placement is the mirror rule — props are bottom-anchored in their grid and
/// `rowBand` records where each one's paint lives, so the layout can say "the
/// worm's baseline is the cushion's top row" and mean it.
///
/// **Static, on purpose (R-A13).** The stars do not twinkle, the moon does
/// not phase, nothing here is a `TimelineView`. Idle is still; the only things
/// in this room that ever change are the lamp, because the SCHEDULE changed
/// (P11), and the window's pane, because the MOOD changed (Track Z R-Z11) —
/// every art bit has a text twin (the whisper line, the window's legend).
enum DeskSceneSprites {

    /// Where each prop's paint lives inside its own grid. Asserted by
    /// `DeskSceneSpritesTests`, and consumed by `deskSceneLayout` (the
    /// cushion's top row is the worm's baseline) — so an art edit that drifts
    /// a prop upward fails a test instead of silently pushing furniture into
    /// the worm's cells.
    static let rowBand: [DeskProp: ClosedRange<Int>] = [
        .pane: 4...19,
        .window: 2...22,
        .lamp: 4...23,
        .plant: 10...23,
        .cushion: 19...23,
        .mug: 17...23,
    ]

    /// The window's glass, in its own grid (rows 4…19, cols 2…17 — jambs and
    /// mullions included, the frame occludes them). Named once: the window
    /// hotspot (Track Z §6.2) and the weather pane (§7.3) both sit on it, and
    /// `DeskHotspotTests` checks the worked grid below agrees with it.
    static let windowGlass = (rows: 4...19, cols: 2...17)

    /// The canonical grid per prop. The lamp's entry is the LIT variant and
    /// the pane's the NIGHT sky; the others are reached through
    /// `grid(_:lampLit:weather:)`, the scene's only state-dependent lookup.
    static var all: [DeskProp: PixelGrid] {
        [.pane: pane(.night), .window: window, .lamp: lampLit, .plant: plant, .cushion: cushion, .mug: mug]
    }

    /// The grid to draw for `prop`. Only the lamp reads `lampLit` and only the
    /// pane reads `weather` — P11 / R-Z11: the scene encodes STATE, never
    /// quantity, and those are its two bits (the schedule, the mood).
    static func grid(_ prop: DeskProp, lampLit isLit: Bool, weather: WindowWeather = .night) -> PixelGrid {
        switch prop {
        case .pane: return pane(weather)
        case .window: return window
        case .lamp: return isLit ? lampLit : lampDark
        case .plant: return plant
        case .cushion: return cushion
        case .mug: return mug
        }
    }

    /// The bounding box of a grid's non-transparent cells, or `nil` for an
    /// empty grid. Production code, not a test helper: `deskSceneLayout`'s
    /// contract is stated in terms of what a prop actually PAINTS (the pile
    /// column must clear the furniture, not the transparent padding around
    /// it), so the definition of "the prop" lives with the art.
    static func inkBounds(_ grid: PixelGrid) -> (rows: ClosedRange<Int>, cols: ClosedRange<Int>)? {
        var minRow = Int.max, maxRow = Int.min, minCol = Int.max, maxCol = Int.min
        for (r, row) in grid.enumerated() {
            for (c, ch) in row.enumerated() where ch != DeskPalette.transparent {
                minRow = min(minRow, r); maxRow = max(maxRow, r)
                minCol = min(minCol, c); maxCol = max(maxCol, c)
            }
        }
        guard minRow <= maxRow, minCol <= maxCol else { return nil }
        return (minRow...maxRow, minCol...maxCol)
    }

    // MARK: - The window (rows 2…22, cols 0…19)

    /// The frame, mullions and sill — every glass cell transparent; the sky
    /// is the pane behind it (Track Z §7.3). A 2-cell dusk-plum frame (`f`):
    /// cols 0–1 and 18–19 are the jambs, cols 9–10 and rows 11–12 the
    /// mullions that split the glass into four panes, and a `d` sill on the
    /// band's last row. Because the frame is drawn OVER the pane, the jambs
    /// and mullions occlude the weather for free — occlusion is the only
    /// depth cue a pixel window has.
    ///
    /// The night sky, the hand-drawn crescent and the four static stars that
    /// used to be painted here now live in `nightPane`, unchanged cell for
    /// cell except the stars, which moved off the cells the worm covers
    /// (design defect 8).
    static let window: PixelGrid = [
        "........................",
        "........................",
        "ffffffffffffffffffff....",   // 2  top frame
        "ffffffffffffffffffff....",   // 3
        "ff.......ff.......ff....",   // 4
        "ff.......ff.......ff....",   // 5
        "ff.......ff.......ff....",   // 6
        "ff.......ff.......ff....",   // 7
        "ff.......ff.......ff....",   // 8
        "ff.......ff.......ff....",   // 9
        "ff.......ff.......ff....",   // 10
        "ffffffffffffffffffff....",   // 11 horizontal mullion
        "ffffffffffffffffffff....",   // 12
        "ff.......ff.......ff....",   // 13
        "ff.......ff.......ff....",   // 14
        "ff.......ff.......ff....",   // 15
        "ff.......ff.......ff....",   // 16
        "ff.......ff.......ff....",   // 17
        "ff.......ff.......ff....",   // 18
        "ff.......ff.......ff....",   // 19
        "ffffffffffffffffffff....",   // 20 bottom frame
        "ffffffffffffffffffff....",   // 21
        "dddddddddddddddddddd....",   // 22 sill
        "........................",
    ]

    // MARK: - The lamp (rows 4…23, cols 0…9)

    /// A floor lamp, authored ONCE as a template: `S` is the shade's fill and
    /// `R` its rim, and the two variants are the same silhouette with those
    /// two characters substituted. `lampLit` and `lampDark` therefore differ
    /// only where the shade is — by construction, not by discipline — which
    /// is what makes the lamp the cheapest possible state bit (P11).
    ///
    /// Lit iff Sleep is scheduled (R-A3). The schedule row says the same
    /// thing in words, so the art is never the only place a reader can learn
    /// it; the lamp is a glance, the sentence is the fact.
    private static let lampTemplate: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "...SSSS.................",   // 4  shade
        "..SSSSSS................",   // 5
        ".SSSSSSSS...............",   // 6
        "SSSSSSSSSS..............",   // 7
        "RRRRRRRRRR..............",   // 8  the rim the light spills from
        "....dd..................",   // 9  pole
        "....dd..................",   // 10
        "....dd..................",   // 11
        "....dd..................",   // 12
        "....dd..................",   // 13
        "....dd..................",   // 14
        "....dd..................",   // 15
        "....dd..................",   // 16
        "....dd..................",   // 17
        "....dd..................",   // 18
        "....dd..................",   // 19
        "....dd..................",   // 20
        "....dd..................",   // 21
        "..dddddd................",   // 22 base
        ".dddddddd...............",   // 23
    ]

    static let lampLit: PixelGrid = lampTemplate.map {
        String($0.map { ch in ch == "S" ? "m" : (ch == "R" ? "s" : ch) })
    }
    /// Unlit: the shade and its rim both fall back to the mug's cold steel,
    /// so a dark lamp reads as an object in the room rather than a hole in it.
    static let lampDark: PixelGrid = lampTemplate.map {
        String($0.map { ch in (ch == "S" || ch == "R") ? "i" : ch })
    }

    // MARK: - The plant (rows 10…23, cols 0…8)

    /// Alternating `g`/`h` so the foliage has depth without a third green, on
    /// a terracotta pot. It encodes nothing: P11 — the scene carries exactly
    /// one data-driven bit, and it is the lamp.
    static let plant: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "....h...................",   // 10
        "...ghg..................",   // 11
        "..ghghg.................",   // 12
        ".ghghghg................",   // 13
        "ghghghghg...............",   // 14 the widest leaf span
        ".ghghghgh...............",   // 15
        "..ghghgh................",   // 16
        "...g.g..................",   // 17 stems
        "....gg..................",   // 18
        "..tttttt................",   // 19 pot rim
        "...tttt.................",   // 20
        "...tttt.................",   // 21
        "...tttt.................",   // 22
        "...dddd.................",   // 23 the pot's shadow on the floor
    ]

    // MARK: - The cushion (rows 19…23, cols 0…19)

    /// What the worm sits on. Its TOP ink row is load-bearing geometry, not
    /// decoration: `deskSceneLayout` puts the worm's baseline exactly there
    /// (`testTheWormsBaselineIsTheCushionsTopCell`), so a cushion that grew a
    /// row taller would raise the worm with it rather than clip it.
    static let cushion: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "...cccccccccccccc.......",   // 19 top — the worm's baseline
        ".cccccccccccccccccc.....",   // 20
        "cccccccccccccccccccc....",   // 21
        "pppppppppppppppppppp....",   // 22 the squashed underside
        "..pppppppppppppppp......",   // 23
    ]

    // MARK: - The mug (rows 17…23, cols 0…5)

    /// Steel body, a highlight on the rim, a handle on the right. No steam:
    /// steam would have to move, and R-A13 says idle is still.
    static let mug: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "uuuu....................",   // 17 rim highlight
        "iiiiii..................",   // 18 the handle attaches
        "iiii.i..................",   // 19 the handle's gap
        "iiiiii..................",   // 20 the handle rejoins
        "iiii....................",   // 21
        "iiii....................",   // 22
        "dddd....................",   // 23 shadow
    ]

    // MARK: - The weather pane (Track Z §7.3, R-Z11)

    /// The sky behind the frame: 16×16 of ink (the window's glass rows 4…19,
    /// cols 2…17), authored flush to column 0 and placed at `cellX: 20`, so the
    /// frame's jambs and mullions occlude it for free. One grid per weather;
    /// the weather is a function of the mood alone. `WindowSpritesTests` proves
    /// the sun, moon, stars and bolt clear the worm's union ink over every
    /// frame, pose and reaction of the moods that show them, and every cloud is
    /// at least half visible.
    static func pane(_ weather: WindowWeather) -> PixelGrid {
        switch weather {
        case .night: nightPane
        case .dawn: dawnPane
        case .clear: clearPane
        case .fair: fairPane
        case .overcast: overcastPane
        case .storm: stormPane
        case .curtains: curtainsPane
        }
    }

    /// The legend's thumbnail: the pane's 16×16 of glass, as its own grid.
    static func paneThumbnail(_ weather: WindowWeather) -> PixelGrid {
        pane(weather)[windowGlass.rows].map { String($0.prefix(windowGlass.cols.count)) }
    }

    /// Today's crescent, cell for cell, on night glass; four static stars moved
    /// off the cells the worm covers (design defect 8); the meadow a silhouette.
    ///
    /// The crescent is **hand-drawn, seven rows**, not generated: at seven
    /// cells a computed disc-minus-disc reads as a blob, because the
    /// anti-aliasing that makes that construction work is exactly what a pixel
    /// grid does not have. Two hues — `m` for the lit face, `n` for the
    /// terminator — so the moon has a direction instead of being a flat shape.
    private static let nightPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "kkkmmnkkkkkkkkkk........",   // 4  the crescent begins
        "kkmmnkkkkkskkkkk........",   // 5  star
        "kmmnkkkkkkkkkkkk........",   // 6
        "kmmnkkkkkkkkkkkk........",   // 7
        "kmmnkskkkkkkkkkk........",   // 8  star
        "kkmmnkkkkkkkkkkk........",   // 9
        "kkkmmnkkkkkkkkkk........",   // 10 the crescent ends
        "kkkkkkkkkkkkkkkk........",   // 11 (behind the mullion)
        "kkkkkkkkkkkkkkkk........",   // 12 (behind the mullion)
        "kkkskkkkkkkkkkkk........",   // 13 star
        "kkkkkkkkkkskkkkk........",   // 14 star
        "dkkkkkkkkkkkkkkd........",   // 15 the meadow, a silhouette
        "dddkkkkkkkkkkddd........",   // 16
        "dddddkkkkkkddddd........",   // 17
        "dddddddddddddddd........",   // 18
        "dddddddddddddddd........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// A cycle just finished: cushion-plum over terracotta, a half sun rising
    /// behind the right slope.
    private static let dawnPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "cccccccccccccccc........",   // 4
        "cccccccccccccccc........",   // 5
        "cccccccccccccccc........",   // 6
        "cccccccccccccccc........",   // 7
        "cccccccccccccccc........",   // 8
        "cccccccccccccccc........",   // 9
        "cccccccccccccccc........",   // 10
        "cccccccccccccccc........",   // 11
        "cccccccccccccccc........",   // 12
        "ttttttttttnntttt........",   // 13 the sun's rim
        "tttttttttnmmnttt........",   // 14
        "gttttttttttttttg........",   // 15
        "gggttttttttttggg........",   // 16
        "pggggttttttggggp........",   // 17
        "ppggggggggggggpp........",   // 18
        "ppppggppppggpppp........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// Caught up: day sky, haze, the meadow bowl with three dandelions and one seed clock.
    private static let clearPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "yyyyyyyyyyyyyyyy........",   // 4
        "yymmyyyyyyyyyyyy........",   // 5  the sun (the moon's cream, a gold rim)
        "ymmmnyyyyyyyyyyy........",   // 6
        "ymmmnyyyyyyyyyyy........",   // 7
        "yynnyyyyyyyyyyyy........",   // 8
        "yyyyyyyyyyyyyyyy........",   // 9
        "yyyyyyyyyyyyyyyy........",   // 10
        "yyyyyyyyyyyyyyyy........",   // 11
        "yyyyyyyyyyyyyyyy........",   // 12
        "vvvvvvvvvvvvvvvv........",   // 13 haze
        "vvvvvvvvvvvvvvvv........",   // 14
        "hvsvvvvvvvvvvvuh........",   // 15 dandelion, seed clock
        "hhhvsvvvvvvvshhh........",   // 16
        "ghhhhvvvvvvhhhhg........",   // 17
        "gghhhhhhhhhhhhgg........",   // 18
        "gggghhgggghhgggg........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// Things are waiting: the clear sky with two clouds, the sun half behind one.
    private static let fairPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "yyyyyyyyyyyyyyyy........",   // 4
        "yymmyyyyyyjjyyyy........",   // 5  sun; the second cloud peeks out
        "ymmmnyyyyjjjjyyy........",   // 6
        "ymmmjjjyyxxxxyyy........",   // 7  the first cloud crosses the sun
        "yynjjjjjjyyyyyyy........",   // 8
        "yyjjjjjjjyyyyyyy........",   // 9
        "yyyxxxxxyyyyyyyy........",   // 10 its shaded underside
        "yyyyyyyyyyyyyyyy........",   // 11
        "yyyyyyyyyyyyyyyy........",   // 12
        "vvvvvvvvvvvvvvvv........",   // 13
        "vvvvvvvvvvvvvvvv........",   // 14
        "hvsvvvvvvvvvvvuh........",   // 15
        "hhhvsvvvvvvvshhh........",   // 16
        "ghhhhvvvvvvhhhhg........",   // 17
        "gghhhhhhhhhhhhgg........",   // 18
        "gggghhgggghhgggg........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// Overdue: a grey sky, two clouds, and the dandelions closed — they close
    /// in bad weather (a small true thing, not an encoding).
    private static let overcastPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "xxxxxxxxxxjjxxxx........",   // 4
        "xjjjxxxxxjjjxxxx........",   // 5
        "jjjjjjxxxNNNxxxx........",   // 6
        "NNNNNNxxxxxxxxxx........",   // 7
        "xxxxxxxxxxxxxxxx........",   // 8
        "xxxxxxxxxxxxxxxx........",   // 9
        "xxxxxxxxxxxxxxxx........",   // 10
        "xxxxxxxxxxxxxxxx........",   // 11
        "xxxxxxxxxxxxxxxx........",   // 12
        "vvvvvvvvvvvvvvvv........",   // 13
        "vvvvvvvvvvvvvvvv........",   // 14
        "hvvvvvvvvvvvvvvh........",   // 15
        "hhhvvvvvvvvvvhhh........",   // 16
        "ghhhhvvvvvvhhhhg........",   // 17
        "gghhhhhhhhhhhhgg........",   // 18
        "gggghhgggghhgggg........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// The last cycle failed: a dark sky, two clouds, rain in both panes, a
    /// static bolt (no flash — refused, §7.3), the meadow a silhouette.
    private static let stormPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
        "KNNNKKKKKKNNKKKK........",   // 4
        "NxxxNNKKKNxNKKKK........",   // 5
        "NNNNsNNKKNNNKKKK........",   // 6  the bolt starts
        "KKKKsKKKKKKKKKKK........",   // 7
        "UKKsUKKKUKKKUKKK........",   // 8  rain
        "KUsKKUKKKUKKKUKK........",   // 9
        "KKsKKKUKKKUKKKUK........",   // 10 the bolt ends above the mullion
        "KKKKKKKKKKKKKKKK........",   // 11
        "KKKKKKKKKKKKKKKK........",   // 12
        "UKKKUKKKUKKKUKKK........",   // 13
        "KUKKKUKKKUKKKUKK........",   // 14
        "dKUKKKUKKKUKKKUd........",   // 15
        "dddKKKKKKKKKKddd........",   // 16
        "dddddKKKKKKddddd........",   // 17
        "dddddddddddddddd........",   // 18
        "dddddddddddddddd........",   // 19
        "........................",
        "........................",
        "........................",
        "........................",
    ]

    /// No reading yet: the curtains are drawn, a fold every third column.
    private static let curtainsPane: PixelGrid = [
        "........................",
        "........................",
        "........................",
        "........................",
    ] + Array(repeating: "ccpccpccpccpccpc........", count: 16) + [
        "........................",
        "........................",
        "........................",
        "........................",
    ]
}
