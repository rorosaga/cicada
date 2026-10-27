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

    func testAConfirmedPaintClearsOnlyOnALaterAnswer() async throws {
        let wire = try ProjectFixtures.load()
        let (cache, reads) = await listCache(wire)
        let id = UUID()
        cache.paint(.header(id: "pick-and-place-demo", name: "Pick Demo", description: nil), id: id)
        XCTAssertEqual(cache.displayList?.projects.first { $0.id == "pick-and-place-demo" }?.name, "Pick Demo")
        cache.confirmPaint(id)
        reads.listReplies = [.success(Conditional(value: nil, etag: "l1", notModified: true))]
        await cache.refreshList()
        XCTAssertTrue(cache.paints.isEmpty, "an answer requested after the confirmation holds the write")
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
}
