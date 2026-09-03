import XCTest
@testable import CicadaApp

/// G60 — the question object on the wire, and the resolve mutation carrying
/// `optionKey` / `remindDays` through to the API.
@MainActor
final class InboxQuestionTests: XCTestCase {

    private func decode(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    // MARK: - Decoding

    func testDecodesTheNewOptionObjectShape() throws {
        let item = try decode("""
        {"id":"inbox-001","kind":"conflict","requiredInput":"choice",
         "title":"Where does Rodrigo work now?","body":"Conflicting beliefs.",
         "question":"Where does Rodrigo work now?","predicate":"works-at",
         "allowOther":true,"allowDefer":true,
         "hint":"You said https://x.example is where to check this",
         "remindAfter":null,"updatedDate":"2026-08-30",
         "options":[
           {"key":"a","label":"MongoDB","description":"6 months ago",
            "claimId":"clm_a","observedAt":"2026-02-18",
            "lastReferenced":"2026-02-18","ageDays":193},
           {"key":"both","label":"Both are true (different contexts)"}]}
        """)

        XCTAssertEqual(item.question, "Where does Rodrigo work now?")
        XCTAssertEqual(item.predicate, "works-at")
        XCTAssertTrue(item.allowOther)
        XCTAssertTrue(item.allowDefer)
        XCTAssertEqual(item.hint, "You said https://x.example is where to check this")
        XCTAssertNil(item.remindAfter)
        XCTAssertEqual(item.updatedDate, "2026-08-30")
        XCTAssertEqual(item.options.map(\.key), ["a", "both"])
        XCTAssertEqual(item.options[0].claimId, "clm_a")
        XCTAssertEqual(item.options[0].ageDays, 193)
        XCTAssertNil(item.options[1].claimId)
    }

    func testDecodesTheLegacyFlatStringOptions() throws {
        let item = try decode("""
        {"id":"inbox-009","kind":"conflict","requiredInput":"choice",
         "title":"Conflicting information","body":"ctx",
         "options":["mongodb","supahost","Both are true (different contexts)"]}
        """)

        XCTAssertEqual(item.options.map(\.key), ["0", "1", "2"])
        XCTAssertEqual(item.options.map(\.label),
                       ["mongodb", "supahost", "Both are true (different contexts)"])
        XCTAssertNil(item.question)
        XCTAssertFalse(item.allowOther)
        XCTAssertFalse(item.allowDefer)
    }

    func testDecodesWithNoOptionsAtAll() throws {
        let item = try decode("""
        {"id":"inbox-010","kind":"decay","requiredInput":"choice",
         "title":"No recent mentions","body":"ctx"}
        """)
        XCTAssertTrue(item.options.isEmpty)
    }

    func testQuestionTextFallsBackToTitleThenBody() throws {
        let withQuestion = try decode("""
        {"id":"a","kind":"conflict","requiredInput":"choice","title":"T","body":"B",
         "question":"Q?"}
        """)
        XCTAssertEqual(withQuestion.questionText, "Q?")

        let withoutQuestion = try decode("""
        {"id":"b","kind":"conflict","requiredInput":"choice","title":"T","body":"B"}
        """)
        XCTAssertEqual(withoutQuestion.questionText, "T")

        let titleless = try decode("""
        {"id":"c","kind":"conflict","requiredInput":"choice","title":"","body":"B"}
        """)
        XCTAssertEqual(titleless.questionText, "B")
    }

    func testAgeCapsuleIsShort() throws {
        func capsule(_ days: Int?) -> String? {
            InboxOption(key: "k", label: "L", description: nil, claimId: nil,
                        observedAt: nil, lastReferenced: nil, ageDays: days).ageCapsule
        }
        XCTAssertNil(capsule(nil))
        XCTAssertEqual(capsule(0), "today")
        XCTAssertEqual(capsule(5), "5 d")
        XCTAssertEqual(capsule(20), "3 wk")
        XCTAssertEqual(capsule(193), "6 mo")
        XCTAssertEqual(capsule(800), "2 y")
    }

    // MARK: - Mutation

    func testResolvePassesOptionKeyAndRemindDaysThrough() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: api)
        api.replies[.inbox] = .notModified

        let vm = InboxViewModel(store: store)
        let ok = await vm.resolve(id: "inbox-001", action: "resolve", optionKey: "b")

        XCTAssertTrue(ok)
        XCTAssertTrue(api.writes.contains("resolveInbox:inbox-001:resolve:b:nil"))
    }

    func testDeferPassesRemindDaysAndHidesTheCard() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: api)
        api.replies[.inbox] = .notModified

        let vm = InboxViewModel(store: store)
        let ok = await vm.resolve(id: "inbox-001", action: "defer", remindDays: 14)

        XCTAssertTrue(ok)
        XCTAssertTrue(api.writes.contains("resolveInbox:inbox-001:defer:nil:14"))
    }
}

final class QuestionSelectionTests: XCTestCase {

    func testStartsOnTheFirstOption() {
        let s = QuestionSelection(optionCount: 3, allowOther: true)
        XCTAssertEqual(s.index, 0)
        XCTAssertEqual(s.rowCount, 4)   // 3 options + the Other… row
        XCTAssertFalse(s.isOtherRow)
    }

    func testMoveDownAndUpWrapAround() {
        var s = QuestionSelection(optionCount: 3, allowOther: false)
        s.moveDown(); s.moveDown()
        XCTAssertEqual(s.index, 2)
        s.moveDown()
        XCTAssertEqual(s.index, 0, "wraps to the top")
        s.moveUp()
        XCTAssertEqual(s.index, 2, "wraps to the bottom")
    }

    func testTheOtherRowIsTheLastRowWhenAllowed() {
        var s = QuestionSelection(optionCount: 2, allowOther: true)
        s.moveDown(); s.moveDown()
        XCTAssertTrue(s.isOtherRow)
        XCTAssertEqual(s.activate(), .openOther)
        XCTAssertTrue(s.otherExpanded)
    }

    func testActivateOnAnOptionPicksIt() {
        var s = QuestionSelection(optionCount: 3, allowOther: true)
        s.moveDown()
        XCTAssertEqual(s.activate(), .pick(1))
        XCTAssertFalse(s.otherExpanded)
    }

    func testOpenOtherJumpsToTheOtherRow() {
        var s = QuestionSelection(optionCount: 3, allowOther: true)
        s.openOther()
        XCTAssertTrue(s.isOtherRow)
        XCTAssertTrue(s.otherExpanded)
    }

    func testOpenOtherIsANoOpWhenNotAllowed() {
        var s = QuestionSelection(optionCount: 3, allowOther: false)
        s.openOther()
        XCTAssertFalse(s.otherExpanded)
        XCTAssertEqual(s.index, 0)
    }

    func testNoOptionsAndNoOtherIsInert() {
        var s = QuestionSelection(optionCount: 0, allowOther: false)
        XCTAssertEqual(s.rowCount, 0)
        s.moveDown()
        XCTAssertEqual(s.index, 0)
        XCTAssertNil(s.activate())
    }

    // MARK: - G115 Phase 1 keys

    func testStartsOnTheRecommendedOption() {
        let s = QuestionSelection(optionCount: 3, allowOther: true, initialIndex: 2)
        XCTAssertEqual(s.index, 2)
        let clamped = QuestionSelection(optionCount: 3, allowOther: false, initialIndex: 9)
        XCTAssertEqual(clamped.index, 0, "an out-of-range recommendation never highlights a missing row")
    }

    func testNumberKeysPickWithinTheOptionCount() {
        var s = QuestionSelection(optionCount: 2, allowOther: true)
        XCTAssertEqual(s.pickNumber(1), .pick(0))
        XCTAssertEqual(s.pickNumber(2), .pick(1))
        XCTAssertNil(s.pickNumber(3), "3 is the Other row, never a numbered pick")
        XCTAssertNil(s.pickNumber(0))
        XCTAssertEqual(s.index, 1, "a number key also moves the highlight")
    }

    func testEscapeClosesOtherFirstThenCollapses() {
        var s = QuestionSelection(optionCount: 2, allowOther: true)
        s.openOther()
        XCTAssertEqual(s.escape(), .closeOther)
        XCTAssertFalse(s.otherExpanded)
        XCTAssertEqual(s.escape(), .collapse)
    }
}
