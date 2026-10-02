import XCTest
@testable import CicadaApp

final class RoomSpriteTests: XCTestCase {
    func testRoomSheetsHaveExactTagsCanvasesAndSlices() throws {
        let contracts: [(String, Int, Int, Set<String>, Set<String>)] = [
            ("room-backdrop", 110, 64, ["dark", "lit"], ["glow"]),
            ("room-window", 40, 38, ["idle"], ["glass"]),
            ("room-weather", 36, 32, Set(WindowWeather.all.map(\.rawValue)), []),
            ("room-lamp", 18, 50, ["dark", "lit"], ["ink", "shade"]),
            ("room-fly", 20, 26, ["buzz"], ["ink"]),
            ("room-beanbag", 62, 12, ["idle"], ["ink", "seat"]),
            ("room-plant", 12, 22, ["idle"], ["ink"]),
            ("room-mug", 8, 9, ["idle"], ["ink"]),
            ("room-spines", 24, 12, Set(SpineKind.allCases.map(\.rawValue)), []),
        ]
        for (name, w, h, tags, slices) in contracts {
            let sheet = try SpriteTestAssets.sheet(name)
            XCTAssertEqual(sheet.frameSize, CGSize(width: w, height: h), name)
            XCTAssertEqual(Set(sheet.tags.keys), tags, name)
            XCTAssertEqual(Set(sheet.slices.keys), slices, name)
            let data = try SpriteTestAssets.data(name)
            XCTAssertTrue(data.frames.allSatisfy { $0.frame.w == w && $0.frame.h == h && $0.sourceSize.w == w && $0.sourceSize.h == h })
            XCTAssertTrue(data.meta.frameTags.allSatisfy { $0.direction == "forward" && $0.from <= $0.to })
            SpriteTestAssets.assertCaps(sheet)
            if slices.contains("ink") { XCTAssertEqual(sheet.slices["ink"], SpriteTestAssets.bounds(try SpriteTestAssets.unionInk(sheet)), name) }
        }
        for state in BookwormSpriteTests.states {
            let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))
            XCTAssertEqual(Set(sheet.slices.keys), ["ink", "eye", "lensL", "lensR"])
            XCTAssertEqual(sheet.slices["ink"], SpriteTestAssets.bounds(try SpriteTestAssets.unionInk(sheet)), sheet.name)
        }
    }

    func testLampAndBackdropDifferOnlyInTheDeclaredSlices() throws {
        for (name, slice) in [("room-lamp", "shade"), ("room-backdrop", "glow")] {
            let sheet = try SpriteTestAssets.sheet(name)
            let dark = try SpriteTestAssets.plane(sheet, frame: SpriteTestAssets.clip(sheet, "dark").order[0])
            let lit = try SpriteTestAssets.plane(sheet, frame: SpriteTestAssets.clip(sheet, "lit").order[0])
            let changed = Set(dark.pixels.indices.filter { dark.pixels[$0] != lit.pixels[$0] }.map { SpriteTestAssets.Cell(x: $0 % dark.w, y: $0 / dark.w) })
            XCTAssertFalse(changed.isEmpty, name)
            XCTAssertEqual(try XCTUnwrap(sheet.slices[slice]), SpriteTestAssets.bounds(changed), name)
        }
    }

    func testFlyIsPixelSizedOutsideTheGlassAndPileAndRestsOnTheShade() throws {
        let fly = try SpriteTestAssets.sheet("room-fly"), lamp = try SpriteTestAssets.sheet("room-lamp")
        let clip = try SpriteTestAssets.clip(fly, "buzz")
        let glass = CGRect(x: 20, y: 27, width: 36, height: 32)
        let lampInk = SpriteTestAssets.scene(try SpriteTestAssets.unionInk(lamp), x: 0, y: 0, h: 50)
        let shade = try XCTUnwrap(lamp.slices["shade"])
        let shadeScene = CGRect(x: shade.minX, y: 50 - shade.maxY, width: shade.width, height: shade.height)
        for (step, frame) in clip.order.enumerated() {
            let ink = try SpriteTestAssets.plane(fly, frame: frame).ink
            XCTAssertLessThanOrEqual(ink.count, 2)
            let scene = SpriteTestAssets.scene(ink, x: 0, y: 32, h: 26)
            XCTAssertTrue(scene.allSatisfy { $0.x < 110 && !glass.contains(CGPoint(x: Double($0.x) + 0.5, y: Double($0.y) + 0.5)) })
            if step == 0 {
                XCTAssertGreaterThanOrEqual(ink.count, 1)
                XCTAssertTrue(scene.allSatisfy { cell in
                    shadeScene.insetBy(dx: -1, dy: -1).contains(CGPoint(x: Double(cell.x) + 0.5, y: Double(cell.y) + 0.5))
                        && lampInk.contains { abs($0.x - cell.x) + abs($0.y - cell.y) == 1 }
                })
            }
        }
    }

    func testRainNeverFlashes() throws {
        let sheet = try SpriteTestAssets.sheet("room-weather")
        let storm = try SpriteTestAssets.clip(sheet, "storm")
        let values = try storm.order.map { frame -> Double in
            let pixels = try SpriteTestAssets.plane(sheet, frame: frame).pixels.filter { $0.alpha > 0 }
            XCTAssertFalse(pixels.isEmpty)
            return pixels.reduce(0.0) { sum, p in
                sum + 0.2126 * Double((p.rgb >> 16) & 255) + 0.7152 * Double((p.rgb >> 8) & 255) + 0.0722 * Double(p.rgb & 255)
            } / Double(max(1, pixels.count))
        }
        let mean = values.reduce(0, +) / Double(values.count)
        XCTAssertGreaterThan(mean, 0)
        for value in values { XCTAssertLessThanOrEqual(abs(value - mean), mean * 0.02 + 1e-9) }
    }

    /// The spec leaves this sidecar's serialization open. Run B must supply this explicit per-frame contract.
    func testWeatherMotionStepsIncludingTheSeam() throws {
        struct Motion: Decodable {
            struct Point: Decodable { let x, y: Int }
            struct Element: Decodable { let name: String; let positions, steps: [Point]; let wrap: Point }
            struct Tag: Decodable { let tag: String; let elements: [Element] }
            let tags: [Tag]
        }
        let motion = try JSONDecoder().decode(Motion.self, from: SpriteTestAssets.artData("room-motion.json"))
        let sheet = try SpriteTestAssets.sheet("room-weather")
        XCTAssertEqual(Set(motion.tags.map(\.tag)), Set(WindowWeather.all.map(\.rawValue)))
        for tag in motion.tags {
            let clip = try SpriteTestAssets.clip(sheet, tag.tag)
            XCTAssertFalse(tag.elements.isEmpty)
            for element in tag.elements {
                XCTAssertFalse(element.name.isEmpty)
                XCTAssertEqual(element.positions.count, clip.order.count)
                XCTAssertEqual(element.steps.count, clip.order.count)
                let n = try XCTUnwrap(element.positions.isEmpty ? nil : element.positions.count)
                guard element.steps.count == n else { return XCTFail("motion steps must cover every frame") }
                func wrapped(_ x: Int, _ period: Int) -> Int { period > 0 ? ((x % period) + period) % period : x }
                for i in 0..<n {
                    let next = element.positions[(i + 1) % n], current = element.positions[i], step = element.steps[i]
                    XCTAssertEqual(wrapped(current.x + step.x, element.wrap.x), wrapped(next.x, element.wrap.x), "\(tag.tag)/\(element.name) x #\(i)")
                    XCTAssertEqual(wrapped(current.y + step.y, element.wrap.y), wrapped(next.y, element.wrap.y), "\(tag.tag)/\(element.name) y #\(i)")
                }
            }
        }
    }
}
