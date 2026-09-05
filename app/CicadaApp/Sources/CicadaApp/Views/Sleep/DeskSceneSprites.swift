import Foundation

/// The five things in the room (G125 v3 Task 3). There is deliberately no
/// `shelfBooks` case: the page's ONE volume encoding is the real
/// `BookPileView`, and a painted spine stack at the same pixel scale
/// eighteen points away would ask the reader to tell a chart from wallpaper
/// by taste (P10). `deskSceneLayout` reserves a column for the real pile
/// instead, and `DeskSceneLayoutTests` proves no prop reaches into it.
enum DeskProp: String, CaseIterable, Hashable {
    case window, lamp, plant, cushion, mug
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
/// not phase, nothing here is a `TimelineView`. Idle is still; the only thing
/// in this room that ever changes is the lamp, and it changes because the
/// SCHEDULE changed (P11) — every art bit has a text twin.
enum DeskSceneSprites {

    /// Where each prop's paint lives inside its own grid. Asserted by
    /// `DeskSceneSpritesTests`, and consumed by `deskSceneLayout` (the
    /// cushion's top row is the worm's baseline) — so an art edit that drifts
    /// a prop upward fails a test instead of silently pushing furniture into
    /// the worm's cells.
    static let rowBand: [DeskProp: ClosedRange<Int>] = [
        .window: 2...22,
        .lamp: 4...23,
        .plant: 10...23,
        .cushion: 19...23,
        .mug: 17...23,
    ]

    /// The canonical grid per prop. The lamp's entry is the LIT variant; the
    /// dark one is reached through `grid(_:lampLit:)`, which is the only
    /// state-dependent lookup in the scene.
    static var all: [DeskProp: PixelGrid] {
        [.window: window, .lamp: lampLit, .plant: plant, .cushion: cushion, .mug: mug]
    }

    /// The grid to draw for `prop`. Only the lamp reads `lampLit` — P11: the
    /// scene encodes STATE, never quantity, and the lamp is its one bit.
    static func grid(_ prop: DeskProp, lampLit isLit: Bool) -> PixelGrid {
        switch prop {
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

    /// The worked grid. A 2-cell dusk-plum frame (`f`) around night glass
    /// (`k`) — cols 0–1 and 18–19 are the jambs, cols 9–10 and rows 11–12 the
    /// mullions that split it into four panes — four static stars (`s`, one
    /// per pane), a `d` sill on the band's last row, and the crescent.
    ///
    /// The crescent is **hand-drawn, seven rows**, not generated: at seven
    /// cells a computed disc-minus-disc reads as a blob, because the
    /// anti-aliasing that makes that construction work is exactly what a pixel
    /// grid does not have. Two hues — `m` for the lit face, `n` for the
    /// terminator — so the moon has a direction instead of being a flat shape.
    static let window: PixelGrid = [
        "........................",
        "........................",
        "ffffffffffffffffffff....",   // 2  top frame
        "ffffffffffffffffffff....",   // 3
        "ffkkkmmnkffkkkkkkkff....",   // 4  the crescent begins
        "ffkkmmnkkffkkkkkkkff....",   // 5
        "ffkmmnkkkffkkkskkkff....",   // 6  star · upper-right pane
        "ffkmmnkkkffkkkkkkkff....",   // 7
        "ffkmmnkkkffkkkkkkkff....",   // 8
        "ffkkmmnkkffkkkkkskff....",   // 9  star · upper-right pane
        "ffkkkmmnkffkkkkkkkff....",   // 10 the crescent ends
        "ffffffffffffffffffff....",   // 11 horizontal mullion
        "ffffffffffffffffffff....",   // 12
        "ffkkkkkkkffkkkkkkkff....",   // 13
        "ffkkkkkkkffkkkkkkkff....",   // 14
        "ffkkkskkkffkkkkkkkff....",   // 15 star · lower-left pane
        "ffkkkkkkkffkkkkkkkff....",   // 16
        "ffkkkkkkkffkkkskkkff....",   // 17 star · lower-right pane
        "ffkkkkkkkffkkkkkkkff....",   // 18
        "ffkkkkkkkffkkkkkkkff....",   // 19
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
}
