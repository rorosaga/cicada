import AppKit
import XCTest
@testable import CicadaApp

final class WindowSpritesTests: XCTestCase {
    static let moods: [BookwormState] = [.sleeping(stage: 2), .digesting, .happy, .reading, .hungry, .error, .awake]

    func testRulingNineForEveryWeatherFrameAndEveryReachableWormFrame() throws {
        let pane = try SpriteTestAssets.sheet("room-weather")
        let frame = try SpriteTestAssets.sheet("room-window")
        let frameMask = SpriteTestAssets.scene(try SpriteTestAssets.unionInk(frame), x: 18, y: 23, h: 38)
        let roles = try SpriteTestAssets.palette().roles
        for weather in WindowWeather.all {
            var hidden = frameMask
            for mood in Self.moods where windowWeather(for: mood) == weather {
                let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(mood, .room))
                var tags = BookwormArt.requiredTags(mood)
                tags.subtract(["intro", "outro"])
                hidden.formUnion(SpriteTestAssets.scene(try SpriteTestAssets.unionInk(sheet, tags: tags), x: 36, y: 9, h: 48))
            }
            if [.night, .dawn, .clear, .fair, .overcast].contains(weather) {
                let sleeping = try SpriteTestAssets.sheet("bookworm-sleeping")
                let tag = weather == .night ? "intro" : "outro"
                hidden.formUnion(SpriteTestAssets.scene(try SpriteTestAssets.unionInk(sleeping, tags: [tag]), x: 36, y: 9, h: 48))
            }
            let clip = try SpriteTestAssets.clip(pane, weather.rawValue)
            for (step, index) in clip.order.enumerated() {
                let plane = try SpriteTestAssets.plane(pane, frame: index)
                let celestial = SpriteTestAssets.scene(plane.cells { $0.alpha > 0 && (roles[$0.rgb]?.hasPrefix("celestial.") ?? false) }, x: 20, y: 27, h: 32)
                let cloud = SpriteTestAssets.scene(plane.cells { $0.alpha > 0 && (roles[$0.rgb]?.hasPrefix("cloud.") ?? false) }, x: 20, y: 27, h: 32)
                XCTAssertTrue(celestial.isDisjoint(with: hidden), "\(weather.rawValue) frame \(step): celestial ink hidden")
                XCTAssertGreaterThanOrEqual(cloud.subtracting(hidden).count * 2, cloud.count, "\(weather.rawValue) frame \(step): cloud hidden")
            }
        }
    }

    func testSevenDistinctWeatherKeyFrames() throws {
        let sheet = try SpriteTestAssets.sheet("room-weather")
        let keys = try WindowWeather.all.map { weather -> Data in
            let plane = try SpriteTestAssets.plane(sheet, frame: SpriteTestAssets.clip(sheet, weather.rawValue).order[0])
            return Data(plane.pixels.flatMap { [UInt8(($0.rgb >> 16) & 255), UInt8(($0.rgb >> 8) & 255), UInt8($0.rgb & 255), UInt8($0.alpha)] })
        }
        XCTAssertEqual(Set(keys).count, 7)
    }

    /// Always render and validate all composites. The flag controls writing only, never sheet acceptance.
    func testRoomCompositesAtUnitAndMaximumZoom() throws {
        let write = ProcessInfo.processInfo.environment["CICADA_WRITE_COMPOSITES"] == "1"
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-sprite-composites")
        if write { try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true) }
        for scale in [1.0, 1.4] {
            let layout = deskSceneLayout(uiScale: scale)
            for mood in Self.moods { for lit in [false, true] {
                let width = Int(layout.size.width), height = Int(layout.size.height)
                let context = try XCTUnwrap(CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                    bytesPerRow: width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
                context.interpolationQuality = .none
                context.setShouldAntialias(false)
                for layer in layout.layers {
                    if let art = RoomArt.tag(layer.prop, lampLit: lit, weather: windowWeather(for: mood)) {
                        let sheet = try SpriteTestAssets.sheet(art.sheet)
                        let image = try XCTUnwrap(sheet.frameImage(SpriteTestAssets.clip(sheet, art.tag).order[0]))
                        context.draw(image, in: CGRect(x: CGFloat(layer.cellX) * layout.cell, y: CGFloat(layer.cellY) * layout.cell,
                            width: CGFloat(layer.w) * layout.cell, height: CGFloat(layer.h) * layout.cell))
                    }
                }
                let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(mood, .room))
                let image = try XCTUnwrap(sheet.frameImage(SpriteTestAssets.clip(sheet, "idle").order[0]))
                context.draw(image, in: CGRect(origin: layout.wormOrigin, size: CGSize(width: 64 * layout.cell, height: 48 * layout.cell)))
                let composite = try XCTUnwrap(context.makeImage())
                XCTAssertEqual(composite.width, width); XCTAssertEqual(composite.height, height)
                if write {
                    let bytes = try XCTUnwrap(NSBitmapImageRep(cgImage: composite).representation(using: .png, properties: [:]))
                    try bytes.write(to: dir.appendingPathComponent("\(mood.caseName)-\(lit ? "lit" : "dark")-\(scale).png"))
                }
            } }
        }
    }
}
