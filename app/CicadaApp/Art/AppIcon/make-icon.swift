// Builds Cicada's macOS app icon from the menu-bar bookworm (owner 2026-10-26, provisional: "for now").
//
//   swift app/CicadaApp/Art/AppIcon/make-icon.swift            (from the repository root)
//   swift app/CicadaApp/Art/AppIcon/make-icon.swift --preview <out.png>
//
// Input: the menu bar's own sprite sheet, app/CicadaApp/Sources/CicadaApp/Resources/sprites/bookworm-small.png (18 × 18
// frames, exported from Art/sprites/bookworm-2026-10-01/menubar.aseprite), and its JSON: the key frame of the `awake`
// tag — the worm the status item shows at rest, without its code-drawn badge (a number on a Dock icon would read as
// a count). Output, beside this file: Cicada-1024.png (the preview, also copied to the plugin's icon) and Cicada.icns
// (the ten sizes macOS asks for, packed by iconutil from a temporary iconset). bundle.sh copies Cicada.icns into the
// app, so `make app`, `make install-app` and the release build all carry it.
//
// The plate is Apple's macOS app-icon grid: an 824 px continuous-corner square centred on a 1024 canvas (100 px of
// margin for the shadow) with a soft drop shadow, filled with graphite from DESIGN_RULES §3.1's dark column — `bgButton`
// #232427 at the top to `bgPane` #141517 at the bottom — with a faint light edge.
//
// The art keeps its pixels. The canvas is 32 art-pixel units wide, the worm's 18 × 16 opaque box sits at units (7, 8),
// so at every size from 32 px up each art pixel is a whole (size / 32) square drawn with nearest-neighbour and lands on
// whole device pixels: 32 px → 1, 64 → 2, 128 → 4, 256 → 8, 512 → 16, 1024 → 32. The worm spans 56 % of the canvas,
// 70 % of the plate — inside the grid's glyph area. 16 px (16@1x, only drawn on a non-Retina display) cannot hold 18
// art pixels at a whole factor, so it gets its own hand-drawn 12 × 12 worm in the same two colours (`smallRows`),
// placed on whole pixels — still hard-edged, never area-averaged.
import AppKit
import CoreGraphics
import Foundation

let here = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
let root = here.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
let sprites = root.appendingPathComponent("app/CicadaApp/Sources/CicadaApp/Resources/sprites")
let sheetURL = sprites.appendingPathComponent("bookworm-small.png")
let jsonURL = sprites.appendingPathComponent("bookworm-small.json")

let srgb = CGColorSpace(name: CGColorSpace.sRGB)!

guard let sheet = NSImage(contentsOf: sheetURL)?.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fatalError("cannot read \(sheetURL.path)")
}

/// The `awake` tag's first frame rectangle, in the sheet's own (y-down) pixels.
func awakeKeyFrame() -> CGRect {
    let data = try! Data(contentsOf: jsonURL)
    let json = try! JSONSerialization.jsonObject(with: data) as! [String: Any]
    let frames = json["frames"] as! [[String: Any]]
    let tags = (json["meta"] as! [String: Any])["frameTags"] as! [[String: Any]]
    let awake = tags.first { ($0["name"] as? String) == "awake" }!
    let rect = frames[awake["from"] as! Int]["frame"] as! [String: Int]
    return CGRect(x: rect["x"]!, y: rect["y"]!, width: rect["w"]!, height: rect["h"]!)
}

/// RGBA pixels (straight alpha, y down) of an image.
func pixels(_ image: CGImage) -> [UInt8] {
    let w = image.width, h = image.height
    var data = [UInt8](repeating: 0, count: w * h * 4)
    let ctx = CGContext(data: &data, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: srgb,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
    return data
}

func makeImage(from data: [UInt8], width: Int, height: Int) -> CGImage {
    var copy = data
    let ctx = CGContext(data: &copy, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                        space: srgb, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    return ctx.makeImage()!
}

/// The art's opaque bounding box, in its own pixels (y down).
func opaqueBounds(_ image: CGImage) -> CGRect {
    let w = image.width, h = image.height, data = pixels(image)
    var minX = w, minY = h, maxX = -1, maxY = -1
    for y in 0..<h { for x in 0..<w where data[(y * w + x) * 4 + 3] > 0 {
        minX = min(minX, x); maxX = max(maxX, x); minY = min(minY, y); maxY = max(maxY, y)
    } }
    return CGRect(x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1)
}

let frame = sheet.cropping(to: awakeKeyFrame())!
let art = frame.cropping(to: opaqueBounds(frame))!   // 18 × 16
precondition(art.width == 18 && art.height == 16, "the menu-bar worm's opaque box changed (\(art.width) × \(art.height)); recheck the grid")

/// The 16 px worm, drawn by hand at 12 × 12 in the art's own two colours (`#` its outline, `a` its body, both read
/// from the sheet): the head over the bridge, two round lenses with a dark centre, the tail curling down to the right.
/// A nearest-neighbour sample of the 18 px art dropped the left lens and the tail, so this is its own drawing.
let smallRows = [
    "....#####...",
    "...#aaaaa#..",
    "...#aaaaa#..",
    ".###a#####..",
    "#aaa#a#aaa#.",
    "#a#a#a#a#a#.",
    "#aaa#a#aaa#.",
    ".###.#a###..",
    ".....#aa#...",
    "......#aa#..",
    ".......#aa#.",
    "........##..",
]

func smallArt(from art: CGImage) -> CGImage {
    let src = pixels(art)
    func colour(_ x: Int, _ y: Int) -> [UInt8] { Array(src[((y * art.width) + x) * 4 ..< ((y * art.width) + x) * 4 + 4]) }
    let outline = colour(8, 0), body = colour(1, 5)   // the worm's own outline and body pixels
    let cols = smallRows[0].count, rows = smallRows.count
    var out = [UInt8](repeating: 0, count: cols * rows * 4)
    for (y, row) in smallRows.enumerated() {
        precondition(row.count == cols, "smallRows must be rectangular")
        for (x, ch) in row.enumerated() where ch != "." {
            out.replaceSubrange((y * cols + x) * 4 ..< (y * cols + x) * 4 + 4, with: ch == "#" ? outline : body)
        }
    }
    return makeImage(from: out, width: cols, height: rows)
}

let small = smallArt(from: art)

/// Apple's app-icon plate: a superellipse (n = 5) close to the system's continuous corners.
func platePath(in rect: CGRect) -> CGPath {
    let path = CGMutablePath()
    let n = 5.0, a = rect.width / 2, b = rect.height / 2, cx = rect.midX, cy = rect.midY
    let steps = 720
    for i in 0...steps {
        let t = Double(i) / Double(steps) * 2 * .pi
        let c = cos(t), s = sin(t)
        let x = cx + a * copysign(pow(abs(c), 2 / n), c)
        let y = cy + b * copysign(pow(abs(s), 2 / n), s)
        if i == 0 { path.move(to: CGPoint(x: x, y: y)) } else { path.addLine(to: CGPoint(x: x, y: y)) }
    }
    path.closeSubpath()
    return path
}

func render(size: Int) -> CGImage {
    let s = CGFloat(size) / 1024
    let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0, space: srgb,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    let plateRect = CGRect(x: 100 * s, y: 100 * s, width: 824 * s, height: 824 * s)
    let plate = platePath(in: plateRect)

    // Soft shadow under the plate (Apple's template: a short, diffuse drop).
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -10 * s), blur: 28 * s,
                  color: CGColor(srgbRed: 0, green: 0, blue: 0, alpha: 0.35))
    ctx.addPath(plate); ctx.setFillColor(CGColor(srgbRed: 0.078, green: 0.082, blue: 0.090, alpha: 1)); ctx.fillPath()
    ctx.restoreGState()

    // The plate: graphite, `bgButton` at the top to `bgPane` at the bottom (DESIGN_RULES §3.1, dark column).
    ctx.saveGState()
    ctx.addPath(plate); ctx.clip()
    let gradient = CGGradient(colorsSpace: srgb, colors: [
        CGColor(srgbRed: 0x23 / 255.0, green: 0x24 / 255.0, blue: 0x27 / 255.0, alpha: 1),   // bgButton #232427
        CGColor(srgbRed: 0x14 / 255.0, green: 0x15 / 255.0, blue: 0x17 / 255.0, alpha: 1),   // bgPane   #141517
    ] as CFArray, locations: [0, 1])!
    ctx.drawLinearGradient(gradient, start: CGPoint(x: 0, y: plateRect.maxY), end: CGPoint(x: 0, y: plateRect.minY),
                           options: [])
    ctx.restoreGState()

    // A hairline of light on the plate's edge, as every macOS icon has.
    ctx.saveGState()
    ctx.addPath(plate); ctx.clip()
    ctx.addPath(plate); ctx.setStrokeColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 0.07))
    ctx.setLineWidth(max(1, 4 * s)); ctx.strokePath()
    ctx.restoreGState()

    // The worm, nearest-neighbour on whole device pixels (CG's origin is bottom-left, so y counts from the bottom).
    ctx.interpolationQuality = .none
    if size % 32 == 0 {
        let unit = size / 32
        ctx.draw(art, in: CGRect(x: 7 * unit, y: size - (8 + 16) * unit, width: 18 * unit, height: 16 * unit))
    } else {
        precondition(size == 16, "only 16 px is drawn off the 32-unit grid")
        ctx.draw(small, in: CGRect(x: 2, y: 16 - 2 - 12, width: 12, height: 12))
    }
    return ctx.makeImage()!
}

func writePNG(_ image: CGImage, to url: URL) {
    let rep = NSBitmapImageRep(cgImage: image)
    try! rep.representation(using: .png, properties: [:])!.write(to: url)
}

/// A review sheet: 512, 128, 32 and 16 px at 1× on a light and a dark desktop, plus 32 and 16 blown up 8× with
/// nearest-neighbour so their pixels can be read.
func preview(to url: URL) {
    let width = 1600, height = 1240
    let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0, space: srgb,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.interpolationQuality = .none
    let backs: [(CGColor, Int)] = [
        (CGColor(srgbRed: 0.93, green: 0.93, blue: 0.94, alpha: 1), height / 2),   // light desktop (top half)
        (CGColor(srgbRed: 0.11, green: 0.12, blue: 0.14, alpha: 1), 0),            // dark desktop (bottom half)
    ]
    for (color, y0) in backs {
        ctx.setFillColor(color); ctx.fill(CGRect(x: 0, y: y0, width: width, height: height / 2))
        var x = 40
        for size in [512, 128, 32, 16] {
            let img = render(size: size)
            ctx.draw(img, in: CGRect(x: x, y: y0 + (height / 2 - size) / 2, width: size, height: size))
            x += size + 40
        }
        for size in [32, 16] {
            let img = render(size: size)
            let big = size * 8
            ctx.draw(img, in: CGRect(x: x, y: y0 + (height / 2 - big) / 2, width: big, height: big))
            x += big + 40
        }
    }
    writePNG(ctx.makeImage()!, to: url)
}

let args = CommandLine.arguments
if let i = args.firstIndex(of: "--preview"), i + 1 < args.count {
    preview(to: URL(fileURLWithPath: args[i + 1]))
    print("wrote \(args[i + 1])")
    exit(0)
}

let iconset = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-\(UUID().uuidString).iconset")
try! FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
for (points, scale) in [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)] {
    let name = scale == 1 ? "icon_\(points)x\(points).png" : "icon_\(points)x\(points)@2x.png"
    writePNG(render(size: points * scale), to: iconset.appendingPathComponent(name))
}
let png1024 = here.appendingPathComponent("Cicada-1024.png")
writePNG(render(size: 1024), to: png1024)
// The Claude Code plugin's icon is a copy of the app icon (docs/architecture/mcp.md, "The Claude Code plugin").
let pluginIcon = root.appendingPathComponent("plugins/cicada/.claude-plugin/icon.png")
try? FileManager.default.removeItem(at: pluginIcon)
try! FileManager.default.copyItem(at: png1024, to: pluginIcon)

let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["--convert", "icns", "--output", here.appendingPathComponent("Cicada.icns").path, iconset.path]
try! iconutil.run(); iconutil.waitUntilExit()
precondition(iconutil.terminationStatus == 0, "iconutil failed")
try? FileManager.default.removeItem(at: iconset)
print("wrote \(here.appendingPathComponent("Cicada.icns").path), \(png1024.path), \(pluginIcon.path)")
