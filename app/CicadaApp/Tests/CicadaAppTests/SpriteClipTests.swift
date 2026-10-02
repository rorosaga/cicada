import SwiftUI
import XCTest
@testable import CicadaApp

final class SpriteClipTests: XCTestCase {
    func testEveryEnvironmentMoodAndLampStateStaysInsideTheRoomRedrawBudget() throws {
        let weather = try SpriteTestAssets.sheet("room-weather"), fx = try SpriteTestAssets.sheet("room-skyfx")
        let fly = try SpriteTestAssets.sheet("room-fly")
        for base in WindowWeather.all { for time in SkyPhase.allCases {
            for mood in WindowSpritesTests.moods { for lit in [false, true] {
                let scenery = Scenery.resolve(mode: .choose, clock: .day, forecast: nil, mood: mood,
                                              manual: .init(time: time, base: base))
                let worm = try SpriteTestAssets.sheet(BookwormArt.sheetName(mood, .room, lighting: scenery.lighting, lampLit: lit))
                var clips = [try SpriteTestAssets.clip(weather, scenery.weatherTag), try SpriteTestAssets.clip(worm, "idle")]
                if let tag = scenery.overlayTag { clips.append(try SpriteTestAssets.clip(fx, tag)) }
                if lit { clips.append(try SpriteTestAssets.clip(fly, "buzz")) }
                // Separate leaves redraw even on coincident boundaries; sum, rather than deduplicating them.
                var boundaries = 60 // The independent wall-clock leaf ticks once per second.
                for clip in clips where clip.order.count > 1 {
                    let schedule = SpriteFrameSchedule(tracks: [.init(origin: SpriteClock.origin, seconds: clip.seconds, loops: true)])
                    let entries = schedule.entries(from: SpriteClock.origin, mode: .normal)
                    _ = entries.next()
                    while let date = entries.next(), date.timeIntervalSince(SpriteClock.origin) <= 60 { boundaries += 1 }
                }
                XCTAssertLessThanOrEqual(boundaries, 1800, "\(scenery.weatherTag) \(mood.caseName) lamp \(lit)")
            } }
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

    func testBoundaryFiftyMicrosecondsAheadIsNeverSkipped() throws {
        for loops in [true, false] {
            let track = SpriteFrameSchedule.Track(origin: at(0), seconds: clip.seconds, loops: loops)
            for (step, boundary) in [0.1, 0.3, 0.6].enumerated() {
                let before = at(boundary - 0.00005)
                XCTAssertEqual(clip.loopStep(at: before, profile: .full), step)
                let next = try XCTUnwrap(SpriteFrameSchedule.nextBoundary(after: before, track: track))
                XCTAssertEqual(next.timeIntervalSinceReferenceDate, boundary + 0.0005, accuracy: 0.000001,
                               "a re-evaluation just before the boundary must still schedule that frame")
                if loops {
                    XCTAssertEqual(clip.loopStep(at: next, profile: .full), (step + 1) % clip.order.count)
                } else {
                    XCTAssertEqual(clip.onceStep(at: next, startedAt: at(0), profile: .full),
                                   step + 1 == clip.order.count ? nil : step + 1)
                }
            }
        }
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
