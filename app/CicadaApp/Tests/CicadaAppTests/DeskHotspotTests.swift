import CoreGraphics
import XCTest
@testable import CicadaApp

/// Track Z §6.2 / R-Z8 — the hotspot layer is derived from the pure layout, in
/// whole cells, so it can never drift from the art it sits on.
final class DeskHotspotTests: XCTestCase {

    private var scales: [Double] { (8...14).map { Double($0) / 10 } }

    /// Owner 2026-10-02: clicking the worm must not leave a blue focus ring around it. The worm stays a keyboard and
    /// VoiceOver stop (Full Keyboard Access, Space/Return/Esc), but a pointer click activates it without taking focus,
    /// the way a macOS button behaves.
    func test_wormHotspotIsActivateOnlyFocusSoAClickDrawsNoRing() throws {
        let root = SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp")
        let room = try String(contentsOf: root.appendingPathComponent("Views/Sleep/StudyRoom.swift"), encoding: .utf8)
        let hotspot = try XCTUnwrap(room.range(of: "struct WormHotspot: View")).lowerBound
        let body = String(room[hotspot...])
        XCTAssertTrue(body.contains(".focusable(interactions: .activate)"))
        XCTAssertFalse(body.contains(".focusable()\n"))
        XCTAssertTrue(body.contains(".onKeyPress(.space)"))
        XCTAssertTrue(body.contains(".onKeyPress(.return)"))
    }

    func test_everyHotspotIsWholeCellsInsideTheScene() {
        for scale in scales {
            let layout = deskSceneLayout(uiScale: scale)
            let spots = deskHotspots(layout)
            XCTAssertEqual(Set(spots.keys), Set(DeskHotspot.allCases))
            for (spot, rect) in spots {
                for v in [rect.minX, rect.minY, rect.width, rect.height] {
                    XCTAssertEqual(v.truncatingRemainder(dividingBy: layout.cell), 0, "\(spot) @\(scale)")
                }
                XCTAssertTrue(CGRect(origin: .zero, size: layout.size).contains(rect), "\(spot) @\(scale)")
            }
        }
    }

    /// Pairwise disjoint — a pointer is over one thing or none; the window
    /// stops where the worm starts.
    func test_hotspotsNeverOverlap() {
        for scale in scales {
            let spots = Array(deskHotspots(deskSceneLayout(uiScale: scale)).values)
            for i in spots.indices { for j in spots.indices where j > i {
                XCTAssertTrue(spots[i].intersection(spots[j]).isEmpty, "@\(scale)")
            } }
        }
    }

    /// P10 — the lamp and the window never reach into the real pile's column.
    func test_theLampAndTheWindowStayOutOfThePileColumn() {
        for scale in scales {
            let layout = deskSceneLayout(uiScale: scale)
            let spots = deskHotspots(layout)
            for spot in [DeskHotspot.lamp, .window] {
                XCTAssertTrue(spots[spot]!.intersection(layout.pileFrame).isEmpty, "\(spot) @\(scale)")
            }
        }
    }

    func test_theEyesAreInsideTheWorm() {
        for scale in scales {
            let layout = deskSceneLayout(uiScale: scale)
            let eye = CGPoint(x: (CGFloat(DeskHotspots.eyeCell.col) + 0.5) * layout.cell,
                              y: (CGFloat(DeskHotspots.eyeCell.row) + 0.5) * layout.cell)
            XCTAssertTrue(deskHotspots(layout)[.worm]!.contains(eye), "@\(scale)")
        }
    }

    /// Independently measure real PNG union ink, then pin the finished art at 3 pt per cell.
    func test_theCellsTheDesignNames() throws {
        let layout = deskSceneLayout(uiScale: 1.0)
        let spots = deskHotspots(layout)
        var ink = Set<SpriteTestAssets.Cell>()
        for state in BookwormSpriteTests.states where state.caseName != "curious" {
            ink.formUnion(try SpriteTestAssets.unionInk(SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))))
        }
        let worm = SpriteTestAssets.bounds(SpriteTestAssets.scene(ink, x: 36, y: 9, h: 48))
        let lamp = try SpriteTestAssets.sheet("room-lamp")
        let lampBox = SpriteTestAssets.bounds(SpriteTestAssets.scene(try SpriteTestAssets.unionInk(lamp), x: 0, y: 0, h: 50))
        _ = try SpriteTestAssets.sheet("room-window")
        let window = CGRect(x: 20, y: 27, width: min(36, worm.minX - 20), height: 32)
        func points(_ rect: CGRect) -> CGRect { CGRect(x: rect.minX * 3, y: rect.minY * 3, width: rect.width * 3, height: rect.height * 3) }
        XCTAssertEqual(spots[.worm], points(worm))
        XCTAssertEqual(spots[.lamp], points(lampBox))
        XCTAssertEqual(spots[.window], points(window))
        XCTAssertEqual(worm, CGRect(x: 40, y: 9, width: 56, height: 48))
        XCTAssertEqual(spots[.worm], CGRect(x: 120, y: 27, width: 168, height: 144))
        XCTAssertEqual(spots[.lamp], CGRect(x: 6, y: 0, width: 42, height: 150))
        XCTAssertEqual(spots[.window], CGRect(x: 60, y: 81, width: 60, height: 96))
        XCTAssertEqual(DeskHotspots.eyeCell.col, 64)
        XCTAssertEqual(DeskHotspots.eyeCell.row, 34)
        // The wall clock is an inert text-twin leaf, never a fourth hotspot.
        XCTAssertEqual(Set(spots.keys), [.worm, .lamp, .window])
    }

    func test_sceneBottomLeadingFlipsY() {
        let layout = deskSceneLayout(uiScale: 1.0)
        XCTAssertEqual(sceneBottomLeading(CGPoint(x: 200, y: 70), in: layout), CGPoint(x: 200, y: 122))
        XCTAssertEqual(sceneBottomLeading(CGPoint(x: 10, y: 0), in: layout), CGPoint(x: 10, y: 192))
    }
}
