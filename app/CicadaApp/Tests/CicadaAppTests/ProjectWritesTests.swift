import XCTest
@testable import CicadaApp

/// R-PP19…R-PP21 — every Projects write is a `Mutation`: painted where the answer is known, rolled back in words, and
/// never a relative word sent as a value.
@MainActor
final class ProjectWritesTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func harness() async throws -> (Store, FakeSyncAPI, ProjectsCache, FakeProjectsAPI) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        let reads = FakeProjectsAPI()
        reads.timelineReplies["rover-arm-project"] = [
            .success(Conditional(value: try ProjectFixtures.timeline("rover-arm-project"), etag: "t1", notModified: false))]
        let cache = ProjectsCache(api: reads)
        await cache.refreshTimeline("rover-arm-project")
        return (store, api, cache, reads)
    }

    func testSettlingAThreadHidesItAtOnceAndSendsTheWrite() async throws {
        let (store, api, cache, _) = try await harness()
        let camera = try XCTUnwrap(cache.display("rover-arm-project")?.now.threads.first { $0.since == "2026-08-30" })
        let write = ProjectWrite(projectId: "rover-arm-project", action: .settle(claimId: camera.claimId, status: "done"),
                                 cache: cache, day: ProjectFixtures.today)
        api.gateWrites = true
        let running = Task { await store.perform(write) }
        await api.waitForParkedWrite()
        XCTAssertFalse(try XCTUnwrap(cache.display("rover-arm-project")).now.threads.contains { $0.claimId == camera.claimId },
                       "painted before the server answers")
        api.releaseWriteGate()
        let ok = await running.value
        XCTAssertTrue(ok)
        XCTAssertEqual(api.writes.last, "settleProjectThread:rover-arm-project:\(camera.claimId):done")
    }

    /// A 409 — Sleep is writing — rolls the paint back and says the server's own sentence.
    func testA409RollsBackAndSaysSoInPlainWords() async throws {
        let (store, api, cache, _) = try await harness()
        api.projectWriteError = APIError.httpError(409, #"{"detail":"Sleep is writing this project, try again in a moment"}"#)
        let write = ProjectWrite(projectId: "rover-arm-project",
                                 action: .changeMilestone(slug: "first-grasp", change: MilestoneChange(status: "done")),
                                 cache: cache, day: ProjectFixtures.today)
        let ok = await store.perform(write)
        XCTAssertFalse(ok)
        XCTAssertEqual(cache.display("rover-arm-project")?.milestones.first { $0.slug == "first-grasp" }?.status, "planned")
        XCTAssertEqual(store.toast, "Sleep is writing this project, try again in a moment")
        XCTAssertTrue(cache.overlays["rover-arm-project", default: []].isEmpty)
    }

    /// R-PP21 — the Log paints nothing (the server decides the day) and sends no relative word as a value.
    func testTheLogKeepsTheServersDayAndSaysHowItWasDecided() async throws {
        let (store, api, cache, _) = try await harness()
        api.projectWriteReply = ProjectWriteResponse(action: "created", claimId: "clm_x", day: "2026-09-22",
                                                     dateBasis: "stated", episodeId: "ep_2026-09-23_050")
        let write = ProjectWrite(projectId: "rover-arm-project",
                                 action: .log(text: "Yesterday I got the guide", status: "done", when: nil),
                                 cache: cache, day: ProjectFixtures.today)
        XCTAssertNil(write.overlay)
        let ok = await store.perform(write)
        XCTAssertTrue(ok)
        XCTAssertEqual(write.result?.day, "2026-09-22")
        XCTAssertEqual(api.writes.last, "logProjectHappening:rover-arm-project:done:nil")
        XCTAssertEqual(ProjectLogWords.confirmation("Rover Arm Project", answer: try XCTUnwrap(write.result), sentDay: false,
                                                    today: ProjectFixtures.today, locale: us),
                       "Logged on Rover Arm Project for Sep 22 (yesterday) — dated from your words")
        XCTAssertEqual(ProjectLogWords.confirmation("Rover Arm Project",
                                                    answer: ProjectWriteResponse(action: "created", claimId: "c",
                                                                                 day: "2026-09-20", dateBasis: "person"),
                                                    sentDay: true, today: ProjectFixtures.today, locale: us),
                       "Logged on Rover Arm Project for Sep 20 (3 days ago) — the day you picked")
        XCTAssertEqual(ProjectLogWords.confirmation("Rover Arm Project",
                                                    answer: ProjectWriteResponse(action: "created", claimId: "c",
                                                                                 day: "2026-09-23", dateBasis: "person"),
                                                    sentDay: false, today: ProjectFixtures.today, locale: us),
                       "Logged on Rover Arm Project for Sep 23 (today) — no day in your words, so today")
    }

    /// DR-54 — only a 409's or a 422's sentence is shown as the server wrote it; a 400's or a 404's names ids.
    func testFailureWordsNeverLeakAnId() {
        XCTAssertEqual(ProjectWriteFailure.message(APIError.httpError(422, #"{"detail":"Say one day, or pick it with the date chip"}"#)),
                       "Say one day, or pick it with the date chip")
        XCTAssertEqual(ProjectWriteFailure.message(APIError.httpError(404, #"{"detail":"No happening or milestone 'clm_x' on this project"}"#)),
                       Copy.Projects.notOnProject)
        XCTAssertEqual(ProjectWriteFailure.message(APIError.httpError(400, #"{"detail":"on must be a date (YYYY-MM-DD)"}"#)),
                       Copy.Projects.saveFailed)
        XCTAssertEqual(ProjectWriteFailure.message(APIError.httpError(422, #"{"detail":[{"loc":["body","text"]}]}"#)),
                       Copy.Projects.saveFailed, "a validation list is not a sentence")
        XCTAssertEqual(ProjectWriteFailure.message(APIError.serverUnreachable), Copy.Projects.backendDown)
        XCTAssertEqual(ProjectWriteFailure.message(nil), Copy.Projects.saveFailed)
    }

    /// A paint stays until the server's next answer holds the write, and every paint does what it says.
    func testOverlaysPaintThenClearOnTheNextAnswer() async throws {
        let (store, _, cache, reads) = try await harness()
        let add = ProjectWrite(projectId: "rover-arm-project", action: .addMilestone(name: "Demo dry run", target: "2026-10-03"),
                               cache: cache, day: ProjectFixtures.today)
        _ = await store.perform(add)
        cache.confirm(add.overlayId)
        XCTAssertTrue(try XCTUnwrap(cache.display("rover-arm-project")).milestones
            .contains { $0.name == "Demo dry run" && ProjectPlan.isPending($0) })
        reads.timelineReplies["rover-arm-project"] = [
            .success(Conditional(value: try ProjectFixtures.timeline("rover-arm-project"), etag: "t2", notModified: false))]
        await cache.refreshTimeline("rover-arm-project")
        XCTAssertTrue(cache.overlays["rover-arm-project", default: []].isEmpty, "the server's answer replaces the paint")

        var t = try ProjectFixtures.timeline("rover-arm-project")
        func paint(_ change: ProjectOverlay.Change) -> ProjectOverlay {
            ProjectOverlay(id: UUID(), projectId: "rover-arm-project", change: change, day: ProjectFixtures.today)
        }
        let quiet = try XCTUnwrap(t.now.threads.first { $0.since == "2026-08-30" }).claimId
        t = ProjectOverlay.apply([paint(.threadRestated(claimId: quiet))], to: t)
        XCTAssertEqual(t.now.threads.first { $0.claimId == quiet }?.lastHeard, "2026-09-23", "still going: heard from today")
        t = ProjectOverlay.apply([paint(.milestoneRenamed(slug: "first-grasp", name: "First pick"))], to: t)
        XCTAssertEqual(t.milestones.first { $0.slug == "first-grasp" }?.name, "First pick")
        t = ProjectOverlay.apply([paint(.milestoneDone(slug: "first-grasp"))], to: t)
        XCTAssertEqual(t.milestones.first { $0.slug == "first-grasp" }?.doneOn, "2026-09-23")
        t = ProjectOverlay.apply([paint(.withdrawn(claimId: quiet))], to: t)
        XCTAssertFalse(t.items.contains { $0.id == quiet })
        XCTAssertFalse(t.now.threads.contains { $0.claimId == quiet })
    }

    /// R-PP20 — the controls wait while Sleep writes (the server's own 409 condition).
    func testWritesWaitWhileSleepRuns() {
        func status(_ sleep: String) -> StatusSnapshot {
            StatusSnapshot(sleep: .init(status: sleep, stage: 0, totalStages: 5, cycleId: nil, error: nil),
                           inbox: .init(total: 0, byKind: [:]), episodes: .init(unprocessed: 0, lastIngestedAt: nil),
                           lastSleepAt: nil, nextSleepAt: nil)
        }
        XCTAssertTrue(ProjectWriteGate.blocked(status("running")))
        XCTAssertFalse(ProjectWriteGate.blocked(status("idle")))
        XCTAssertFalse(ProjectWriteGate.blocked(nil))
    }

    /// Final review — a `reinforced` answer names a claim that was already there (claim_reconciler rule 2), so the
    /// Log arms Undo only for a claim it `written`; withdrawing the other would retract a line the person never wrote.
    func testAReinforcedLogArmsNoUndo() {
        XCTAssertEqual(ProjectLogWords.undoableClaim(ProjectWriteResponse(action: "written", claimId: "clm_new")), "clm_new")
        XCTAssertNil(ProjectLogWords.undoableClaim(ProjectWriteResponse(action: "reinforced", claimId: "clm_old")))
        XCTAssertNil(ProjectLogWords.undoableClaim(ProjectWriteResponse(action: "written")))
        XCTAssertEqual(Copy.Projects.alreadyNoted("Rover Arm Project"), "Already on Rover Arm Project — noted")
    }

    /// Final review — the story shows the owner's events that name the project, but a write reaches only the tree
    /// (`_find_event`), so a row on another page offers no Done / Not right and D leaves it alone.
    func testOnlyARowInTheTreeCanBeWritten() throws {
        var t = try ProjectFixtures.timeline("rover-arm-project")
        t.project.children = ["rover-arm-gripper"]
        XCTAssertTrue(t.holds(nil))
        XCTAssertTrue(t.holds("rover-arm-project"))
        XCTAssertTrue(t.holds("rover-arm-gripper"))
        XCTAssertFalse(t.holds("bob-example"))
        t.now.threads = [ProjectOpenThread(claimId: "clm_mine", text: "a", since: "2026-09-01", lastHeard: "2026-09-01"),
                         ProjectOpenThread(claimId: "clm_owner", text: "b", since: "2026-09-01", lastHeard: "2026-09-01",
                                           on: "bob-example")]
        XCTAssertNotNil(t.settleableThread("clm_mine"))
        XCTAssertNil(t.settleableThread("clm_owner"))
        XCTAssertNil(t.settleableThread("clm_missing"))
    }

    /// Final review — ↗ opens only an http(s) link with a host; an agent-stored `file://` or custom scheme draws none.
    func testAParticipantLinkOpensOnlyOnTheWeb() {
        XCTAssertEqual(ParticipantChip.webLink("https://example.com/guide.pdf")?.host, "example.com")
        XCTAssertNotNil(ParticipantChip.webLink("HTTP://example.com"))
        for bad in ["file:///etc/hosts", "smb://example.com/share", "x-custom://open", "https:///nohost", "example.com", "", nil] {
            XCTAssertNil(ParticipantChip.webLink(bad), String(describing: bad))
        }
    }

    /// Final review — the cached formatters give the same words as before, per locale.
    func testRelativeDayFormattingIsStableAcrossCalls() {
        let day = ISODay(year: 2026, month: 9, day: 20)
        let first = RelativeDay.absolute(day, today: ProjectFixtures.today, locale: us)
        XCTAssertEqual(RelativeDay.absolute(day, today: ProjectFixtures.today, locale: us), first)
        XCTAssertEqual(first, "Sep 20")
        XCTAssertNotEqual(RelativeDay.absolute(day, today: ProjectFixtures.today, locale: Locale(identifier: "de_DE")), "")
    }
}
