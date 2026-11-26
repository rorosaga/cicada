import AppKit

/// Owner 2026-11-25: a list's bubble wears its source's real mark (DR-52). graph.js cannot read the app's bundle, so each
/// distinct mark (an origin, `OriginIconography.logoName`) is drawn once into a small PNG and handed over as a data URL
/// with the bubbles. A mark with no bundled logo is left out: the bubble then draws its ring and count alone.
@MainActor
enum GraphMarks {
    /// The side of the PNG handed to the canvas, in pixels: a bubble's mark is at most ~40 pt on a Retina screen.
    static let pixels = 64
    private static var cache: [String: String] = [:]

    /// The data URL of each mark that has a bundled logo.
    static func dataURLs(for marks: some Sequence<String>) -> [String: String] {
        var out: [String: String] = [:]
        for mark in Set(marks) {
            if let hit = cache[mark] { out[mark] = hit; continue }
            guard let name = OriginIconography.logoName(for: mark),
                  let image = LogoImage.bundledImageNow(for: name),
                  let url = png(image) else { continue }
            cache[mark] = url
            out[mark] = url
        }
        return out
    }

    private static func png(_ image: NSImage) -> String? {
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                         bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                         colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return nil }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        image.draw(in: NSRect(x: 0, y: 0, width: pixels, height: pixels), from: .zero, operation: .sourceOver, fraction: 1)
        NSGraphicsContext.restoreGraphicsState()
        guard let data = rep.representation(using: .png, properties: [:]) else { return nil }
        return "data:image/png;base64," + data.base64EncodedString()
    }
}
