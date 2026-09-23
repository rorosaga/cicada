import CoreGraphics

/// The room's three hotspots (Track Z §6.2). Spines are their own buttons
/// inside `BookPileView` — their frames are SwiftUI layout, not lattice cells
/// (Z-P14). Z-P14 also means only `.worm` is drawn as a button in Z5: the lamp
/// lands with its popover (Z6) and the window with its legend (Z8), because a
/// hotspot that opens nothing would break R-Z2. Their rectangles are derived
/// and tested now so those tasks only add the button.
enum DeskHotspot: Hashable, CaseIterable {
    case worm, lamp, window
}

enum DeskHotspots {
    /// The worm's ink span on the scene lattice: the 20 columns `DeskScene`
    /// lines up with the cushion (scene cols 30…49), and the worm box's full
    /// height (rows 4…27), cap and hop included.
    static let wormCols = (DeskScene.wormCell.x + 2)...(DeskScene.wormCell.x + 21)
    static let wormRows = DeskScene.wormCell.y...(DeskScene.wormCell.y + BookwormSprites.size - 1)
    /// The glasses' bridge (grid row 7, col 12) in scene cells — the invariant
    /// test's anchor for "the eyes are inside the worm".
    static let eyeCell = (col: DeskScene.wormCell.x + 12, row: DeskScene.wormCell.y + BookwormSprites.size - 1 - 7)
}

/// Whole-cell rectangles in points, bottom-leading origin — the same space
/// `DeskSceneLayout` uses — derived from cells, never from typed points, so
/// the hotspot layer cannot drift from the art (R-Z8).
func deskHotspots(_ layout: DeskSceneLayout) -> [DeskHotspot: CGRect] {
    let last = BookwormSprites.size - 1
    func rect(cols: ClosedRange<Int>, rows: ClosedRange<Int>) -> CGRect {
        CGRect(x: CGFloat(cols.lowerBound) * layout.cell, y: CGFloat(rows.lowerBound) * layout.cell,
               width: CGFloat(cols.count) * layout.cell, height: CGFloat(rows.count) * layout.cell)
    }
    var spots: [DeskHotspot: CGRect] = [.worm: rect(cols: DeskHotspots.wormCols, rows: DeskHotspots.wormRows)]
    // A grid's row 0 is its TOP; the scene counts rows up from the floor, so
    // grid row r of a layer at `cellY` sits at scene row `cellY + last − r`.
    if let lamp = layout.layers.first(where: { $0.prop == .lamp }),
       let ink = DeskSceneSprites.inkBounds(DeskSceneSprites.lampLit) {
        spots[.lamp] = rect(cols: (lamp.cellX + ink.cols.lowerBound)...(lamp.cellX + ink.cols.upperBound),
                            rows: (lamp.cellY + last - ink.rows.upperBound)...(lamp.cellY + last - ink.rows.lowerBound))
    }
    if let window = layout.layers.first(where: { $0.prop == .window }) {
        let glass = DeskSceneSprites.windowGlass
        // Clipped where the worm starts, so the two never overlap (§6.2).
        let lastCol = min(window.cellX + glass.cols.upperBound, DeskHotspots.wormCols.lowerBound - 1)
        spots[.window] = rect(cols: (window.cellX + glass.cols.lowerBound)...lastCol,
                              rows: (window.cellY + last - glass.rows.upperBound)...(window.cellY + last - glass.rows.lowerBound))
    }
    return spots
}

/// `onContinuousHover` reports top-left points; the scene is bottom-leading.
func sceneBottomLeading(_ point: CGPoint, in layout: DeskSceneLayout) -> CGPoint {
    CGPoint(x: point.x, y: layout.size.height - point.y)
}

/// Where the worm looks for a pointer at `pointerX` (Track Z §6.2). Left of
/// the worm's ink → `.left`, right of it → `.right`, over it → `.center`,
/// with one cell of hysteresis: leaving a side takes a whole cell, so a sweep
/// back and forth across an edge changes the gaze at most once. States whose
/// eyes must not move (§6.4) always look ahead. Named `gazeFor`, not `gaze`,
/// because `RoomModel.gaze` would shadow it (Z-P22).
func gazeFor(pointerX: CGFloat?, layout: DeskSceneLayout, previous: Gaze, state: BookwormState) -> Gaze {
    guard state.acceptsGaze, let x = pointerX else { return .center }
    let left = CGFloat(DeskHotspots.wormCols.lowerBound) * layout.cell
    let right = CGFloat(DeskHotspots.wormCols.upperBound + 1) * layout.cell
    switch previous {
    case .left where x < left + layout.cell: return .left
    case .right where x >= right - layout.cell: return .right
    default: break
    }
    if x < left { return .left }
    if x >= right { return .right }
    return .center
}
