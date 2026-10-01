import SwiftUI
import XCTest
@testable import CicadaApp

final class SpriteClipTests: XCTestCase {
    func testEveryMoodAndLampStateStaysInsideTheRoomRedrawBudget() throws {
        let weather = try SpriteTestAssets.sheet("room-weather")
        let fly = try SpriteTestAssets.sheet("room-fly")
        for mood in WindowSpritesTests.moods { for lit in [false, true] {
            let worm = try SpriteTestAssets.sheet(BookwormArt.sheetName(mood, .room))
            var clips = [try SpriteTestAssets.clip(weather, windowWeather(for: mood).rawValue), try SpriteTestAssets.clip(worm, "idle")]
            if lit { clips.append(try SpriteTestAssets.clip(fly, "buzz")) }
            let schedule = SpriteFrameSchedule(tracks: clips.map { .init(origin: SpriteClock.origin, seconds: $0.seconds, loops: true) })
            let entries = schedule.entries(from: SpriteClock.origin, mode: .normal)
            _ = entries.next()
            var boundaries = 0
            while let date = entries.next(), date.timeIntervalSince(SpriteClock.origin) <= 60 { boundaries += 1 }
            XCTAssertLessThanOrEqual(boundaries, 1800, "\(mood.caseName) lamp \(lit)")
        } }
    }
    private let clip = SpriteClip(sheet: "synthetic", tag: "idle", order: [4, 1, 4], seconds: [0.1, 0.2, 0.3])
    private func at(_ t: Double) -> Date { SpriteClock.origin.addingTimeInterval(t) }

    func testCumulativeBoundaryInclusiveModuloAndNegativeDates() {
        for (t, step) in [(0.0, 0), (0.099, 0), (0.1, 1), (0.299, 1), (0.3, 2), (0.6, 0), (1.3, 1), (-1, 0)] {
            XCTAssertEqual(clip.loopStep(at: at(t), profile: .full), step, "\(t)")
        }
        XCTAssertEqual(clip.loopStep(at: at(5), profile: .still), 0)
        XCTAssertEqual(clip.loopStep(at: at(0.2), profile: .gentle), 1)
        XCTAssertEqual(clip.loopStep(at: at(0.6), profile: .gentle), 2)
        XCTAssertEqual(clip.loopStep(at: at(1.2), profile: .gentle), 0)
    }

    func testOncePlaysThenEndsAndClampsBeforeStart() {
        XCTAssertEqual(clip.onceStep(at: at(-1), startedAt: at(0), profile: .full), 0)
        XCTAssertEqual(clip.onceStep(at: at(0.1), startedAt: at(0), profile: .full), 1)
        XCTAssertNil(clip.onceStep(at: at(0.6), startedAt: at(0), profile: .full))
        XCTAssertEqual(clip.onceStep(at: at(0.6), startedAt: at(0), profile: .gentle), 2)
        XCTAssertEqual(clip.onceStep(at: at(3), startedAt: at(0), profile: .still), 0)
        let empty = SpriteClip(sheet: "synthetic", tag: "empty", order: [], seconds: [])
        XCTAssertEqual(empty.loopStep(at: at(1), profile: .full), 0)
        XCTAssertNil(empty.onceStep(at: at(1), startedAt: at(0), profile: .full))
    }

    func testProfileAndPauseRules() {
        XCTAssertEqual(SpritePlaybackProfile.of(reduceMotion: true, lowPower: false), .still)
        XCTAssertEqual(SpritePlaybackProfile.of(reduceMotion: true, lowPower: true), .still)
        XCTAssertEqual(SpritePlaybackProfile.of(reduceMotion: false, lowPower: true), .gentle)
        XCTAssertEqual(SpritePlaybackProfile.gentle.slowdown, 2)
        XCTAssertTrue(SceneRunPolicy.isPaused(windowVisible: false, hostPaused: false))
        XCTAssertTrue(SceneRunPolicy.isPaused(windowVisible: true, hostPaused: true))
        XCTAssertFalse(SceneRunPolicy.isPaused(windowVisible: true, hostPaused: false))
    }

    func testDegenerateClockInputsClampWithoutIndexing() {
        for seconds in [[0.0], [-1.0], [Double.nan], [Double.infinity], [Double.greatestFiniteMagnitude]] {
            let broken = SpriteClip(sheet: "synthetic", tag: "bad", order: [0], seconds: seconds)
            XCTAssertEqual(broken.loopStep(at: at(1), profile: .gentle), 0)
        }
        let mismatch = SpriteClip(sheet: "synthetic", tag: "bad", order: [0, 1], seconds: [1])
        XCTAssertNil(mismatch.onceStep(at: at(1), startedAt: at(0), profile: .full))
        XCTAssertEqual(clip.loopStep(at: at(.infinity), profile: .full), 0)
        XCTAssertEqual(clip.onceStep(at: at(.nan), startedAt: at(0), profile: .full), 0)
    }

    func testNextBoundaryLoopAndOnce() throws {
        let loop = SpriteFrameSchedule.Track(origin: at(0), seconds: clip.seconds, loops: true)
        let once = SpriteFrameSchedule.Track(origin: at(0), seconds: clip.seconds, loops: false)
        XCTAssertEqual(try XCTUnwrap(SpriteFrameSchedule.nextBoundary(after: at(0), track: loop)).timeIntervalSinceReferenceDate, 0.1005, accuracy: 0.000001)
        XCTAssertEqual(try XCTUnwrap(SpriteFrameSchedule.nextBoundary(after: at(0.1), track: loop)).timeIntervalSinceReferenceDate, 0.3005, accuracy: 0.000001)
        XCTAssertEqual(try XCTUnwrap(SpriteFrameSchedule.nextBoundary(after: at(0.6), track: loop)).timeIntervalSinceReferenceDate, 0.7005, accuracy: 0.000001)
        XCTAssertNil(SpriteFrameSchedule.nextBoundary(after: at(0.6), track: once))
        XCTAssertNil(SpriteFrameSchedule.nextBoundary(after: at(0), track: .init(origin: at(0), seconds: [], loops: true)))
    }

    func testScheduleMergesTracksAndAdvancesSharedBoundaries() throws {
        let schedule = SpriteFrameSchedule(tracks: [.init(origin: at(0), seconds: [0.1, 0.2], loops: false),
                                                    .init(origin: at(0), seconds: [0.1, 0.1, 0.2], loops: false)])
        let dates = Array(schedule.entries(from: at(0), mode: .normal))
        XCTAssertEqual(dates.count, 5)
        for (date, t) in zip(dates, [0, 0.1005, 0.2005, 0.3005, 0.4005]) {
            XCTAssertEqual(date.timeIntervalSinceReferenceDate, t, accuracy: 0.000001)
        }
    }
}
