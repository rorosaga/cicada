import SwiftUI
import XCTest
@testable import CicadaApp

/// The opened page change (owner 2026-11-24: "pages render normally, not as raw markdown … and I don't get why a page
/// was modified, what influenced this change?"), from the SHARED fixtures the backend writes
/// (`api/tests/test_sleep_v5_app_fixtures.py`): the wire decodes, why is said once, a fact says what moved in words,
/// and prose becomes the article's own rows with the changed words marked. Synthetic names only.
final class RunPageChangeModelTests: XCTestCase {
    private let us = Locale(identifier: "en_US_POSIX")

    private static let fixtures = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("fixtures")

    private func changes() throws -> [String: SleepPageChange] {
        try JSONDecoder().decode([String: SleepPageChange].self,
                                 from: Data(contentsOf: Self.fixtures.appendingPathComponent("sleep-page-change.json")))
    }

    // MARK: The wire

    func testTheFixturesDecodeEveryCase() throws {
        let all = try changes()
        XCTAssertEqual(Set(all.keys), ["fed", "step", "faded", "bookkeeping"])
        let fed = try XCTUnwrap(all["fed"])
        XCTAssertEqual(fed.change, "updated")
        XCTAssertEqual(fed.conversations.map(\.id), ["ep_2026-10-02_000"])
        XCTAssertTrue(fed.conversations[0].inRun)
        XCTAssertEqual(fed.facts.added.count, 1)
        XCTAssertEqual(fed.facts.added[0].claim.text, "fed-page fact 2")
        XCTAssertEqual(fed.facts.added[0].conversation, "ep_2026-10-02_000")
        XCTAssertEqual(fed.facts.changed[0].changes.map(\.field), ["valid_to", "confidence"])
        XCTAssertEqual(fed.prose.blocks.map(\.op), [.context, .edited, .context, .context, .added, .context, .removed])
        XCTAssertEqual(fed.prose.blocks[1].segments.map(\.op), [.equal, .added, .equal])
        XCTAssertEqual(fed.other.map(\.field), ["aliases"])
        XCTAssertEqual(fed.page.steps, [.reading])
        XCTAssertEqual(try XCTUnwrap(all["step"]).page.steps, [.sourceCheck])
        XCTAssertTrue(try XCTUnwrap(all["faded"]).empty)
        XCTAssertEqual(try XCTUnwrap(all["faded"]).facts.faded, 1)
        XCTAssertFalse(try XCTUnwrap(all["faded"]).hasContent)
    }

    func testTheItemsFixtureCarriesFadedStepsAndTheNewCounts() throws {
        let items = try JSONDecoder().decode(SleepConsolidated.self,
                                             from: Data(contentsOf: Self.fixtures.appendingPathComponent("sleep-run-items.json")))
        XCTAssertEqual(items.faded.map(\.id), ["faded-one"])
        XCTAssertEqual(items.fadedPages.map(\.change), [.faded])
        XCTAssertEqual(items.counts["faded"], 1)
        XCTAssertEqual(items.counts["bookkeeping"], 1, "a diagnostic: the app never lists it")
        XCTAssertFalse(items.pages.contains { $0.change == .faded })
        XCTAssertEqual(items.updated.first { $0.id == "restored" }?.steps, [.decay, .reading])
    }

    func testTheHistoryFixtureCarriesTheClosedCardsWholeCounts() throws {
        let entry = try JSONDecoder().decode(SleepHistoryEntry.self,
                                             from: Data(contentsOf: Self.fixtures.appendingPathComponent("sleep-history-run.json")))
        XCTAssertEqual([entry.entitiesArchived, entry.entitiesRemoved, entry.entitiesFaded], [0, 0, 0])
        XCTAssertEqual(entry.run?.archived, 0)
        XCTAssertEqual(entry.run?.faded, 0)
    }

    /// The closed card says what the opened card says: archived, removed and faded join created and updated.
    func testTheClosedCardCountsEveryKind() throws {
        let entry = try JSONDecoder().decode(SleepHistoryEntry.self, from: Data("""
        {"commitHash": "aaa1111", "date": "2026-11-22T03:00:00+00:00", "message": "Sleep cycle", "filesChanged": [],
         "kind": "sleep", "entitiesCreated": 1, "entitiesUpdated": 5, "entitiesArchived": 3, "entitiesRemoved": 1,
         "entitiesFaded": 285, "episodes": 1, "sessions": 1, "authors": []}
        """.utf8))
        let card = try XCTUnwrap(RunCardModel.cards([entry], locale: us).first)
        XCTAssertEqual(card.summary, "1 conversation · 1 new page · 5 updated · 3 archived · 1 removed · 285 faded")
        XCTAssertEqual(Copy.RunCard.summary(conversations: 2, created: 0, updated: 0, faded: 4, locale: us),
                       "2 conversations · 4 pages faded")
    }

    func testAMistypedPartOfTheChangeNeverFailsTheDecode() throws {
        let change = try JSONDecoder().decode(SleepPageChange.self, from: Data("""
        {"change": "updated", "page": {"id": "p"}, "conversations": [{"id": "e", "inRun": "yes"}, 7],
         "facts": {"added": [{"claim": 3}, {"claim": {"id": "c", "text": "A sentence."}, "changes": [{"field": 4}]}]},
         "prose": {"blocks": [{"op": "mystery", "markdown": 1}]}, "other": "x"}
        """.utf8))
        XCTAssertEqual(change.conversations.map(\.id), ["e"])
        XCTAssertEqual(change.facts.added.map(\.claim.text), ["A sentence."], "the bad fact is dropped, not the page")
        XCTAssertEqual(change.facts.added[0].changes.map(\.field), ["details"])
        XCTAssertEqual(change.other, [])
    }

    func testThePathNamesTheRunOrTheCommit() {
        XCTAssertEqual(SleepPageChange.path(.run("sleep_a"), page: "alpha-project"), "/sleep/runs/sleep_a/pages/alpha-project/change")
        XCTAssertEqual(SleepPageChange.path(.commit("abc1234"), page: "a b"), "/sleep/history/abc1234/pages/a%20b/change")
    }

    // MARK: Why, said once

    func testWhyIsWhatTheCardItSitsUnderDoesNotAlreadySay() throws {
        let all = try changes()
        let fed = try XCTUnwrap(all["fed"])
        XCTAssertTrue(RunPageChangeModel.why(fed, parent: .init(conversation: "ep_2026-10-02_000")).isEmpty,
                      "the card is that conversation: nothing to add")
        XCTAssertEqual(RunPageChangeModel.why(fed, parent: .init(conversation: "ep_2026-10-01_001")).conversations.map(\.id),
                       ["ep_2026-10-02_000"], "another conversation of the run fed it too")
        let step = try XCTUnwrap(all["step"])
        XCTAssertTrue(RunPageChangeModel.why(step, parent: .init(step: .sourceCheck)).isEmpty)
        XCTAssertEqual(RunPageChangeModel.why(step, parent: .none).steps, [.sourceCheck],
                       "with no card to say it, the panel says the step")
        XCTAssertEqual(RunPageChangeModel.why(step, parent: .init(step: .conflict)).steps, [.sourceCheck])
    }

    func testAFactsConversationIsShownOnlyWhenNothingElseSaidIt() throws {
        let fed = try XCTUnwrap(changes()["fed"])
        let fact = fed.facts.added[0]
        XCTAssertNil(RunPageChangeModel.factConversation(fact, in: fed, parent: .init(conversation: "ep_2026-10-02_000")))
        XCTAssertNil(RunPageChangeModel.factConversation(fact, in: fed, parent: .none),
                     "already named once by the why section")
        XCTAssertEqual(RunPageChangeModel.factConversation(fact, in: fed, parent: .init(step: .decay))?.id, nil,
                       "a conversation the why section names is never named again")
    }

    func testEveryStepHasItsOwnWordsAndNoneNamesAProvider() {
        let words = SleepConsolidated.Step.allCases.flatMap { [Copy.RunChange.stepTitle($0), Copy.RunChange.stepSentence($0)] }
        XCTAssertEqual(Set(words).count, words.count, "each step says its own thing")
        for word in words {
            for provider in ["Claude", "OpenAI", "ChatGPT", "Gemini", "Anthropic", "model"] {
                XCTAssertFalse(word.contains(provider), "\(word) names a provider")
            }
        }
        XCTAssertEqual(Copy.RunChange.stepTitle(.sourceCheck), "Sources re-checked")
        XCTAssertEqual(Copy.RunChange.stepSentence(.summary), "Its short summary was rewritten")
    }

    // MARK: A fact, in words

    func testAFactSaysWhatMovedInWordsNeverAFieldNameOrAnId() throws {
        let fed = try XCTUnwrap(changes()["fed"])
        XCTAssertEqual(RunPageChangeModel.factWords(fed.facts.changed[0], locale: us),
                       "Ended Sep 30 · Confidence 80% → 60%")
        func fact(_ changes: String) throws -> SleepPageChange.Fact {
            try JSONDecoder().decode(SleepPageChange.Fact.self, from: Data("""
            {"claim": {"id": "c", "text": "T."}, "changes": \(changes)}
            """.utf8))
        }
        XCTAssertEqual(RunPageChangeModel.factWords(try fact("""
        [{"field": "text"}, {"field": "object"}, {"field": "predicate"}]
        """), locale: us), "Reworded", "reworded once, however many parts moved")
        XCTAssertEqual(RunPageChangeModel.factWords(try fact("""
        [{"field": "superseded_by", "before": null, "after": "clm_2026-09-01_004"}, {"field": "sources", "added": ["ep_x", "ep_y"]}]
        """), locale: us), "Replaced by another fact · Backed by 2 more conversations")
        XCTAssertEqual(RunPageChangeModel.factWords(try fact("""
        [{"field": "valid_to", "before": "2026-09-30", "after": null}, {"field": "source_trust", "after": "user_stated"}]
        """), locale: us), "No longer ended · Now counted as: \(SourceTrust.userStated.label.lowercasedFirst)")
        XCTAssertNil(RunPageChangeModel.factWords(try fact("[]"), locale: us))
        for field in ["clm_", "valid_to", "superseded_by", "source_trust"] {
            XCTAssertFalse((RunPageChangeModel.factWords(fed.facts.changed[0], locale: us) ?? "").contains(field))
        }
    }

    func testAPageLevelChangeIsInWords() {
        func lines(_ field: String, before: String? = nil, after: String? = nil, added: [String] = [], removed: [String] = []) -> [String] {
            RunPageChangeModel.otherLines(.init(field: field, before: before, after: after, added: added, removed: removed))
        }
        XCTAssertEqual(lines("status", before: "active", after: "archived"), ["Active → Archived"])
        XCTAssertEqual(lines("aliases", added: ["The Fed"]), ["Also called The Fed"])
        XCTAssertEqual(lines("aliases", added: ["A"], removed: ["B"]), ["Also called A", "No longer called B"])
        XCTAssertEqual(lines("name", before: "Old", after: "New"), ["Renamed from Old to New"])
        XCTAssertEqual(lines("decay_class", after: "volatile"), ["Kept as short-lived"])
        XCTAssertEqual(lines("something-else", after: "x"), [])
    }

    func testTheLineOverTheChangeSaysEachPartOnceAndOnlyWhenItStandsAlone() throws {
        let fed = try XCTUnwrap(changes()["fed"])
        XCTAssertEqual(RunPageChangeModel.summary(fed, locale: us),
                       "1 new fact · 1 fact changed · 1 passage added · 1 passage edited · 1 passage removed · 1 other change")
        XCTAssertEqual(RunPageChangeModel.sectionCount(fed, parent: .init(conversation: "ep_2026-10-02_000")), 4,
                       "facts added, facts changed, text, the page: each is labelled")
        let step = try XCTUnwrap(changes()["step"])
        XCTAssertEqual(RunPageChangeModel.sectionCount(step, parent: .init(step: .sourceCheck)), 1,
                       "one part: no label, and the line over it says what it holds")
        XCTAssertEqual(RunPageChangeModel.summary(step, locale: us), "1 new fact")
        XCTAssertNil(RunPageChangeModel.summary(try XCTUnwrap(changes()["faded"]), locale: us))
    }

    // MARK: The text, as the article draws it

    func testProseIsTheArticlesOwnRowsNotRawMarkdown() throws {
        let fed = try XCTUnwrap(changes()["fed"])
        let heading = RunPageChangeModel.rows(fed.prose.blocks[0])
        XCTAssertEqual(heading.map(\.kind), [.heading(level: 1)])
        XCTAssertEqual(String(heading[0].text.characters), "Fed Page", "no # in what is drawn")
        let item = RunPageChangeModel.rows(fed.prose.blocks[6])
        XCTAssertEqual(item.count, 1)
        guard case .item = item[0].kind else { return XCTFail("a list item is drawn as one") }
        XCTAssertEqual(String(item[0].text.characters), "item two", "no - in the words: the marker is the article's")
        let section = RunPageChangeModel.rows(.init(op: .context, markdown: "## Empty section", level: 2))
        XCTAssertEqual(section.map(\.kind), [.heading(level: 2)],
                       "a heading alone is still drawn (the article drops an empty section)")
    }

    func testAnEditedParagraphMarksItsNewWordsAddedAndItsOldWordsRemovedInPlace() throws {
        let fed = try XCTUnwrap(changes()["fed"])
        let rows = RunPageChangeModel.rows(fed.prose.blocks[1])
        XCTAssertEqual(rows.count, 1)
        let text = rows[0].text
        XCTAssertEqual(String(text.characters), "Intro paragraph about the alpha-project and its shipping day, now on Fridays.")
        let added = text.runs.filter { $0[ProseMark.self] == .added }.map { String(text[$0.range].characters) }
        XCTAssertEqual(added.joined(), ", now on Fridays")
        XCTAssertTrue(text.runs.allSatisfy { $0[ProseMark.self] != .removed })
    }

    func testARemovedWordStaysWhereItStoodAndNeverRunsIntoTheNewOne() throws {
        let block = SleepPageChange.Block(op: .edited, markdown: "Ships now every Friday.", level: 0, segments: [
            .init(.equal, "Ships "), .init(.removed, "monthly"), .init(.added, "now every Friday"), .init(.equal, ".")])
        let text = try XCTUnwrap(RunPageChangeModel.rows(block)[0].text)
        XCTAssertEqual(String(text.characters), "Ships monthly now every Friday.")
        XCTAssertEqual(text.runs.filter { $0[ProseMark.self] == .removed }.map { String(text[$0.range].characters) }, ["monthly"])
    }

    func testAListItemsSyntaxIsStrippedBeforeTheSegmentsAreLaidOverIt() throws {
        let block = SleepPageChange.Block(op: .edited, markdown: "- Notes go out Friday", level: 0, segments: [
            .init(.equal, "- Notes go out "), .init(.removed, "Monday"), .init(.added, "Friday")])
        let rows = RunPageChangeModel.rows(block)
        XCTAssertEqual(String(rows[0].text.characters), "Notes go out Monday Friday")
        XCTAssertEqual(rows[0].text.runs.filter { $0[ProseMark.self] == .added }.count, 1)
    }

    func testARemovedBlockIsStruckThroughWhole() throws {
        let rows = RunPageChangeModel.rows(.init(op: .removed, markdown: "A paragraph that went."))
        XCTAssertTrue(rows[0].text.runs.allSatisfy { $0[ProseMark.self] == .removed })
        let kept = RunPageChangeModel.rows(.init(op: .removed, markdown: "A paragraph that went."), marked: false)
        XCTAssertTrue(kept[0].text.runs.allSatisfy { $0[ProseMark.self] == nil }, "a removed page is whole text, not a strike")
    }

    func testAHeadingIsSaidOnceInAQuietLineAndNotWhenItsOwnBlockIsThere() throws {
        let fed = try XCTUnwrap(changes()["fed"])
        let items = RunPageChangeModel.proseItems(fed.prose.blocks)
        XCTAssertEqual(items.count, fed.prose.blocks.count, "each block sits under a heading that is itself drawn")
        let loose = RunPageChangeModel.proseItems([
            .init(op: .edited, markdown: "One.", heading: "Where it stands"),
            .init(op: .added, markdown: "Two.", heading: "Where it stands"),
            .init(op: .added, markdown: "Three.", heading: "History")])
        XCTAssertEqual(loose.compactMap { if case .under(let h, _) = $0 { h } else { nil } }, ["Where it stands", "History"])
        XCTAssertEqual(RunPageChangeModel.plain("## A *bold* [[alpha-project]] title"), "A bold alpha-project title")
    }

    // MARK: Marks in the text engine

    @MainActor
    func testTheTextEngineWashesAddedWordsAndStrikesRemovedOnes() throws {
        let block = SleepPageChange.Block(op: .edited, markdown: "Ships now every Friday.", level: 0, segments: [
            .init(.equal, "Ships "), .init(.removed, "monthly"), .init(.added, "now every Friday"), .init(.equal, ".")])
        let rows = RunPageChangeModel.rows(block)
        let paragraphs = PageRun.paragraphs(rows, entityId: nil, citations: nil, lone: nil, related: [:], index: .empty)
        let built = PageText.build(paragraphs, context: PageAttachmentContext())
        let text = built.text
        var washed = ""
        var struck = ""
        text.enumerateAttributes(in: NSRange(location: 0, length: text.length)) { attrs, range, _ in
            let part = (text.string as NSString).substring(with: range)
            if attrs[.backgroundColor] != nil { washed += part }
            if attrs[.strikethroughStyle] != nil { struck += part }
        }
        XCTAssertEqual(struck, "monthly")
        XCTAssertTrue(washed.contains("now every Friday"))
        XCTAssertFalse(washed.contains("Ships"))
    }
}

/// A commit is immutable: an opened chip asks once, and a bank switch forgets the answer.
@MainActor
final class SleepPageChangeLoadingTests: XCTestCase {
    func testAnOpenedChipAsksOnceAndABankSwitchForgets() async throws {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        var asked: [String] = []
        let vm = SleepViewModel(store: store, putSchedule: { $0 }, fetchPageChange: { key, page in
            asked.append("\(key.path)|\(page)")
            return SleepPageChange(change: "updated", page: .init(id: page))
        })
        _ = try await vm.pageChange(.run("sleep_a"), page: "alpha-project")
        _ = try await vm.pageChange(.run("sleep_a"), page: "alpha-project")
        _ = try await vm.pageChange(.run("sleep_a"), page: "beta-tool")
        XCTAssertEqual(asked.count, 2, "the second ask of the same page is the session's")
        await vm.bankChanged()
        _ = try await vm.pageChange(.run("sleep_a"), page: "alpha-project")
        XCTAssertEqual(asked.count, 3, "another bank's pages are not this one's")
    }
}
