import XCTest
@testable import CicadaApp

/// A `ProjectsAPI` that answers from a queue and records the ETag each call sent.
@MainActor
final class FakeProjectsAPI: ProjectsAPI {
    var listReplies: [Result<Conditional<ProjectsResponse>, any Error>] = []
    var timelineReplies: [String: [Result<Conditional<ProjectTimeline>, any Error>]] = [:]
    private(set) var listETags: [String?] = []
    private(set) var timelineETags: [String: [String?]] = [:]
    /// Parks the next list fetch until `release()` — lets a test switch banks mid-flight.
    var gated = false
    private var gate: CheckedContinuation<Void, Never>?

    func release() { gate?.resume(); gate = nil }

    func fetchProjects(etag: String?) async throws -> Conditional<ProjectsResponse> {
        listETags.append(etag)
        if gated { gated = false; await withCheckedContinuation { gate = $0 } }
        guard !listReplies.isEmpty else { throw APIError.serverUnreachable }
        return try listReplies.removeFirst().get()
    }

    func fetchProjectTimeline(id: String, etag: String?) async throws -> Conditional<ProjectTimeline> {
        timelineETags[id, default: []].append(etag)
        guard var queue = timelineReplies[id], !queue.isEmpty else { throw APIError.serverUnreachable }
        let next = queue.removeFirst()
        timelineReplies[id] = queue
        return try next.get()
    }
}

/// R-PP3 / R-PJ7 — the cache revalidates with the server's ETag, keeps last-known-good, says a 404 as "gone", and
/// forgets everything on a bank switch — including an answer that was in flight across it.
@MainActor
final class ProjectsCacheTests: XCTestCase {
    private func fresh<T>(_ v: T, _ etag: String) -> Result<Conditional<T>, any Error> {
        .success(Conditional(value: v, etag: etag, notModified: false))
    }
    private func notModified<T>(_ etag: String) -> Result<Conditional<T>, any Error> {
        .success(Conditional(value: nil, etag: etag, notModified: true))
    }

    func testTheListIsFetchedThenRevalidatedWithItsETag() async throws {
        let wire = try ProjectFixtures.load()
        let api = FakeProjectsAPI()
        api.listReplies = [fresh(wire.projects, "e1"), notModified("e1")]
        let cache = ProjectsCache(api: api)
        await cache.refreshList()
        await cache.refreshList()
        XCTAssertEqual(api.listETags, [nil, "e1"], "never an ETag with nothing cached; then the one the server sent")
        XCTAssertEqual(cache.list?.projects.count, wire.projects.projects.count, "a 304 keeps what was shown")
        XCTAssertEqual(cache.listPhase, .loaded)
    }

    func testAFailureKeepsWhatWasShownAndSaysSoOnlyWhenNothingWas() async throws {
        let wire = try ProjectFixtures.load()
        let api = FakeProjectsAPI()
        api.listReplies = [fresh(wire.projects, "e1"), .failure(APIError.serverUnreachable)]
        let cache = ProjectsCache(api: api)
        await cache.refreshList()
        await cache.refreshList()
        XCTAssertNotNil(cache.list)
        XCTAssertEqual(cache.listPhase, .loaded, "a failed revalidation over good data stays silent")
        let cold = ProjectsCache(api: FakeProjectsAPI())
        await cold.refreshList()
        guard case .failed(let message) = cold.listPhase else { return XCTFail("\(cold.listPhase)") }
        XCTAssertTrue(message.contains("isn't answering"), message)
    }

    func testATimelineRevalidatesAndA404ReadsAsGone() async throws {
        let rover = try ProjectFixtures.timeline("rover-arm-project")
        let api = FakeProjectsAPI()
        api.timelineReplies["rover-arm-project"] = [fresh(rover, "t1"), notModified("t1")]
        api.timelineReplies["gone-project"] = [.failure(APIError.httpError(404, #"{"detail":"No project"}"#))]
        let cache = ProjectsCache(api: api)
        await cache.refreshTimeline("rover-arm-project")
        await cache.refreshTimeline("rover-arm-project")
        XCTAssertEqual(api.timelineETags["rover-arm-project"], [nil, "t1"])
        XCTAssertEqual(cache.display("rover-arm-project")?.project.id, "rover-arm-project")
        await cache.refreshTimeline("gone-project")
        XCTAssertEqual(cache.phase("gone-project"), .gone)
        XCTAssertNil(cache.display("gone-project"))
    }

    func testABankSwitchForgetsEverythingAndDropsAnAnswerInFlight() async throws {
        let wire = try ProjectFixtures.load()
        let api = FakeProjectsAPI()
        api.listReplies = [fresh(wire.projects, "e1")]
        api.gated = true
        let cache = ProjectsCache(api: api)
        let inFlight = Task { await cache.refreshList() }
        while api.listETags.isEmpty { await Task.yield() }
        cache.reset()
        api.release()
        await inFlight.value
        XCTAssertNil(cache.list, "an answer for the old bank never paints the new one")
        XCTAssertEqual(cache.listPhase, .idle)
    }

    func testTimelinesAreBounded() async throws {
        let rover = try ProjectFixtures.timeline("rover-arm-project")
        let api = FakeProjectsAPI()
        let cache = ProjectsCache(api: api)
        for i in 0...ProjectsCache.timelineCapacity {
            api.timelineReplies["p\(i)"] = [fresh(rover, "t\(i)")]
            await cache.refreshTimeline("p\(i)")
        }
        XCTAssertNil(cache.display("p0"), "the least recent is forgotten")
        XCTAssertNotNil(cache.display("p\(ProjectsCache.timelineCapacity)"))
    }

    /// The page asks again only when a component both ETags fold moved (R-PJ7) — never on a Sleep tick alone.
    func testRevalidationFollowsTheComponentsTheETagsFold() {
        let a = VersionVector(version: "1", components: ["entities": "1", "episodes": "1", "inbox": "1", "sleep": "1"])
        XCTAssertTrue(ProjectsRefresh.shouldRevalidate(old: nil, new: a))
        XCTAssertFalse(ProjectsRefresh.shouldRevalidate(old: a, new: a))
        XCTAssertFalse(ProjectsRefresh.shouldRevalidate(old: a, new: nil))
        for key in ["entities", "episodes", "inbox", "bank"] {
            var c = a.components
            c[key] = "2"
            XCTAssertTrue(ProjectsRefresh.shouldRevalidate(old: a, new: VersionVector(version: "2", components: c)), key)
        }
        var sleepOnly = a.components
        sleepOnly["sleep"] = "2"
        XCTAssertFalse(ProjectsRefresh.shouldRevalidate(old: a, new: VersionVector(version: "2", components: sleepOnly)))
    }
}
