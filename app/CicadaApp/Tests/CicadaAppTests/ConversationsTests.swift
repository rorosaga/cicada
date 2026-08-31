import XCTest
@testable import CicadaApp

/// G48 §3-§5 on the app side: the wire types, the two fetches, and the
/// view model's resumable gating.
@MainActor
final class ConversationsTests: XCTestCase {

    private let uuid = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    // MARK: - Decoding

    func testConversationSummaryDecodesTheCamelCaseWirePayload() throws {
        let json = """
        {
            "conversationId": "\(uuid)",
            "kind": "mcp",
            "harness": "claude-code",
            "origin": "mcp",
            "title": "Index choice",
            "firstSeen": "2026-08-30T10:00:00Z",
            "lastSeen": "2026-08-30T12:00:00Z",
            "episodeCount": 2,
            "entityIds": ["sqlite-vec", "cicada"],
            "entityCount": 2,
            "model": "gpt-5.4-mini",
            "resumable": true
        }
        """.data(using: .utf8)!

        let convo = try JSONDecoder().decode(ConversationSummary.self, from: json)

        XCTAssertEqual(convo.id, uuid)
        XCTAssertEqual(convo.kind, "mcp")
        XCTAssertEqual(convo.harness, "claude-code")
        XCTAssertEqual(convo.title, "Index choice")
        XCTAssertEqual(convo.episodeCount, 2)
        XCTAssertEqual(convo.entityIds, ["sqlite-vec", "cicada"])
        XCTAssertEqual(convo.model, "gpt-5.4-mini")
        XCTAssertTrue(convo.resumable)
        XCTAssertEqual(convo.hiddenEntityCount, 0)
    }

    func testConversationSummaryToleratesAnOlderBackendMissingEverythingOptional() throws {
        let json = #"{"conversationId": "uuid-abc"}"#.data(using: .utf8)!
        let convo = try JSONDecoder().decode(ConversationSummary.self, from: json)

        XCTAssertEqual(convo.kind, "mcp")
        XCTAssertEqual(convo.title, "")
        XCTAssertEqual(convo.entityIds, [])
        XCTAssertEqual(convo.entityCount, 0)
        XCTAssertNil(convo.model)
        XCTAssertFalse(convo.resumable)
    }

    func testACappedEntityListReportsWhatTheBackendWithheld() throws {
        let json = """
        {"conversationId": "\(uuid)", "entityIds": ["a", "b"], "entityCount": 40}
        """.data(using: .utf8)!
        let convo = try JSONDecoder().decode(ConversationSummary.self, from: json)
        XCTAssertEqual(convo.hiddenEntityCount, 38)
    }

    func testAnOlderBackendWithoutEntityCountNeverShowsAPhantomMore() throws {
        let json = #"{"conversationId": "x", "entityIds": ["a", "b"]}"#.data(using: .utf8)!
        let convo = try JSONDecoder().decode(ConversationSummary.self, from: json)
        XCTAssertEqual(convo.entityCount, 2)
        XCTAssertEqual(convo.hiddenEntityCount, 0)
    }

    func testResumeDescriptorDecodes() throws {
        let json = """
        {"mode": "terminal", "argv": ["claude", "--resume", "\(uuid)"],
         "cwd": "/Users/x/p", "displayCommand": "claude --resume \(uuid)"}
        """.data(using: .utf8)!
        let descriptor = try JSONDecoder().decode(ResumeDescriptor.self, from: json)

        XCTAssertEqual(descriptor.mode, "terminal")
        XCTAssertEqual(descriptor.argv, ["claude", "--resume", uuid])
        XCTAssertEqual(descriptor.cwd, "/Users/x/p")
        XCTAssertEqual(descriptor.displayCommand, "claude --resume \(uuid)")
    }

    func testResumeDescriptorToleratesANullCwd() throws {
        let json = #"{"mode": "terminal", "argv": [], "cwd": null, "displayCommand": "x"}"#
            .data(using: .utf8)!
        XCTAssertNil(try JSONDecoder().decode(ResumeDescriptor.self, from: json).cwd)
    }

    // MARK: - APIClient

    func testFetchRecentConversationsSendsTheLimit() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/conversations/recent")
            XCTAssertTrue((request.url?.query ?? "").contains("limit=20"))
            let body = """
            [{"conversationId": "\(self.uuid)", "title": "Index choice", "resumable": true}]
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let rows = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchRecentConversations(limit: 20)

        XCTAssertEqual(rows.map(\.id), [uuid])
    }

    func testFetchRecentConversationsIsEmptyAgainstABackendWithoutTheEndpoint() async throws {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 404,
                                           httpVersion: nil, headerFields: nil)!
            return (response, Data("Not Found".utf8))
        }
        let rows = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchRecentConversations(limit: 20)
        XCTAssertTrue(rows.isEmpty)
    }

    func testFetchConversationGetsTheIdPath() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/conversations/\(self.uuid)")
            let body = """
            {"conversationId": "\(self.uuid)", "title": "Index choice", "resumable": true}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let convo = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchConversation(id: uuid)

        XCTAssertEqual(convo?.id, uuid)
        XCTAssertEqual(convo?.title, "Index choice")
    }

    func testFetchConversationIsNilOnA404() async throws {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 404,
                                           httpVersion: nil, headerFields: nil)!
            return (response, Data("Not Found".utf8))
        }
        let convo = try await APIClient(session: MockURLProtocol.makeSession())
            .fetchConversation(id: uuid)
        XCTAssertNil(convo)
    }

    func testResumeConversationPostsToTheIdPath() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/conversations/\(self.uuid)/resume")
            let body = """
            {"mode": "terminal", "argv": ["claude", "--resume", "\(self.uuid)"],
             "cwd": "/Users/x/p", "displayCommand": "claude --resume \(self.uuid)"}
            """.data(using: .utf8)!
            let response = HTTPURLResponse(url: request.url!, statusCode: 200,
                                           httpVersion: nil, headerFields: nil)!
            return (response, body)
        }

        let descriptor = try await APIClient(session: MockURLProtocol.makeSession())
            .resumeConversation(id: uuid)

        XCTAssertEqual(descriptor.displayCommand, "claude --resume \(uuid)")
    }

    func testResumeConversationSurfacesA409() async throws {
        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(url: request.url!, statusCode: 409,
                                           httpVersion: nil, headerFields: nil)!
            return (response, Data(#"{"detail":{"reason":"transcript_gone"}}"#.utf8))
        }

        do {
            _ = try await APIClient(session: MockURLProtocol.makeSession())
                .resumeConversation(id: uuid)
            XCTFail("expected a 409")
        } catch APIError.httpError(let code, _) {
            XCTAssertEqual(code, 409)
        }
    }

    // MARK: - ViewModel

    func testLoadPublishesRowsAndMarksLoaded() async {
        let api = FakeSyncAPI()
        api.recentConversations = [
            ConversationSummary(conversationId: uuid, title: "Index choice", resumable: true),
        ]
        let vm = ConversationsViewModel(api: api)

        XCTAssertFalse(vm.hasLoaded)
        await vm.load()

        XCTAssertTrue(vm.hasLoaded)
        XCTAssertNil(vm.errorMessage)
        XCTAssertEqual(vm.conversations.map(\.id), [uuid])
    }

    func testLoadedAndEmptyIsNotAnError() async {
        let api = FakeSyncAPI()
        api.recentConversations = []
        let vm = ConversationsViewModel(api: api)
        await vm.load()

        XCTAssertTrue(vm.hasLoaded)
        XCTAssertNil(vm.errorMessage)
        XCTAssertTrue(vm.conversations.isEmpty)
    }

    func testAFailedLoadKeepsHasLoadedFalseAndSaysSo() async {
        let api = FakeSyncAPI()
        api.failRecentConversations = true
        let vm = ConversationsViewModel(api: api)
        await vm.load()

        XCTAssertFalse(vm.hasLoaded)
        XCTAssertEqual(vm.errorMessage, "Couldn't load conversations")
    }

    func testResumeLaunchesAndReportsTheApp() async {
        let api = FakeSyncAPI()
        api.resumeDescriptor = ResumeDescriptor(
            mode: "terminal", argv: ["claude", "--resume", uuid],
            cwd: "/Users/x/p", displayCommand: "claude --resume \(uuid)"
        )
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })

        let outcome = await vm.resume(uuid)
        XCTAssertEqual(outcome, .launched("Ghostty"))
    }

    func testResumeFallsBackToTheClipboardAndReportsTheCommand() async {
        let api = FakeSyncAPI()
        api.resumeDescriptor = ResumeDescriptor(
            mode: "terminal", argv: ["claude", "--resume", uuid],
            cwd: nil, displayCommand: "claude --resume \(uuid)"
        )
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .clipboard })

        let outcome = await vm.resume(uuid)
        XCTAssertEqual(outcome, .copied("claude --resume \(uuid)"))
    }

    func testA409BecomesTheGoneOutcome() async {
        let api = FakeSyncAPI()
        api.resumeError = APIError.httpError(409, #"{"detail":{"reason":"transcript_gone"}}"#)
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })

        let outcome = await vm.resume(uuid)
        XCTAssertEqual(outcome, .gone)
    }

    /// PR #20 review fix: a 404 (the bank has no record of this conversation
    /// — see `POST /conversations/{id}/resume`'s 404/409/400 contract) must
    /// not read as the generic "couldn't reach the backend" outage copy.
    func testA404BecomesAnUnavailableConversationFailureNotAGenericOutage() async {
        let api = FakeSyncAPI()
        api.resumeError = APIError.httpError(404, "unknown conversation")
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })

        let outcome = await vm.resume(uuid)
        XCTAssertEqual(outcome, .failed("This conversation is no longer available in this bank"))
    }

    func testCopyCommandCopiesTheDisplayCommandAndReportsIt() async {
        let api = FakeSyncAPI()
        api.resumeDescriptor = ResumeDescriptor(
            mode: "terminal", argv: ["claude", "--resume", uuid],
            cwd: "/Users/x/p", displayCommand: "claude --resume \(uuid)"
        )
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })

        let outcome = await vm.copyCommand(for: uuid)
        XCTAssertEqual(outcome, .copied("claude --resume \(uuid)"))
    }

    func testCopyCommandA409BecomesTheGoneOutcome() async {
        let api = FakeSyncAPI()
        api.resumeError = APIError.httpError(409, #"{"detail":{"reason":"transcript_gone"}}"#)
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })

        let outcome = await vm.copyCommand(for: uuid)
        XCTAssertEqual(outcome, .gone)
    }

    /// PR #20 round-2 review fix: `copyCommand` shares `resume`'s 404 handling
    /// (a bank switch or deletion between the row rendering and the tap), so
    /// it must not read as the generic "couldn't reach the backend" outage
    /// copy either — see `testA404BecomesAnUnavailableConversationFailureNotAGenericOutage`
    /// for the `resume` half of this contract.
    func testCopyCommandA404BecomesAnUnavailableConversationFailureNotAGenericOutage() async {
        let api = FakeSyncAPI()
        api.resumeError = APIError.httpError(404, "unknown conversation")
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })

        let outcome = await vm.copyCommand(for: uuid)
        XCTAssertEqual(outcome, .failed("This conversation is no longer available in this bank"))
    }

    func testANonResumableIdIsNeverEvenSentToTheBackend() async {
        let api = FakeSyncAPI()
        api.recentConversations = [
            ConversationSummary(conversationId: "ses_2026-08-31_deadbeef", resumable: false),
        ]
        let vm = ConversationsViewModel(api: api, launch: { _, _ in .ghostty })
        await vm.load()

        XCTAssertFalse(vm.canResume("ses_2026-08-31_deadbeef"))
        XCTAssertTrue(vm.conversations[0].resumable == false)
    }

    // MARK: - Entity chips (spec §4)

    func testEveryEntityIsAChipWhenTheyFit() {
        let convo = ConversationSummary(conversationId: uuid,
                                        entityIds: ["cicada", "sqlite-vec"], entityCount: 2)
        let plan = ConversationRow.chipPlan(for: convo)
        XCTAssertEqual(plan.ids, ["cicada", "sqlite-vec"])
        XCTAssertEqual(plan.hidden, 0, "no '+N more' when nothing is withheld")
    }

    func testARowWithNoEntitiesPlansNoChips() {
        let plan = ConversationRow.chipPlan(for: ConversationSummary(conversationId: uuid))
        XCTAssertTrue(plan.ids.isEmpty)
        XCTAssertEqual(plan.hidden, 0)
    }

    func testTheRowTruncatesToItsChipLimitAndCountsTheRest() {
        let ids = (0..<10).map { "e\($0)" }
        let convo = ConversationSummary(conversationId: uuid, entityIds: ids, entityCount: 10)
        let plan = ConversationRow.chipPlan(for: convo, limit: 6)
        XCTAssertEqual(plan.ids.count, 6)
        XCTAssertEqual(plan.hidden, 4)
    }

    /// "+N more" is measured against the honest total, so it covers BOTH the
    /// ids this row truncated and the ones the backend's own cap withheld.
    func testHiddenCountsTheBackendCapTooNotJustTheRowLimit() {
        let ids = (0..<12).map { "e\($0)" }   // session_stats.MAX_CONVERSATION_ENTITIES
        let convo = ConversationSummary(conversationId: uuid, entityIds: ids, entityCount: 40)
        let plan = ConversationRow.chipPlan(for: convo, limit: 6)
        XCTAssertEqual(plan.ids.count, 6)
        XCTAssertEqual(plan.hidden, 34)
    }

    func testAnOlderBackendWithoutEntityCountNeverPlansAPhantomMoreChip() throws {
        let json = #"{"conversationId": "x", "entityIds": ["a", "b"]}"#.data(using: .utf8)!
        let convo = try JSONDecoder().decode(ConversationSummary.self, from: json)
        let plan = ConversationRow.chipPlan(for: convo)
        XCTAssertEqual(plan.ids, ["a", "b"])
        XCTAssertEqual(plan.hidden, 0)
    }

    // MARK: - Section persistence

    func testActivitySectionRoundTripsTheConversationsCase() {
        XCTAssertEqual(ActivitySection.restored(from: "Conversations"), .conversations)
        XCTAssertEqual(ActivitySection.conversations.rawValue, "Conversations")
        XCTAssertEqual(ActivitySection.restored(from: "Nonsense"), .usage)
        XCTAssertTrue(ActivitySection.allCases.contains(.conversations))
    }
}
