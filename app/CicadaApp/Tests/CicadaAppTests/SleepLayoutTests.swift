import SwiftUI
import XCTest
@testable import CicadaApp

/// G125 v3 Task 7 — the page's two-column arrangement, as a pure function of
/// the width it is given. The reflow boundary is NAMED here rather than left
/// to a `>` buried in a `body`, so "what happens at exactly 1000 pt" has an
/// answer a reader can check.
final class SleepLayoutTests: XCTestCase {

    func test_sleepLayout_isTwoColumnAtAComfortableWidth() {
        XCTAssertTrue(sleepLayout(width: 1200).isTwoColumn)
    }

    func test_sleepLayout_stacksBelowTheBoundary() {
        XCTAssertFalse(sleepLayout(width: 999).isTwoColumn)
        XCTAssertFalse(sleepLayout(width: 640).isTwoColumn)
    }

    /// The boundary is inclusive, and it is asserted rather than guessed: a
    /// reflow that happens at 1000 in one build and 1001 in the next is the
    /// kind of drift only a test at the exact value catches.
    func test_sleepLayout_theBoundaryItselfIsTwoColumn() {
        XCTAssertEqual(SleepLayout.twoColumnMinWidth, 1000)
        XCTAssertTrue(sleepLayout(width: SleepLayout.twoColumnMinWidth).isTwoColumn)
    }

    /// `maxContentWidth` is part of the layout, not a leftover literal in the
    /// body: the stacked page keeps the 760 pt column it has always had, and
    /// the two-column page needs a cap no two columns could fit inside.
    func test_sleepLayout_carriesTheContentCapForBothArrangements() {
        XCTAssertEqual(sleepLayout(width: 999).maxContentWidth, 760)
        XCTAssertGreaterThan(sleepLayout(width: 1200).maxContentWidth, 1000)
    }

    /// Stacked means one column of full width — a fraction below 1 there would
    /// silently narrow the hero on a small window.
    func test_sleepLayout_leftFractionIsTheWholeWidthWhenStacked() {
        XCTAssertEqual(sleepLayout(width: 999).leftFraction, 1.0, accuracy: 1e-9)
    }

    /// Roughly two thirds — the hero, the room and the queue are the page's
    /// subject; memory sources and past cycles are its margin.
    func test_sleepLayout_leftColumnIsTheWiderOneWhenSideBySide() {
        let fraction = sleepLayout(width: 1200).leftFraction
        XCTAssertGreaterThan(fraction, 0.55)
        XCTAssertLessThan(fraction, 0.75)
    }

    /// Stacked means there is nothing to divide — `nil`, so a caller cannot
    /// accidentally pin a one-column page to two thirds of itself.
    func test_leftColumnWidth_isNilWhenStacked() {
        XCTAssertNil(sleepLayout(width: 900).leftColumnWidth(available: 900, padding: 24, gutter: 16))
    }

    /// The two columns plus the gutter fit inside the content cap, and the left
    /// one lands near the 760 pt the single column has always had — the point
    /// of the wider cap.
    func test_leftColumnWidth_fitsInsideTheCapAndKeepsTheOldColumnWidth() {
        let layout = sleepLayout(width: 1400)
        guard let left = layout.leftColumnWidth(available: 1400, padding: 24, gutter: 16) else {
            return XCTFail("a two-column layout must have a left width")
        }
        let content = layout.maxContentWidth - 48 - 16
        XCTAssertLessThan(left, content)
        XCTAssertEqual(left, content * layout.leftFraction, accuracy: 0.001)
        XCTAssertGreaterThan(left, 700)
    }

    /// A width of zero arrives on the first layout pass of a freshly opened
    /// window; it must not read as "narrow, therefore stacked and then reflow
    /// a frame later" — but it must never be two columns either, because a
    /// zero-width two-column split would divide a zero.
    func test_sleepLayout_zeroWidthStacks() {
        XCTAssertFalse(sleepLayout(width: 0).isTwoColumn)
        XCTAssertEqual(sleepLayout(width: 0).maxContentWidth, 760)
    }
}

/// G125 v3 Task 8 — the page's liveness, as a pure function of the connection,
/// the last successful refresh and whether there is already news on screen.
///
/// The rule under test is R-A12: a disconnected page is *shown*, one
/// desaturation step down with an `as of HH:MM` chip that dates it — never
/// blanked, never faked — and the **error state is exempt**, because an error
/// banner at 85% saturation is news whispered.
final class SleepLivenessTests: XCTestCase {

    private let then = Date(timeIntervalSinceReferenceDate: 800_000_000)
    /// A `now` far enough past `then` to clear `SleepLiveness.staleAfter` —
    /// i.e. the backend really has gone quiet, not merely lost its stream.
    private var wellAfter: Date { then.addingTimeInterval(SleepLiveness.staleAfter + 1) }

    func test_connected_isLive() {
        XCTAssertEqual(sleepLiveness(isConnected: true, refreshedAt: then, isError: false, now: wellAfter),
                       .live)
    }

    /// The only stale case: the backend is gone, it had at some point
    /// confirmed what is on screen — a real timestamp to date the page by —
    /// and that confirmation is now older than `staleAfter`.
    func test_disconnectedWithARefreshedAt_isStaleAndCarriesThatDate() {
        XCTAssertEqual(sleepLiveness(isConnected: false, refreshedAt: then, isError: false, now: wellAfter),
                       .stale(asOf: then))
    }

    /// R-A12: news stays at full contrast. The error meant here is a failed
    /// **cycle** (`SleepViewModel.lastError`, i.e. `status.error`) — something
    /// the reader can act on — and it is the one thing on the page that must
    /// not read as "probably out of date".
    func test_disconnectedWithAFailedCycle_staysLive() {
        XCTAssertEqual(sleepLiveness(isConnected: false, refreshedAt: then, isError: true, now: wellAfter),
                       .live)
    }

    /// The round-1 regression, pinned. A stopped backend makes every `load()`
    /// fetch fail, which sets `SleepViewModel.errorMessage` — a *transport*
    /// failure, not news. If that were routed into `isError`, this page would
    /// report itself `.live` in the exact state liveness exists for, and would
    /// flip back and forth as fetches succeeded and failed. Only the caller
    /// can confuse the two, so this test states the contract the call site
    /// must honour: disconnected + a real `refreshedAt` + no cycle failure is
    /// ALWAYS `.stale`.
    func test_disconnectedWithOnlyAFailedFetch_isStill_stale() {
        XCTAssertEqual(sleepLiveness(isConnected: false, refreshedAt: then, isError: false, now: wellAfter),
                       .stale(asOf: then))
        XCTAssertEqual(SleepLiveness.stale(asOf: then).saturation,
                       SleepLiveness.staleSaturation,
                       accuracy: 1e-9)
        XCTAssertNotNil(SleepLiveness.stale(asOf: then).asOf)
    }

    /// The backend has never confirmed anything, so there is no hour to
    /// print. A chip reading "as of 00:00" would be a fabricated timestamp —
    /// the same refusal `—` carries everywhere else on this page (P18).
    ///
    /// Review round 2: this refusal was reachable only in theory, because the
    /// call site passed `Snapshot.loadedAt`, which a disk hydrate stamps, so a
    /// cold launch against a stopped backend printed the launch minute. The
    /// argument is `refreshedAt` now, and
    /// `StoreTests.testDiskHydrateLeavesRefreshedAtNilSoTheStalenessChipHasNoHourToFabricate`
    /// pins that a hydrate really does leave it nil.
    func test_disconnectedWithNothingEverConfirmed_staysLive() {
        XCTAssertEqual(sleepLiveness(isConnected: false, refreshedAt: nil, isError: false, now: wellAfter),
                       .live)
    }

    /// Final review, finding 1 — the regression this threshold exists for.
    ///
    /// `store.isConnected` means "the SSE stream is open", not "the backend is
    /// alive": `SyncEngine.start` holds it false for the whole reconnect
    /// backoff while the loop inside that window is still polling a healthy
    /// backend every 3 s. Keying the chip off the flag alone printed
    /// "Not connected — showing the last reading · as of 16:12" with 16:12
    /// seconds old, on every backend restart. A confirmation younger than
    /// `staleAfter` is not stale, whatever the transport says.
    func test_aRecentConfirmationIsNotStaleEvenWhileTheStreamIsDown() {
        let duringBackoff = then.addingTimeInterval(SyncEngine.maxBackoff)
        XCTAssertLessThan(SyncEngine.maxBackoff, SleepLiveness.staleAfter,
                          "the threshold must clear the transport's own worst-case silence")
        XCTAssertEqual(sleepLiveness(isConnected: false, refreshedAt: then, isError: false, now: duringBackoff),
                       .live,
                       "a dropped stream over a backend that answered a moment ago is not staleness")
    }

    /// The boundary, both sides of it: `staleAfter` is a strict threshold, so
    /// a confirmation exactly that old is still live and one second older is
    /// not. Pinned so the comparison can't silently become `>=` or lose its
    /// unit.
    func test_theThresholdIsStrictAndMeasuredInSeconds() {
        let exactly = then.addingTimeInterval(SleepLiveness.staleAfter)
        XCTAssertEqual(sleepLiveness(isConnected: false, refreshedAt: then, isError: false, now: exactly),
                       .live)
        XCTAssertEqual(sleepLiveness(isConnected: false, refreshedAt: then, isError: false,
                                     now: exactly.addingTimeInterval(1)),
                       .stale(asOf: then))
    }

    /// ONE desaturation step (R-A12) — a value on the enum rather than a
    /// literal in the body, so "one step" is a number a reader can check.
    func test_oneDesaturationStepAndOnlyWhenStale() {
        XCTAssertEqual(SleepLiveness.live.saturation, 1.0, accuracy: 1e-9)
        XCTAssertEqual(SleepLiveness.stale(asOf: then).saturation, 0.85, accuracy: 1e-9)
        XCTAssertEqual(SleepLiveness.staleSaturation, 0.85, accuracy: 1e-9)
    }

    func test_asOfIsNilWhenLive() {
        XCTAssertNil(SleepLiveness.live.asOf)
        XCTAssertEqual(SleepLiveness.stale(asOf: then).asOf, then)
    }

    /// The chip is ONE number over a page built from several domains, so it
    /// takes the OLDEST reading on screen: claiming the newest would overstate
    /// how fresh the stalest card is.
    func test_stalestRefreshedAt_takesTheOldestAndIgnoresDomainsNeverConfirmed() {
        let older = then.addingTimeInterval(-600)
        XCTAssertEqual(SleepLiveness.stalestRefreshedAt(then, older), older)
        XCTAssertEqual(SleepLiveness.stalestRefreshedAt(nil, then), then)
        XCTAssertNil(SleepLiveness.stalestRefreshedAt(nil, nil))
    }

    /// The chip's wording, with the zone injected so the assertion never
    /// depends on the runner's locale — the same seam
    /// `SleepHistoryPresentation.timeText` opened for exactly this reason.
    func test_asOfChipNamesTheHourAndMinute() {
        var utcNoonish = DateComponents()
        utcNoonish.year = 2026; utcNoonish.month = 9; utcNoonish.day = 5
        utcNoonish.hour = 16; utcNoonish.minute = 12
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let date = cal.date(from: utcNoonish)!
        XCTAssertEqual(Copy.asOf(date, timeZone: TimeZone(identifier: "UTC")!), "as of 16:12")
    }
}
