import AppKit
import XCTest
@testable import CicadaApp

final class WindowSpritesTests: XCTestCase {
    static let moods: [BookwormState] = [.sleeping(stage: 2), .digesting, .happy, .reading, .hungry, .error, .awake]

    func testRulingNineForEveryWeatherFrameAndEveryReachableWormFrame() throws {
        let pane = try SpriteTestAssets.sheet("room-weather")
        let roles = try SpriteTestAssets.palette().roles
        for base in WindowWeather.all { for time in SkyPhase.allCases { for lit in [false, true] {
            let scenery = Scenery(base: base, time: time, overlay: nil, source: .chosen)
            let windowArt = try XCTUnwrap(RoomArt.tag(.window, lampLit: lit, scenery: scenery))
            let frame = try SpriteTestAssets.sheet(windowArt.sheet)
            var hidden = SpriteTestAssets.scene(try SpriteTestAssets.unionInk(frame, tags: [windowArt.tag]), x: 18, y: 23, h: 38)
            // All moods are possible in all environments, including both transitions.
            for mood in BookwormArt.states {
                let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(mood, .room, lighting: scenery.lighting, lampLit: lit))
                hidden.formUnion(SpriteTestAssets.scene(try SpriteTestAssets.unionInk(sheet),
                                                       x: DeskScene.wormCell.x, y: DeskScene.wormCell.y, h: 48))
            }
            let clip = try SpriteTestAssets.clip(pane, scenery.weatherTag)
            for (step, index) in clip.order.enumerated() {
                let plane = try SpriteTestAssets.plane(pane, frame: index)
                let celestial = SpriteTestAssets.scene(plane.cells { $0.alpha > 0 && (roles[$0.rgb]?.hasPrefix("celestial.") ?? false) }, x: 20, y: 27, h: 32)
                let cloud = SpriteTestAssets.scene(plane.cells { $0.alpha > 0 && (roles[$0.rgb]?.hasPrefix("cloud.") ?? false) }, x: 20, y: 27, h: 32)
                XCTAssertTrue(celestial.isDisjoint(with: hidden), "\(scenery.weatherTag) #\(step): celestial ink hidden")
                XCTAssertGreaterThanOrEqual(cloud.subtracting(hidden).count * 2, cloud.count, "\(scenery.weatherTag) #\(step): cloud hidden")
            }
        } } }
    }

    func testFifteenDistinctWeatherKeyFrames() throws {
        let sheet = try SpriteTestAssets.sheet("room-weather")
        let keys = try Scenery.weatherTags.map { tag -> Data in
            let plane = try SpriteTestAssets.plane(sheet, frame: SpriteTestAssets.clip(sheet, tag).order[0])
            return Data(plane.pixels.flatMap { [UInt8(($0.rgb >> 16) & 255), UInt8(($0.rgb >> 8) & 255), UInt8($0.rgb & 255), UInt8($0.alpha)] })
        }
        XCTAssertEqual(Set(keys).count, WindowWeather.all.count * SkyPhase.allCases.count)
    }

    func testSkyEffectsAreTransparentAndLeaveBaseKeyShapesVisible() throws {
        let fx = try SpriteTestAssets.sheet("room-skyfx"), pane = try SpriteTestAssets.sheet("room-weather")
        let roles = try SpriteTestAssets.palette().roles
        for time in SkyPhase.allCases {
            let overlays: [SkyOverlay] = [.mist, time == .night ? .shootingstar : .rainbow]
            for overlay in overlays {
                let clip = try SpriteTestAssets.clip(fx, "\(overlay.rawValue)-\(time.tag)")
                for frame in clip.order {
                    let cover = try SpriteTestAssets.plane(fx, frame: frame).ink
                    XCTAssertLessThan(cover.count, 36 * 32, "overlay cannot become an opaque pane")
                    for base in WindowWeather.all {
                        let tag = "\(base.rawValue)-\(time.tag)"
                        for index in try SpriteTestAssets.clip(pane, tag).order {
                            let pixels = try SpriteTestAssets.plane(pane, frame: index)
                            for prefix in ["celestial.", "cloud.", "weather.rain.", "weather.curtain."] {
                                let shape = pixels.cells { $0.alpha > 0 && (roles[$0.rgb]?.hasPrefix(prefix) ?? false) }
                                if !shape.isEmpty { XCTAssertFalse(shape.subtracting(cover).isEmpty, "\(tag) hidden by \(clip.tag)") }
                            }
                        }
                    }
                }
            }
        }
    }

    /// All environments, moods, lamp choices and zoom extremes render; missing resources always fail.
    func testRoomCompositesAtUnitAndMaximumZoom() throws {
        let write = ProcessInfo.processInfo.environment["CICADA_WRITE_COMPOSITES"] == "1"
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-sprite-composites")
        if write { try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true) }
        for scale in [1.0, 1.4] {
            let layout = deskSceneLayout(uiScale: scale)
            for base in WindowWeather.all { for time in SkyPhase.allCases { for mood in Self.moods { for lit in [false, true] {
                let scenery = Scenery.resolve(mode: .choose, clock: .day, forecast: nil, mood: mood,
                                              manual: .init(time: time, base: base))
                let width = Int(layout.size.width), height = Int(layout.size.height)
                let context = try XCTUnwrap(CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                    bytesPerRow: width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
                context.interpolationQuality = .none
                context.setShouldAntialias(false)
                for layer in layout.layers {
                    if let art = RoomArt.tag(layer.prop, lampLit: lit, scenery: scenery) {
                        let sheet = try SpriteTestAssets.sheet(art.sheet)
                        let clock = RoomClockReading.layers(at: Date(timeIntervalSince1970: 13 * 3600 + 24 * 60 + 36),
                                                            zone: TimeZone(secondsFromGMT: 0)!, lighting: scenery.lighting,
                                                            reduceMotion: false)
                        let indices = layer.prop == .clock ? try clock.map { hand -> Int in
                            let clip = try SpriteTestAssets.clip(sheet, hand.tag)
                            return try XCTUnwrap(clip.order.indices.contains(hand.index) ? clip.order[hand.index] : nil,
                                                 "Clock is missing hand angle \(hand.index)")
                        }
                            : [try SpriteTestAssets.clip(sheet, art.tag).order[0]]
                        for index in indices {
                            let image = try XCTUnwrap(sheet.frameImage(index))
                            context.draw(image, in: CGRect(x: CGFloat(layer.cellX) * layout.cell, y: CGFloat(layer.cellY) * layout.cell,
                                width: CGFloat(layer.w) * layout.cell, height: CGFloat(layer.h) * layout.cell))
                        }
                    }
                }
                let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(mood, .room, lighting: scenery.lighting, lampLit: lit))
                let image = try XCTUnwrap(sheet.frameImage(SpriteTestAssets.clip(sheet, "idle").order[0]))
                context.draw(image, in: CGRect(origin: layout.wormOrigin, size: CGSize(width: 64 * layout.cell, height: 48 * layout.cell)))
                let composite = try XCTUnwrap(context.makeImage())
                XCTAssertEqual(composite.width, width); XCTAssertEqual(composite.height, height)
                if write {
                    let bytes = try XCTUnwrap(NSBitmapImageRep(cgImage: composite).representation(using: .png, properties: [:]))
                    try bytes.write(to: dir.appendingPathComponent("\(scenery.weatherTag)-\(mood.caseName)-\(lit ? "lit" : "dark")-\(scale).png"))
                }
            } } } }
        }
    }
}
