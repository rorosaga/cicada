import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Inbox v2 (owner 2026-10-26: "fix how dense the inbox looks … I don't really get the confirmation of links … as are
/// possible duplicates … When I open the drop-downs, it can be smoother"). Placeholders only — never a bank.
@MainActor
final class InboxV2Tests: XCTestCase {
    private func decode(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    private func item(_ id: String, kind: String = "conflict", page: String = "alpha-project",
                      name: String = "Alpha Project") throws -> InboxItem {
        try decode(#"{"id":"\#(id)","kind":"\#(kind)","requiredInput":"choice","title":"\#(id)","priority":0.5,"createdDate":"2026-09-01","entityId":"\#(page)","entityName":"\#(name)"}"#)
    }

    // MARK: The fold's motion (DR-60, DR-61, DR-65, DR-66)

    func testAKeyTogglesAFoldInOneFrameAndAClickEasesIt() {
        XCTAssertEqual(DisclosureMotion.trigger(for: .keyDown), .keyboard)
        XCTAssertEqual(DisclosureMotion.trigger(for: .keyUp), .keyboard)
        XCTAssertEqual(DisclosureMotion.trigger(for: .leftMouseUp), .pointer)
        XCTAssertEqual(DisclosureMotion.trigger(for: nil), .pointer)
        XCTAssertNil(DisclosureMotion.animation(.keyboard, opening: true, reduceMotion: false), "DR-60")
        XCTAssertNil(DisclosureMotion.animation(.keyboard, opening: false, reduceMotion: true), "DR-60")
        XCTAssertNotNil(DisclosureMotion.animation(.pointer, opening: true, reduceMotion: false))
        XCTAssertNotNil(DisclosureMotion.animation(.pointer, opening: true, reduceMotion: true),
                        "DR-66: Reduce Motion keeps a short fade, never nothing")
    }

    func testTheFoldsDurationsSitUnderTheUICeilingAndClosingIsQuicker() {
        XCTAssertLessThanOrEqual(CicadaMotion.disclosureOpenDuration, 0.3, "DR-61's 300 ms UI ceiling")
        XCTAssertLessThan(CicadaMotion.disclosureCloseDuration, CicadaMotion.disclosureOpenDuration, "DR-65")
    }

    func testTheRevealReportsItsShareOfTheContentsHeight() {
        XCTAssertEqual(DisclosureReveal(progress: 0.25).animatableData, 0.25)
        var reveal = DisclosureReveal(progress: 0)
        reveal.animatableData = 0.6
        XCTAssertEqual(reveal.progress, 0.6)
    }

    /// The fold's motion is chosen once, at the shared header: callers no longer wrap their toggle in `Instant.run`,
    /// which would pin every click to one frame.
    func testTheInboxFoldsLeaveTheirMotionToTheSharedHeader() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        let disclosure = try String(contentsOf: root.appendingPathComponent("Views/Common/Disclosure.swift"),
                                    encoding: .utf8)
        XCTAssertTrue(disclosure.contains("DisclosureMotion.toggle(opening: !isOpen, reduceMotion: reduceMotion, toggle)"))
        let list = try String(contentsOf: root.appendingPathComponent("Views/Inbox/InboxQuestionList.swift"),
                              encoding: .utf8)
        XCTAssertFalse(list.contains("Instant.run { toggle() }"))
        // Inbox freeze (2026-10-29): every group is open (ruling 48 (17)), so no group's body arrives as a fold; each
        // line is the lazy stack's own child (`InboxListDraw`), which a group's one reveal block would defeat.
        XCTAssertFalse(list.contains("disclosureReveal()"))
        // Ruling 48 (17), DR-81 — the settled groups and the link review's extra pages are no folds any more: open,
        // capped, "All N" to a sheet.
        for file in ["Views/Inbox/SettledChecksSection.swift", "Views/Inbox/InboxTopCards.swift"] {
            let source = try String(contentsOf: root.appendingPathComponent(file), encoding: .utf8)
            XCTAssertFalse(source.contains("DisclosureHeader("), file)
            XCTAssertTrue(source.contains("FullListSheet("), file)
        }
    }

    // MARK: The list in blocks

    func testTheGroupedListDrawsAHeaderAndItsBodyAsOneBlock() throws {
        let c1 = try item("c1"), c2 = try item("c2"), d1 = try item("d1", kind: "decay", page: "beta", name: "Beta")
        let lines: [InboxListLine] = [
            .kind(.conflict, count: 2, open: true, review: nil),
            .page(id: "x", name: "Alpha Project", count: 2),
            .entry(.item(c1), nested: true), .entry(.item(c2), nested: true),
            .kind(.decay, count: 1, open: false, review: nil),
        ]
        let blocks = InboxListBlock.blocks(lines)
        XCTAssertEqual(blocks.count, 2)
        XCTAssertEqual(blocks.map(\.kind), [.conflict, .decay])
        XCTAssertEqual(blocks.map(\.body.count), [3, 0], "a closed group is its header alone")
        XCTAssertEqual(blocks.map(\.isFirst), [true, false])
        XCTAssertEqual(Set(blocks.map(\.id)).count, 2)

        // A kind's tab has no header: one block, its kind read from its questions.
        let tab = InboxListBlock.blocks([.entry(.item(d1), nested: false)])
        XCTAssertEqual(tab.count, 1)
        XCTAssertNil(tab[0].header)
        XCTAssertEqual(tab[0].kind, .decay)
    }

    func testEveryKindHasAPluralTitleAndAPlainExplainer() {
        let kinds: [InboxKind] = [.decay, .conflict, .clarification, .mergeSuggestion, .divergence, .normalization,
                                  .removal, .followup, .pageEdit, .agentRequest, .unknown]
        for kind in kinds {
            XCTAssertFalse(kind.groupTitle.isEmpty)
            let words = Copy.Inbox.kindExplainer(kind)
            XCTAssertTrue(words.hasSuffix("."), "\(kind): one sentence or two, ended")
            for jargon in ["decay", "predicate", "fold", "clarification", "divergence", "entity", "claim"] {
                XCTAssertFalse(words.lowercased().contains(jargon), "\(kind) says \(jargon)")
            }
        }
        XCTAssertEqual(InboxKind.decay.label, "Fading")
        XCTAssertEqual(InboxKind.mergeSuggestion.groupTitle, "Possible duplicates")
    }

    // MARK: Possible duplicates side by side

    func testAPossibleDuplicateShowsBothSidesWithTheirPagesAndSaysWhatMergeDoes() throws {
        let merge = try decode(#"{"id":"m1","kind":"merge_suggestion","requiredInput":"merge","title":"Is Tool Example A (CLI) the same as Tool Example A?","entityId":"tool-example-a-cli","entityName":"Tool Example A (CLI)","mergeTargetHint":"tool-example-a","uncertaintyType":"Possible duplicate of Tool Example A","createdDate":"2026-09-01"}"#)
        let nodes = [FindFixtures.node("tool-example-a", "Tool Example A", type: .tool, summary: "A command-line tool.")]
        let pair = MergePair.of(merge, nodes: nodes)
        XCTAssertEqual(pair.mention.name, "Tool Example A (CLI)")
        XCTAssertFalse(pair.mention.hasPage, "a name below the promotion bar is only a name")
        XCTAssertEqual(pair.existing.id, "tool-example-a")
        XCTAssertEqual(pair.existing.name, "Tool Example A")
        XCTAssertEqual(pair.existing.type, .tool)
        XCTAssertEqual(pair.existing.summary, "A command-line tool.")
        XCTAssertTrue(pair.canMerge)
        XCTAssertEqual(pair.mergeWords, Copy.Inbox.Duplicate.mergeNames("Tool Example A (CLI)", "Tool Example A"))

        // Both sides have pages: Merge folds one into the other.
        let both = MergePair.of(merge, nodes: nodes + [FindFixtures.node("tool-example-a-cli", "Tool Example A (CLI)",
                                                                         type: .tool)])
        XCTAssertTrue(both.mention.hasPage)
        XCTAssertEqual(both.mergeWords, Copy.Inbox.Duplicate.mergeFolds("Tool Example A (CLI)", "Tool Example A"))
        XCTAssertTrue(both.mergeWords.contains("another name"))
    }

    /// Review of #481: after the person types another page under "Something else", the side by side and Merge's
    /// sentence show the page that will be sent, never Sleep's suggestion.
    func testTheExistingSideFollowsThePageThePersonTyped() throws {
        let merge = try decode(#"{"id":"m3","kind":"merge_suggestion","requiredInput":"merge","title":"Is Bob E. the same as Bob Example?","entityId":"bob-e","entityName":"Bob E.","mergeTargetHint":"bob-example","uncertaintyType":"Possible duplicate of Bob Example","createdDate":"2026-09-01"}"#)
        let nodes = [FindFixtures.node("bob-example", "Bob Example", type: .person, summary: "A friend."),
                     FindFixtures.node("bob-other", "Bob Other", type: .person, summary: "A colleague.")]
        let seeded = MergePair.of(merge, nodes: nodes, target: "bob-example")
        XCTAssertFalse(seeded.existingIsTyped, "the field still holds Sleep's page")
        XCTAssertEqual(seeded.existing.name, "Bob Example")

        let byName = MergePair.of(merge, nodes: nodes, target: "bob other")
        XCTAssertTrue(byName.existingIsTyped)
        XCTAssertEqual(byName.existing.id, "bob-other")
        XCTAssertEqual(byName.existing.summary, "A colleague.")
        XCTAssertTrue(byName.mergeWords.contains("Bob Other"))
        XCTAssertFalse(byName.mergeWords.contains("Bob Example"))

        let byId = MergePair.of(merge, nodes: nodes, target: "bob-other")
        XCTAssertEqual(byId.existing.name, "Bob Other")

        let unknown = MergePair.of(merge, nodes: nodes, target: "Nobody Example")
        XCTAssertTrue(unknown.existingIsTyped)
        XCTAssertFalse(unknown.existing.hasPage, "a name with no page is said as such")
        XCTAssertEqual(unknown.existing.name, "Nobody Example")
    }

    func testAPossibleDuplicateWithNoPageNamedCannotMergeAtOnce() throws {
        let merge = try decode(#"{"id":"m2","kind":"merge_suggestion","requiredInput":"merge","title":"Is Bea the same as Bea Example?","entityId":"bea","entityName":"Bea","uncertaintyType":"Possible duplicate of Bea Example","createdDate":"2026-09-01"}"#)
        let pair = MergePair.of(merge, nodes: [])
        XCTAssertFalse(pair.canMerge)
        XCTAssertEqual(pair.existing.name, "Bea Example", "the candidate's name as Sleep wrote it")
        XCTAssertFalse(pair.existing.hasPage)
    }

    // MARK: Confirm N links, in words

    private func row(_ id: String, page: String = "bob-example", pageName: String = "Bob Example",
                     pageType: String = "person", ref: String = "https://github.com/bob-example",
                     kind: String = "github", evidence: WhereToCheckRow.Evidence? = nil) -> WhereToCheckRow {
        WhereToCheckRow(id: id, page: page, pageName: pageName, pageType: pageType, ref: ref, linkKind: kind,
                        label: "bob-example", addedBy: "cicada", evidence: evidence)
    }

    func testALinkSaysWhatItIsWhyItIsThereAndWhatConfirmingDoes() {
        let profile = row("r1", evidence: .init(episode: "ep", start: 0, end: 4, kind: "user"))
        XCTAssertEqual(WhereToCheckWords.kindName("github", pageType: "person"), "GitHub profile")
        XCTAssertEqual(WhereToCheckWords.why(profile), Copy.WhereToCheck.fromYou)
        XCTAssertEqual(WhereToCheckWords.effect(profile, kind: "github"),
                       Copy.WhereToCheck.effectPersonProfile("Bob Example", "GitHub profile"))
        XCTAssertTrue(WhereToCheckWords.effect(profile, kind: "github").contains("picture"))
        XCTAssertEqual(WhereToCheckWords.declineLabel(profile), Copy.WhereToCheck.notTheirs)

        let site = row("r2", page: "globex-example", pageName: "Globex Example", pageType: "company",
                       ref: "https://www.example.com/", kind: "website", evidence: .init(page: true))
        XCTAssertEqual(WhereToCheckWords.effect(site, kind: "website"), Copy.WhereToCheck.effectWebsite("Globex Example"))
        XCTAssertTrue(WhereToCheckWords.effect(site, kind: "website").contains("logo"))
        XCTAssertEqual(WhereToCheckWords.why(site), Copy.WhereToCheck.fromPage)
        XCTAssertEqual(WhereToCheckWords.declineLabel(site), Copy.WhereToCheck.notThis)
        XCTAssertEqual(WhereToCheckWords.shortRef(site.ref), "example.com")

        let repo = row("r3", page: "alpha-project", pageName: "Alpha Project", pageType: "project",
                       ref: "https://github.com/example/alpha", kind: "repo")
        XCTAssertFalse(WhereToCheckWords.effect(repo, kind: "repo").contains("picture"),
                       "a picture comes only from a person's own account (G146)")
        XCTAssertEqual(WhereToCheckWords.why(repo), Copy.WhereToCheck.fromAgentNoLine)
        XCTAssertEqual(WhereToCheckWords.shortRef(repo.ref), "github.com/example/alpha")
    }

    func testTheReviewNamesEachPageOnceWhereItsFirstLinkIs() {
        let rows = [row("a"), row("b", page: "alpha-project", pageName: "Alpha Project", pageType: "project"),
                    row("c", ref: "https://x.com/bob_example", kind: "x")]
        let pages = WhereToCheckWords.byPage(rows)
        XCTAssertEqual(pages.map(\.page), ["bob-example", "alpha-project"])
        XCTAssertEqual(pages.map { $0.rows.map(\.id) }, [["a", "c"], ["b"]])
    }
}
