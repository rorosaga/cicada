import XCTest
@testable import CicadaApp

final class RoomSpriteTests: XCTestCase {
    func testRoomSheetsHaveExactTagsCanvasesAndSlices() throws {
        let contracts: [(String, Int, Int, Set<String>, Set<String>)] = [
            ("room-backdrop", 110, 64, ["dark", "lit", "night-dark", "night-lit"], ["glow"]),
            ("room-window", 40, 38, ["idle", "night-dark", "night-lit"], ["glass"]),
            ("room-weather", 36, 32, Set(Scenery.weatherTags), []),
            ("room-skyfx", 36, 32, Set(SkyOverlay.tags), []),
            ("room-lamp", 18, 50, ["dark", "lit", "night-dark", "night-lit"], ["ink", "shade"]),
            ("room-fly", 20, 26, ["buzz"], ["ink"]),
            ("room-beanbag", 62, 12, ["idle", "night-dark", "night-lit"], ["ink", "seat"]),
            ("room-plant", 12, 22, ["idle", "night-dark", "night-lit"], ["ink"]),
            ("room-mug", 8, 9, ["idle", "night-dark", "night-lit"], ["ink"]),
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
    }

    func testDayWormSliceContractIncludesErrorLensL() throws {
        for state in BookwormSpriteTests.states {
            let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))
            XCTAssertEqual(Set(sheet.slices.keys), Set(["ink", "eye", "lensL", "lensR"] + (state.caseName == "error" ? ["errorLensL"] : [])))
            if state.caseName == "error" { XCTAssertEqual(sheet.slices["errorLensL"], CGRect(x: 10, y: 17, width: 5, height: 6)) }
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
        let placement = try XCTUnwrap(DeskScene.plan.first { $0.prop == .fly })
        let lampLayer = try XCTUnwrap(DeskScene.plan.first { $0.prop == .lamp })
        let pane = try XCTUnwrap(DeskScene.plan.first { $0.prop == .pane })
        let glass = CGRect(x: pane.cellX, y: pane.cellY, width: pane.w, height: pane.h)
        let pile = CGRect(x: DeskScene.pileCell.x, y: DeskScene.pileCell.y,
                          width: DeskScene.pileCell.width, height: DeskScene.pileCell.height)
        let lampInk = SpriteTestAssets.scene(try SpriteTestAssets.unionInk(lamp), x: lampLayer.cellX, y: lampLayer.cellY, h: lampLayer.h)
        let shade = try XCTUnwrap(lamp.slices["shade"])
        let sceneShade = CGRect(x: CGFloat(lampLayer.cellX) + shade.minX,
                                y: CGFloat(lampLayer.cellY + lampLayer.h) - shade.maxY,
                                width: shade.width, height: shade.height)
        let frames = try clip.order.map { SpriteTestAssets.scene(try SpriteTestAssets.plane(fly, frame: $0).ink,
                                                               x: placement.cellX, y: placement.cellY, h: placement.h) }
        XCTAssertTrue(Self.flyVisibilityIsValid(frames, shade: sceneShade), "empty runs may start only behind the shade")
        for (step, frame) in clip.order.enumerated() {
            let ink = try SpriteTestAssets.plane(fly, frame: frame).ink
            XCTAssertLessThanOrEqual(ink.count, 2)
            let scene = frames[step]
            XCTAssertTrue(scene.allSatisfy {
                let point = CGPoint(x: Double($0.x) + 0.5, y: Double($0.y) + 0.5)
                return !pile.contains(point) && !glass.contains(point)
            })
            if step == 0 {
                XCTAssertGreaterThanOrEqual(ink.count, 1)
                XCTAssertTrue(scene.allSatisfy { cell in
                    // `shade` bounds the changed lighting pixels, excluding the unchanged top rim (row 0).
                    // §5.4 says ON TOP: the fly must sit exactly one cell above the actual shade silhouette.
                    Double(cell.x) >= sceneShade.minX && Double(cell.x) < sceneShade.maxX
                        && lampInk.contains(.init(x: cell.x, y: cell.y - 1))
                        && cell.y == (lampInk.filter { $0.x == cell.x }.map(\.y).max() ?? -2) + 1
                })
            }
        }
    }

    private static func flyVisibilityIsValid(_ frames: [Set<SpriteTestAssets.Cell>], shade: CGRect) -> Bool {
        guard var lastVisible = frames.last(where: { !$0.isEmpty }) else { return false }
        for frame in frames {
            if frame.isEmpty {
                guard lastVisible.allSatisfy({ shade.contains(CGPoint(x: Double($0.x) + 0.5, y: Double($0.y) + 0.5)) }) else { return false }
            } else {
                guard frame.count <= 2 else { return false }
                lastVisible = frame
            }
        }
        return true
    }

    func testFlyVisibilityGuardRejectsOpenAirDisappearancesAndMissingFly() {
        let shade = CGRect(x: 0, y: 38, width: 18, height: 12)
        let hidden: Set<SpriteTestAssets.Cell> = [.init(x: 14, y: 43)]
        let open: Set<SpriteTestAssets.Cell> = [.init(x: 19, y: 51)]
        XCTAssertTrue(Self.flyVisibilityIsValid([open, hidden, [], [], open], shade: shade))
        XCTAssertFalse(Self.flyVisibilityIsValid([hidden, open, [], hidden], shade: shade))
        XCTAssertFalse(Self.flyVisibilityIsValid([[], []], shade: shade))
        XCTAssertFalse(Self.flyVisibilityIsValid([hidden.union(open).union([.init(x: 10, y: 40)])], shade: shade))
    }

    func testRainNeverFlashes() throws {
        let sheet = try SpriteTestAssets.sheet("room-weather")
        for time in SkyPhase.allCases {
        let storm = try SpriteTestAssets.clip(sheet, "rainy-\(time.tag)")
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
        XCTAssertEqual(Set(motion.tags.map(\.tag)), Set(Scenery.weatherTags + SkyOverlay.tags))
        XCTAssertEqual(motion.tags.count, Set(motion.tags.map(\.tag)).count, "no duplicate motion records")
        for tag in motion.tags {
            let sheet = try SpriteTestAssets.sheet(SkyOverlay.tags.contains(tag.tag) ? "room-skyfx" : "room-weather")
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
