import SwiftUI

/// One prop placed on the scene's cell lattice. `cellX`/`cellY` are the
/// bottom-leading corner of the prop's own 24×24 grid, counted in CELLS from
/// the scene's bottom-leading origin — never in points, so the whole floor
/// plan is scale-free and `uiScale` enters exactly once, in `cell`.
struct DeskLayer: Equatable {
    let prop: DeskProp
    let cellX: Int
    let cellY: Int
    /// Back → front. Strictly ascending across the scene (tested), so two
    /// props can never end up drawn in an order that depends on dictionary
    /// iteration.
    let z: Int
}

/// The composed room: where every prop goes, where the worm sits, and the
/// column reserved for the REAL book pile.
struct DeskSceneLayout: Equatable {
    /// Points per grid cell — the one place `uiScale` and the snapped point
    /// size turn into geometry.
    let cell: CGFloat
    /// The whole scene box, bottom-leading origin.
    let size: CGSize
    /// Back → front.
    let layers: [DeskLayer]
    /// Bottom-leading corner of the worm's own 24×24 box, in points.
    let wormOrigin: CGPoint
    /// Where the real `BookPileView` goes — a `CGRect` with a bottom-leading
    /// origin, like everything else here. NOT a painted prop (P10).
    let pileFrame: CGRect
}

/// The lattice the room is composed on. Both numbers are geometry, not
/// taste, and the tests say so:
///
/// - `rows = 28` because the worm is 24 cells tall and sits ON the cushion,
///   whose top ink row is 4 cells off the floor. A 24-cell box cannot hold a
///   24-cell worm raised 4 cells.
/// - `cols = 90` because the room's floor line (lamp · plant · cushion+worm ·
///   mug) is 58 cells at the worm's own scale — every prop is drawn at the
///   worm's point size, so a room that holds a 20-cell worm is a wide room —
///   and the pile column after it has to fit a full-width `BookPileView`
///   spine: 150 pt, i.e. 30 cells at `uiScale == 1.0`. P10 forbids solving
///   that by painting a smaller fake pile instead, so the box is as wide as
///   the real one needs.
enum DeskScene {
    static let cols = 90
    static let rows = 28

    /// The prop floor plan, in cells. Each entry is `(prop, cellX, cellY, z)`;
    /// `cellX` is the scene column the prop's paint STARTS at, because every
    /// grid is authored flush to column 0 (`DeskSceneSprites`' own rule).
    ///
    /// Reading left to right: a floor lamp, a potted plant, then the night
    /// window on the wall with the cushion centred under it and the worm on
    /// the cushion, and a mug on the floor to his right. The window is
    /// `cellY: 4` — it hangs on the wall, its sill one cell above the
    /// cushion's top; the four floor objects are `cellY: 0`.
    ///
    /// Two facts about the horizontal placement, both read off the first
    /// composites rather than guessed:
    ///
    /// - Nothing thin stands in front of a PANE. A plant placed under one
    ///   read as a plant growing inside the glass — a pixel window has no
    ///   depth cue but occlusion, and interleaved leaves and glass just look
    ///   like one texture. The plant overlaps the window's left jamb (a solid
    ///   two-cell frame) and stops there.
    /// - The worm is 20 cells of ink and the window is 20 cells wide, so a
    ///   worm centred on the window erases it. The cushion sits under the
    ///   window's RIGHT third; the moon and the left panes stay in view.
    static let plan: [DeskLayer] = [
        DeskLayer(prop: .window, cellX: 18, cellY: 4, z: 0),
        DeskLayer(prop: .lamp, cellX: 0, cellY: 0, z: 1),
        DeskLayer(prop: .plant, cellX: 11, cellY: 0, z: 2),
        DeskLayer(prop: .cushion, cellX: 30, cellY: 0, z: 3),
        DeskLayer(prop: .mug, cellX: 52, cellY: 0, z: 4),
    ]

    /// The worm's own 24×24 box, in cells. `cellY: 4` is the cushion's top ink
    /// row (`DeskSceneSprites.cushion` row 19 → 23 − 19 = 4 cells off the
    /// floor), which is what puts his tail ON the cushion rather than through
    /// it; `cellX: 28` lines his 20-cell-wide ink up with the cushion's own,
    /// at scene cols 30…49.
    static let wormCell = (x: 28, y: 4)

    /// The reserved pile column, in cells: 30 wide so a full-width spine fits
    /// (`BookPileView` draws up to 150 pt), 26 tall so a tall pile has
    /// headroom without leaving the scene.
    static let pileCell = (x: 60, y: 0, width: 30, height: 26)
}

/// The room, composed on ONE cell lattice (P12). Every prop is its own 24×24
/// grid rendered at the SAME snapped point size as the worm, positioned by an
/// integer CELL count — a prop that should look smaller is authored smaller
/// inside its grid, never rendered at a second point size, because two pixel
/// scales in one picture read as a bug at any zoom and would break G130 R6's
/// single `snappedPointSize` call. There is deliberately NO painted book
/// stack: the page's one volume encoding is `BookPileView`, and a decorative
/// spine stack at the same pixel scale would ask the reader to tell a chart
/// from wallpaper by taste (P10).
///
/// Pure and view-free, like `bookPileLayout` and `studyRows` beside it, so the
/// whole picture can be argued about in a unit test rather than by eye.
func deskSceneLayout(pointSize: CGFloat = 120,
                     uiScale: Double = CicadaTheme.uiScale) -> DeskSceneLayout {
    // The ONE snap for the whole scene (P12): the worm's own entry point, so
    // the room and the character can never disagree about how big a pixel is.
    let scenePt = BookwormRenderer.snappedPointSize(pointSize * CGFloat(uiScale))
    let cell = scenePt / CGFloat(BookwormRenderer.gridSize)
    return DeskSceneLayout(
        cell: cell,
        size: CGSize(width: CGFloat(DeskScene.cols) * cell, height: CGFloat(DeskScene.rows) * cell),
        layers: DeskScene.plan,
        wormOrigin: CGPoint(x: CGFloat(DeskScene.wormCell.x) * cell,
                            y: CGFloat(DeskScene.wormCell.y) * cell),
        pileFrame: CGRect(x: CGFloat(DeskScene.pileCell.x) * cell,
                          y: CGFloat(DeskScene.pileCell.y) * cell,
                          width: CGFloat(DeskScene.pileCell.width) * cell,
                          height: CGFloat(DeskScene.pileCell.height) * cell))
}

/// The room as pixels. A back-to-front stack of cached prop images, every one
/// `.interpolation(.none)` so a cell stays a hard square at any zoom.
///
/// **No `TimelineView`** — the backdrop is static (R-A13: idle is still). The
/// whole stack is hit-test-transparent and accessibility-hidden: the worm
/// already carries the state label and `BookPileView` its own, and six props
/// read aloud would bury both.
struct DeskSceneView: View {
    /// The worm's requested point size — the scene snaps it exactly the way
    /// `BookwormView` does, so passing the same number to both is what keeps
    /// them on one lattice.
    var pointSize: CGFloat = 120
    /// R-A3 — lit iff Sleep is scheduled. The one data-driven bit in the room
    /// (P11), and the schedule row states the same fact in words.
    var lampLit: Bool

    var body: some View {
        let layout = deskSceneLayout(pointSize: pointSize)
        let spritePt = layout.cell * CGFloat(BookwormRenderer.gridSize)
        ZStack(alignment: .bottomLeading) {
            // An explicit transparent floor so the ZStack's own size is the
            // scene box even before a prop is placed — offsets are measured
            // from a rect, not from whatever the widest child happened to be.
            Color.clear
            ForEach(layout.layers, id: \.prop) { layer in
                Image(nsImage: PixelRenderer.cachedImage(
                    key: Self.cacheKey(layer.prop, lampLit: lampLit, pointSize: spritePt),
                    grid: DeskSceneSprites.grid(layer.prop, lampLit: lampLit),
                    gridSize: BookwormRenderer.gridSize,
                    pointSize: spritePt,
                    palette: DeskPalette.ns))
                    .interpolation(.none)
                    .frame(width: spritePt, height: spritePt)
                    // Bottom-leading: +x is right, −y is up.
                    .offset(x: CGFloat(layer.cellX) * layout.cell,
                            y: -CGFloat(layer.cellY) * layout.cell)
            }
        }
        .frame(width: layout.size.width, height: layout.size.height, alignment: .bottomLeading)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    /// Namespaced per P13: `PixelRenderer`'s scene cache has no state enum to
    /// derive a key from, so whoever asks for an image owns its identity. The
    /// variant segment is `-` for every prop but the lamp, whose two grids
    /// must never share a key.
    static func cacheKey(_ prop: DeskProp, lampLit: Bool, pointSize: CGFloat) -> String {
        let variant = prop == .lamp ? (lampLit ? "lit" : "dark") : "-"
        return "desk.\(prop.rawValue)|\(variant)|\(Int(pointSize))"
    }
}
