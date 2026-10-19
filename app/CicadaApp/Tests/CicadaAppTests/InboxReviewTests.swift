import XCTest
@testable import CicadaApp

/// The quick review (owner 2026-10-19): one kind at a time, one card at a time, the same answers in the same place,
/// keyboard-first, a progress count, and undo. The queue, the answers, the keys, undo and progress are pure; the
/// answer itself goes through the Inbox's own hold (`Store.hold`), so it sends nothing until the Undo window closes
/// and nothing new writes. Synthetic data only.
@MainActor
final class InboxReviewTests: XCTestCase {
    private static let items = """
    [{"id":"inbox-001","kind":"decay","requiredInput":"choice","priority":0.31,"entityId":"alpha-project",
      "entityName":"Alpha Project","title":"No recent mentions of Alpha Project","question":"Still tracking Alpha Project?",
      "createdDate":"2026-10-01","recommendedKey":"archive",
      "options":[{"key":"archive","label":"Archive","recommended":true,"lastReferenced":"2026-03-02"},
                 {"key":"keep","label":"Keep active","lastReferenced":"2026-03-02"}],
      "subject":{"summary":"A synthetic side project.","conversations":3,"lastSaid":"2026-03-02"}},
     {"id":"inbox-002","kind":"decay","requiredInput":"choice","priority":0.35,"entityId":"beta-project",
      "entityName":"Beta Project","title":"No recent mentions of Beta Project","question":"Still tracking Beta Project?",
      "createdDate":"2026-10-02",
      "options":[{"key":"archive","label":"Archive","recommended":true},{"key":"keep","label":"Keep active"}]},
     {"id":"inbox-003","kind":"decay","requiredInput":"choice","priority":0.2,"entityId":"gamma-project",
      "entityName":"Gamma Project","title":"No recent mentions of Gamma Project","createdDate":"2026-10-03"},
     {"id":"inbox-004","kind":"normalization","requiredInput":"choice","priority":0.3,"entityId":"beta-library",
      "entityName":"Beta Library","title":"Confirm a predicate fold for Beta Library","createdDate":"2026-10-01",
      "options":[{"key":"0","label":"Correct fold","recommended":true},{"key":"1","label":"Wrong fold — keep separate"}],
      "fold":{"raw":"built with","canonical":"uses","claims":3,"pages":2,"example":"Beta Library is built with a toolkit"},
      "subject":{"summary":"A synthetic library.","conversations":1}},
     {"id":"inbox-005","kind":"conflict","requiredInput":"choice","priority":0.8,"entityId":"bob-example",
      "entityName":"Bob Example","title":"Where does Bob Example work?","question":"Where does Bob Example work?",
      "createdDate":"2026-10-01",
      "options":[{"key":"a","label":"company-a","observedAt":"2026-03-02","ageDays":200},
                 {"key":"b","label":"company-b","observedAt":"2026-08-01","ageDays":60},
                 {"key":"both","label":"Both are true (different contexts)"}]},
     {"id":"inbox-006","kind":"conflict","requiredInput":"choice","priority":0.8,"entityId":"carol-example",
      "entityName":"Carol Example","title":"What does Carol Example use?","createdDate":"2026-10-02",
      "options":[{"key":"a","label":"tool-a"},{"key":"b","label":"tool-b"},{"key":"ax","label":"tool-c"},
                 {"key":"both","label":"Both are true (different contexts)"},{"key":"neither","label":"Neither"}]},
     {"id":"inbox-007","kind":"conflict","requiredInput":"choice","priority":0.8,"entityId":"dave-example",
      "entityName":"Dave Example","title":"What does Dave Example know?","createdDate":"2026-10-03","informational":true,
      "options":[{"key":"a","label":"x"},{"key":"b","label":"y"}]},
     {"id":"inbox-008","kind":"clarification","requiredInput":"freetext","priority":0.5,"entityId":"delta-example",
      "entityName":"Delta Example","title":"Who is Delta Example?","question":"Who is Delta Example?",
      "createdDate":"2026-10-01","allowOther":true},
     {"id":"inbox-009","kind":"clarification","requiredInput":"freetext","priority":0.5,"entityId":"partner-of-owner",
      "entityName":"Partner","title":"What's the name of your partner?","question":"What's the name of your partner?",
      "createdDate":"2026-10-02","asks":"name","allowOther":true,
      "options":[{"key":"rather_not_say","label":"I'd rather not say"}]},
     {"id":"inbox-010","kind":"followup","requiredInput":"choice","priority":0.5,"entityId":"alpha-project",
      "entityName":"Alpha Project","title":"How did it go?","createdDate":"2026-10-01",
      "options":[{"key":"done","label":"Done"}]}]
    """

    private func decoded() throws -> [InboxItem] {
        try JSONDecoder().decode([InboxItem].self, from: Data(Self.items.utf8))
    }

    private func item(_ id: String) throws -> InboxItem {
        try XCTUnwrap(try decoded().first { $0.id == id })
    }

    private func makeModel() throws -> (Store, FakeSyncAPI, InboxViewModel) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)), api: api)
        api.replies[.inbox] = .notModified
        api.honorsCancellation = true
        store.inbox.value = try decoded()
        store.graceWait = { _ in try? await Task.sleep(for: .seconds(3600)) }
        return (store, api, InboxViewModel(store: store))
    }

    private func eventually(_ condition: @autoclosure () -> Bool,
                            file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<200_000 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("never happened", file: file, line: line)
    }

    private let utc = TimeZone(identifier: "UTC")!
    private let en = Locale(identifier: "en_GB")

    // MARK: The wire

    func testTheReviewContextDecodesAndAnOlderPayloadStillDoes() throws {
        let decay = try item("inbox-001")
        XCTAssertEqual(decay.subject, InboxSubject(summary: "A synthetic side project.", conversations: 3,
                                                   lastSaid: "2026-03-02"))
        XCTAssertNil(decay.fold)
        let fold = try item("inbox-004")
        XCTAssertEqual(fold.fold, InboxFold(raw: "built with", canonical: "uses", claims: 3, pages: 2,
                                            example: "Beta Library is built with a toolkit"))
        XCTAssertNil(try item("inbox-008").subject)
        // A malformed review field costs the field, never the card.
        let bad = #"[{"id":"inbox-1","kind":"decay","requiredInput":"choice","title":"t","fold":{"raw":1}}]"#
        let items = try JSONDecoder().decode([InboxItem].self, from: Data(bad.utf8))
        XCTAssertEqual(items.count, 1)
        XCTAssertNil(items[0].fold)
    }

    // MARK: The entry points

    func testOneEntryPerKindWithSomethingToReviewInOrderWithItsCount() throws {
        let entries = ReviewEntries.of(try decoded())
        XCTAssertEqual(entries.map(\.kind), [.decay, .fold, .conflict, .question])
        // The legacy decay (no options) and the informational conflict stay in the Inbox; a follow-up has no review.
        XCTAssertEqual(entries.map(\.count), [2, 1, 2, 2])
        XCTAssertEqual(Copy.Inbox.Review.entry(.decay, 49), "Fading pages · 49")
        XCTAssertEqual(ReviewEntries.of([]), [])
    }

    // MARK: The answers, in the same place on every card

    func testDecayIsKeepThenLetFadeWhateverOrderTheServerSent() throws {
        let answers = try XCTUnwrap(ReviewCard.answers(try item("inbox-001")))
        XCTAssertEqual(answers.map(\.number), [1, 2])
        XCTAssertEqual(answers.map(\.label), ["Keep", "Let fade"])
        XCTAssertEqual(answers.map(\.resolution.optionKey), ["keep", "archive"])
        XCTAssertEqual(answers.map(\.resolution.action), ["resolve", "resolve"])
        XCTAssertEqual(answers.map(\.recommended), [false, true], "Sleep's proposal is marked, never pre-picked")
        XCTAssertNil(ReviewCard.answers(try item("inbox-003")), "a legacy decay keeps its full card")
    }

    func testAFoldIsSameOrDifferentInItsTwoNames() throws {
        let fold = try item("inbox-004")
        let answers = try XCTUnwrap(ReviewCard.answers(fold))
        XCTAssertEqual(answers.map(\.label), ["Same", "Different"])
        XCTAssertEqual(answers.map(\.resolution.optionKey), ["0", "1"])
        XCTAssertEqual(answers[0].detail, "File \u{201C}built with\u{201D} under \u{201C}uses\u{201D}")
        XCTAssertEqual(answers[1].detail, "Keep \u{201C}built with\u{201D} as its own")
        XCTAssertEqual(ReviewContext.question(fold), "Is \u{201C}built with\u{201D} the same as \u{201C}uses\u{201D}?")
        XCTAssertEqual(ReviewContext.lines(fold), ["Covers 3 facts on 2 pages"])
        XCTAssertEqual(ReviewContext.summary(fold), "A synthetic library.")
    }

    func testAConflictIsEachSideWithItsDayThenBoth() throws {
        let answers = try XCTUnwrap(ReviewCard.answers(try item("inbox-005"), locale: en, timeZone: utc))
        XCTAssertEqual(answers.map(\.number), [1, 2, 3])
        XCTAssertEqual(answers.map(\.label), ["company-a", "company-b", "Both"])
        XCTAssertEqual(answers.map(\.resolution.optionKey), ["a", "b", "both"])
        XCTAssertEqual(answers[0].detail, "Said 2 Mar 2026 · 7 months ago")
        XCTAssertEqual(answers[1].detail, "Said 1 Aug 2026 · 2 months ago")

        let more = try XCTUnwrap(ReviewCard.answers(try item("inbox-006")))
        XCTAssertEqual(more.map(\.resolution.optionKey), ["a", "b", "ax", "both"], "a third side keeps its place; Neither is the full card's")
        XCTAssertNil(ReviewCard.answers(try item("inbox-007")), "a multi-valued conflict is shown, never asked (G98)")
    }

    func testAQuestionTakesWordsAndANameQuestionKeepsItsDecline() throws {
        let open = try item("inbox-008")
        XCTAssertTrue(ReviewCard.takesText(open))
        XCTAssertEqual(ReviewCard.answers(open), [])
        XCTAssertEqual(ReviewCard.typed(open, text: "  a synthetic colleague "),
                       QuestionResolution(action: "resolve", answer: "a synthetic colleague"))
        XCTAssertNil(ReviewCard.typed(open, text: "   "))

        let name = try item("inbox-009")
        XCTAssertTrue(ReviewCard.takesText(name))
        XCTAssertEqual(try XCTUnwrap(ReviewCard.answers(name)).map(\.resolution.optionKey), ["rather_not_say"])
        XCTAssertEqual(ReviewCard.typed(name, text: "Erin Example"), NameAnswer.resolution(name: "Erin Example"))
    }

    func testADecayCardSaysWhenItWasLastSaidAndInHowManyConversations() throws {
        let now = try XCTUnwrap(InboxAge.date("2026-10-19"))
        XCTAssertEqual(ReviewContext.lines(try item("inbox-001"), now: now, locale: en, timeZone: utc),
                       ["Last said 2 Mar 2026", "In 3 conversations"])
        // No subject (an older server): the option's own day, and no count it cannot know.
        XCTAssertEqual(ReviewContext.lines(try item("inbox-002"), now: now, locale: en, timeZone: utc),
                       ["Last said: not recorded"])
        XCTAssertEqual(Copy.Inbox.Review.conversations(1), "In 1 conversation")
    }

    // MARK: The queue, progress and undo

    func testTheQueueIsTheKindsReviewableQuestionsInTheInboxsOrder() throws {
        let review = InboxReview(kind: .decay, items: try decoded())
        XCTAssertEqual(review.queue, ["inbox-002", "inbox-001"], "priority first, as the Inbox lists them")
        XCTAssertEqual(review.currentId, "inbox-002")
        XCTAssertEqual(review.total, 2)
        XCTAssertEqual(review.position, 1)
        XCTAssertEqual(InboxReview(kind: .conflict, items: try decoded()).queue, ["inbox-006", "inbox-005"])
    }

    func testAnswerAndSkipMoveOnAndCountProgress() throws {
        var review = InboxReview(kind: .decay, items: try decoded())
        XCTAssertTrue(review.record(.answered("inbox-002")))
        XCTAssertEqual(review.currentId, "inbox-001")
        XCTAssertEqual(review.position, 2)
        XCTAssertFalse(review.record(.skipped("inbox-002")), "only the card on screen can be decided")
        XCTAssertTrue(review.record(.skipped("inbox-001")))
        XCTAssertTrue(review.isFinished)
        XCTAssertEqual([review.answered, review.skipped, review.left, review.position], [1, 1, 0, 2])
        XCTAssertEqual(Copy.Inbox.Review.progress(answered: 1, skipped: 1, left: 0), "1 answered · 1 skipped · 0 left")
    }

    func testUndoTakesBackASkipAlwaysAndAnAnswerOnlyWhileItIsHeld() throws {
        var review = InboxReview(kind: .decay, items: try decoded())
        review.record(.answered("inbox-002"))
        review.record(.skipped("inbox-001"))
        XCTAssertEqual(review.undo(heldId: "inbox-002"), .skipped("inbox-001"))
        XCTAssertEqual(review.currentId, "inbox-001", "the skipped card is back on screen")
        XCTAssertNil(review.undoable(heldId: nil), "an answer already sent has nothing to undo")
        XCTAssertEqual(review.undo(heldId: "inbox-002"), .answered("inbox-002"))
        XCTAssertEqual(review.currentId, "inbox-002")
        XCTAssertNil(review.undo(heldId: nil))
    }

    func testTheReviewFollowsTheInbox() throws {
        var review = InboxReview(kind: .conflict, items: try decoded())
        review.record(.answered("inbox-006"))
        // inbox-005 settled elsewhere; inbox-006 (answered) is hidden while held.
        review.reconcile(visible: [])
        XCTAssertEqual(review.queue, ["inbox-006"])
        XCTAssertTrue(review.isFinished)
        // The answer came back (refused, rolled back) and nothing else is left: its card is on screen again.
        review.reconcile(visible: ["inbox-006"])
        XCTAssertEqual(review.currentId, "inbox-006")
        XCTAssertEqual(review.answered, 0)
    }

    /// Review B1 — a refused answer goes back AFTER the card being read, never in front of it: answer A (held), answer
    /// B (A sends), read C; A is rolled back → C stays on screen and A waits at the end.
    func testARefusedAnswerNeverDisplacesTheCardBeingRead() throws {
        let three = try decoded().filter { $0.kind == .decay }.map { item -> InboxItem in
            var copy = item
            copy.options = [InboxOption(key: "keep", label: "Keep active", description: nil, claimId: nil,
                                        observedAt: nil, lastReferenced: nil, ageDays: nil),
                            InboxOption(key: "archive", label: "Archive", description: nil, claimId: nil,
                                        observedAt: nil, lastReferenced: nil, ageDays: nil)]
            return copy
        }
        var review = InboxReview(kind: .decay, items: three)
        XCTAssertEqual(review.queue, ["inbox-002", "inbox-001", "inbox-003"])
        review.record(.answered("inbox-002"))   // A
        review.record(.answered("inbox-001"))   // B
        XCTAssertEqual(review.currentId, "inbox-003")   // C on screen
        review.reconcile(visible: ["inbox-002", "inbox-003"])   // A rolled back; B still sending
        XCTAssertEqual(review.currentId, "inbox-003", "the card being read stays")
        XCTAssertEqual(review.queue, ["inbox-001", "inbox-003", "inbox-002"])
        XCTAssertEqual([review.answered, review.left], [1, 2])
        review.record(.skipped("inbox-003"))
        XCTAssertEqual(review.currentId, "inbox-002", "the refused one comes back after it")
    }

    func testAnAnswerOrSkipForACardNoLongerOnScreenIsIgnored() throws {
        let (store, api, vm) = try makeModel()
        vm.startReview(.decay)
        XCTAssertEqual(vm.reviewItem?.id, "inbox-002")
        XCTAssertFalse(vm.reviewAnswer(itemId: "inbox-001", QuestionResolution(action: "resolve", optionKey: "keep")),
                       "a key or button drawn for another card is a no-op")
        XCTAssertNil(store.currentHeld)
        vm.reviewSkip(itemId: "inbox-001")
        XCTAssertEqual(vm.reviewItem?.id, "inbox-002")
        XCTAssertEqual(vm.review?.history, [])
        XCTAssertEqual(api.writes, [])
    }

    // MARK: Keys

    func testOneKeyPerAnswerAKeyToSkipAndTheFieldOwnsItsKeys() {
        XCTAssertEqual(ReviewKeys.action("1", answers: 2, takesText: false, fieldFocused: false), .answer(0))
        XCTAssertEqual(ReviewKeys.action("2", answers: 2, takesText: false, fieldFocused: false), .answer(1))
        XCTAssertNil(ReviewKeys.action("3", answers: 2, takesText: false, fieldFocused: false))
        XCTAssertNil(ReviewKeys.action("0", answers: 2, takesText: false, fieldFocused: false))
        XCTAssertNil(ReviewKeys.action("1", answers: 0, takesText: true, fieldFocused: false))
        XCTAssertEqual(ReviewKeys.action("s", answers: 2, takesText: false, fieldFocused: false), .skip)
        XCTAssertEqual(ReviewKeys.action("S", answers: 2, takesText: false, fieldFocused: false), .skip)
        XCTAssertEqual(ReviewKeys.action("o", answers: 0, takesText: true, fieldFocused: false), .type)
        XCTAssertEqual(ReviewKeys.action("\r", answers: 0, takesText: true, fieldFocused: false), .type)
        XCTAssertNil(ReviewKeys.action("o", answers: 2, takesText: false, fieldFocused: false))
        XCTAssertNil(ReviewKeys.action("\r", answers: 2, takesText: false, fieldFocused: false),
                     "⏎ never accepts a recommendation: one decision per card")
        for key in ["1", "s", "o", "\r"] {
            XCTAssertNil(ReviewKeys.action(key, answers: 2, takesText: true, fieldFocused: true), key)
        }
        XCTAssertTrue(ReviewKeys.undoShortcut(fieldFocused: false))
        XCTAssertFalse(ReviewKeys.undoShortcut(fieldFocused: true), "⌘Z is the field's while it has focus (R-DI4)")
    }

    // MARK: Through the Inbox's own hold

    func testAnAnswerIsTheInboxsHoldAndUndoSendsNothing() async throws {
        let (store, api, vm) = try makeModel()
        vm.startReview(.decay)
        XCTAssertEqual(vm.reviewItem?.id, "inbox-002")
        XCTAssertTrue(vm.reviewAnswer(itemId: "inbox-002", QuestionResolution(action: "resolve", optionKey: "keep")))
        XCTAssertEqual(api.writes, [], "a tap is not a commit")
        XCTAssertEqual(store.currentHeld?.id, "inbox-002")
        XCTAssertEqual(vm.reviewItem?.id, "inbox-001", "the next card swaps in")
        XCTAssertTrue(vm.canUndoReview)
        XCTAssertEqual(vm.reviewLastStep, store.currentHeld?.label)

        vm.reviewUndo()
        XCTAssertNil(store.currentHeld)
        XCTAssertEqual(vm.reviewItem?.id, "inbox-002", "Undo puts the card back")
        XCTAssertEqual(api.writes, [], "an undone answer sends nothing")
        XCTAssertFalse(vm.canUndoReview)
    }

    func testTheNextAnswerSendsTheLastAndSkipsWriteNothing() async throws {
        let (store, api, vm) = try makeModel()
        vm.startReview(.decay)
        vm.reviewSkip(itemId: "inbox-002")
        XCTAssertEqual(vm.reviewItem?.id, "inbox-001")
        XCTAssertEqual(api.writes, [])
        XCTAssertEqual(vm.reviewLastStep, Copy.Inbox.skipped)
        vm.reviewAnswer(itemId: "inbox-001", QuestionResolution(action: "resolve", optionKey: "archive"))
        XCTAssertTrue(vm.review?.isFinished ?? false)
        XCTAssertEqual(store.currentHeld?.id, "inbox-001")
        // A second review's answer sends the first — the Inbox's one Undo window, unchanged.
        vm.endReview()
        vm.startReview(.fold)
        vm.reviewAnswer(itemId: "inbox-004", QuestionResolution(action: "resolve", optionKey: "0"))
        await eventually(api.writes == ["resolveInbox:inbox-001:resolve:archive:nil"])
        XCTAssertEqual(store.currentHeld?.id, "inbox-004")
    }

    func testABankSwitchEndsTheReview() throws {
        let (_, _, vm) = try makeModel()
        vm.startReview(.question)
        XCTAssertNotNil(vm.review)
        vm.resetColumns()
        XCTAssertNil(vm.review)
    }

    /// DR-60 — a key path never animates: the review's handlers run in `Instant.run`, and the file has no
    /// `withAnimation` at all.
    func testTheReviewNeverAnimatesAKey() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(contentsOf: root.appendingPathComponent("Sources/CicadaApp/Views/Inbox/InboxReviewView.swift"),
                                encoding: .utf8)
        XCTAssertFalse(source.contains("withAnimation"))
        XCTAssertTrue(source.contains("Instant.run { viewModel.reviewAnswer(itemId: itemId, resolution) }"))
    }
}
