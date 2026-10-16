import SwiftUI
import XCTest
@testable import CicadaApp

/// Track Z §4.1 (R-A1 amended), and the Sleep redesign (2026-10-16, DESIGN §3.2/§6.5) — the room's sentence, control and
/// whisper keep the 760 pt text column; the art left its card and takes a WHOLE number of points per lattice cell,
/// chosen by the width it may take (5 from 880, 4 from 720, else 3), so a pixel is never resampled (ruling R3).
final class SleepLayoutTests: XCTestCase {

    func test_theColumnIsSevenSixty() {
        XCTAssertEqual(SleepLayout.contentWidth, 760)
        XCTAssertEqual(SleepLayout.artMaxWidth, 880)
    }

    /// The step function, at its edges, and whole points everywhere — never fractional, so a resize never blurs a pixel.
    func test_theArtScaleIsAWholePointStepFunction() {
        XCTAssertEqual(SleepLayout.artScale(columnWidth: 880), 5)
        XCTAssertEqual(SleepLayout.artScale(columnWidth: 879.5), 4)
        XCTAssertEqual(SleepLayout.artScale(columnWidth: 720), 4)
        XCTAssertEqual(SleepLayout.artScale(columnWidth: 719), 3)
        XCTAssertEqual(SleepLayout.artScale(columnWidth: 480), 3)
        var previous: CGFloat = 0
        for tenth in stride(from: 2000, through: 16000, by: 5) {
            let width = CGFloat(tenth) / 10
            let scale = SleepLayout.artScale(columnWidth: width)
            XCTAssertEqual(scale, scale.rounded(), "\(width) — whole points only")
            XCTAssertGreaterThanOrEqual(scale, previous, "\(width) — a wider column never draws a smaller room")
            previous = scale
            if width >= 320 {
                XCTAssertLessThanOrEqual(CGFloat(RoomLattice.cols) * scale, width, "\(width) — the art fits its column")
            }
        }
    }

    /// The layout's own geometry follows the cell: 800 × 320 at 5 pt, every hotspot on whole cells.
    func test_theRoomAtFivePointsIsEightHundredByThreeTwenty() {
        let layout = deskSceneLayout(pixelScale: 5)
        XCTAssertEqual(layout.size, CGSize(width: 800, height: 320))
        for rect in deskHotspots(layout).values {
            XCTAssertEqual(rect.minX.truncatingRemainder(dividingBy: 5), 0)
            XCTAssertEqual(rect.minY.truncatingRemainder(dividingBy: 5), 0)
        }
    }

    /// ColumnLayout for the new page (DESIGN §6.5), at the reference windows: with nothing open the list column IS the
    /// page, and at 1440 and at the 1200 minimum — rail or labelled sidebar — the room draws at 5 pt.
    func test_atTheReferenceWindowsTheRoomIsFivePoints() {
        for (window, nav) in [(1440.0, ShellMetrics.railWidth), (1200.0, ShellMetrics.railWidth),
                              (1200.0, ShellMetrics.sidebarWidth)] {
            let plan = ColumnLayout.plan(contentWidth: window - nav, navWidth: nav, scale: 1,
                                         hasDetail: false, hasTrailing: false)
            XCTAssertEqual(plan.listStyle, .wide)
            let art = min(plan.list - 2 * plan.gutter, SleepLayout.artMaxWidth)
            XCTAssertEqual(SleepLayout.artScale(columnWidth: art), 5, "\(window) with a \(nav) pt rail")
        }
    }

    /// An open saved item (STATE 1) collapses the list to the triage column — 328 at 1440, 280 at 1200 — and the
    /// detail keeps the question's floor (DR-27); the Reader beside the room still leaves it a whole-point scale.
    func test_anOpenItemIsTheTriageColumnAtFourteenFortyAndTwelveHundred() {
        let wide = ColumnLayout.plan(contentWidth: 1440 - 56, navWidth: 56, scale: 1, hasDetail: true, hasTrailing: false)
        XCTAssertEqual(wide.listStyle, .triage)
        XCTAssertEqual(wide.list, 328)
        XCTAssertGreaterThanOrEqual(wide.detail, ColumnLayout.minQuestion)
        let narrow = ColumnLayout.plan(contentWidth: 1200 - 56, navWidth: 56, scale: 1, hasDetail: true, hasTrailing: false)
        XCTAssertEqual(narrow.listStyle, .triage)
        XCTAssertEqual(narrow.list, 280)
        let reader = ColumnLayout.plan(contentWidth: 1200 - 208, navWidth: 208, scale: 1.4, hasDetail: false, hasTrailing: true)
        let art = min(reader.list - 2 * reader.gutter, SleepLayout.artMaxWidth)
        XCTAssertLessThanOrEqual(CGFloat(RoomLattice.cols) * SleepLayout.artScale(columnWidth: art), max(art, 320))
    }
}

/// The page's tabs (DESIGN §3.4, §3.5): which show, which opens, and where a choice falls back.
final class SleepTabTests: XCTestCase {
    func test_waitingHidesAtZeroAndVideosOnlyWithAVideo() {
        XCTAssertEqual(SleepTab.visible(waitingHasRows: true, videos: 6), [.waiting, .saved, .videos, .pastReads])
        XCTAssertEqual(SleepTab.visible(waitingHasRows: false, videos: 0), [.saved, .pastReads])
    }

    func test_thePageOpensOnWaitingWhileAnythingWaitsElsePastReads() {
        XCTAssertEqual(SleepTab.resolve(chosen: nil, waitingHasRows: true, videos: 0), .waiting)
        XCTAssertEqual(SleepTab.resolve(chosen: nil, waitingHasRows: false, videos: 0), .pastReads)
    }

    func test_aChoiceWinsWhileItsTabShowsAndFallsBackWhenItHides() {
        XCTAssertEqual(SleepTab.resolve(chosen: .saved, waitingHasRows: true, videos: 0), .saved)
        XCTAssertEqual(SleepTab.resolve(chosen: .videos, waitingHasRows: true, videos: 0), .waiting,
                       "the last video went: the page's own tab, never an undrawn list")
        XCTAssertEqual(SleepTab.resolve(chosen: .waiting, waitingHasRows: false, videos: 2), .pastReads)
    }

    func test_onlyTheSavedListsHaveFind() {
        XCTAssertEqual(SleepTab.allCases.filter(\.hasFind), [.saved, .videos])
    }

    func test_theTabsCarryTheirCountsAndPastReadsNone() {
        let tabs = SleepTabRow.tabs([.waiting, .saved, .videos, .pastReads], waiting: 42, saved: 318, videos: 6)
        XCTAssertEqual(tabs.map(\.label), ["Waiting", "Saved", "Videos", "Past reads"])
        XCTAssertEqual(tabs.map(\.count), [42, 318, 6, nil])
        XCTAssertEqual(SavedViewMenu.label(kind: nil), "View")
        XCTAssertEqual(SavedViewMenu.label(kind: .paper), "View · Papers")
    }

    /// DR-25/DR-26 — the eyebrow replaced the "Sleep Cycle" title.
    func test_theEyebrowSaysWhatWaitsAndWhenItLastRead() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let twoHours = ISO8601DateFormatter().string(from: now.addingTimeInterval(-2 * 3_600))
        XCTAssertEqual(SleepEyebrow.text(waiting: 42, lastSleepAt: twoHours, now: now),
                       "Sleep · 42 waiting · last read 2 h ago")
        XCTAssertEqual(SleepEyebrow.text(waiting: 0, lastSleepAt: nil, now: now), "Sleep · nothing waiting")
        XCTAssertEqual(SleepEyebrow.text(waiting: 1_200, lastSleepAt: nil, now: now),
                       "Sleep · \(UsageFormat.count(1_200)) waiting", "counts go through UsageFormat (DR-21)")
        XCTAssertEqual(SleepEyebrow.ago(now.addingTimeInterval(-30), now: now), "just now")
        XCTAssertEqual(SleepEyebrow.ago(now.addingTimeInterval(-12 * 60), now: now), "12 min ago")
        XCTAssertEqual(SleepEyebrow.ago(now.addingTimeInterval(-3 * 86_400), now: now), "3 days ago")
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
