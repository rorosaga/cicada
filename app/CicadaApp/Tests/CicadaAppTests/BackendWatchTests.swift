import XCTest
@testable import CicadaApp

/// Production blocker (2026-11-06) — the backend that dies under a running app: what the person is told, how soon a
/// backend this app started comes back, and that a page never calls an unread memory empty.
@MainActor
final class BackendWatchTests: XCTestCase {
    private let t0 = Date(timeIntervalSince1970: 1_000_000)
    private func at(_ s: TimeInterval) -> Date { t0.addingTimeInterval(s) }

    // MARK: Reach

    func testNothingIsSaidInTheFirstSecondsOfALaunch() {
        var tracker = BackendReachTracker(now: t0)
        XCTAssertEqual(tracker.observe(.noAnswer, now: at(1)), .up)
        XCTAssertEqual(tracker.observe(.noAnswer, now: at(19)), .up)
        XCTAssertEqual(tracker.observe(.noAnswer, now: at(20)), .notAnswering)
    }

    func testSilenceCountsFromTheLastRealAnswer() {
        var tracker = BackendReachTracker(now: t0)
        tracker.answered(now: at(100))
        XCTAssertEqual(tracker.observe(.noAnswer, now: at(110)), .up)
        XCTAssertEqual(tracker.observe(.noAnswer, now: at(120)), .notAnswering)
    }

    func testItClearsByItselfWhenTheBackendAnswers() {
        var tracker = BackendReachTracker(now: t0)
        XCTAssertEqual(tracker.observe(.noAnswer, now: at(30)), .notAnswering)
        XCTAssertEqual(tracker.observe(.cicada(fullAccess: true), now: at(34)), .up)
    }

    func testASlowAnswerIsNotDownUntilTheSilenceBoundSaysHung() {
        var tracker = BackendReachTracker(now: t0)
        XCTAssertEqual(tracker.observe(.slow, now: at(500)), .up, "a busy backend is not down, however long the wait")
        XCTAssertEqual(tracker.observe(.slow, now: at(7_300), hung: false), .up)
        XCTAssertEqual(tracker.observe(.slow, now: at(7_400), hung: true), .notAnswering)
        XCTAssertEqual(tracker.observe(.slow, now: at(7_404), hung: false), .up, "starting up again is not hung")
    }

    func testAForeignListenerAndARefusedKeyEachNeedTwoLooksInARow() {
        var tracker = BackendReachTracker(now: t0)
        XCTAssertEqual(tracker.observe(.foreign, now: at(1)), .up)
        XCTAssertEqual(tracker.observe(.foreign, now: at(5)), .portHeld)

        tracker = BackendReachTracker(now: t0)
        XCTAssertEqual(tracker.observe(.cicada(fullAccess: false), now: at(1)), .up)
        XCTAssertEqual(tracker.observe(.cicada(fullAccess: false), now: at(5)), .tokenRefused)
        XCTAssertEqual(tracker.observe(.cicada(fullAccess: true), now: at(9)), .up)
    }

    func testTheThreeStatesAreToldApart() {
        var tracker = BackendReachTracker(now: t0)
        tracker.observe(.foreign, now: at(1)); tracker.observe(.foreign, now: at(2))
        XCTAssertEqual(tracker.reach, .portHeld)
        tracker.observe(.cicada(fullAccess: false), now: at(3)); tracker.observe(.cicada(fullAccess: false), now: at(4))
        XCTAssertEqual(tracker.reach, .tokenRefused)
        tracker.observe(.noAnswer, now: at(40))
        XCTAssertEqual(tracker.reach, .notAnswering)
    }

    func testFailuresAreReadAsTheyAre() {
        XCTAssertEqual(BackendReading.classify(error: URLError(.cannotConnectToHost)), .noAnswer)
        XCTAssertEqual(BackendReading.classify(error: URLError(.timedOut)), .slow)
        XCTAssertEqual(BackendReading.classify(error: URLError(.networkConnectionLost)), .slow)
        XCTAssertEqual(BackendReading.classify(error: URLError(.cannotParseResponse)), .foreign)
        XCTAssertEqual(BackendReading.classify(error: APIError.httpError(404, "")), .foreign)
        XCTAssertEqual(BackendReading.classify(error: APIError.decodingError("")), .foreign)
    }

    // MARK: Restart policy

    func testARestartBacksOffAndGivesUp() {
        var policy = BackendRestartPolicy()
        let decisions = (0..<7).map { _ in policy.childEnded(ranFor: 1) }
        XCTAssertEqual(decisions, BackendRestartPolicy.delays.map { .restart(after: $0) } + [.giveUp, .giveUp])
        XCTAssertLessThan(BackendRestartPolicy.delays.reduce(0, +), 150, "bounded: a couple of minutes, not forever")
        XCTAssertEqual(BackendRestartPolicy.delays, BackendRestartPolicy.delays.sorted(), "each wait at least the last")
    }

    func testABackendThatRanWellStartsTheCountAgain() {
        var policy = BackendRestartPolicy()
        for _ in 0..<4 { _ = policy.childEnded(ranFor: 1) }
        XCTAssertEqual(policy.childEnded(ranFor: BackendRestartPolicy.healthyRun), .restart(after: BackendRestartPolicy.delays[0]))
    }

    // MARK: The banner

    func testTheBannerSaysOneThingAndOffersOneAction() {
        func banner(_ reach: BackendReach, retrying: Bool = false, server: Bool = false) -> BackendBanner? {
            BackendBanner.make(reach: reach, retrying: retrying, onServer: server, port: 8123)
        }
        XCTAssertNil(banner(.up))
        XCTAssertEqual(banner(.notAnswering), BackendBanner(line: Copy.Reach.stopped, action: Copy.Reach.restart))
        XCTAssertEqual(banner(.notAnswering, retrying: true), BackendBanner(line: Copy.Reach.restarting, action: nil),
                       "nothing to click while the app is already restarting it")
        XCTAssertEqual(banner(.portHeld)?.line, Copy.Reach.portHeld(8123))
        XCTAssertTrue(Copy.Reach.portHeld(8123).contains("8123"))
        XCTAssertEqual(banner(.tokenRefused)?.line, Copy.Reach.keyRefused)
        XCTAssertEqual(banner(.notAnswering, server: true)?.action, Copy.Reach.tryAgain, "nothing to restart on a server")
        let lines = [BackendReach.notAnswering, .portHeld, .tokenRefused].compactMap { banner($0)?.line }
        XCTAssertEqual(Set(lines).count, 3, "the three states the person can act on differently read differently")
    }

    // MARK: The watch

    func testTheWatchPublishesToTheStoreAndClearsWhenTheBackendAnswers() async {
        var clock = t0
        var readings: [BackendReading] = [.noAnswer, .noAnswer, .cicada(fullAccess: true)]
        var published: [BackendReach] = []
        var silence: [SleepProbe.Answer] = []
        let watch = BackendWatch(
            port: 8000, onServer: false,
            probe: { readings.removeFirst() },
            noteSilence: { silence.append($0); return false },
            publish: { published.append($0) },
            isRetrying: { false }, restart: {},
            now: { clock })
        clock = at(5);  await watch.step()
        XCTAssertEqual(watch.reach, .up)
        clock = at(25); await watch.step()
        XCTAssertEqual(watch.reach, .notAnswering)
        XCTAssertEqual(watch.banner?.line, Copy.Reach.stopped)
        clock = at(29); await watch.step()
        XCTAssertEqual(watch.reach, .up)
        XCTAssertNil(watch.banner)
        XCTAssertEqual(published, [.notAnswering, .up])
        XCTAssertEqual(silence, [.noAnswer, .noAnswer, .idle], "every look goes to the one silence bound")
    }

    func testTheBannersButtonRestartsThenLooksAtOnce() async {
        var order: [String] = []
        let watch = BackendWatch(
            port: 8000, onServer: false,
            probe: { order.append("look"); return .noAnswer },
            noteSilence: { _ in false }, publish: { _ in },
            isRetrying: { false }, restart: { order.append("restart") })
        await watch.fix()
        XCTAssertEqual(order, ["restart", "look"])
    }

    // MARK: Pages never call an unread memory empty

    private func tempCache() -> SnapshotCache {
        SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString))
    }

    func testAFailedReadOrAnUnansweringBackendIsNotAnEmptyMemory() async {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        XCTAssertFalse(store.couldNotRead(.graph), "before anything failed, nothing is claimed")

        api.replies[.graph] = .failure
        await store.refresh([.graph])
        XCTAssertTrue(store.couldNotRead(.graph))
        XCTAssertFalse(store.couldNotRead(.inbox), "a different domain's failure is not this one's")
        XCTAssertEqual(store.domainErrors[.graph], Copy.Reach.readFailed(.graph))
        XCTAssertFalse(store.domainErrors[.graph]!.contains("graph"), "a domain's name never reaches the words")

        api.replies[.graph] = .value((try! JSONDecoder().decode(GraphResponse.self, from: Data("{}".utf8))))
        await store.refresh([.graph])
        XCTAssertFalse(store.couldNotRead(.graph), "read, and empty, is empty")

        store.reach = .notAnswering
        XCTAssertTrue(store.couldNotRead(.inbox), "with no backend answering no page can say it is empty")
        store.reach = .up
        XCTAssertFalse(store.couldNotRead(.inbox))
    }

    func testEveryDomainHasWordsWithoutItsName() {
        for domain in SyncDomain.allCases {
            let words = Copy.Reach.readFailed(domain)
            XCTAssertTrue(words.hasPrefix("Couldn't read "))
            XCTAssertFalse(words.contains(domain.rawValue), "\(domain.rawValue) leaked into \(words)")
        }
    }

    func testASearchTheBackendRefusedOrFailedIsSaid() {
        XCTAssertTrue(FindServerPhase.isFailure(APIError.httpError(401, "")))
        XCTAssertTrue(FindServerPhase.isFailure(APIError.httpError(500, "")))
        XCTAssertFalse(FindServerPhase.isFailure(APIError.httpError(422, "")))
        XCTAssertFalse(FindServerPhase.isFailure(URLError(.cancelled)))
    }
}
