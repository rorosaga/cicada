import CoreGraphics

/// Hotspot keys and interaction semantics are unchanged; geometry comes from authored slices.
enum DeskHotspot: Hashable, CaseIterable { case worm, lamp, window }

enum DeskHotspots {
    static var wormCols: ClosedRange<Int> {
        let ink = BookwormArt.wormInk
        return (DeskScene.wormCell.x + Int(ink.minX))...(DeskScene.wormCell.x + Int(ink.maxX) - 1)
    }
    static var wormRows: ClosedRange<Int> {
        let ink = BookwormArt.wormInk
        return (DeskScene.wormCell.y + 48 - Int(ink.maxY))...(DeskScene.wormCell.y + 47 - Int(ink.minY))
    }
    static var eyeCell: (col: Int, row: Int) {
        let eye = BookwormArt.eyePixel
        return (DeskScene.wormCell.x + Int(eye.x), DeskScene.wormCell.y + 47 - Int(eye.y))
    }
}

/// Whole-cell, disjoint rectangles in bottom-leading scene points. Missing sheets use their declared canvases.
func deskHotspots(_ layout: DeskSceneLayout) -> [DeskHotspot: CGRect] {
    func rect(cols: ClosedRange<Int>, rows: ClosedRange<Int>) -> CGRect {
        CGRect(x: CGFloat(cols.lowerBound) * layout.cell, y: CGFloat(rows.lowerBound) * layout.cell,
               width: CGFloat(cols.count) * layout.cell, height: CGFloat(rows.count) * layout.cell)
    }
    var spots: [DeskHotspot: CGRect] = [.worm: rect(cols: DeskHotspots.wormCols, rows: DeskHotspots.wormRows)]
    if let lamp = layout.layers.first(where: { $0.prop == .lamp }) {
        let ink = SpriteSheets.sheet(named: "room-lamp")?.slices["ink"] ?? CGRect(x: 0, y: 0, width: lamp.w, height: lamp.h)
        spots[.lamp] = rect(cols: (lamp.cellX + Int(ink.minX))...(lamp.cellX + Int(ink.maxX) - 1),
                            rows: (lamp.cellY + lamp.h - Int(ink.maxY))...(lamp.cellY + lamp.h - 1 - Int(ink.minY)))
    }
    if let window = layout.layers.first(where: { $0.prop == .window }) {
        let glass = SpriteSheets.sheet(named: "room-window")?.slices["glass"] ?? CGRect(x: 2, y: 2, width: 36, height: 32)
        let firstCol = window.cellX + Int(glass.minX)
        let lastCol = min(window.cellX + Int(glass.maxX) - 1, DeskHotspots.wormCols.lowerBound - 1)
        if lastCol >= firstCol {
            spots[.window] = rect(cols: firstCol...lastCol,
                rows: (window.cellY + window.h - Int(glass.maxY))...(window.cellY + window.h - 1 - Int(glass.minY)))
        }
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
