import AppKit
import XCTest
@testable import CicadaApp

/// Real-sheet acceptance helpers. Every required resource is unwrapped, never skipped when missing.
enum SpriteTestAssets {
    static let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    static let art = root.appendingPathComponent("Art/sprites/bookworm-2026-10-01")
    static let dayWormNames = MascotRegistry.all.flatMap { mascot in
        BookwormArt.states.map { BookwormArt.sheetName($0, .room, mascot: mascot) }
    }
    static let nightWormNames = MascotRegistry.all.flatMap { mascot in
        BookwormArt.states.flatMap { state in
            [false, true].map { BookwormArt.sheetName(state, .room, lighting: .dark, lampLit: $0, mascot: mascot) }
        }
    }
    static let roomNames = ["room-backdrop", "room-clock", "room-window", "room-weather", "room-skyfx", "room-lamp", "room-fly", "room-beanbag", "room-plant", "room-mug", "room-spines"]
    static let sheetNames = dayWormNames + nightWormNames + MascotRegistry.all.map(\.menuBarSheet) + roomNames

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
        struct Night: Decodable {
            struct Glyph: Decodable {
                struct Box: Decodable { let x, y, w, h: Int }
                let box: Box
                let colors: [String: String]
            }
            struct Glyphs: Decodable { let question: Glyph }
            let ramps: [String: [String]]
            let glyphs: Glyphs
        }
        struct SceneryColors: Decodable {
            struct Color: Decodable { let id, hex, role: String }
            let ramps: [String: [String: String]]
            let colors: [Color]
        }
        struct Clock: Decodable { let colors: [String: String] }
        let colors: [Entry]
        let night: Night
        let scenery: SceneryColors
        let clock: Clock
        /// Exactly tools/night_palette.py's allowed_colors: authoring colours plus all declared derivatives.
        var declaredHexes: [String] {
            colors.map(\.hex) + night.ramps.values.flatMap { $0 }
                + Array(night.glyphs.question.colors.values)
                + scenery.ramps.values.flatMap { $0.values }
                + scenery.colors.map(\.hex) + Array(clock.colors.values)
        }
        var allowedColors: Set<UInt32> {
            Set(declaredHexes.compactMap { UInt32($0.dropFirst(), radix: 16) })
        }
        var roles: [UInt32: String] {
            var result: [UInt32: String] = [:]
            for color in colors {
                for hex in night.ramps[color.key] ?? [] {
                    if let rgb = UInt32(hex.dropFirst(), radix: 16) { result[rgb] = color.role }
                }
            }
            // Sky tints retain their authoring role, so night/dusk visibility checks inspect actual shapes too.
            for ramp in scenery.ramps.values {
                for color in colors {
                    if let hex = ramp[color.key], let rgb = UInt32(hex.dropFirst(), radix: 16) { result[rgb] = color.role }
                }
            }
            for color in scenery.colors {
                if let rgb = UInt32(color.hex.dropFirst(), radix: 16) { result[rgb] = color.role }
            }
            for color in colors {
                if let rgb = UInt32(color.hex.dropFirst(), radix: 16) { result[rgb] = color.role }
            }
            return result
        }
        func rgb(_ key: String) throws -> UInt32 {
            let color = try XCTUnwrap(colors.first { $0.key == key }, "palette has no key \(key)")
            return try XCTUnwrap(UInt32(color.hex.dropFirst(), radix: 16), "bad palette colour")
        }
        func rgbSet(_ key: String, lighting: RoomLighting) throws -> Set<UInt32> {
            if lighting == .day { return [try rgb(key)] }
            return try Set(XCTUnwrap(night.ramps[key], "missing night ramp \(key)").map {
                try XCTUnwrap(UInt32($0.dropFirst(), radix: 16), "bad night colour")
            })
        }
    }
    static func palette() throws -> Palette {
        try JSONDecoder().decode(Palette.self, from: artData("palette.json"))
    }

    /// The owner's X shapes, including their clear skin perimeter, must survive every error frame.
    static func assertErrorMarks(_ plane: Plane, small: Bool, palette: Palette, lighting: RoomLighting = .day,
                                 file: StaticString = #filePath, line: UInt = #line) throws {
        let k = try palette.rgbSet("K", lighting: lighting), sweat = try palette.rgbSet("S", lighting: lighting)
        let skin = try palette.colors.filter { $0.role.hasPrefix("worm.") && $0.key != "K" }
            .reduce(into: Set<UInt32>()) { $0.formUnion(try palette.rgbSet($1.key, lighting: lighting)) }
        let patterns = small ? [(["K.K", ".K.", "K.K"], CGRect(x: 2, y: 4, width: 4, height: 6)),
                                (["K.K", ".K.", "K.K"], CGRect(x: 10, y: 4, width: 5, height: 6))]
            : [(["K.K", ".K.", ".K.", "K.K"], CGRect(x: 10, y: 16, width: 5, height: 7)),
               (["K....K", ".K..K.", "..KK..", ".K..K.", "K....K"], CGRect(x: 23, y: 17, width: 8, height: 9))]
        for (rows, box) in patterns {
            let chars = rows.map(Array.init), w = rows[0].count, h = rows.count
            var found = false
            for y in Int(box.minY)...(Int(box.maxY) - h) { for x in Int(box.minX)...(Int(box.maxX) - w) {
                let shape = (0..<h).allSatisfy { dy in (0..<w).allSatisfy { dx in
                    let p = plane.at(x + dx, y + dy)
                    return p.alpha > 0 && (chars[dy][dx] == "K" ? k.contains(p.rgb) : skin.contains(p.rgb) && !k.contains(p.rgb))
                } }
                let gap = small || ((-1...w).allSatisfy { dx in
                    !k.contains(plane.at(x + dx, y - 1).rgb) && !k.contains(plane.at(x + dx, y + h).rgb)
                } && (0..<h).allSatisfy { dy in
                    !k.contains(plane.at(x - 1, y + dy).rgb) && !k.contains(plane.at(x + w, y + dy).rgb)
                })
                found = found || (shape && gap)
            } }
            XCTAssertTrue(found, "Missing black X in \(box)", file: file, line: line)
        }
        XCTAssertGreaterThanOrEqual(plane.count(sweat), small ? 2 : 1, "error keeps its drop", file: file, line: line)
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
        func count(_ rgbs: Set<UInt32>) -> Int { pixels.filter { $0.alpha > 0 && rgbs.contains($0.rgb) }.count }
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
            if clip.order.count == 1 || sheet.name == "room-spines" || sheet.name == "room-clock" {
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
