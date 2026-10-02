import XCTest
@testable import CicadaApp

final class RoomClockTests: XCTestCase {
    private let utc = TimeZone(secondsFromGMT: 0)!
    private func date(_ value: String) -> Date { ISO8601DateFormatter().date(from: value)! }

    func testSecondScheduleStartsOnWholeSecondsIncludingBeforeTheReferenceDate() {
        for value in [-1.73, -0.01, 0, 0.73, 812_345_678.99] {
            let instant = Date(timeIntervalSinceReferenceDate: value)
            let start = RoomClockReading.secondBoundary(at: instant)
            XCTAssertEqual(start.timeIntervalSinceReferenceDate, floor(value))
            XCTAssertLessThanOrEqual(start, instant)
            XCTAssertLessThan(instant.timeIntervalSince(start), 1)
        }
    }

    func testEverySecondMapsToTheContractAnglesAndWrapsAtNoon() {
        let start = date("2026-10-02T00:00:00Z")
        for second in 0..<86400 {
            let frames = RoomClockReading.indices(at: start.addingTimeInterval(Double(second)), zone: utc)
            XCTAssertEqual(frames.hour, ((second / 3600) % 12) * 5 + (second / 60 % 60) / 12)
            XCTAssertEqual(frames.minute, second / 60 % 60)
            XCTAssertEqual(frames.second, second % 60)
        }
    }

    func testTimeZoneHalfHourAndDaylightSavingClockChanges() {
        let instant = date("2026-10-02T00:59:58Z")
        XCTAssertEqual(RoomClockReading.indices(at: instant, zone: TimeZone(identifier: "Asia/Kolkata")!),
                       .init(hour: 32, minute: 29, second: 58))
        let madrid = TimeZone(identifier: "Europe/Madrid")!
        XCTAssertEqual(RoomClockReading.indices(at: date("2026-10-25T00:59:59Z"), zone: madrid),
                       .init(hour: 14, minute: 59, second: 59))
        XCTAssertEqual(RoomClockReading.indices(at: date("2026-10-25T01:00:00Z"), zone: madrid),
                       .init(hour: 10, minute: 0, second: 0))
    }

    func testLightingAndReduceMotionSelectStateArtWithoutASecondHand() {
        for lighting in [RoomLighting.day, .dark] {
            for reduced in [false, true] {
                let layers = RoomClockReading.layers(at: date("2026-10-02T13:24:36Z"), zone: utc,
                                                     lighting: lighting, reduceMotion: reduced)
                let suffix = lighting == .dark ? "-night" : ""
                XCTAssertEqual(layers.map(\.tag), ["face", "hour", "minute"].map { $0 + suffix }
                               + (reduced ? [] : ["second" + suffix]))
                XCTAssertEqual(layers.map(\.index), [0, 7, 24] + (reduced ? [] : [36]))
            }
        }
        XCTAssertEqual(RoomClockReading.label(at: date("2026-10-02T13:24:36Z"), zone: utc,
                                               locale: Locale(identifier: "en_GB")), "Wall clock, 13:24")
    }

    func testClockBoxNeverOverlapsAnyExistingDayWormFrameOrWindowShadePile() throws {
        let layer = try XCTUnwrap(DeskScene.plan.first { $0.prop == .clock })
        let box = Set((0..<layer.h).flatMap { y in (0..<layer.w).map { x in
            SpriteTestAssets.Cell(x: layer.cellX + x, y: layer.cellY + y)
        } })
        for name in SpriteTestAssets.dayWormNames {
            let sheet = try SpriteTestAssets.sheet(name)
            XCTAssertTrue(box.isDisjoint(with: SpriteTestAssets.scene(try SpriteTestAssets.unionInk(sheet),
                x: DeskScene.wormCell.x, y: DeskScene.wormCell.y, h: 48)), name)
        }
        for prop in [DeskProp.window, .lamp] {
            let other = try XCTUnwrap(DeskScene.plan.first { $0.prop == prop })
            let sheet = try SpriteTestAssets.sheet("room-" + prop.rawValue)
            XCTAssertTrue(box.isDisjoint(with: SpriteTestAssets.scene(try SpriteTestAssets.unionInk(sheet),
                x: other.cellX, y: other.cellY, h: other.h)))
        }
        XCTAssertLessThanOrEqual(layer.cellX + layer.w, DeskScene.pileCell.x)
        XCTAssertEqual(layer.z, 1)
    }

    func testTimelineAndAccessibleTextBelongOnlyToTheVisibleClockLeaf() throws {
        let root = SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/Views/Sleep")
        let clock = try String(contentsOf: root.appendingPathComponent("RoomClock.swift"), encoding: .utf8)
        XCTAssertTrue(clock.contains("onScreen && windowVisible && !hostPaused"))
        XCTAssertTrue(clock.contains("TimelineView(.periodic(from: RoomClockReading.secondBoundary(at: Date()), by: CicadaMotion.roomClockTick))"))
        XCTAssertTrue(clock.contains("TimelineView(.everyMinute)"), "without seconds Reduce Motion updates at minute boundaries")
        XCTAssertTrue(clock.contains("reading(at: context.date)"))
        XCTAssertTrue(clock.contains(".help(label)"))
        XCTAssertTrue(clock.contains(".accessibilityLabel(label)"))
        XCTAssertFalse(clock.contains("Button") || clock.contains("onTapGesture"))
        let room = try String(contentsOf: root.appendingPathComponent("StudyRoom.swift"), encoding: .utf8)
        XCTAssertTrue(room.contains("RoomClock(lighting: scenery.lighting, cell: scene.cell, onScreen: onScreen)"))
        XCTAssertFalse(room.contains("TimelineView") || room.contains(".periodic("))
        XCTAssertGreaterThan(RoomA11yOrder.window, RoomA11yOrder.clock)
        XCTAssertGreaterThan(RoomA11yOrder.clock, RoomA11yOrder.lamp)
        XCTAssertEqual(CicadaMotion.roomClockTick, 1)
    }
}
