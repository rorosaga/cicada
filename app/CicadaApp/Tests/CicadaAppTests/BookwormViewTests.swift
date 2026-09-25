import XCTest
@testable import CicadaApp

/// G107: the page mascot's frame is a pure function of the clock, so a
/// `TimelineView` tick needs no stored state, two mascots on screen stay in
/// step, and Reduce Motion is a single early return (ruling R7).
final class BookwormViewTests: XCTestCase {

    private func at(_ seconds: TimeInterval) -> Date { Date(timeIntervalSinceReferenceDate: seconds) }

    func testFrameAdvancesOncePerIntervalAndWraps() {
        XCTAssertEqual(BookwormView.frameIndex(at: at(0), interval: 0.5, count: 4, reduceMotion: false), 0)
        XCTAssertEqual(BookwormView.frameIndex(at: at(0.49), interval: 0.5, count: 4, reduceMotion: false), 0)
        XCTAssertEqual(BookwormView.frameIndex(at: at(0.5), interval: 0.5, count: 4, reduceMotion: false), 1)
        XCTAssertEqual(BookwormView.frameIndex(at: at(1.75), interval: 0.5, count: 4, reduceMotion: false), 3)
        XCTAssertEqual(BookwormView.frameIndex(at: at(2.0), interval: 0.5, count: 4, reduceMotion: false), 0)
    }

    func testReduceMotionHoldsFrameZero() {
        XCTAssertEqual(BookwormView.frameIndex(at: at(1.75), interval: 0.5, count: 4, reduceMotion: true), 0)
    }

    func testDegenerateInputsNeverCrash() {
        XCTAssertEqual(BookwormView.frameIndex(at: at(3), interval: 0.5, count: 0, reduceMotion: false), 0)
        XCTAssertEqual(BookwormView.frameIndex(at: at(3), interval: 0, count: 4, reduceMotion: false), 0)
        XCTAssertEqual(BookwormView.frameIndex(at: at(-1.2), interval: 0.5, count: 4, reduceMotion: false), 1)
    }

    /// Page sizes are multiples of 24 so every sprite cell is an integer
    /// number of points (ruling R3) — the sizes the call sites use.
    func testPageSizesAreWholeCells() {
        for size in [48, 96, 120] as [CGFloat] {
            XCTAssertEqual(size.truncatingRemainder(dividingBy: 24), 0, "\(size)")
        }
    }

    /// G130 R6: the mascot snaps its SCALED size back onto a multiple of 24
    /// (`max(24, 24 · round(x / 24))`) so ⌘+/⌘− never leaves a sprite cell a
    /// fractional point and the cache key — an `Int` — stays stable.
    func testSnappedPointSizeRoundsToTheNearestCellMultiple() {
        XCTAssertEqual(BookwormRenderer.snappedPointSize(120), 120, "already on a cell boundary")
        XCTAssertEqual(BookwormRenderer.snappedPointSize(120 * 1.1), 144, "132 rounds up (schoolbook 5.5 -> 6)")
        XCTAssertEqual(BookwormRenderer.snappedPointSize(120 * 0.8), 96, "96 is already a multiple of 24")
        XCTAssertEqual(BookwormRenderer.snappedPointSize(10), 24, "the floor is one cell, never zero")
    }
}
