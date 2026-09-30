// Builds Cicada's macOS app icon from the book-and-glasses pixel art.
//
//   swift app/CicadaApp/Art/AppIcon/make-icon.swift            (from the repository root)
//
// Input: docs/design/cicada-icon/v4/cicada-book-glasses-128.png — the 128 px export of the Aseprite source
// (docs/design/cicada-icon/v4/cicada-book-glasses-128.aseprite). Output, beside this file: Cicada-1024.png (the
// preview) and Cicada.icns (the ten sizes macOS asks for, packed by iconutil from a temporary iconset). bundle.sh
// copies Cicada.icns into the app.
//
// The plate is Apple's app-icon grid: a 824 pt continuous-corner square centred on a 1024 canvas with a soft shadow,
// filled with a near-black graphite. The art keeps its pixels: where the size puts a whole number of icon pixels on
// each art pixel (1024 px: 5) it is drawn with nearest-neighbour and no smoothing; at every other size it is first
// blown up with nearest-neighbour to the next whole multiple and then area-averaged down, so edges stay hard-ish and
// never ring.
import AppKit
import CoreGraphics
import Foundation

let here = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
let root = here.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
let source = root.appendingPathComponent("docs/design/cicada-icon/v4/cicada-book-glasses-128.png")

guard let art = NSImage(contentsOf: source)?.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fatalError("cannot read \(source.path)")
}

/// The art's opaque bounding box, in the 128 px source's pixels (y down).
func opaqueBounds(_ image: CGImage) -> CGRect {
    let w = image.width, h = image.height
    var data = [UInt8](repeating: 0, count: w * h * 4)
    let ctx = CGContext(data: &data, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                        space: CGColorSpace(name: CGColorSpace.sRGB)!,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
    var minX = w, minY = h, maxX = -1, maxY = -1
    for y in 0..<h { for x in 0..<w where data[(y * w + x) * 4 + 3] > 0 {
        minX = min(minX, x); maxX = max(maxX, x); minY = min(minY, y); maxY = max(maxY, y)
    } }
    return CGRect(x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1)
}

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

let box = opaqueBounds(art)
let cropped = art.cropping(to: box)!   // CGImage cropping is in the image's own (y-down) pixel space

func render(size: Int) -> CGImage {
    let s = CGFloat(size) / 1024
    let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                        space: CGColorSpace(name: CGColorSpace.sRGB)!,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    let plateRect = CGRect(x: 100 * s, y: 100 * s, width: 824 * s, height: 824 * s)
    let plate = platePath(in: plateRect)

    // Soft shadow under the plate (Apple's template: a short, diffuse drop).
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -10 * s), blur: 28 * s,
                  color: CGColor(srgbRed: 0, green: 0, blue: 0, alpha: 0.35))
    ctx.addPath(plate); ctx.setFillColor(CGColor(srgbRed: 0.08, green: 0.08, blue: 0.09, alpha: 1)); ctx.fillPath()
    ctx.restoreGState()

    // The plate: a near-black graphite, a touch lighter at the top.
    ctx.saveGState()
    ctx.addPath(plate); ctx.clip()
    let gradient = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB)!, colors: [
        CGColor(srgbRed: 0.125, green: 0.129, blue: 0.141, alpha: 1),   // #202124
        CGColor(srgbRed: 0.078, green: 0.082, blue: 0.090, alpha: 1),   // #141517
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

    // The art: 6 × its 128 px pixels on the 1024 canvas, centred on the plate (a hair below centre, where the eye
    // puts the middle of a resting object).
    let scale = 6 * s
    let w = box.width * scale, h = box.height * scale
    let artRect = CGRect(x: (CGFloat(size) - w) / 2, y: (CGFloat(size) - h) / 2 - 12 * s, width: w, height: h)
    if scale == scale.rounded() {
        ctx.interpolationQuality = .none
        ctx.draw(cropped, in: artRect.integral)
    } else {
        ctx.interpolationQuality = .high
        ctx.draw(nearest(cropped, by: Int(max(1, scale.rounded(.up)))), in: artRect)
    }
    return ctx.makeImage()!
}

/// The art blown up by a whole number with nearest-neighbour, so a smooth downsample of it averages whole pixels.
func nearest(_ image: CGImage, by factor: Int) -> CGImage {
    if factor == 1 { return image }
    let ctx = CGContext(data: nil, width: image.width * factor, height: image.height * factor, bitsPerComponent: 8,
                        bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.interpolationQuality = .none
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: ctx.width, height: ctx.height))
    return ctx.makeImage()!
}

func writePNG(_ image: CGImage, to url: URL) {
    let rep = NSBitmapImageRep(cgImage: image)
    try! rep.representation(using: .png, properties: [:])!.write(to: url)
}

let iconset = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-\(UUID().uuidString).iconset")
try! FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
for (points, scale) in [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)] {
    let name = scale == 1 ? "icon_\(points)x\(points).png" : "icon_\(points)x\(points)@2x.png"
    writePNG(render(size: points * scale), to: iconset.appendingPathComponent(name))
}
writePNG(render(size: 1024), to: here.appendingPathComponent("Cicada-1024.png"))

let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["--convert", "icns", "--output", here.appendingPathComponent("Cicada.icns").path, iconset.path]
try! iconutil.run(); iconutil.waitUntilExit()
precondition(iconutil.terminationStatus == 0, "iconutil failed")
try? FileManager.default.removeItem(at: iconset)
print("wrote \(here.appendingPathComponent("Cicada.icns").path)")
