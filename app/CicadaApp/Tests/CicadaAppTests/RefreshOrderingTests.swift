import XCTest
@testable import CicadaApp

/// A `ProjectsAPI` whose every call parks until the test answers it — so two refreshes of one resource can be made to
/// land in either order.
@MainActor
final class ParkingProjectsAPI: ProjectsAPI {
    typealias ListReply = Result<Conditional<ProjectsResponse>, any Error>
    typealias TimelineReply = Result<Conditional<ProjectTimeline>, any Error>
    private(set) var listWaiters: [CheckedContinuation<ListReply, Never>] = []
    private(set) var timelineWaiters: [CheckedContinuation<TimelineReply, Never>] = []

    func fetchProjects(etag: String?) async throws -> Conditional<ProjectsResponse> {
        try await withCheckedContinuation { listWaiters.append($0) }.get()
    }

    func fetchProjectTimeline(id: String, etag: String?) async throws -> Conditional<ProjectTimeline> {
        try await withCheckedContinuation { timelineWaiters.append($0) }.get()
    }

    func answerList(_ i: Int, _ reply: ListReply) { listWaiters[i].resume(returning: reply) }
    func answerTimeline(_ i: Int, _ reply: TimelineReply) { timelineWaiters[i].resume(returning: reply) }
}

/// `BacklogAPI`'s parking twin.
@MainActor
final class ParkingBacklogAPI: BacklogAPI {
    typealias ListReply = Result<Conditional<BacklogList>, any Error>
    private(set) var listWaiters: [CheckedContinuation<ListReply, Never>] = []

    func fetchBacklog(project: String, etag: String?) async throws -> Conditional<BacklogList> {
        try await withCheckedContinuation { listWaiters.append($0) }.get()
    }

    func fetchBacklogItem(project: String, item: String, etag: String?) async throws -> Conditional<BacklogItem> {
        throw APIError.serverUnreachable
    }

    func answerList(_ i: Int, _ reply: ListReply) { listWaiters[i].resume(returning: reply) }
}

/// Audit 2026-10-05 P2-6 — an epoch separates banks, not two refreshes of one resource in one bank. A write's refresh
/// and a sync event's can land in either order; the older answer must never overwrite the newer one, and a confirmed
/// write's paint is cleared only by an answer that was requested after the write was confirmed.
@MainActor
final class RefreshOrderingTests: XCTestCase {
    private func fresh<T>(_ v: T, _ etag: String) -> Result<Conditional<T>, any Error> {
        .success(Conditional(value: v, etag: etag, notModified: false))
    }

    private func until(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        var spins = 0
        while !condition() {
            spins += 1
            if spins > 10_000 { return XCTFail("never parked", file: file, line: line) }
            await Task.yield()
        }
    }

    func testAnOlderListAnswerNeverOverwritesANewerOne() async throws {
        let wire = try ProjectFixtures.load()
        var newer = wire.projects
        newer.projects.removeLast()
        let api = ParkingProjectsAPI()
        let cache = ProjectsCache(api: api)
        let first = Task { await cache.refreshList() }
        await until { api.listWaiters.count == 1 }
        let second = Task { await cache.refreshList() }
        await until { api.listWaiters.count == 2 }
        api.answerList(1, fresh(newer, "e2"))
        await second.value
        api.answerList(0, fresh(wire.projects, "e1"))
        await first.value
        XCTAssertEqual(cache.list, newer, "the answer to the older request lands last but is not kept")
    }

    func testAnOlderTimelineAnswerNeverOverwritesANewerOne() async throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        var newer = t
        newer.milestones.removeAll()
        let api = ParkingProjectsAPI()
        let cache = ProjectsCache(api: api)
        let first = Task { await cache.refreshTimeline(t.project.id) }
        await until { api.timelineWaiters.count == 1 }
        let second = Task { await cache.refreshTimeline(t.project.id) }
        await until { api.timelineWaiters.count == 2 }
        api.answerTimeline(1, fresh(newer, "t2"))
        await second.value
        api.answerTimeline(0, fresh(t, "t1"))
        await first.value
        XCTAssertEqual(cache.display(t.project.id)?.milestones.count, 0)
    }

    func testAnAnswerRequestedBeforeAWriteWasConfirmedKeepsItsPaint() async throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let api = ParkingProjectsAPI()
        let cache = ProjectsCache(api: api)
        let overlay = ProjectOverlay(id: UUID(), projectId: t.project.id,
                                     change: .milestoneAdded(name: "Ship it", target: nil), day: ProjectFixtures.today)
        cache.add(overlay)
        // A sync event's refresh goes out before the server has the write…
        let early = Task { await cache.refreshTimeline(t.project.id) }
        await until { api.timelineWaiters.count == 1 }
        cache.confirm(overlay.id)
        // …and lands after the write was confirmed, holding the state from before it.
        api.answerTimeline(0, fresh(t, "t1"))
        await early.value
        XCTAssertTrue(cache.display(t.project.id)?.milestones.contains { $0.name == "Ship it" } ?? false,
                      "an answer from before the write must not wipe its paint")
        // The write's own refresh, requested after the confirm, settles it.
        var after = t
        after.milestones.append(ProjectMilestone(slug: "ship-it", name: "Ship it", status: "planned", target: nil))
        let settle = Task { await cache.refreshTimeline(t.project.id) }
        await until { api.timelineWaiters.count == 2 }
        api.answerTimeline(1, fresh(after, "t2"))
        await settle.value
        XCTAssertEqual(cache.display(t.project.id)?.milestones.filter { $0.name == "Ship it" }.count, 1)
    }

    func testAnOlderBacklogAnswerNeverOverwritesANewerOne() async throws {
        let wire = try BacklogFixtures.load()
        var newer = wire.list
        newer.items.removeLast()
        let api = ParkingBacklogAPI()
        let cache = BacklogCache(api: api)
        let project = wire.list.project
        let first = Task { await cache.refreshList(project) }
        await until { api.listWaiters.count == 1 }
        let second = Task { await cache.refreshList(project) }
        await until { api.listWaiters.count == 2 }
        api.answerList(1, fresh(newer, "b2"))
        await second.value
        api.answerList(0, fresh(wire.list, "b1"))
        await first.value
        XCTAssertEqual(cache.list(project)?.items.count, newer.items.count)
    }

    func testA304RequestedAfterTheConfirmSettlesThePaint() async throws {
        var t = try ProjectFixtures.timeline("rover-arm-project")
        t.milestones.append(ProjectMilestone(slug: "ship-it", name: "Ship it", status: "planned", target: nil))
        let api = ParkingProjectsAPI()
        let cache = ProjectsCache(api: api)
        let overlay = ProjectOverlay(id: UUID(), projectId: t.project.id,
                                     change: .milestoneAdded(name: "Ship it", target: nil), day: ProjectFixtures.today)
        cache.add(overlay)
        // The fresh answer (already holding the write) lands before the confirm…
        let early = Task { await cache.refreshTimeline(t.project.id) }
        await until { api.timelineWaiters.count == 1 }
        api.answerTimeline(0, fresh(t, "t1"))
        await early.value
        cache.confirm(overlay.id)
        // …so the write's own refresh is a 304, which must still settle the paint.
        let settle = Task { await cache.refreshTimeline(t.project.id) }
        await until { api.timelineWaiters.count == 2 }
        api.answerTimeline(1, .success(Conditional(value: nil, etag: "t1", notModified: true)))
        await settle.value
        XCTAssertEqual(cache.display(t.project.id)?.milestones.filter { $0.name == "Ship it" }.count, 1)
    }
}
