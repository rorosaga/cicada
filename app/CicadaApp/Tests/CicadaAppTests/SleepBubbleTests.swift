import XCTest
@testable import CicadaApp

/// G125 Task 5: the speech bubble's copy is pure and clock-free (R8) — same
/// state + same context always produces the same sentence, every line stays
/// under the 60-char budget the bubble's `frame(maxWidth: 260)` was sized
/// for, and the two states that read live numbers (`reading`, `sleeping`
/// stage 1) actually show them.
final class SleepBubbleTests: XCTestCase {

    private let allStates: [BookwormState] = [
        .awake, .reading, .sleeping(stage: 1), .sleeping(stage: 2), .sleeping(stage: 3),
        .sleeping(stage: 4), .sleeping(stage: 5), .digesting, .happy, .curious(count: 3),
        .hungry, .error,
    ]

    func testEveryStateProducesNonEmptyTextUnder60Chars() {
        let ctx = BubbleContext(unprocessed: 4, topOriginLabel: "Safari tab", topOriginCount: 2,
                                 stage: 1, read: 2, total: 4, hoursSinceLastCycle: 10)
        for state in allStates {
            let text = sleepBubbleText(state, ctx)
            XCTAssertFalse(text.isEmpty, state.caseName)
            XCTAssertLessThanOrEqual(text.count, 60, "\(state.caseName): '\(text)' (\(text.count) chars)")
        }
    }

    func testReadingNamesTheCountAndTheTopOrigin() {
        let ctx = BubbleContext(unprocessed: 188, topOriginLabel: "Safari tab", topOriginCount: 120)
        let text = sleepBubbleText(.reading, ctx)
        XCTAssertTrue(text.contains("188"), text)
        XCTAssertTrue(text.contains("Safari tab"), text)
    }

    func testReadingWithNoTopOriginStillNamesTheCount() {
        let ctx = BubbleContext(unprocessed: 4)
        let text = sleepBubbleText(.reading, ctx)
        XCTAssertTrue(text.contains("4"), text)
    }

    /// A queue of 0 with `.reading` only happens while `intakeInFlight` is
    /// true and the fetch hasn't caught up — the line should read as
    /// something just arrived, not "0 to read".
    func testReadingWithZeroUnprocessedReadsAsSomethingJustArrived() {
        let text = sleepBubbleText(.reading, BubbleContext(unprocessed: 0))
        XCTAssertEqual(text, "Something new just landed. Let me look.")
    }

    func testSleepingStageOneNamesReadAndTotal() {
        let ctx = BubbleContext(stage: 1, read: 12, total: 188)
        let text = sleepBubbleText(.sleeping(stage: 1), ctx)
        XCTAssertTrue(text.contains("12"), text)
        XCTAssertTrue(text.contains("188"), text)
    }

    func testSleepingStageOneWithNoTotalYetStillReturnsSomething() {
        let text = sleepBubbleText(.sleeping(stage: 1), BubbleContext())
        XCTAssertEqual(text, "Reading…")
    }

    func testHungryNamesDaysWhenGapIsLongAndNeverExclaims() {
        let text = sleepBubbleText(.hungry, BubbleContext(unprocessed: 9, hoursSinceLastCycle: 72))
        XCTAssertTrue(text.contains("3 days"), text)
        XCTAssertFalse(text.contains("!"), text)
    }

    func testHungryWithoutALongGapNeverExclaimsEither() {
        for n in [3, 4] {
            let text = sleepBubbleText(.hungry, BubbleContext(unprocessed: n, hoursSinceLastCycle: 1))
            XCTAssertFalse(text.contains("!"), text)
        }
    }

    func testErrorNeverExclaims() {
        XCTAssertFalse(sleepBubbleText(.error, BubbleContext()).contains("!"))
    }

    func testSameInputsAlwaysProduceTheSameString() {
        let ctx = BubbleContext(unprocessed: 17, topOriginLabel: "Telegram", topOriginCount: 5, stage: 2)
        for state in allStates {
            XCTAssertEqual(sleepBubbleText(state, ctx), sleepBubbleText(state, ctx), state.caseName)
        }
    }

    /// R8: the variant is a pure function of the inputs already in hand — no
    /// hidden clock or RNG — so different counts MAY pick a different line
    /// (this only asserts determinism, never that they must differ).
    func testReadingVariantIsDeterministicAcrossNearbyCounts() {
        let five = sleepBubbleText(.reading, BubbleContext(unprocessed: 5))
        let six = sleepBubbleText(.reading, BubbleContext(unprocessed: 6))
        XCTAssertEqual(five, sleepBubbleText(.reading, BubbleContext(unprocessed: 5)))
        XCTAssertEqual(six, sleepBubbleText(.reading, BubbleContext(unprocessed: 6)))
    }
}
