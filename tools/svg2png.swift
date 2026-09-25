import AppKit

// svg2png <in.svg> <out.png> <size> — square, alpha, aspect-fit, centered.
//
// Why AppKit and not a library: on a stock Mac `rsvg-convert`, ImageMagick,
// Inkscape and cairosvg are all absent and `qlmanage -t` hung past 120 s
// (measured 2026-09-05). `NSImage` decodes SVG natively and builds in ~1.6 s
// with no dependency. Its limit is real and is why R10 exists: it does not
// honour every clipPath/mask/filter, and it reports success anyway — so every
// PNG this writes is opened and eyeballed before it is committed (R-L8).
let a = CommandLine.arguments
guard a.count == 4, let size = Int(a[3]), size > 0 else {
    fputs("usage: svg2png <in.svg> <out.png> <size>\n", stderr); exit(2)
}
guard let src = NSImage(contentsOfFile: a[1]), src.size.width > 0, src.size.height > 0 else {
    fputs("decode failed: \(a[1])\n", stderr); exit(1)
}
let S = CGFloat(size)
let scale = min(S / src.size.width, S / src.size.height)
let w = src.size.width * scale, h = src.size.height * scale
guard let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
) else { fputs("alloc failed\n", stderr); exit(1) }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSGraphicsContext.current?.imageInterpolation = .high
src.draw(in: NSRect(x: (S - w) / 2, y: (S - h) / 2, width: w, height: h),
         from: .zero, operation: .sourceOver, fraction: 1.0)
NSGraphicsContext.restoreGraphicsState()
guard let data = rep.representation(using: .png, properties: [:]) else {
    fputs("encode failed\n", stderr); exit(1)
}
try data.write(to: URL(fileURLWithPath: a[2]))
FileHandle.standardError.write("ok \(size)x\(size) from \(Int(src.size.width))x\(Int(src.size.height))\n".data(using: .utf8)!)
