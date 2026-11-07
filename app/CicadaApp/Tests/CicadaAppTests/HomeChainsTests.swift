import XCTest
@testable import CicadaApp

/// #501's same-person chains in the app (coordinator 2026-10-29, after #509): asked once on Home, on a page and in the
/// chat — "Are A, B and C the same person?" — and answered pair by pair, one tap each; never joined by one answer or
/// by typed words alone (ruling 41). Synthetic names.
@MainActor
final class HomeChainsTests: XCTestCase {
    private let question = "Are Sam Example, Samantha Example and Sammy Example the same person?"

    private func pair(_ id: String, page: String, hint: String, a: String, b: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(#"""
        {"id":"\#(id)","kind":"merge_suggestion","requiredInput":"merge","title":"t","priority":0.5,
         "createdDate":"2026-10-20","entityId":"\#(page)","entityName":"\#(a)","entityType":"person",
         "mergeTargetHint":"\#(hint)","spokenQuestion":"Are \#(a) and \#(b) the same person?",
         "chain":["m1","m2"],"chainQuestion":"\#(question)",
         "chainReason":"These names come up the way one name would, and I only join people on your word.",
         "chainPairs":[{"id":"m1","a":"Sam Example","b":"Samantha Example"},
                       {"id":"m2","a":"Sammy Example","b":"Samantha Example"}]}
        """#.utf8))
    }

    private func items() throws -> [InboxItem] {
        [try pair("m1", page: "sam-example", hint: "samantha-example", a: "Sam Example", b: "Samantha Example"),
         try pair("m2", page: "sammy-example", hint: "samantha-example", a: "Sammy Example", b: "Samantha Example")]
    }

    func testAChainIsOneQuestionOnHomeAndInTheCatchUp() throws {
        let f = HomeQuestions.figures(try items(), now: .now)
        XCTAssertEqual(f.rows.map(\.id), ["m1"])
        XCTAssertEqual(f.rows.first?.question, question)
        XCTAssertEqual(f.catchUp, ["m1"], "the chat asks it once")
        XCTAssertEqual(f.total, 2, "All N still counts every question")
        // Once the first pair is answered, the other stands for the chain.
        XCTAssertEqual(HomeQuestions.leads(Array(try items().dropFirst())).map(\.id), ["m2"])
    }

    func testAPageShowsTheChainOnceWhicheverPairTouchesIt() throws {
        XCTAssertEqual(HomeQuestions.onPage(try items(), entityId: "sammy-example").map(\.id), ["m1"])
        XCTAssertEqual(HomeQuestions.onPage(try items(), entityId: "samantha-example").map(\.id), ["m1"])
    }

    func testEachPairIsItsOwnTapAndAnswersOnlyItself() throws {
        let all = try items()
        let chips = CatchupAnswers.chips(all[0], open: all)
        XCTAssertEqual(chips.map(\.label), ["Sam Example is Samantha Example", "Sam Example isn't Samantha Example",
                                            "Sammy Example is Samantha Example", "Sammy Example isn't Samantha Example",
                                            "Skip"])
        XCTAssertEqual(chips[2].itemId, "m2")
        XCTAssertEqual(chips[2].resolution,
                       QuestionResolution(action: "merge", mergeTarget: "samantha-example",
                                          mergeSurvivor: "samantha-example"))
        XCTAssertEqual(chips[1].resolution?.action, "reject")
    }

    func testTheChatStaysOnTheChainUntilEveryPairIsAnsweredOneTapEach() async throws {
        var open = try items()
        var held: [(String, QuestionResolution)] = []
        let decay = try JSONDecoder().decode(InboxItem.self, from: Data(#"{"id":"d1","kind":"decay","requiredInput":"choice","title":"Still tracking Beta?","allowDefer":true,"options":[{"key":"keep","label":"Keep"},{"key":"archive","label":"Archive"}]}"#.utf8))
        open.append(decay)
        let s = CatchupSession(
            queue: HomeQuestions.figures(open, now: .now).catchUp, items: { open },
            hold: { item, r in held.append((item.id, r)); open.removeAll { $0.id == item.id }; return true },
            heldId: { held.last?.0 }, release: { nil },
            turn: { _, _, _, _ in CatchupTurnReply(reply: nil) }, record: { _, _ in })
        s.start()
        XCTAssertTrue(s.lines.contains { if case .cicada(let t, _) = $0.kind { t.hasPrefix(self.question) } else { false } })
        s.tap(try XCTUnwrap(s.chips.first { $0.id == "same:m1" }))
        XCTAssertEqual(held.map(\.0), ["m1"], "one tap answers one pair")
        XCTAssertNotNil(s.currentId)
        XCTAssertEqual(s.current?.id, "m2", "the chain stays until its other pair is answered")
        XCTAssertEqual(s.chips.filter { $0.role == .answer }.map(\.itemId), ["m2", "m2"])
        s.tap(try XCTUnwrap(s.chips.first { $0.id == "different:m2" }))
        XCTAssertEqual(held.map(\.0), ["m1", "m2"])
        XCTAssertEqual(held.last?.1.action, "reject")
        XCTAssertEqual(s.current?.id, "d1", "then the talk moves on")
    }

    /// The owner's case, 2026-11-05 (placeholders): one message, two answers. Both go in one hold under one Undo, the
    /// parting before the join, and neither the proposal nor the chain's taps stay.
    func testTwoAnswersInOneMessageResolveBothPairsAtOnce() async throws {
        var open = try items()
        let decay = try JSONDecoder().decode(InboxItem.self, from: Data(#"{"id":"d1","kind":"decay","requiredInput":"choice","title":"Still tracking Beta?","allowDefer":true,"options":[{"key":"keep","label":"Keep"},{"key":"archive","label":"Archive"}]}"#.utf8))
        open.append(decay)
        var held: [[(String, QuestionResolution)]] = []
        let s = CatchupSession(
            queue: HomeQuestions.figures(open, now: .now).catchUp, items: { open },
            hold: { _, _ in XCTFail("one hold for the whole answer"); return false },
            heldId: { held.last?.first?.0 }, release: { nil },
            turn: { _, _, _, _ in
                CatchupTurnReply(reply: nil, readings: [
                    .init(itemId: "m1", optionKey: "same", answer: nil, quote: "she is Samantha"),
                    .init(itemId: "m2", optionKey: "different", answer: nil, quote: "nothing to do with her")
                ], move: "next")
            }, record: { _, _ in },
            holdAll: { parts in
                held.append(parts.map { ($0.item.id, $0.resolution) })
                open.removeAll { o in parts.contains { $0.item.id == o.id } }
                return true
            })
        s.start()
        s.draft = "she is Samantha, I'm nothing to do with her"
        await s.send()
        XCTAssertEqual(held.count, 1)
        XCTAssertEqual(held[0].map(\.0), ["m2", "m1"], "apart first, the join last")
        XCTAssertEqual(held[0].map(\.1.quote), ["nothing to do with her", "she is Samantha"], "each on its own words")
        XCTAssertNil(s.confirmation)
        XCTAssertEqual(s.current?.id, "d1", "the chain is settled and its tap row gone")
        XCTAssertTrue(s.lines.contains {
            if case .noted(let text, "m2") = $0.kind {
                text == "Noted: Sammy Example isn't Samantha Example, Sam Example is Samantha Example"
            } else { false }
        })
        XCTAssertEqual(s.undoableId, "m2", "one Undo for the whole answer")
    }

    /// A part-answer stays on the chain with only the open pair's taps, and a join carried on a parted pair names who.
    func testAPartAnswerKeepsOnlyTheOpenPairAndAJoinSaysWho() async throws {
        var open = try items()
        var held: [(String, QuestionResolution)] = []
        let s = CatchupSession(
            queue: HomeQuestions.figures(open, now: .now).catchUp, items: { open },
            hold: { item, r in held.append((item.id, r)); open.removeAll { $0.id == item.id }; return true },
            heldId: { held.last?.0 }, release: { nil },
            turn: { _, _, _, _ in
                CatchupTurnReply(reply: "And the other two?", readings: [
                    .init(itemId: "m1", optionKey: "same", answer: nil, quote: "is Other", mergeTarget: "other-page",
                          targetName: "Other Example")], unjoined: [.init(a: "X Example", b: "Y Example")], move: "stay")
            }, record: { _, _ in })
        s.start()
        s.draft = "Sam is Other"
        await s.send()
        XCTAssertEqual(held.first?.1.mergeTarget, "other-page")
        XCTAssertEqual(held.first?.1.mergeSurvivor, "other-page")
        XCTAssertEqual(s.current?.id, "m2", "the other pair is still open")
        XCTAssertEqual(s.chips.filter { $0.role == .answer }.map(\.itemId), ["m2", "m2"])
        XCTAssertTrue(s.lines.contains {
            if case .noted("Noted: Sam Example is Other Example", "m1") = $0.kind { true } else { false }
        })
        XCTAssertTrue(s.lines.contains {
            if case .aside("I couldn't join X Example and Y Example from here.") = $0.kind { true } else { false }
        }, "a join no question can carry is said, never dropped in silence")
    }
}
