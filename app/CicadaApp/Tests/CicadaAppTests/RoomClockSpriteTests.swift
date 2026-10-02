import XCTest
@testable import CicadaApp

final class RoomClockSpriteTests: XCTestCase {
    func testClockHasExactStateTagsAndSixtyWholePixelHandAngles() throws {
        let sheet = try SpriteTestAssets.sheet("room-clock")
        XCTAssertEqual(sheet.frameSize, CGSize(width: 15, height: 15))
        XCTAssertEqual(Set(sheet.tags.keys), Set(["face", "hour", "minute", "second"].flatMap { [$0, $0 + "-night"] }))
        let centre = 7.0
        var lengths: [String: Double] = [:]
        for suffix in ["", "-night"] {
            XCTAssertEqual(try SpriteTestAssets.clip(sheet, "face" + suffix).order.count, 1)
            for hand in ["hour", "minute", "second"] {
                let clip = try SpriteTestAssets.clip(sheet, hand + suffix)
                XCTAssertEqual(clip.order.count, 60)
                XCTAssertEqual(Set(clip.order).count, 60)
                XCTAssertTrue(clip.seconds.allSatisfy { $0 == 1 }, "Angles are state frames, never timed loops")
                var distinct = Set<Set<SpriteTestAssets.Cell>>()
                for (angle, frame) in clip.order.enumerated() {
                    let plane = try SpriteTestAssets.plane(sheet, frame: frame), ink = plane.ink
                    distinct.insert(ink)
                    XCTAssertTrue(ink.contains(.init(x: 7, y: 7)), "Every hand pivots on the centre pixel")
                    XCTAssertLessThanOrEqual(ink.count, 10, "One-cell line, not a dial or broad hand")
                    let radians = Double(angle) * .pi / 30
                    for cell in ink {
                        let x = Double(cell.x) - centre, y = Double(cell.y) - centre
                        XCTAssertGreaterThanOrEqual(x * sin(radians) - y * cos(radians), -0.01)
                        XCTAssertLessThanOrEqual(abs(x * cos(radians) + y * sin(radians)), 1.1, "Wrong hand angle #\(angle)")
                        XCTAssertLessThanOrEqual(hypot(x, y), 6.5)
                        let p = plane.at(cell.x, cell.y)
                        let r = Int((p.rgb >> 16) & 255), g = Int((p.rgb >> 8) & 255), b = Int(p.rgb & 255)
                        if hand == "second" { XCTAssertGreaterThan(r, max(g, b) + (suffix.isEmpty ? 20 : 10)) }
                        else { XCTAssertLessThanOrEqual(max(r, g, b), 80, "Black hour/minute hands") }
                    }
                    if angle == 0 { lengths[hand + suffix] = ink.map { centre - Double($0.y) }.max() }
                }
                // Pixel angles can coincide on a small grid, but sixty records must still cover a full turn.
                XCTAssertGreaterThanOrEqual(distinct.count, 16)
            }
            XCTAssertLessThan(try XCTUnwrap(lengths["hour" + suffix]), try XCTUnwrap(lengths["minute" + suffix]))
            XCTAssertLessThan(try XCTUnwrap(lengths["minute" + suffix]), try XCTUnwrap(lengths["second" + suffix]))
        }
    }

    func testNightFaceAndSecondHandAreDarkerWithTheSameRegistration() throws {
        let sheet = try SpriteTestAssets.sheet("room-clock")
        func luminance(_ plane: SpriteTestAssets.Plane) -> Double {
            let ink = plane.pixels.filter { $0.alpha > 0 }
            return ink.reduce(0) { $0 + 0.2126 * Double(($1.rgb >> 16) & 255)
                + 0.7152 * Double(($1.rgb >> 8) & 255) + 0.0722 * Double($1.rgb & 255) } / Double(max(1, ink.count))
        }
        for tag in ["face", "hour", "minute", "second"] {
            let day = try SpriteTestAssets.clip(sheet, tag), night = try SpriteTestAssets.clip(sheet, tag + "-night")
            XCTAssertEqual(day.order.count, night.order.count)
            for (a, b) in zip(day.order, night.order) {
                let dayPlane = try SpriteTestAssets.plane(sheet, frame: a), nightPlane = try SpriteTestAssets.plane(sheet, frame: b)
                XCTAssertEqual(dayPlane.ink, nightPlane.ink)
                XCTAssertFalse(dayPlane.ink.isEmpty)
                if tag == "face" || tag == "second" { XCTAssertLessThan(luminance(nightPlane), luminance(dayPlane)) }
            }
        }
    }

    func testClockInkClearsEveryDayAndNightWormFrameAndOtherProps() throws {
        let clock = try SpriteTestAssets.sheet("room-clock")
        let layer = try XCTUnwrap(DeskScene.plan.first { $0.prop == .clock })
        let clockInk = SpriteTestAssets.scene(try SpriteTestAssets.unionInk(clock), x: layer.cellX, y: layer.cellY, h: layer.h)
        XCTAssertTrue(clockInk.allSatisfy { $0.x < DeskScene.pileCell.x })
        for name in SpriteTestAssets.dayWormNames + SpriteTestAssets.nightWormNames {
            let worm = try SpriteTestAssets.sheet(name)
            XCTAssertTrue(clockInk.isDisjoint(with: SpriteTestAssets.scene(try SpriteTestAssets.unionInk(worm),
                x: DeskScene.wormCell.x, y: DeskScene.wormCell.y, h: 48)), name)
        }
        for prop in [DeskProp.window, .lamp] {
            let other = try XCTUnwrap(DeskScene.plan.first { $0.prop == prop })
            let sheet = try SpriteTestAssets.sheet("room-" + prop.rawValue)
            XCTAssertTrue(clockInk.isDisjoint(with: SpriteTestAssets.scene(try SpriteTestAssets.unionInk(sheet),
                x: other.cellX, y: other.cellY, h: other.h)))
        }
    }
}
