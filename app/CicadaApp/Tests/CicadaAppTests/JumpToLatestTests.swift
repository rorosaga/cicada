import XCTest
@testable import CicadaApp

/// Owner 2026-11-23: every chat glides back to its newest message, "fast but smooth", faster the further it is.
@MainActor
final class JumpToLatestTests: XCTestCase {
    func testALongerWayTakesLongerButMovesFaster() {
        let near = CicadaMotion.jumpToLatestDuration(distance: 2_000)
        let far = CicadaMotion.jumpToLatestDuration(distance: 20_000)
        XCTAssertGreaterThan(far, near)
        XCTAssertGreaterThan(20_000 / far, 2_000 / near, "points per second grow with the distance")
    }

    func testTheGlideStaysUnderTheMotionCeiling() {
        for d in [0, 500, 5_000, 50_000, 5_000_000] as [CGFloat] {
            XCTAssertLessThanOrEqual(CicadaMotion.jumpToLatestDuration(distance: d), CicadaMotion.maxDuration)
            XCTAssertGreaterThan(CicadaMotion.jumpToLatestDuration(distance: d), 0)
        }
    }

    func testTheButtonShowsOnlyWellAboveTheNewestMessage() {
        XCTAssertFalse(JumpToLatest.isAway(distanceFromEnd: 0))
        XCTAssertFalse(JumpToLatest.isAway(distanceFromEnd: CicadaTheme.scaled(JumpToLatest.threshold)))
        XCTAssertTrue(JumpToLatest.isAway(distanceFromEnd: CicadaTheme.scaled(JumpToLatest.threshold) + 1))
        XCTAssertTrue(JumpToLatest.isAway(distanceFromEnd: 5_000))
    }

    /// The scroll view itself says where it is (2026-11-25): a real `NSScrollView` moved in one step away from its end
    /// and back — the case two SwiftUI measures got wrong — tells the chat each crossing, once.
    func testTheScrollViewsOwnDistanceFromItsEndDrivesTheButton() async throws {
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 300, height: 400))
        let document = FlippedView(frame: NSRect(x: 0, y: 0, width: 300, height: 4_000))
        scroll.documentView = document
        let clip = scroll.contentView
        func move(toDistanceFromEnd d: CGFloat) async {
            clip.setBoundsOrigin(NSPoint(x: 0, y: document.frame.height - clip.bounds.height - d))
            scroll.reflectScrolledClipView(clip)
            for _ in 0..<3 { await Task.yield(); try? await Task.sleep(nanoseconds: 20_000_000) }
        }
        await move(toDistanceFromEnd: 0)
        let scroller = JumpToLatestScroller()
        var told: [Bool] = []
        scroller.scrollView = scroll
        scroller.onAway = { told.append($0) }
        await move(toDistanceFromEnd: 0)
        XCTAssertEqual(told, [false], "at the end: said once, not away")
        await move(toDistanceFromEnd: 500)
        await move(toDistanceFromEnd: 0)
        await move(toDistanceFromEnd: 2_000)
        await move(toDistanceFromEnd: 2_100)
        await move(toDistanceFromEnd: 40)
        XCTAssertEqual(told, [false, true, false, true, false], "each crossing once, in one step either way")
        // Content that grows while the view stays put is away; scrolled to its new end in the same pass, it is not.
        document.setFrameSize(NSSize(width: 300, height: 4_600))
        clip.setBoundsOrigin(NSPoint(x: 0, y: 4_600 - clip.bounds.height))
        await move(toDistanceFromEnd: 0)
        XCTAssertEqual(told.last, false)
        XCTAssertEqual(told.count, 5, "a line appended to a chat pinned to its end never flashes the button")
    }

    /// The newest message is where the anchor is, not where the document ends (the Reader draws more under a
    /// conversation); and a chat whose lazy stack dropped the anchor is away.
    func testTheAnchorsOwnPlaceInTheDocumentIsTheMeasure() async throws {
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 300, height: 400))
        let document = FlippedView(frame: NSRect(x: 0, y: 0, width: 300, height: 4_000))
        scroll.documentView = document
        let clip = scroll.contentView
        func show(bottom: CGFloat) async {
            clip.setBoundsOrigin(NSPoint(x: 0, y: bottom - clip.bounds.height))
            scroll.reflectScrolledClipView(clip)
            for _ in 0..<3 { await Task.yield(); try? await Task.sleep(nanoseconds: 20_000_000) }
        }
        let scroller = JumpToLatestScroller()
        var told: [Bool] = []
        scroller.scrollView = scroll
        scroller.onAway = { told.append($0) }
        let probe = JumpToLatestAnchorProbe(frame: NSRect(x: 0, y: 3_000, width: 300, height: 1))
        document.addSubview(probe)                    // the newest message ends at 3,000; 1,000 pt more are drawn under it
        await show(bottom: 3_020)
        XCTAssertEqual(told.last, false, "the newest message is on screen, whatever is drawn under it")
        await show(bottom: 4_000)
        XCTAssertEqual(told.last, false, "under the newest message is not away from it")
        await show(bottom: 2_800)
        XCTAssertEqual(told.last, true)
        await show(bottom: 3_000 - CicadaTheme.scaled(JumpToLatest.threshold) + 1)
        XCTAssertEqual(told.last, false, "inside the threshold")
        probe.setFrameOrigin(NSPoint(x: 0, y: 3_600))  // messages arrived: the anchor moved, the view did not
        for _ in 0..<3 { await Task.yield(); try? await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertEqual(told.last, true)
        await show(bottom: 3_600)
        XCTAssertEqual(told.last, false)
        probe.removeFromSuperview()                    // the lazy stack dropped the anchor's row
        for _ in 0..<3 { await Task.yield(); try? await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertEqual(told.last, true, "a chat that had an anchor and has none now is away")
        // An old anchor dying after its replacement arrived changes nothing.
        let next = JumpToLatestAnchorProbe(frame: NSRect(x: 0, y: 3_600, width: 300, height: 1))
        let old = JumpToLatestAnchorProbe(frame: NSRect(x: 0, y: 100, width: 300, height: 1))
        document.addSubview(old)
        document.addSubview(next)
        for _ in 0..<3 { await Task.yield(); try? await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertEqual(told.last, false)
        old.removeFromSuperview()
        for _ in 0..<3 { await Task.yield(); try? await Task.sleep(nanoseconds: 20_000_000) }
        XCTAssertEqual(told.last, false, "the listed anchor still stands")
    }
}

private final class FlippedView: NSView {
    override var isFlipped: Bool { true }
}
