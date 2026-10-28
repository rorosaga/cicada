import XCTest
@testable import CicadaApp

/// Projects v2 (ruling 45, wire g141-7): the list is the person's own, everything detected is suggested, the header is
/// theirs, and the knowledge panel says why each conversation is tied. Synthetic demo fiction only.
@MainActor
final class ProjectsMineTests: XCTestCase {
    private func listCache(_ wire: ProjectFixtures.Wire) async -> (ProjectsCache, FakeProjectsAPI) {
        let reads = FakeProjectsAPI()
        reads.listReplies = [.success(Conditional(value: wire.projects, etag: "l1", notModified: false))]
        let cache = ProjectsCache(api: reads)
        await cache.refreshList()
        return (cache, reads)
    }

    /// The demo wire: Bob's own projects are listed, the repository-born one waits under Suggested with its reason.
    func testTheFixtureSplitsMineFromSuggested() throws {
        let wire = try ProjectFixtures.load()
        let mine = wire.projects.projects.filter(\.mine).map(\.id)
        XCTAssertTrue(mine.contains("pick-and-place-demo"))
        XCTAssertTrue(mine.contains("rover-arm-project"), "progress logged in the app counts on day one (Q2)")
        XCTAssertFalse(mine.contains("garden-sensor-project"))
        let garden = try XCTUnwrap(wire.projects.suggested.first { $0.id == "garden-sensor-project" })
        XCTAssertEqual(garden.whyKind, "repo")
        XCTAssertTrue(garden.why.contains("garden-sensor"))
        XCTAssertEqual(wire.projects.suggested.first?.whyKind, "repo", "strongest reason first")
        let pick = try XCTUnwrap(wire.timelines["pick-and-place-demo"])
        XCTAssertEqual(pick.project.description, "Get the rover arm to pick a part off the bench and place it in a tray.")
        XCTAssertEqual(pick.project.descriptionBy?.isPerson, true)
        XCTAssertEqual(pick.project.mineVia, "app")
    }

    /// An older server sends no `mine`: every row reads as the person's, as the page always drew.
    func testAServerBeforeG1417KeepsEveryRow() throws {
        let json = #"{"projects":[{"id":"alpha","name":"Alpha"}],"tzName":"UTC"}"#
        let list = try JSONDecoder().decode(ProjectsResponse.self, from: Data(json.utf8))
        XCTAssertEqual(list.projects.first?.mine, true)
        XCTAssertTrue(list.suggested.isEmpty)
    }

    func testAcceptAndDismissPaintTheListAndRollBack() async throws {
        let (cache, _) = await listCache(try ProjectFixtures.load())
        let accept = UUID()
        cache.paint(.accept(id: "garden-sensor-project", name: nil), id: accept)
        XCTAssertEqual(cache.displayList?.projects.first { $0.id == "garden-sensor-project" }?.mine, true)
        XCTAssertFalse(cache.displayList?.suggested.contains { $0.id == "garden-sensor-project" } ?? true)
        cache.unpaint(accept)
        XCTAssertEqual(cache.displayList?.projects.first { $0.id == "garden-sensor-project" }?.mine, false)
        let dismiss = UUID()
        cache.paint(.dismiss(id: "garden-sensor-project"), id: dismiss)
        XCTAssertEqual(cache.displayList?.suggested.first { $0.id == "garden-sensor-project" }?.dismissed, true)
        XCTAssertEqual(cache.displayList?.dismissed, (cache.list?.dismissed ?? 0) + 1)
    }

    func testEveryChangeGoesToItsRoute() {
        XCTAssertEqual(ProjectChange.create(name: "A", description: "B").route.path, "/projects")
        XCTAssertEqual(ProjectChange.accept(id: "g-p-abc123", name: "Garden").route.path, "/projects/g-p-abc123/accept")
        XCTAssertEqual(ProjectChange.accept(id: "x", name: "Garden").route.body["name"] as? String, "Garden")
        XCTAssertEqual(ProjectChange.header(id: "a b", name: nil, description: "").route.method, "PATCH")
        XCTAssertEqual(ProjectChange.header(id: "a b", name: nil, description: "").route.path, "/projects/a%20b")
        XCTAssertEqual(ProjectChange.tie(id: "p", episode: "ep_1", remove: true).route.body["remove"] as? Bool, true)
        XCTAssertEqual(ProjectChange.withdrawInfluence(id: "p", claimId: "c1", page: nil, ref: nil, predicate: nil)
            .route.path, "/projects/p/influences/withdraw")
    }

    func testAWriteGoesThroughTheStoreAndAFailureRollsBack() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        let (cache, _) = await listCache(try ProjectFixtures.load())
        api.projectWriteError = APIError.httpError(409, #"{"detail":"Sleep is writing this project, try again in a moment"}"#)
        let w = ProjectOwnershipWrite(.accept(id: "garden-sensor-project", name: nil), cache: cache)
        let ok = await store.perform(w)
        XCTAssertFalse(ok)
        XCTAssertTrue(cache.paints.isEmpty)
        XCTAssertEqual(store.toast, "Sleep is writing this project, try again in a moment")
        XCTAssertEqual(api.projectChanges, [.accept(id: "garden-sensor-project", name: nil)])
    }

    func testAnUntiePaintsTheConversationOut() {
        let page = ProjectConversationsPage(project: "p", total: 2, counts: ["named": 2], conversations: [
            ProjectConversationRow(episodeId: "ep_1", title: "One", why: ["named"]),
            ProjectConversationRow(episodeId: "ep_2", title: "Two", why: ["named"])])
        let out = ProjectPaint.apply([ProjectPaint(id: UUID(), change: .tie(id: "p", episode: "ep_1", remove: true))],
                                     to: page, project: "p")
        XCTAssertEqual(out.conversations.map(\.episodeId), ["ep_2"])
        XCTAssertEqual(out.total, 1)
    }

    /// The why line says every signal in words, so hover is never the only explanation.
    func testTheWhyLineSaysEachSignal() {
        XCTAssertEqual(Copy.ProjectsMine.whyLine(["named": 6, "repo": 4, "claims": 3, "added": 1]),
                       "6 you named it in · 4 in its repository · 3 Sleep tied · 1 added by hand")
        XCTAssertEqual(Copy.ProjectsMine.why("provider", provider: "ChatGPT"), "In your ChatGPT project")
    }

    /// Q7: side by side when there is room, the panel folded under the card when there is not.
    func testThePanelFoldsUnderTheCardWhenNarrow() {
        XCTAssertTrue(ProjectKnowledgeLayout.sideBySide(available: 1100))
        XCTAssertFalse(ProjectKnowledgeLayout.sideBySide(available: 700))
    }

    func testAListWithNoneOfMineButSuggestionsSaysSo() {
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 0, suggestions: 3, lines: 0,
                                            finding: false), .emptyMine)
        XCTAssertEqual(ProjectsListState.of(phase: .loaded, hasList: true, rows: 0, lines: 0, finding: false), .empty)
    }

    /// Projects v3 (decision 9): done items read in the Timeline — every story row and every milestone marked done,
    /// newest first; nothing is a separate Done fold.
    func testTheTimelineHoldsTheStoryAndEveryDoneMilestoneNewestFirst() throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        let entries = ProjectOpen.timeline(t)
        let items = t.items.filter { $0.kind != "created" }.count
        let done = t.milestones.filter { $0.status == "done" && $0.source != "expectedEnd" }.count
        XCTAssertGreaterThan(done, 0, "the demo has a finished milestone — a test over nothing passes vacuously")
        XCTAssertEqual(entries.count, items + done)
        let days = entries.compactMap(\.day)
        XCTAssertEqual(days, days.sorted(by: >))
        let coming = ProjectOpen.comingUp(t, backlog: nil, today: ProjectFixtures.today)
        XCTAssertTrue(coming.milestones.allSatisfy { $0.milestone.status == "planned" })
        XCTAssertLessThanOrEqual(coming.capped().count, ProjectOpen.cap)
    }

    /// Decision 10: an Add paints the person's tie at once (a proposal they took moves out of the proposals), and
    /// "Not part of it" leaves the list before the server answers.
    func testPagesPaintTheirAddAndTheirRemoval() throws {
        var t = try ProjectFixtures.timeline("rover-arm-project")
        t.pages = [ProjectPageRow(id: "p-1", name: "Proposed Example", tie: "proposed", by: "cursor"),
                   ProjectPageRow(id: "p-2", name: "Said Example", count: 3)]
        t.pagesTotal = 2
        t.pageCounts = ["proposed": 1, "said": 1]
        let took = ProjectPagesPaint.apply(t, entity: "p-1", name: nil, type: nil, remove: false)
        XCTAssertEqual(took.pages.map(\.tie), ["user", "said"])
        XCTAssertEqual(took.pageCounts["user"], 1)
        XCTAssertEqual(took.pageCounts["proposed"], 0)
        let gone = ProjectPagesPaint.apply(t, entity: "p-2", name: nil, type: nil, remove: true)
        XCTAssertEqual(gone.pages.map(\.id), ["p-1"])
        XCTAssertEqual(gone.pagesTotal, 1)
        let added = ProjectPagesPaint.apply(t, entity: "p-3", name: "New Example", type: "tool", remove: false)
        XCTAssertEqual(added.pages.map(\.id), ["p-1", "p-3", "p-2"], "after the proposals, before the rest")
        XCTAssertEqual(added.pagesTotal, 3)
    }

    /// Owner 2026-10-28: the head is lighter — how the project is the person's and who edited it move into `.help`.
    func testTheHeadersProvenanceIsWordsForHelpNotADrawnLine() throws {
        let t = try ProjectFixtures.timeline("rover-arm-project")
        XCTAssertFalse(ProjectHeaderEditor.provenance(t.project).isEmpty)
    }

    /// Review of #493 (5): a kind the record does not know is never labelled "Thing".
    func testAnUnknownKindIsNotAGroupLabel() {
        XCTAssertTrue(ProjectInfluence.knownTags.contains("Film"))
        XCTAssertFalse(ProjectInfluence.knownTags.contains("Thing"))
    }

    /// Review of #493: a paint drawn by the list and the timeline waits for both, so neither flashes the old words.
    func testAPaintWaitsForEveryReadThatDrawsIt() async throws {
        let wire = try ProjectFixtures.load()
        let reads = FakeProjectsAPI()
        reads.listReplies = [.success(Conditional(value: wire.projects, etag: "l1", notModified: false))]
        reads.timelineReplies["pick-and-place-demo"] = [
            .success(Conditional(value: try XCTUnwrap(wire.timelines["pick-and-place-demo"]), etag: "t1",
                                 notModified: false))]
        let cache = ProjectsCache(api: reads)
        await cache.refreshList()
        let id = UUID()
        cache.paint(.header(id: "pick-and-place-demo", name: "Pick Demo", description: nil), id: id)
        cache.confirmPaint(id)
        await cache.refreshTimeline("pick-and-place-demo")
        XCTAssertEqual(cache.paints.count, 1, "the list has not answered yet")
        XCTAssertEqual(cache.displayList?.projects.first { $0.id == "pick-and-place-demo" }?.name, "Pick Demo")
        reads.listReplies = [.success(Conditional(value: nil, etag: "l1", notModified: true))]
        await cache.refreshList()
        XCTAssertTrue(cache.paints.isEmpty)
    }

    /// Review of #493: what a header edit sends — clicking away saves like ⏎; an unchanged or empty name sends nothing.
    func testAHeaderDraftSendsOnlyARealChange() throws {
        let ref = try ProjectFixtures.timeline("pick-and-place-demo").project
        XCTAssertEqual(ProjectHeaderDraft.change(.name, draft: " Pick Demo ", ref: ref)?.name, "Pick Demo")
        XCTAssertNil(ProjectHeaderDraft.change(.name, draft: "  ", ref: ref))
        XCTAssertNil(ProjectHeaderDraft.change(.name, draft: ref.name, ref: ref))
        XCTAssertEqual(ProjectHeaderDraft.change(.description, draft: "", ref: ref)?.description, "", "clears it")
        XCTAssertNil(ProjectHeaderDraft.change(nil, draft: "x", ref: ref), "Esc cleared the field first: nothing")
    }

    /// Review of #493 (DR-58): a day is the reader's words, never the raw ISO string.
    func testDaysAreSpokenNotIso() {
        let today = ISODay(year: 2026, month: 10, day: 27)
        let words = Copy.ProjectsMine.day("2026-08-20", today: today, locale: Locale(identifier: "en_US"))
        XCTAssertNotNil(words)
        XCTAssertFalse(words?.contains("2026-08-20") ?? true)
        XCTAssertFalse(Copy.ProjectsMine.startedLine("app", day: "2026-08-20").contains("2026-08-20"))
    }

    /// Review of #493: the Reader opened from a project's panel carries the project, so its header offers the untie.
    func testTheReaderKnowsWhichProjectOpenedIt() {
        let target = ReaderTarget(episode: "ep_2026-09-12_001", subjectId: "p", fromProject: "p")
        XCTAssertEqual(target.fromProject, "p")
        XCTAssertNil(ReaderTarget(episode: "ep_2026-09-12_001").fromProject)
    }
}
