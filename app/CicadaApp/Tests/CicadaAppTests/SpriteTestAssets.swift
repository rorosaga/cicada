import AppKit
import XCTest
@testable import CicadaApp

/// Real-sheet acceptance helpers. Every required resource is unwrapped, never skipped when missing.
enum SpriteTestAssets {
    static let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    static let art = root.appendingPathComponent("Art/sprites/bookworm-2026-10-01")
    static let sheetNames = BookwormArt.states.map { BookwormArt.sheetName($0, .room) } + ["bookworm-small"]
        + ["room-backdrop", "room-window", "room-weather", "room-lamp", "room-fly", "room-beanbag", "room-plant", "room-mug", "room-spines"]

    static func url(_ name: String, ext: String) throws -> URL {
        try XCTUnwrap(Bundle.cicadaResources.cicadaResource(name, ext: ext, in: "sprites"), "Missing sheet resource: \(name).\(ext)")
    }
    static func sheet(_ name: String) throws -> SpriteSheet {
        try XCTUnwrap(SpriteSheets.sheet(named: name), "Missing or invalid sheet: \(name)")
    }
    static func data(_ name: String) throws -> AsepriteSheetData {
        try JSONDecoder().decode(AsepriteSheetData.self, from: Data(contentsOf: url(name, ext: "json")))
    }
    static func clip(_ sheet: SpriteSheet, _ tag: String) throws -> SpriteClip {
        try XCTUnwrap(sheet.clip(tag), "\(sheet.name) missing tag \(tag)")
    }
    static func artData(_ name: String) throws -> Data {
        try XCTUnwrap(try? Data(contentsOf: art.appendingPathComponent(name)), "Missing or unreadable art sidecar: \(name)")
    }

    struct Palette: Decodable {
        struct Entry: Decodable { let key, hex, group, role: String }
        let colors: [Entry]
        var roles: [UInt32: String] {
            colors.reduce(into: [:]) { result, color in
                if let rgb = UInt32(color.hex.dropFirst(), radix: 16) { result[rgb] = color.role }
            }
        }
        func rgb(_ key: String) throws -> UInt32 {
            let color = try XCTUnwrap(colors.first { $0.key == key }, "palette has no key \(key)")
            return try XCTUnwrap(UInt32(color.hex.dropFirst(), radix: 16), "bad palette colour")
        }
    }
    static func palette() throws -> Palette {
        try JSONDecoder().decode(Palette.self, from: artData("palette.json"))
    }

    struct Cell: Hashable { let x, y: Int }
    struct Pixel: Equatable { let rgb: UInt32; let alpha: Int }
    struct Plane {
        let w, h: Int
        let pixels: [Pixel]
        init(_ image: CGImage) {
            // AppKit may rasterize an NSImage to a floating-point bitmap. Read a fixed 8-bit surface,
            // while leaving the exported PNG's raw 8-bit palette samples untouched.
            let original = NSBitmapImageRep(cgImage: image)
            let rep: NSBitmapImageRep
            if original.bitsPerSample == 8 && !original.bitmapFormat.contains(.floatingPointSamples) {
                rep = original
            } else {
                let context = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                    bytesPerRow: image.width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
                rep = NSBitmapImageRep(cgImage: context.makeImage()!)
            }
            w = rep.pixelsWide; h = rep.pixelsHigh
            var out: [Pixel] = []
            out.reserveCapacity(w * h)
            var values = [Int](repeating: 0, count: rep.samplesPerPixel)
            for y in 0..<h { for x in 0..<w {
                rep.getPixel(&values, atX: x, y: y)
                let rgb = UInt32(values[0]) << 16 | UInt32(values[1]) << 8 | UInt32(values[2])
                out.append(.init(rgb: rgb, alpha: rep.hasAlpha ? values[3] : 255))
            } }
            pixels = out
        }
        func at(_ x: Int, _ y: Int) -> Pixel { pixels[y * w + x] }
        func cells(where predicate: (Pixel) -> Bool) -> Set<Cell> {
            Set(pixels.enumerated().compactMap { predicate($0.element) ? Cell(x: $0.offset % w, y: $0.offset / w) : nil })
        }
        var ink: Set<Cell> { cells { $0.alpha > 0 } }
        func count(_ rgb: UInt32) -> Int { pixels.filter { $0.alpha > 0 && $0.rgb == rgb }.count }
    }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var planes: [String: Plane] = [:]
    static func plane(_ sheet: SpriteSheet, frame: Int) throws -> Plane {
        let key = "\(sheet.name)|\(sheet.rectIndex[frame])"
        lock.lock(); defer { lock.unlock() }
        if let hit = planes[key] { return hit }
        let plane = Plane(try XCTUnwrap(sheet.frameImage(frame), "\(sheet.name) frame \(frame)"))
        planes[key] = plane
        return plane
    }
    static func bounds(_ cells: Set<Cell>) -> CGRect {
        guard let x0 = cells.map(\.x).min(), let x1 = cells.map(\.x).max(),
              let y0 = cells.map(\.y).min(), let y1 = cells.map(\.y).max() else { return .null }
        return CGRect(x: x0, y: y0, width: x1 - x0 + 1, height: y1 - y0 + 1)
    }
    static func scene(_ cells: Set<Cell>, x: Int, y: Int, h: Int) -> Set<Cell> {
        Set(cells.map { Cell(x: x + $0.x, y: y + h - 1 - $0.y) })
    }
    static func unionInk(_ sheet: SpriteSheet, tags: Set<String>? = nil) throws -> Set<Cell> {
        let clips = try (tags ?? Set(sheet.tags.keys)).map { try clip(sheet, $0) }
        var ink = Set<Cell>()
        for frame in Set(clips.flatMap(\.order)) { ink.formUnion(try plane(sheet, frame: frame).ink) }
        return ink
    }

    static func assertCaps(_ sheet: SpriteSheet, file: StaticString = #filePath, line: UInt = #line) {
        for clip in sheet.tags.values {
            for seconds in clip.seconds {
                XCTAssertGreaterThanOrEqual(seconds, CicadaMotion.spriteFrameMin, "\(sheet.name)/\(clip.tag)", file: file, line: line)
                XCTAssertLessThanOrEqual(seconds, CicadaMotion.spriteFrameMax, "\(sheet.name)/\(clip.tag)", file: file, line: line)
            }
            if clip.order.count == 1 || sheet.name == "room-spines" {
                XCTAssertTrue(clip.seconds.allSatisfy { $0 == 1 }, "\(sheet.name)/\(clip.tag)", file: file, line: line)
            } else if clip.tag == "intro" || clip.tag == "outro" {
                XCTAssertLessThanOrEqual(clip.total, CicadaMotion.spriteTransitionMax, file: file, line: line)
            } else if BookwormReaction.allCases.contains(where: { clip.tag.hasPrefix($0.rawValue + ".") }) {
                XCTAssertLessThanOrEqual(clip.total, clip.tag.hasPrefix("perk.") ? CicadaMotion.spritePerkMax : CicadaMotion.spriteBeatMax, file: file, line: line)
            } else {
                XCTAssertGreaterThanOrEqual(clip.total, CicadaMotion.spriteLoopMin, file: file, line: line)
                XCTAssertLessThanOrEqual(clip.total, CicadaMotion.spriteLoopMax, file: file, line: line)
            }
        }
    }
}
