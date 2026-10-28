import XCTest
@testable import CicadaApp

/// Ruling 48 (1), (2), (8) — the questions on Home and on each page, and the catch-up chat (owner 2026-10-28).
/// Synthetic items, placeholder names.
@MainActor
final class HomeQuestionsTests: XCTestCase {
    private func item(_ id: String, kind: String = "conflict", page: String = "alpha-project",
                      name: String = "Alpha Project", options: String = #"[{"key":"a","label":"Org Gamma"},{"key":"neither","label":"Not anymore"}]"#,
                      extra: String = "") throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(#"""
        {"id":"\#(id)","kind":"\#(kind)","requiredInput":"choice","title":"t \#(id)","priority":0.5,
         "createdDate":"2026-10-20","entityId":"\#(page)","entityName":"\#(name)","entityType":"project",
         "allowDefer":true,"allowOther":true,"options":\#(options),
         "spokenQuestion":"Plain \#(id)?","spokenReason":"Because \#(id)."\#(extra)}
        """#.utf8))
    }

    // MARK: Home

    func testHomeShowsOnePagePerRowInTheServersOrderWithItsPlainQuestion() throws {
        let items = [try item("q1"), try item("q2"), try item("q3", page: "beta", name: "Beta"),
                     try item("q4", page: ""), try item("q5", page: "gamma"), try item("q6", page: "delta")]
        let f = HomeQuestions.figures(items, now: .now)
        XCTAssertEqual(f.rows.map(\.id), ["q1", "q3", "q4", "q5"], "one row per page, at most four, server order")
        XCTAssertEqual(f.rows[0].onPage, 2)
        XCTAssertEqual(f.rows[0].question, "Plain q1?")
        XCTAssertEqual(f.rows[0].reason, "Because q1.")
        XCTAssertEqual(f.rows[0].entityType, .project)
        XCTAssertEqual(f.total, 6)
        XCTAssertEqual(f.catchUp, ["q1", "q2", "q3", "q4", "q5", "q6"])
        XCTAssertEqual(f.catchUpPages, 5)
    }

    func testOnlyQuestionsCicadaCanAskInASentenceAreAskedTheRestStayInTheList() throws {
        let shown = try item("info", extra: #","informational":true"#)
        let request = try JSONDecoder().decode(InboxItem.self, from: Data(#"{"id":"agentreq-1","kind":"agent_request","requiredInput":"none","title":"Sign in","status":"pending"}"#.utf8))
        let pairNoOther = try item("m1", kind: "merge_suggestion", options: "[]")
        let pair = try item("m2", kind: "merge_suggestion", options: "[]", extra: #","mergeTargetHint":"beta""#)
        let fold = try item("n1", kind: "normalization")
        let f = HomeQuestions.figures([shown, request, pairNoOther, pair, fold], now: .now)
        XCTAssertEqual(f.catchUp, ["m2"], "a fold is the person's housekeeping: it waits in the list")
        XCTAssertEqual(f.total, 5, "All N counts every question in the list")
    }

    func testAPagesStripCarriesItsOwnQuestionsEitherSideOfAPair() throws {
        let items = [try item("q1"), try item("q2", page: "beta"),
                     try item("m1", kind: "merge_suggestion", page: "gamma", options: "[]",
                              extra: #","mergeTargetHint":"alpha-project""#)]
        XCTAssertEqual(HomeQuestions.onPage(items, entityId: "alpha-project").map(\.id), ["q1", "m1"])
        XCTAssertEqual(HomeQuestions.onPage(items, entityId: "").count, 0)
        XCTAssertEqual(Copy.Catchup.stripTitle(1, of: 2), "A question · 1 of 2")
        XCTAssertEqual(Copy.Catchup.stripTitle(1, of: 1), "A question")
    }

    func testTheWirePlainWordsDecodeAndAnOlderServerFallsBackToTheStoredQuestion() throws {
        XCTAssertEqual(try item("q1").askText, "Plain q1?")
        let old = try JSONDecoder().decode(InboxItem.self, from: Data(#"{"id":"q","kind":"decay","requiredInput":"choice","title":"Still tracking Beta?"}"#.utf8))
        XCTAssertNil(old.spokenQuestion)
        XCTAssertEqual(old.askText, "Still tracking Beta?")
    }

    /// Home never waits on `GET /inbox`: its figures are a pure pass over the Store's snapshot. Basis: 500 synthetic
    /// questions on 200 pages, 50 runs, this machine.
    func testHomesFiguresAreCheapAtOwnerScale() throws {
        let items = try (0..<500).map { try item("q\($0)", page: "p\($0 % 200)") }
        var times: [Double] = []
        for _ in 0..<50 {
            let t0 = Date()
            _ = HomeQuestions.figures(items, now: .now)
            times.append(Date().timeIntervalSince(t0) * 1000)
        }
        let p95 = times.sorted()[Int(Double(times.count) * 0.95)]
        print("HomeQuestions.figures p95 ms (500 items):", p95)
        XCTAssertLessThan(p95, 50)
    }

    // MARK: Answers

    func testChipsAreTheInboxsOwnResolutions() throws {
        let q = try item("q1")
        let chips = CatchupAnswers.chips(q)
        XCTAssertEqual(chips.map(\.label), ["Org Gamma", "Not anymore", "Not now", "Skip"])
        XCTAssertEqual(chips[0].resolution, QuestionResolution(action: "resolve", optionKey: "a"))
        XCTAssertEqual(chips[2].resolution, QuestionResolution(action: "defer", remindDays: 7))
        XCTAssertNil(chips[3].resolution, "Skip sends nothing")
        let pair = try item("m", kind: "merge_suggestion", options: "[]", extra: #","mergeTargetHint":"beta""#)
        XCTAssertEqual(CatchupAnswers.chips(pair).prefix(2).map(\.resolution),
                       [QuestionResolution(action: "merge", mergeTarget: "beta", mergeSurvivor: "beta"),
                        QuestionResolution(action: "reject", mergeTarget: "beta")])
    }

    func testAReadingBecomesAResolutionOnlyWhenItFitsTheQuestion() throws {
        let q = try item("q1")
        typealias R = CatchupTurnReply.Reading
        XCTAssertEqual(CatchupAnswers.resolution(q, R(optionKey: "a", answer: nil, quote: "still", confirm: false)),
                       QuestionResolution(action: "resolve", optionKey: "a", quote: "still"),
                       "a reading carries the person's located words as its evidence")
        XCTAssertEqual(CatchupAnswers.resolution(q, R(optionKey: "a", answer: nil, quote: "still", confirm: false),
                                                 sessionId: "catchup-s1")?.sessionId, "catchup-s1")
        XCTAssertNil(CatchupAnswers.resolution(q, R(optionKey: "zz", answer: nil, quote: "x", confirm: false)))
        XCTAssertEqual(CatchupAnswers.resolution(q, R(optionKey: nil, answer: "Org Delta", quote: "Org Delta",
                                                      confirm: false)),
                       QuestionResolution(action: "resolve", answer: "Org Delta", optionKey: "neither",
                                          quote: "Org Delta"))
        let pair = try item("m", kind: "merge_suggestion", options: "[]", extra: #","mergeTargetHint":"beta""#)
        XCTAssertEqual(CatchupAnswers.resolution(pair, R(optionKey: "same", answer: nil, quote: "yes", confirm: true))?.action,
                       "merge")
        XCTAssertNil(CatchupAnswers.resolution(pair, R(optionKey: "a", answer: nil, quote: "yes", confirm: true)))
    }

    // MARK: The chat

    private final class Fake {
        var items: [InboxItem]
        var held: [(String, QuestionResolution)] = []
        var heldId: String?
        var replies: [CatchupTurnReply] = []
        var turns: [(String, String, [String])] = []
        var records: [[CatchupLine]] = []
        init(_ items: [InboxItem]) { self.items = items }
    }

    private func session(_ fake: Fake) -> CatchupSession {
        CatchupSession(
            queue: fake.items.map(\.id), items: { fake.items.filter { $0.id != fake.heldId } },
            hold: { item, r in fake.held.append((item.id, r)); fake.heldId = item.id; return true },
            heldId: { fake.heldId },
            release: { defer { fake.heldId = nil }; return fake.items.first { $0.id == fake.heldId } },
            turn: { id, message, _, upcoming in
                fake.turns.append((id, message, upcoming))
                return fake.replies.isEmpty ? CatchupTurnReply(reply: nil) : fake.replies.removeFirst()
            },
            record: { _, lines in fake.records.append(lines) })
    }

    private func said(_ s: CatchupSession) -> [String] {
        s.lines.compactMap { if case .cicada(let t, _) = $0.kind { return t } else { return nil } }
    }

    func testItAsksTheMostUsedFirstInPlainWordsAndATapIsTheInboxsHeldAnswer() async throws {
        let fake = Fake([try item("q1"), try item("q2", page: "beta")])
        let s = session(fake)
        s.start()
        XCTAssertEqual(said(s), [Copy.Catchup.opening, "Plain q1? Because q1."])
        XCTAssertEqual(s.mood, .asking)
        s.tap(s.chips[0])
        XCTAssertEqual(fake.held.first?.0, "q1")
        XCTAssertEqual(fake.held.first?.1, QuestionResolution(action: "resolve", optionKey: "a"))
        XCTAssertTrue(s.lines.contains { if case .noted("Noted: Org Gamma", "q1") = $0.kind { true } else { false } })
        XCTAssertEqual(s.currentId, "q2")
        XCTAssertEqual(s.position, 2)
        await s.settled()
        XCTAssertTrue(fake.records.isEmpty, "a tap is never the person's words: a chat of taps keeps nothing")
    }

    /// Review B1 of #509 — a tapped label never reaches the record as `user:`, and an undone answer leaves the chat.
    func testATappedThenUndoneAnswerNeverReachesTheRecordAsTheirWords() async throws {
        let fake = Fake([try item("q1"), try item("q2", page: "beta")])
        let s = session(fake)
        s.start()
        s.tap(s.chips[0])
        s.undo("q1")
        XCTAssertFalse(s.lines.contains { if case .tap = $0.kind { true } else { false } }, "the undone tap is gone")
        XCTAssertFalse(s.lines.contains { if case .noted = $0.kind { true } else { false } })
        s.tap(s.chips.first { $0.role == .skip }!)
        fake.replies = [CatchupTurnReply(reply: "Got it.", move: "stay")]
        s.draft = "I typed this myself"
        await s.send()
        await s.settled()
        let record = try XCTUnwrap(fake.records.last)
        let mine = record.compactMap { $0.wire }.filter { $0.who == "you" }.map(\.text)
        XCTAssertEqual(mine, ["I typed this myself"], "only typed words are the person's")
        XCTAssertFalse(record.compactMap { $0.wire?.text }.contains("Org Gamma"))
    }

    func testTheirOwnWordsGetAFollowUpAndAGroundedReadingIsApplied() async throws {
        let fake = Fake([try item("q1"), try item("q2", page: "beta"), try item("q3", page: "gamma")])
        let s = session(fake)
        s.start()
        fake.replies = [CatchupTurnReply(reply: "Do you mean the new team?", move: "stay")]
        s.draft = "kind of, it changed"
        XCTAssertEqual(s.mood, .listening, "the worm reacts while they type")
        await s.send()
        XCTAssertEqual(s.currentId, "q1", "a follow-up stays on the question")
        XCTAssertTrue(fake.held.isEmpty)
        XCTAssertEqual(fake.turns.first?.2, ["q2", "q3"], "the reply may move to an upcoming question")
        // The answer touches another question: the reply moves there, asked in its own words — no template repeat.
        fake.replies = [CatchupTurnReply(reply: "Noted. And is Gamma still going?",
                                         reading: .init(optionKey: "a", answer: nil, quote: "still", confirm: false),
                                         move: "next", nextId: "q3")]
        s.draft = "still there"
        await s.send()
        XCTAssertEqual(fake.held.map(\.0), ["q1"])
        XCTAssertEqual(s.currentId, "q3")
        XCTAssertFalse(said(s).contains("Plain q3? Because q3."))
        XCTAssertEqual(said(s).last, "Noted. And is Gamma still going?")
    }

    func testWhoSomeoneIsIsNeverAppliedFromAReadingOnlyConfirmedByATap() async throws {
        let fake = Fake([try item("m", kind: "merge_suggestion", options: "[]", extra: #","mergeTargetHint":"beta""#)])
        let s = session(fake)
        s.start()
        fake.replies = [CatchupTurnReply(reply: "So they're one person?",
                                         reading: .init(optionKey: "same", answer: nil, quote: "same", confirm: true),
                                         move: "next")]
        s.draft = "yes, same person"
        await s.send()
        XCTAssertTrue(fake.held.isEmpty, "ruling 41: a reading never joins anyone")
        XCTAssertNotNil(s.confirmation)
        s.confirm()
        XCTAssertEqual(fake.held.first?.1.action, "merge")
    }

    func testWithNoEngineItSaysSoAndTakesTapsAndTheirWordsAsAFreeAnswer() async throws {
        let fake = Fake([try item("q1")])
        let s = session(fake)
        s.start()
        fake.replies = [CatchupTurnReply(reply: nil, engine: false, why: "nothing is signed in.")]
        s.draft = "I moved to Org Delta"
        await s.send()
        XCTAssertTrue(s.tapsOnly)
        XCTAssertEqual(s.confirmation?.resolution,
                       QuestionResolution(action: "resolve", answer: "I moved to Org Delta", optionKey: "neither"))
        XCTAssertTrue(fake.held.isEmpty, "nothing is answered until the person taps")
    }

    func testUndoAsksTheQuestionAgainAndStopEndsTheChat() async throws {
        let fake = Fake([try item("q1"), try item("q2", page: "beta")])
        let s = session(fake)
        s.start()
        s.tap(s.chips[0])
        s.undo("q1")
        XCTAssertEqual(s.currentId, "q1")
        XCTAssertEqual(said(s).last, "Plain q1? Because q1.")
        s.stop()
        XCTAssertTrue(s.finished)
        XCTAssertNil(s.current)
        XCTAssertEqual(s.mood, .idle)
    }

    // MARK: The worm

    /// Ruling 18 — the face plays the menu bar sheet's own clips, inside `CicadaMotion`'s sprite caps; no new frames.
    func testEveryMoodIsAClipOfTheMenuBarSheetWithinTheSpriteCaps() throws {
        let sheet = try XCTUnwrap(SpriteSheets.sheet(named: MascotRegistry.bookworm.menuBarSheet))
        for mood in [CatchupSession.Mood.asking, .listening, .thinking, .pleased, .idle] {
            let clip = try XCTUnwrap(sheet.clip(WormFace.tag(mood)), "\(mood)")
            XCTAssertTrue(clip.seconds.allSatisfy { $0 >= CicadaMotion.spriteFrameMin && $0 <= CicadaMotion.spriteFrameMax })
            XCTAssertLessThanOrEqual(clip.total, CicadaMotion.spriteLoopMax)
        }
        XCTAssertEqual(WormFace.tag(.asking), "curious", "the questioning head")
    }
}
