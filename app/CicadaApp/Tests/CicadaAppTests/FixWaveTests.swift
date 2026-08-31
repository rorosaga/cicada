import XCTest
@testable import CicadaApp

/// Pinning tests for the 2026-08-31 post-review fix wave
/// (`.superpowers/sdd/2026-08-31-ui-round-2/final-review.md`): H1, M1, M3,
/// and the Feed sort picker's missing accessibility label. M2 is pinned
/// alongside its sibling tests in `UsageRangeTests.swift`.
final class FixWaveTests: XCTestCase {

    /// Reads a file under `Sources/CicadaApp/`, resolved from this test
    /// file's own path (mirrors `ThemeTokenTests.swiftSources()`) so it works
    /// from any working directory.
    private func sourceFile(_ relativePath: String) throws -> String {
        let testFile = URL(fileURLWithPath: #filePath)
        let packageRoot = testFile
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp package root
        let url = packageRoot
            .appendingPathComponent("Sources/CicadaApp")
            .appendingPathComponent(relativePath)
        return try String(contentsOf: url, encoding: .utf8)
    }

    // MARK: H1 — one trigger, one count

    /// `SleepQueueCard` is now the page's sole "Consolidate now" control
    /// (spec §2.8/§2.9 — "one voice"). `SleepView`'s own progress-card
    /// button must be gone entirely, not just disabled differently.
    func testSleepViewNoLongerDefinesItsOwnConsolidateButton() throws {
        let text = try sourceFile("Views/Sleep/SleepView.swift")
        XCTAssertFalse(text.contains("Copy.consolidateNow"),
                       "SleepView must not re-declare a second Consolidate now control — SleepQueueCard is the sole trigger")
        XCTAssertFalse(text.contains("sleepVM.triggerManually()"),
                       "SleepView must not call triggerManually() directly any more")
    }

    /// `SleepQueueCard` (reads `store.status.episodes.unprocessed`, SSE-live)
    /// and the page's own "EPISODES QUEUED (n)" header (used to read
    /// `sleepVM.episodes`, fetched once per visit) must agree. Pulled out as
    /// a pure function on `SleepView` so the precedence — live status wins,
    /// the once-per-visit count is only a pre-first-snapshot fallback — is
    /// unit-testable without standing up a view.
    func testQueueCountPrefersLiveStatusOverTheStaleFetch() {
        let status = StatusSnapshot(
            sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
            inbox: .init(total: 0, byKind: [:]),
            episodes: .init(unprocessed: 3, lastIngestedAt: nil),
            lastSleepAt: nil, nextSleepAt: nil)

        XCTAssertEqual(SleepView.queueCount(status: status, fallback: 0), 3,
                       "an SSE-live status snapshot must win over the stale sleepVM count")
        XCTAssertEqual(SleepView.queueCount(status: nil, fallback: 5), 5,
                       "before the first status snapshot arrives, fall back to sleepVM's count")
    }

    // MARK: PR #19 review — queue count/rows reconcile trigger

    /// Even after the H1 fix above, the header COUNT and the queue ROWS were
    /// still two different freshness models: the header reads SSE-live
    /// `store.status`, the rows are `sleepVM.episodes` fetched once per
    /// visit. A capture landing while the page is open bumps the live count
    /// without touching the rows — contradictory totals and contents. The
    /// reconcile trigger must fire whenever they disagree, in EITHER
    /// direction (a new capture bumping the count up, or another Sleep
    /// cycle finishing elsewhere and draining it down), and never spin on a
    /// missing snapshot.
    func testQueueNeedsReconcileFiresWhenLiveCountDisagreesWithLoadedRows() {
        XCTAssertTrue(SleepView.queueNeedsReconcile(liveUnprocessed: 3, loadedQueuedCount: 2),
                      "a new capture bumped the live count above the loaded rows — must refetch")
        XCTAssertTrue(SleepView.queueNeedsReconcile(liveUnprocessed: 0, loadedQueuedCount: 2),
                      "another Sleep cycle drained the queue elsewhere — must refetch")
        XCTAssertFalse(SleepView.queueNeedsReconcile(liveUnprocessed: 2, loadedQueuedCount: 2),
                       "counts agree — no refetch owed")
        XCTAssertFalse(SleepView.queueNeedsReconcile(liveUnprocessed: nil, loadedQueuedCount: 2),
                       "no status snapshot yet — queueCount already falls back to the loaded rows, nothing to disagree with")
    }

    // MARK: M1 — advanced view spinner during month reconcile

    /// The old guard was `viewModel.isLoadingRange` alone, which is
    /// exclusively a *non-month* flag — the default month view's `stats`
    /// reads straight from `store.consumption` and is `nil` on a first-ever
    /// launch or after a bank switch, so the panel fell through to
    /// "No usage in this range" mid-reconcile.
    func testUsageAdvancedShowsProgressWhileEitherLoadingFlagIsSet() {
        XCTAssertTrue(UsageAdvancedView.showsProgress(isLoadingRange: true, isLoading: false))
        XCTAssertTrue(UsageAdvancedView.showsProgress(isLoadingRange: false, isLoading: true))
        XCTAssertFalse(UsageAdvancedView.showsProgress(isLoadingRange: false, isLoading: false))
    }

    // MARK: M3 — Settings scene re-paints on theme toggle

    /// `ContentView.swift` documents (and works around) the fact that
    /// `CicadaTheme.*` are static reads SwiftUI doesn't track: it keys its
    /// subtree on `.id(colorSchemeRaw)` alongside `.preferredColorScheme`.
    /// The Settings scene needs the identical pairing or it keeps a stale
    /// palette after a theme toggle while the window is open.
    func testSettingsSceneIsKeyedOnTheColorScheme() throws {
        let text = try sourceFile("CicadaApp.swift")
        guard let settingsRange = text.range(of: "Settings {") else {
            XCTFail("Settings scene not found in CicadaApp.swift")
            return
        }
        let tail = String(text[settingsRange.lowerBound...])
        XCTAssertTrue(tail.contains(".preferredColorScheme"),
                      "precondition: the Settings scene still sets .preferredColorScheme")
        XCTAssertTrue(tail.contains(".id(colorSchemeRaw)"),
                      "Settings scene must key its subtree on colorSchemeRaw, matching ContentView's workaround")
    }

    // MARK: Low — Feed sort picker accessibility label

    /// Every other segmented control on the restructured pages (Activity,
    /// Usage range, Usage mode) got an `.accessibilityLabel`; the Feed sort
    /// control was the one VoiceOver couldn't name.
    func testFeedSortPickerHasAnAccessibilityLabel() throws {
        let text = try sourceFile("Views/Feed/FeedView.swift")
        guard let pickerRange = text.range(of: "viewModel.sort = $0") else {
            XCTFail("Feed sort picker not found in FeedView.swift")
            return
        }
        let tail = String(text[pickerRange.lowerBound...].prefix(400))
        XCTAssertTrue(tail.contains(".accessibilityLabel("),
                      "the Feed sort picker needs an accessibility label")
    }
}
