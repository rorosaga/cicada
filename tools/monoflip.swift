import AppKit

// monoflip <in.png> <out.png> — the `-dark` sibling of a monochrome mark.
//
// This is the ONE transform Cicada ever applies to a vendor mark (R4 / R-L2),
// and it exists for one reason: a black-on-transparent mark disappears on
// `CicadaTheme.surfaceElevated`, which is `#23252E` in dark mode. Inverting the
// luminance of a mark that has no hue is the minimum change that keeps the mark
// legible — it is exact, it is reversible (apply it twice and every pixel comes
// back byte-identical; measured 2026-09-05 on the keyed X mark), and it invents
// nothing the vendor did not draw.
//
// It refuses (exit 3) anything with colour in it. Recolouring a coloured mark
// would be a restyle, and nominative use does not permit one: Chrome, Claude,
// Gemini, RSS and Telegram therefore never get a `-dark` sibling — they are
// legible in both themes as drawn. The guard reads the pixels rather than
// trusting a list, so a mark that turns out to be coloured cannot slip through
// on a hand-maintained allowlist.
//
// Alpha is preserved untouched: the silhouette is the vendor's, only its
// luminance flips.

let args = CommandLine.arguments
guard args.count == 3 else {
    fputs("usage: monoflip <in.png> <out.png>\n", stderr)
    exit(2)
}
let inPath = args[1], outPath = args[2]

guard let data = FileManager.default.contents(atPath: inPath),
      let src = NSBitmapImageRep(data: data) else {
    fputs("decode failed: \(inPath)\n", stderr)
    exit(1)
}

// Canonical deviceRGB / 8-bit raster so the arithmetic below has one known
// layout. It is premultiplied — that is the only format an `NSGraphicsContext`
// will draw into — which the inversion accounts for exactly; see below.
let w = src.pixelsWide, h = src.pixelsHigh
guard w > 0, h > 0 else { fputs("empty raster: \(inPath)\n", stderr); exit(1) }
guard let out = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: w * 4, bitsPerPixel: 32
) else { fputs("alloc failed\n", stderr); exit(1) }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: out)
NSGraphicsContext.current?.imageInterpolation = .none
// `.copy`, so the mark's own alpha survives the read instead of being
// composited against an empty canvas.
src.draw(in: NSRect(x: 0, y: 0, width: CGFloat(w), height: CGFloat(h)),
         from: .zero, operation: .copy, fraction: 1.0,
         respectFlipped: false, hints: [.interpolation: NSNumber(value: NSImageInterpolation.none.rawValue)])
NSGraphicsContext.restoreGraphicsState()
guard let px = out.bitmapData else { fputs("read failed\n", stderr); exit(1) }
let row = out.bytesPerRow

for y in 0..<h {
    for x in 0..<w {
        let i = y * row + x * 4
        let a = Int(px[i + 3])
        if a <= 8 { continue }  // an all-but-invisible edge pixel says nothing about hue
        let r = Int(px[i]), g = Int(px[i + 1]), b = Int(px[i + 2])
        // The bytes are premultiplied, so the stored spread is the straight
        // spread scaled by alpha; compare it back at full scale rather than
        // letting a semi-transparent coloured pixel pass as grey.
        let spread = max(r, max(g, b)) - min(r, min(g, b))
        if spread * 255 > 8 * a {
            fputs("coloured marks are never recoloured (R-L2)\n", stderr)
            fputs("  \(inPath): pixel (\(x),\(y)) has chroma \(spread * 255 / a)/255\n", stderr)
            exit(3)
        }
    }
}

// Invert in premultiplied space: with p = c·α, the premultiplied form of the
// inverted colour (255 − c) is a − p. Integer-exact, and no unpremultiply/
// repremultiply round trip to lose a least-significant bit on soft edges.
for y in 0..<h {
    for x in 0..<w {
        let i = y * row + x * 4
        let a = px[i + 3]
        px[i] = a &- px[i]
        px[i + 1] = a &- px[i + 1]
        px[i + 2] = a &- px[i + 2]
    }
}

guard let png = out.representation(using: .png, properties: [:]) else {
    fputs("encode failed\n", stderr)
    exit(1)
}
try png.write(to: URL(fileURLWithPath: outPath))
FileHandle.standardError.write("ok flipped \(w)x\(h) → \(outPath)\n".data(using: .utf8)!)
