import XCTest
@testable import CicadaApp

/// G48 §4 — a commit's conversations reach the app, and the affordance is
/// invisible wherever there is no conversation to open (pre-G48 history,
/// user-action commits).
@MainActor
final class ConversationAffordanceTests: XCTestCase {

    private let uuid = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"

    func testEntityHistoryEntryDecodesSessions() throws {
        let json = """
        {"date": "2026-08-31", "changeType": "created", "description": "created",
         "author": "gpt-5.4-mini", "commitHash": "abc1234", "sessions": ["\(uuid)"]}
        """.data(using: .utf8)!

        let entry = try JSONDecoder().decode(EntityHistoryEntry.self, from: json)
        XCTAssertEqual(entry.sessions, [uuid])
    }

    func testAPreG48HistoryEntryHasNoSessions() throws {
        let json = """
        {"date": "2026-01-01", "changeType": "created", "description": "created"}
        """.data(using: .utf8)!

        let entry = try JSONDecoder().decode(EntityHistoryEntry.self, from: json)
        XCTAssertEqual(entry.sessions, [])
        XCTAssertEqual(entry.author, "unknown")
    }

    func testContributorCommitDecodesSessions() throws {
        let json = """
        {"commitHash": "abc1234", "date": "2026-08-31", "subject": "Sleep cycle",
         "entities": ["cicada"], "sessions": ["\(uuid)"]}
        """.data(using: .utf8)!

        let commit = try JSONDecoder().decode(ContributorCommit.self, from: json)
        XCTAssertEqual(commit.sessions, [uuid])
    }

    func testAUserActionCommitHasNoSessions() throws {
        let json = #"{"commitHash": "abc", "date": "2026-08-31", "subject": "Add source"}"#
            .data(using: .utf8)!
        XCTAssertEqual(try JSONDecoder().decode(ContributorCommit.self, from: json).sessions, [])
    }

    /// PR #20 round-2 review fix ("conversation control conflicts with
    /// history expansion"): `EntityDetailCard.historyRowButton` used to embed
    /// `FromConversationButton` INSIDE the row's expand/collapse `Button`
    /// label — a `Button` nested in a `Button`'s label, which makes tap
    /// targeting ambiguous. The fix moved it to a trailing sibling in the
    /// row's `HStack` with its own hit region and accessibility label, never
    /// re-wrapped by the expand `Button`. `shouldRender` — the only piece of
    /// that decision this package can unit-test without a view-inspection
    /// library — is untouched by the restructuring and still governs
    /// visibility correctly; the sibling-vs-nested structure itself is
    /// verified by `swift build` (the type-checker) and manual review, since
    /// this target has no ViewInspector/UI-test seam to assert view-tree shape.
    func testTheAffordanceIsHiddenWithoutSessionsAndShownWithThem() {
        XCTAssertFalse(FromConversationButton.shouldRender(sessionIds: []))
        XCTAssertTrue(FromConversationButton.shouldRender(sessionIds: [uuid]))
    }

    func testThePopoverOnlyOffersConversationsTheBackendKnows() async {
        let api = FakeSyncAPI()
        api.conversationsById = [
            uuid: ConversationSummary(conversationId: uuid, title: "Index choice", resumable: true),
        ]
        let vm = ConversationsViewModel(api: api)
        await vm.load(ids: [uuid, "a-session-this-bank-forgot"])

        XCTAssertNotNil(vm.conversation(id: uuid))
        XCTAssertNil(vm.conversation(id: "a-session-this-bank-forgot"))
        XCTAssertEqual(vm.unknownIds, ["a-session-this-bank-forgot"])
    }

    /// The M2 regression: the popover used to resolve ids inside a capped
    /// `/recent` page, so a conversation the bank still has — just not among
    /// the most recent — was reported as missing episodes.
    func testAnAgedConversationIsFoundEvenThoughRecentOmitsIt() async {
        let api = FakeSyncAPI()
        api.recentConversations = []   // it aged past the recent page
        api.conversationsById = [uuid: ConversationSummary(conversationId: uuid, title: "Aged")]
        let vm = ConversationsViewModel(api: api)

        await vm.load(ids: [uuid])

        XCTAssertEqual(api.conversationIdFetches, [uuid], "resolved by id, not inside /recent")
        XCTAssertEqual(vm.conversation(id: uuid)?.title, "Aged")
        XCTAssertTrue(vm.unknownIds.isEmpty, "a found conversation is never reported as unknown")
    }

    func testAFailedByIdLoadIsAnErrorNotAMiss() async {
        let api = FakeSyncAPI()
        api.failConversationById = true
        let vm = ConversationsViewModel(api: api)

        await vm.load(ids: [uuid])

        XCTAssertFalse(vm.hasLoaded, "an unreachable backend must not read as 'the bank forgot it'")
        XCTAssertEqual(vm.errorMessage, "Couldn't load conversations")
        XCTAssertTrue(vm.unknownIds.isEmpty)
    }
}
