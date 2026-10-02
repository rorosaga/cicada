import AppKit

/// The small mascot's own cache (P13). Room frames use each sheet's crop cache directly.
enum BookwormRenderer {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var cache: [String: NSImage] = [:]
    static let maxCacheEntries = 1024
    private static let colors = PixelRenderer.nsColors(BookwormPalette.colors)

    static func cacheKey(state: BookwormState, rectIndex: Int, pointSize: CGFloat,
                         mascot: Mascot = MascotPreference.selected()) -> String {
        "small|\(mascot.id)|\(state.spriteKey)|\(rectIndex)|\(Int(pointSize))"
    }

    static func smallImage(state: BookwormState, frameStep: Int, pointSize: CGFloat,
                           mascot: Mascot = MascotPreference.selected()) -> NSImage {
        let pair = BookwormArt.clip(state, look: .idle, set: .small, mascot: mascot)
        let count = pair?.1.order.count ?? 1
        let step = ((frameStep % count) + count) % count
        let frame = pair?.1.order[step] ?? 0
        let rect = pair?.0.rectIndex[frame] ?? 0
        let key = cacheKey(state: state, rectIndex: rect, pointSize: pointSize, mascot: mascot)
        lock.lock()
        defer { lock.unlock() }
        if let hit = cache[key] { return hit }
        let crop = pair?.0.frameImage(frame)
        let image = composite(crop: crop, overlay: BookwormOverlays.grid(for: state), pointSize: pointSize)
        image.accessibilityDescription = "Cicada — \(state.title), \(state.detail)"
        if cache.count > maxCacheEntries { cache.removeAll() }
        cache[key] = image
        return image
    }

    /// Uncached drawing seam, also used to verify nearest-neighbour orientation with synthetic pixels.
    static func composite(crop: CGImage?, overlay grid: PixelGrid, pointSize: CGFloat) -> NSImage {
        let overlay = PixelRenderer.image(grid: grid, gridSize: 18,
                                          pointSize: pointSize, palette: colors)
        let image = NSImage(size: NSSize(width: pointSize, height: pointSize), flipped: false) { bounds in
            guard let context = NSGraphicsContext.current else { return false }
            context.shouldAntialias = false
            context.imageInterpolation = .none
            if let crop {
                context.cgContext.interpolationQuality = .none
                context.cgContext.setShouldAntialias(false)
                context.cgContext.draw(crop, in: bounds)
                overlay.draw(in: bounds)
            }
            return true
        }
        image.isTemplate = false
        return image
    }
}
