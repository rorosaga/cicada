import AppKit

/// Rasterizes a `PixelGrid` into a COLOUR `NSImage` with nearest-neighbour
/// cells. Colour, not template (G107): a template image is tinted uniformly
/// by the system and so cannot show mood; the 1-px `o` outline is what makes
/// the silhouette survive both the light and the dark menu bar without
/// tinting. Page consumers request sizes that are multiples of 24 so cells
/// are integer points (ruling R3); the menu bar runs 18 pt.
enum BookwormRenderer {
    static let gridSize = BookwormSprites.size

    private static let colors: [Character: NSColor] = BookwormPalette.colors.mapValues { hex in
        NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255,
                alpha: 1)
    }

    /// Render one grid at `pointSize` × `pointSize`. `overlays` are OR-merged
    /// first; the parameter exists only for `MenuBarManager`'s pre-Task-3
    /// call sites — `BookwormSprites.frames(for:)` already bakes every overlay
    /// (R2), so new callers pass none.
    static func image(grid: PixelGrid, overlays: [PixelGrid] = [], pointSize: CGFloat) -> NSImage {
        let merged = overlays.reduce(grid) { BookwormSprites.merge($0, $1) }
        let rows: [[Character]] = (0..<gridSize).map { r in
            r < merged.count ? Array(merged[r].padding(toLength: gridSize, withPad: ".", startingAt: 0)) : Array(repeating: ".", count: gridSize)
        }
        let cell = pointSize / CGFloat(gridSize)
        let image = NSImage(size: NSSize(width: pointSize, height: pointSize), flipped: false) { _ in
            guard let ctx = NSGraphicsContext.current else { return false }
            // Hard edges: a pixel is a pixel at every scale.
            ctx.shouldAntialias = false
            ctx.imageInterpolation = .none
            for (r, line) in rows.enumerated() {
                for (c, ch) in line.enumerated() {
                    guard let color = colors[ch] else { continue }   // "." and unknowns stay clear
                    color.setFill()
                    // Grid row 0 is the top; AppKit's origin is bottom-left.
                    let x = CGFloat(c) * cell
                    let y = CGFloat(gridSize - 1 - r) * cell
                    NSBezierPath(rect: NSRect(x: x, y: y, width: cell, height: cell)).fill()
                }
            }
            return true
        }
        image.isTemplate = false
        return image
    }

    // MARK: - Cache (ruling R5: one cache, keyed state|frame|count|stage|size)

    /// Stable key: `caseName`, then the count (clamped to the badge's 99) or
    /// the stage when the state carries one, then frame and size. Two
    /// `.curious` states that differ only in count MUST get different keys
    /// because the count is drawn into the frame.
    static func cacheKey(state: BookwormState, frameIndex: Int, pointSize: CGFloat) -> String {
        "\(state.spriteKey)|\(frameIndex)|\(Int(pointSize))"
    }

    /// Lock-guarded rather than actor-isolated so BOTH consumers can call it
    /// from where they already are: `MenuBarManager` (main actor) and
    /// `BookwormView`'s `TimelineView` content closure, whose isolation the
    /// SDK does not spell out. An `NSLock` around a dictionary is the whole
    /// cost; `NSImage` is immutable once built.
    private static let lock = NSLock()
    nonisolated(unsafe) private static var cache: [String: NSImage] = [:]

    /// The rendered frame for `state`, drawn at most once per key. A timer
    /// tick is a dictionary hit, never a rasterization — that is what keeps
    /// the always-moving menu bar at negligible CPU.
    static func cachedImage(state: BookwormState, frameIndex: Int, pointSize: CGFloat) -> NSImage {
        let (frames, _) = BookwormSprites.frames(for: state)
        let idx = frames.isEmpty ? 0 : ((frameIndex % frames.count) + frames.count) % frames.count
        let key = cacheKey(state: state, frameIndex: idx, pointSize: pointSize)
        lock.lock()
        let hit = cache[key]
        lock.unlock()
        if let hit { return hit }
        let grid = frames.isEmpty ? BookwormSprites.awakeBase : frames[idx]
        let img = image(grid: grid, pointSize: pointSize)
        lock.lock()
        // 7 states × ≤ 4 frames × ≤ 99 counts × a few sizes is still small,
        // but bound it so a long-running app can never grow it unboundedly.
        if cache.count > 512 { cache.removeAll() }
        // A racing second render of the same key just wins by being last; both
        // images are pixel-identical, so nothing observable depends on which.
        cache[key] = img
        lock.unlock()
        return img
    }
}
