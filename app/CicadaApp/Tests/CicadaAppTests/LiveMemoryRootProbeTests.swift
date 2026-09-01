import XCTest
@testable import CicadaApp

/// G88 follow-up, Devin PR #28 round 2 — the live-memory-root override in
/// `ConnectView` used to be ONE `GET /healthz`; if the just-spawned backend
/// wasn't listening yet, the agent setup snippets kept the `installRoot()`
/// guess indefinitely, partially defeating the split-brain fix. The decision
/// logic now lives in `LiveMemoryRootProbe`, a pure type: given a sequence
/// of `/healthz` outcomes, which root do we show and do we ask again?
final class LiveMemoryRootProbeTests: XCTestCase {

    /// The `CICADA_MEMORY_PATH` the Claude Code snippet would show right now.
    private func shownRoot(_ probe: LiveMemoryRootProbe, home: String = "/x/repo") -> String? {
        let agents = AgentSetupCatalog.all(home: home, memoryRoot: probe.liveRoot)
        let cmd = agents.first { $0.id == "claude-code" }?.steps.first?.command ?? ""
        guard let range = cmd.range(of: "CICADA_MEMORY_PATH=") else { return nil }
        return String(cmd[range.upperBound...].prefix { $0 != " " })
    }

    /// Fold a sequence of outcomes and report what the page would show.
    private func show(after outcomes: [LiveMemoryRootProbe.Outcome]) -> String? {
        var probe = LiveMemoryRootProbe()
        for outcome in outcomes { probe.observe(outcome) }
        return shownRoot(probe)
    }

    // MARK: - Before any answer: the guess, and a first retry is armed

    func testStartsOnTheGuessWithTheFirstRetryArmed() {
        let probe = LiveMemoryRootProbe()
        XCTAssertNil(probe.liveRoot)
        XCTAssertEqual(probe.nextDelay, LiveMemoryRootProbe.minDelay)
        XCTAssertEqual(shownRoot(probe), "/x/repo/memory")
    }

    // MARK: - Unreachable backend: retry with capped backoff, never give up

    func testUnreachableBacksOffFromHalfASecondToEightSecondsAndStaysThere() {
        var probe = LiveMemoryRootProbe()
        var delays: [TimeInterval] = []
        for _ in 0..<7 {
            XCTAssertFalse(probe.observe(.unreachable), "a failed probe never changes what's shown")
            delays.append(probe.nextDelay ?? -1)
        }
        XCTAssertEqual(delays, [1, 2, 4, 8, 8, 8, 8])
        XCTAssertNil(probe.liveRoot)
        XCTAssertEqual(shownRoot(probe), "/x/repo/memory", "still the guess while nobody has answered")
    }

    // MARK: - Convergence: the first answer with a root wins and ends the retries

    func testAnswerAfterFailuresAdoptsTheLiveRootAndStopsRetrying() {
        var probe = LiveMemoryRootProbe()
        probe.observe(.unreachable)
        probe.observe(.unreachable)
        XCTAssertTrue(probe.observe(.answered("/live/memory")), "the shown root changed — rebuild the catalog")
        XCTAssertEqual(probe.liveRoot, "/live/memory")
        XCTAssertNil(probe.nextDelay, "converged: nothing left to learn from asking again")
        XCTAssertEqual(shownRoot(probe), "/live/memory")
    }

    func testSameRootAgainIsNotAChange() {
        var probe = LiveMemoryRootProbe()
        probe.observe(.answered("/live/memory"))
        XCTAssertFalse(probe.observe(.answered("/live/memory")))
    }

    func testAnOlderBackendWithoutTheFieldStopsRetryingButKeepsTheGuess() {
        // `/healthz` answered, so the backend is up; asking again can't make
        // the field appear. Only a reconnect (`beginAttempts`) re-asks.
        for answer in [LiveMemoryRootProbe.Outcome.answered(nil), .answered("")] {
            var probe = LiveMemoryRootProbe()
            XCTAssertFalse(probe.observe(answer))
            XCTAssertNil(probe.liveRoot)
            XCTAssertNil(probe.nextDelay)
            XCTAssertEqual(shownRoot(probe), "/x/repo/memory")
        }
    }

    // MARK: - The guess is never re-applied once a live root has been seen

    func testALaterFailureNeverRegressesToTheGuess() {
        XCTAssertEqual(show(after: [.answered("/live/memory"), .unreachable, .unreachable]), "/live/memory")
    }

    func testALaterAnswerWithoutARootNeverRegressesToTheGuess() {
        XCTAssertEqual(show(after: [.answered("/live/memory"), .answered(nil)]), "/live/memory")
        XCTAssertEqual(show(after: [.answered("/live/memory"), .answered("")]), "/live/memory")
    }

    func testAFailureAfterConvergenceDoesNotReopenTheRetryLoop() {
        var probe = LiveMemoryRootProbe()
        probe.observe(.answered("/live/memory"))
        probe.observe(.unreachable)
        XCTAssertNil(probe.nextDelay)
        XCTAssertEqual(probe.liveRoot, "/live/memory")
    }

    // MARK: - Reconnect: ask again, adopt a NEW live root, keep the old one meanwhile

    func testBeginAttemptsRearmsTheScheduleWithoutTouchingTheLiveRoot() {
        var probe = LiveMemoryRootProbe()
        probe.observe(.unreachable)
        probe.observe(.unreachable)
        probe.observe(.unreachable)
        XCTAssertEqual(probe.nextDelay, 4)
        probe.beginAttempts()
        XCTAssertEqual(probe.nextDelay, LiveMemoryRootProbe.minDelay, "a reconnect restarts the backoff from the bottom")
        XCTAssertNil(probe.liveRoot)

        probe.observe(.answered("/live/memory"))
        probe.beginAttempts()
        XCTAssertEqual(probe.liveRoot, "/live/memory", "re-asking keeps the last live root until a new one arrives")
        XCTAssertEqual(probe.nextDelay, LiveMemoryRootProbe.minDelay)
    }

    func testABackendRestartedOnADifferentRootReplacesTheLiveRoot() {
        var probe = LiveMemoryRootProbe()
        probe.observe(.answered("/live/memory"))
        probe.beginAttempts()
        XCTAssertTrue(probe.observe(.answered("/other/memory")))
        XCTAssertEqual(shownRoot(probe), "/other/memory")
        XCTAssertNil(probe.nextDelay)
    }

    // MARK: - End to end: the sequence the reviewer described

    func testTheStartupRaceConvergesOnceTheBackendAnswers() {
        // App launches, spawns the backend, page renders before it listens:
        // three refused connections, then it answers. The page must land on
        // the live root with no user action.
        XCTAssertEqual(
            show(after: [.unreachable, .unreachable, .unreachable, .answered("/live/memory")]),
            "/live/memory"
        )
    }
}
