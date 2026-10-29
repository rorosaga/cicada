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

    /// #536 review — typed "yes, all the same": each pair is proposed by name and joined only on its own Yes; the chat
    /// never leaves the chain with a pair unasked.
    func testTypedAllTheSameProposesEachPairByNameOneYesEach() async throws {
        var open = try items()
        var held: [(String, QuestionResolution)] = []
        let s = CatchupSession(
            queue: HomeQuestions.figures(open, now: .now).catchUp, items: { open },
            hold: { item, r in held.append((item.id, r)); open.removeAll { $0.id == item.id }; return true },
            heldId: { held.last?.0 }, release: { nil },
            turn: { _, _, _, _ in
                CatchupTurnReply(reply: "Sounds like they're one person — shall I join them?",
                                 reading: .init(optionKey: "same", answer: nil, quote: "all the same", confirm: true),
                                 move: "stay")
            }, record: { _, _ in })
        s.start()
        s.draft = "yes, all the same"
        await s.send()
        XCTAssertTrue(held.isEmpty, "typed words alone join no one")
        XCTAssertEqual(s.confirmation?.label, "Join Sam Example and Samantha Example as one?")
        s.confirm()
        XCTAssertEqual(held.map(\.0), ["m1"], "Yes joins exactly the pair it named")
        XCTAssertEqual(held.first?.1.quote, "all the same")
        XCTAssertEqual(s.current?.id, "m2", "the chain stays: its other pair is still open")
        XCTAssertEqual(s.confirmation?.label, "And Sammy Example and Samantha Example, one too?")
        XCTAssertEqual(s.confirmation?.itemId, "m2")
        s.notQuite()
        XCTAssertEqual(held.map(\.0), ["m1"], "Not quite on the next pair joins nothing")
        XCTAssertEqual(s.current?.id, "m2")
        XCTAssertEqual(s.chips.filter { $0.role == .answer }.map(\.itemId), ["m2", "m2"], "its own chips wait")
    }
}
