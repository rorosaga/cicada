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
        XCTAssertEqual(layers.map(\.z), Array(0..<8))
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
            XCTAssertEqual(art.sheet, RoomArt.tag(layer.prop, lampLit: true, weather: .night)?.sheet)
            XCTAssertEqual([art.x, art.y, art.w, art.h, art.z], [layer.cellX, layer.cellY, layer.w, layer.h, layer.z])
        }
        XCTAssertEqual([plan.worm.x, plan.worm.y, plan.worm.w, plan.worm.h], [36, 9, 64, 48])
        XCTAssertEqual([plan.pile.x, plan.pile.y, plan.pile.w, plan.pile.h], [110, 0, 50, 52])
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
            let name = try XCTUnwrap(RoomArt.tag(layer.prop, lampLit: true, weather: .night)?.sheet)
            let sheet = try SpriteTestAssets.sheet(name)
            for frame in sheet.frameRects.indices {
                let ink = try SpriteTestAssets.plane(sheet, frame: frame).ink
                XCTAssertTrue(ink.allSatisfy { layer.cellX + $0.x < 110 }, name)
            }
        }
    }

    func testLampAndFlyTagsReadOnlyTheSchedule() {
        XCTAssertNil(RoomArt.tag(.fly, lampLit: false, weather: .night))
        XCTAssertEqual(RoomArt.tag(.fly, lampLit: true, weather: .night)?.tag, "buzz")
        for weather in WindowWeather.all {
            XCTAssertEqual(RoomArt.tag(.lamp, lampLit: false, weather: weather)?.tag, "dark")
            XCTAssertEqual(RoomArt.tag(.backdrop, lampLit: true, weather: weather)?.tag, "lit")
            XCTAssertEqual(RoomArt.tag(.pane, lampLit: false, weather: weather)?.tag, weather.rawValue)
        }
    }
}
