import AppKit

/// Rasterizes a `PixelGrid` of ANY square size, in ANY palette, into a COLOUR
/// `NSImage` with nearest-neighbour cells.
///
/// This is `BookwormRenderer`'s body, generalized (G125 v3 Task 2). The Sleep
/// page's study room draws five 24×24 props and — later — a strip of small
/// stage icons; every one of them wants the same three properties the mascot
/// needed: hard pixel edges at any scale, a point size snapped so a cell is a
/// whole number of points, and a cache so a repaint is a dictionary hit rather
/// than a rasterization. Copying that code once per consumer is how two
/// renderers drift into drawing the same grid two different ways, so there is
/// one, and `BookwormRenderer` became four thin forwarders over it.
///
/// COLOUR, not template (G107): a template image is tinted uniformly by the
/// system and so cannot show mood, and the room's night window cannot be a
/// silhouette. The palette is a parameter rather than a global because the
/// room and the character are different drawings — see `DeskPalette`, which
/// exists precisely because `BookwormPalette` is contractually nine keys.
enum PixelRenderer {

    /// Snaps a scaled point size onto a multiple of `gridSize` (G130 R6):
    /// pages request sizes like 120 · `CicadaTheme.uiScale`, and a fractional
    /// multiple would leave a sprite cell a fractional point AND change the
    /// `Int(pointSize)` half of a cache key on every frame instead of once
    /// per zoom step. Floors at ONE WHOLE CELL rather than 0, which a very
    /// small `pointSize` would otherwise round down to.
    ///
    /// The snap is onto the grid's own multiple, not a hardcoded 24 — that is
    /// the whole generalization: a 16-cell icon snaps to 16s, the 24-cell worm
    /// still snaps to 24s, and `BookwormRenderer.snappedPointSize` is exactly
    /// the `gridSize: 24` case of this function.
    static func snappedPointSize(_ pointSize: CGFloat, gridSize: Int) -> CGFloat {
        let g = CGFloat(max(1, gridSize))
        return max(g, g * (pointSize / g).rounded())
    }

    /// `0xRRGGBB` → opaque sRGB. Every palette in the app is authored as hex
    /// literals (they are art hues, deliberately mode-independent — see
    /// `BookwormPalette`'s docstring), so this is the one conversion and no
    /// caller writes the shift-and-divide by hand.
    static func nsColors(_ palette: [Character: UInt32]) -> [Character: NSColor] {
        palette.mapValues { hex in
            NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
                    green: CGFloat((hex >> 8) & 0xFF) / 255,
                    blue: CGFloat(hex & 0xFF) / 255,
                    alpha: 1)
        }
    }

    /// Render one grid at `pointSize` × `pointSize`. The grid is drawn as
    /// given: `BookwormSprites.frames(for:)` already bakes every overlay
    /// (badge, stage dots, nightcap — mascot ruling R2), so there is no merge
    /// seam here either. A short or ragged grid is padded with transparent
    /// cells rather than trapping, which is what lets a prop be authored
    /// incrementally without the app refusing to draw it.
    static func image(grid: PixelGrid, gridSize: Int, pointSize: CGFloat,
                      palette: [Character: NSColor]) -> NSImage {
        let n = max(1, gridSize)
        let rows: [[Character]] = (0..<n).map { r in
            r < grid.count ? Array(grid[r].padding(toLength: n, withPad: ".", startingAt: 0))
                           : Array(repeating: ".", count: n)
        }
        let cell = pointSize / CGFloat(n)
        let image = NSImage(size: NSSize(width: pointSize, height: pointSize), flipped: false) { _ in
            guard let ctx = NSGraphicsContext.current else { return false }
            // Hard edges: a pixel is a pixel at every scale.
            ctx.shouldAntialias = false
            ctx.imageInterpolation = .none
            for (r, line) in rows.enumerated() {
                for (c, ch) in line.enumerated() {
                    guard let color = palette[ch] else { continue }   // "." and unknowns stay clear
                    color.setFill()
                    // Grid row 0 is the top; AppKit's origin is bottom-left.
                    let x = CGFloat(c) * cell
                    let y = CGFloat(n - 1 - r) * cell
                    NSBezierPath(rect: NSRect(x: x, y: y, width: cell, height: cell)).fill()
                }
            }
            return true
        }
        image.isTemplate = false
        return image
    }

    // MARK: - Scene cache (P13)

    /// A SECOND cache, deliberately not the mascot's. `BookwormRenderer`'s
    /// cache wipes wholesale past 512 entries; feeding scene layers and stage
    /// icons through it would make the always-animating worm collateral
    /// damage of every wipe — it would re-rasterize a frame per timer tick
    /// right after a page render. Keys are namespaced by their caller
    /// (`"desk.window|lit|120"`, `"stage.read|32"`) because this cache has no
    /// state enum to derive one from: whoever asks for an image owns its
    /// identity, and two callers sharing a key would share an image.
    ///
    /// Lock-guarded rather than actor-isolated for the same reason the worm's
    /// is: consumers call it from wherever they already are, including a
    /// `TimelineView` content closure whose isolation the SDK does not spell
    /// out. An `NSLock` around a dictionary is the whole cost; `NSImage` is
    /// immutable once built.
    private static let sceneLock = NSLock()
    nonisolated(unsafe) private static var sceneCache: [String: NSImage] = [:]

    /// The rendered grid for `key`, drawn at most once per key.
    static func cachedImage(key: String, grid: PixelGrid, gridSize: Int, pointSize: CGFloat,
                            palette: [Character: NSColor]) -> NSImage {
        sceneLock.lock()
        let hit = sceneCache[key]
        sceneLock.unlock()
        if let hit { return hit }
        let img = image(grid: grid, gridSize: gridSize, pointSize: pointSize, palette: palette)
        sceneLock.lock()
        // A handful of props × a few zoom steps is tiny, but bound it so a
        // long-running app can never grow it unboundedly.
        if sceneCache.count > 512 { sceneCache.removeAll() }
        // A racing second render of the same key just wins by being last; both
        // images are pixel-identical, so nothing observable depends on which.
        sceneCache[key] = img
        sceneLock.unlock()
        return img
    }
}
