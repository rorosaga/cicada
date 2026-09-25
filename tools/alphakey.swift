import AppKit

// alphakey <in.png> <out.png> <light|dark> — recut a two-tone raster to alpha.
//
// Why this exists (R5 / R-L2): two committed marks are fine art on the wrong
// ground — `x.png` is white-on-opaque-black and `codex.png` is
// black-on-opaque-white, both favicon-service artefacts. Inside a rounded card
// they render as an opaque square with the vendor's mark punched out of it.
// Neither has a usable upstream SVG (R-L3), so the fix is to key the ground out
// of the raster we already ship rather than to fetch something else.
//
// The transform is exact, not a threshold: for a dark mark on a light ground
// (`light`) write `alpha = 1 - luma, rgb = 0`; for a light mark on a dark
// ground (`dark`) write `alpha = luma, rgb = 255`. On an anti-aliased edge that
// reproduces the coverage the rasterizer computed, so no fringe is left behind
// — a threshold would leave one.
//
// A recut is a ONE-TIME act, not a step the pipeline repeats (R5): the moment
// the keyed file is committed the opaque original exists only in git history,
// and `scripts/fetch-logos.sh` verifies a `recut` asset's sha and nothing more.
// This tool enforces that by refusing (exit 3) a source that already carries a
// non-opaque pixel — keying an already-keyed file would eat the mark.
//
// Nominative use only: this is not a restyle. The mark's own pixels are what
// decide the alpha; nothing is recoloured beyond dropping a ground that was
// never part of the mark.

let args = CommandLine.arguments
guard args.count == 4, args[3] == "light" || args[3] == "dark" else {
    fputs("usage: alphakey <in.png> <out.png> <light|dark>\n", stderr)
    fputs("  light = a dark mark on a light ground; dark = a light mark on a dark ground\n", stderr)
    exit(2)
}
let inPath = args[1], outPath = args[2], ground = args[3]

guard let data = FileManager.default.contents(atPath: inPath),
      let src = NSBitmapImageRep(data: data) else {
    fputs("decode failed: \(inPath)\n", stderr)
    exit(1)
}

// Read the source through a canonical deviceRGB / 8-bit / non-premultiplied
// raster so the per-pixel math is exact. The redraw is lossless for the sources
// this tool accepts: they are fully opaque (enforced below), and on an opaque
// source premultiplied and straight bytes are the same numbers.
let w = src.pixelsWide, h = src.pixelsHigh
guard w > 0, h > 0 else { fputs("empty raster: \(inPath)\n", stderr); exit(1) }
guard let scratch = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: w * 4, bitsPerPixel: 32
) else { fputs("alloc failed\n", stderr); exit(1) }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: scratch)
NSGraphicsContext.current?.imageInterpolation = .none
// `.copy` and not `.sourceOver`: the source's own alpha must survive the read,
// otherwise the "already keyed" guard below could never see a transparent pixel.
src.draw(in: NSRect(x: 0, y: 0, width: CGFloat(w), height: CGFloat(h)),
         from: .zero, operation: .copy, fraction: 1.0,
         respectFlipped: false, hints: [.interpolation: NSNumber(value: NSImageInterpolation.none.rawValue)])
NSGraphicsContext.restoreGraphicsState()
guard let inBytes = scratch.bitmapData else { fputs("read failed\n", stderr); exit(1) }
let inRow = scratch.bytesPerRow

guard let out = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bitmapFormat: .alphaNonpremultiplied,
    bytesPerRow: w * 4, bitsPerPixel: 32
) else { fputs("alloc failed\n", stderr); exit(1) }
guard let outBytes = out.bitmapData else { fputs("alloc failed\n", stderr); exit(1) }
let outRow = out.bytesPerRow

let mark: UInt8 = (ground == "dark") ? 255 : 0
for y in 0..<h {
    for x in 0..<w {
        let i = y * inRow + x * 4
        let a = inBytes[i + 3]
        if a != 255 {
            fputs("refusing \(inPath): pixel (\(x),\(y)) is already transparent — "
                  + "a keyed mark is never keyed twice (R5)\n", stderr)
            exit(3)
        }
        // Rec. 709 luma, the same weighting the eye applies, so a coloured-but-
        // two-tone mark still keys where a naive average would band.
        let luma = (2126 * Int(inBytes[i]) + 7152 * Int(inBytes[i + 1]) + 722 * Int(inBytes[i + 2])) / 10000
        let alpha = (ground == "dark") ? luma : 255 - luma
        let o = y * outRow + x * 4
        outBytes[o] = mark
        outBytes[o + 1] = mark
        outBytes[o + 2] = mark
        outBytes[o + 3] = UInt8(clamping: alpha)
    }
}

guard let png = out.representation(using: .png, properties: [:]) else {
    fputs("encode failed\n", stderr)
    exit(1)
}
try png.write(to: URL(fileURLWithPath: outPath))
FileHandle.standardError.write(
    "ok keyed \(w)x\(h) on a \(ground) ground → \(outPath)\n".data(using: .utf8)!)
