import XCTest
@testable import CicadaApp

final class DeskSceneLayoutTests: XCTestCase {
    func testEveryZoomStepUsesTheCellTableAndCanvas() {
        for (step, cell) in zip(8...14, [2, 3, 3, 3, 4, 4, 4]) {
            let layout = deskSceneLayout(uiScale: Double(step) / 10)
            XCTAssertEqual(layout.cell, CGFloat(cell))
            XCTAssertEqual(layout.size, CGSize(width: 160 * cell, height: 64 * cell))
            for layer in layout.layers {
                XCTAssertEqual((CGFloat(layer.cellX) * layout.cell).truncatingRemainder(dividingBy: layout.cell), 0)
                XCTAssertEqual((CGFloat(layer.cellY) * layout.cell).truncatingRemainder(dividingBy: layout.cell), 0)
                XCTAssertGreaterThanOrEqual(layer.cellX, 0)
                XCTAssertGreaterThanOrEqual(layer.cellY, 0)
                XCTAssertLessThanOrEqual(layer.cellX + layer.w, 160)
                XCTAssertLessThanOrEqual(layer.cellY + layer.h, 64)
            }
            let scene = CGRect(origin: .zero, size: layout.size)
            XCTAssertTrue(scene.contains(CGRect(origin: layout.wormOrigin, size: CGSize(width: 64 * layout.cell, height: 48 * layout.cell))))
            XCTAssertTrue(scene.contains(layout.pileFrame))
            XCTAssertEqual(layout.wormOrigin.x.truncatingRemainder(dividingBy: layout.cell), 0)
            XCTAssertEqual(layout.wormOrigin.y.truncatingRemainder(dividingBy: layout.cell), 0)
        }
        XCTAssertEqual(deskSceneLayout(uiScale: 1).cell, 3)
        XCTAssertGreaterThanOrEqual(deskSceneLayout(uiScale: 1).pileFrame.width, 150)
    }

    func testEveryPropAppearsExactlyOnceInStrictlyAscendingZOrder() {
        let layers = DeskScene.plan
        XCTAssertEqual(Set(layers.map(\.prop)), Set(DeskProp.allCases))
        XCTAssertEqual(layers.count, DeskProp.allCases.count)
        XCTAssertEqual(layers.map(\.z), Array(0..<DeskProp.allCases.count))
    }

    func testPlanEqualsTheArtRunsData() throws {
        struct Plan: Decodable {
            struct Layer: Decodable { let prop, sheet: String; let x, y, w, h, z: Int }
            struct Box: Decodable { let x, y, w, h: Int }
            let cols, rows: Int
            let origin: String
            let layers: [Layer]
            let worm, pile: Box
        }
        let plan = try JSONDecoder().decode(Plan.self, from: SpriteTestAssets.artData("room-plan.json"))
        XCTAssertEqual(plan.cols, 160); XCTAssertEqual(plan.rows, 64); XCTAssertEqual(plan.origin, "bottom-left")
        XCTAssertEqual(plan.layers.count, DeskScene.plan.count)
        for (art, layer) in zip(plan.layers, DeskScene.plan) {
            XCTAssertEqual(art.prop, layer.prop.rawValue)
            XCTAssertEqual(art.sheet, RoomArt.tag(layer.prop, lampLit: true, scenery: Self.scenery(.sunny, .night, overlay: .mist))?.sheet)
            XCTAssertEqual([art.x, art.y, art.w, art.h, art.z], [layer.cellX, layer.cellY, layer.w, layer.h, layer.z])
        }
        XCTAssertEqual([plan.worm.x, plan.worm.y, plan.worm.w, plan.worm.h],
                       [DeskScene.wormCell.x, DeskScene.wormCell.y, 64, 48])
        XCTAssertEqual([plan.pile.x, plan.pile.y, plan.pile.w, plan.pile.h],
                       [DeskScene.pileCell.x, DeskScene.pileCell.y, DeskScene.pileCell.width, DeskScene.pileCell.height])
    }

    func testWormBaselineEqualsTheBeanbagSeatRow() throws {
        let sheet = try SpriteTestAssets.sheet("room-beanbag")
        let seat = try XCTUnwrap(sheet.slices["seat"])
        let layer = try XCTUnwrap(DeskScene.plan.first { $0.prop == .beanbag })
        XCTAssertEqual(seat.height, 1)
        XCTAssertEqual(layer.cellY + layer.h - 1 - Int(seat.minY), DeskScene.wormCell.y)
    }

    func testPaneEqualsTheWindowGlassInSceneCells() throws {
        let sheet = try SpriteTestAssets.sheet("room-window")
        let glass = try XCTUnwrap(sheet.slices["glass"])
        XCTAssertEqual(glass, CGRect(x: 2, y: 2, width: 36, height: 32))
        let frame = try XCTUnwrap(DeskScene.plan.first { $0.prop == .window })
        let pane = try XCTUnwrap(DeskScene.plan.first { $0.prop == .pane })
        XCTAssertLessThan(pane.z, frame.z)
        XCTAssertEqual(pane.cellX, frame.cellX + Int(glass.minX))
        XCTAssertEqual(pane.cellY, frame.cellY + frame.h - Int(glass.maxY))
        XCTAssertEqual([pane.w, pane.h], [Int(glass.width), Int(glass.height)])
    }

    func testNoPropInkReachesThePileColumn() throws {
        for layer in DeskScene.plan {
            let name = try XCTUnwrap(RoomArt.tag(layer.prop, lampLit: true, scenery: Self.scenery(.sunny, .night, overlay: .mist))?.sheet)
            let sheet = try SpriteTestAssets.sheet(name)
            for frame in sheet.frameRects.indices {
                let ink = try SpriteTestAssets.plane(sheet, frame: frame).ink
                XCTAssertTrue(ink.allSatisfy { layer.cellX + $0.x < DeskScene.pileCell.x }, name)
            }
        }
    }

    static func scenery(_ base: WindowWeather, _ time: SkyPhase, overlay: SkyOverlay? = nil) -> Scenery {
        Scenery(base: base, time: time, overlay: overlay, source: .chosen)
    }

    func testWormCrossfadeIdentityChangesOnlyWithItsLightingSheetSet() throws {
        for mode in SceneryMode.allCases { for time in SkyPhase.allCases { for base in WindowWeather.all {
            for mood in BookwormArt.states { for lit in [false, true] {
                let scene = Scenery.resolve(mode: mode, clock: time, forecast: base, mood: mood,
                                            manual: .init(time: time, base: base))
                let identity = scene.lighting.suffix(lampLit: lit)
                XCTAssertEqual(identity, scene.lighting == .day ? "" : (lit ? "-night-lit" : "-night-dark"))
                let noOverlay = Scenery(base: scene.base, time: scene.time, overlay: nil, source: scene.source)
                XCTAssertEqual(identity, noOverlay.lighting.suffix(lampLit: lit))
                if scene.lighting == .day { XCTAssertEqual(identity, scene.lighting.suffix(lampLit: !lit)) }
            } }
        } } }
        let source = try String(contentsOf: SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/Views/Sleep/DeskScene.swift"), encoding: .utf8)
        let body = try XCTUnwrap(source.range(of: "struct SceneryRoomArt")).lowerBound
        let subtree = String(source[body...])
        let roomID = try XCTUnwrap(subtree.range(of: ".id(appearance)"))
        let worm = try XCTUnwrap(subtree.range(of: "worm().offset"))
        XCTAssertLessThan(roomID.lowerBound, worm.lowerBound, "worm must be a sibling after the room identity, never inside it")
        XCTAssertTrue(subtree.contains(".id(wormLighting)"))
        XCTAssertTrue(subtree.contains("value: wormLighting"))
        XCTAssertTrue(subtree.contains("scenery.lighting.suffix(lampLit: lampLit)"))
    }

    func testLightingAndScheduleSelectTheExactTags() {
        for base in WindowWeather.all { for time in SkyPhase.allCases { for lit in [false, true] {
            let scenery = Self.scenery(base, time, overlay: .mist)
            let dark = time == .night || base == .rainy
            XCTAssertEqual(RoomArt.tag(.lamp, lampLit: lit, scenery: scenery)?.tag,
                           (dark ? "night-" : "") + (lit ? "lit" : "dark"))
            for prop in [DeskProp.window, .plant, .beanbag, .mug] {
                XCTAssertEqual(RoomArt.tag(prop, lampLit: lit, scenery: scenery)?.tag,
                               dark ? "night-\(lit ? "lit" : "dark")" : "idle")
            }
            XCTAssertEqual(RoomArt.tag(.pane, lampLit: lit, scenery: scenery)?.tag, "\(base.rawValue)-\(time.tag)")
            XCTAssertEqual(RoomArt.tag(.skyfx, lampLit: lit, scenery: scenery)?.tag, "mist-\(time.tag)")
            XCTAssertEqual(RoomArt.tag(.fly, lampLit: lit, scenery: scenery)?.tag, lit ? "buzz" : nil)
        } } }
        XCTAssertNil(RoomArt.tag(.skyfx, lampLit: true, scenery: Self.scenery(.sunny, .day)))
    }
}
