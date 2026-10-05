import AppKit
import XCTest
@testable import CicadaApp

/// The room's frames are swapped on a layer at their boundaries, never through a `TimelineView` (measured 2026-10-05:
/// a sub-0.3 s timeline drives the whole window at the display rate — 12% of a core on the Sleep page).
@MainActor
final class SpriteLayerPlayerTests: XCTestCase {
    private func window(holding view: NSView) -> NSWindow {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 64, height: 64), styleMask: [.borderless],
                              backing: .buffered, defer: true)
        window.isReleasedWhenClosed = false
        window.contentView?.addSubview(view)
        return window
    }

    /// One draw per boundary of the busiest weather, each the frame the old timeline closure chose at that moment.
    func testDrawsOncePerBoundaryWithTheTimelinesFrame() throws {
        let sheet = try SpriteTestAssets.sheet("room-weather")
        let clip = try SpriteTestAssets.clip(sheet, "rainy-night")
        let tracks = [SpriteFrameSchedule.Track(origin: SpriteClock.origin, seconds: clip.seconds, loops: true)]
        let start = SpriteClock.origin.addingTimeInterval(812_345_678.25)
        var clock = start
        let view = SpriteLayerPlayerView()
        view.now = { clock }
        let host = window(holding: view)
        defer { view.stop(); host.close() }

        view.play(tracks: tracks) { date in sheet.frameImage(clip.order[clip.loopStep(at: date, profile: .full)]) }
        let afterPlay = view.drawCount
        while let next = view.nextBoundary, next.timeIntervalSince(start) <= 60 {
            clock = next
            view.tick()
            let expected = sheet.frameImage(clip.order[clip.loopStep(at: next, profile: .full)])
            XCTAssertTrue((view.layer?.contents as CFTypeRef?) === (expected as CFTypeRef?), "frame at \(next)")
        }

        // The same boundaries the budget test counts for this clip, and not one more.
        let entries = SpriteFrameSchedule(tracks: tracks).entries(from: start, mode: .normal)
        _ = entries.next()
        var boundaries = 0
        while let date = entries.next(), date.timeIntervalSince(start) <= 60 { boundaries += 1 }
        XCTAssertEqual(view.drawCount - afterPlay, boundaries)
        XCTAssertGreaterThan(boundaries, 100, "a rain loop should move several times a second")
    }

    /// Out of a window nothing is armed; leaving the window disarms; a caller update redraws at once.
    func testArmsOnlyInsideAWindow() throws {
        let sheet = try SpriteTestAssets.sheet("room-fly")
        let clip = try SpriteTestAssets.clip(sheet, "buzz")
        let tracks = [SpriteFrameSchedule.Track(origin: SpriteClock.origin, seconds: clip.seconds, loops: true)]
        let view = SpriteLayerPlayerView()
        view.play(tracks: tracks) { date in sheet.frameImage(clip.order[clip.loopStep(at: date, profile: .full)]) }
        XCTAssertEqual(view.drawCount, 1)
        XCTAssertNotNil(view.layer?.contents)
        XCTAssertNil(view.nextBoundary, "no timer while the view is not in a window")

        let host = window(holding: view)
        XCTAssertNotNil(view.nextBoundary)
        view.removeFromSuperview()
        XCTAssertNil(view.nextBoundary, "leaving the window stops the timer")
        host.close()
    }

    /// The art never takes a click; the room's hotspots do.
    func testIsInert() {
        XCTAssertNil(SpriteLayerPlayerView().hitTest(.zero))
    }

    /// The pattern that cost 12% of a core never returns: no sprite clip plays through a `TimelineView`.
    func testNoSpriteScheduleDrivesATimelineView() throws {
        for file in try ThemeTokenTests.swiftSources() {
            let code = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
                .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
            XCTAssertFalse(code.contains { $0.contains("TimelineView(SpriteFrameSchedule") }, file.lastPathComponent)
        }
        let room = try String(contentsOf: SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/Sprites/SpriteLayerView.swift"))
        let worm = try String(contentsOf: SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/Views/Common/BookwormView.swift"))
        XCTAssertTrue(room.contains("SpriteLayerPlayer(tracks:"))
        XCTAssertTrue(worm.contains("SpriteLayerPlayer(tracks:"))
    }
}
