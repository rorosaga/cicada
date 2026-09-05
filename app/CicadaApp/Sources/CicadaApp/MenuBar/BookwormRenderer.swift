import AppKit

/// The mascot's face on `PixelRenderer` — four thin forwarders that bind the
/// generalized rasterizer to the worm's 24-cell grid and nine-colour palette,
/// plus the mascot's own state-derived cache key and cache.
///
/// It used to BE the rasterizer; G125 v3 Task 2 lifted the body into
/// `PixelRenderer` so the Sleep page's study room could draw its props through
/// the same code path instead of a second, subtly different copy. Every call
/// site and every assertion in the four `Bookworm*Tests` files is unchanged —
/// that they pass unmodified is what proves this forwards rather than
/// re-implements.
///
/// Colour, not template (G107): a template image is tinted uniformly by the
/// system and so cannot show mood; the 1-px `o` outline is what makes the
/// silhouette survive both the light and the dark menu bar without tinting.
/// Page consumers request sizes that are multiples of 24 so cells are integer
/// points (ruling R3); the menu bar runs 18 pt.
enum BookwormRenderer {
    static let gridSize = BookwormSprites.size

    /// Snaps a scaled point size back onto a multiple of 24 (G130 R6) — the
    /// `gridSize: 24` case of `PixelRenderer.snappedPointSize`. Kept as its
    /// own entry point because `BookwormView` calls it on every body eval and
    /// should not have to know the mascot's grid size to do so.
    static func snappedPointSize(_ pointSize: CGFloat) -> CGFloat {
        PixelRenderer.snappedPointSize(pointSize, gridSize: gridSize)
    }

    private static let colors: [Character: NSColor] = PixelRenderer.nsColors(BookwormPalette.colors)

    /// Render one grid at `pointSize` × `pointSize` in the mascot's palette.
    /// The grid is drawn as given: `BookwormSprites.frames(for:)` already
    /// bakes every overlay (badge, stage dots — ruling R2), so there is no
    /// merge seam here.
    static func image(grid: PixelGrid, pointSize: CGFloat) -> NSImage {
        PixelRenderer.image(grid: grid, gridSize: gridSize, pointSize: pointSize, palette: colors)
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
    ///
    /// This stays the mascot's OWN cache and is deliberately not
    /// `PixelRenderer.sceneCache` (P13): this one wipes wholesale past 512
    /// entries, and a page rendering scene layers through a shared dictionary
    /// would make the always-animating worm collateral damage of every wipe.
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
