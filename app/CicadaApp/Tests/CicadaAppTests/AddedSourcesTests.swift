import XCTest
@testable import CicadaApp

/// G61 (owner 2026-10-26) — the "Reading in your browser" area's quick add: a link with a page is that page's source,
/// the person's own; with no page it is saved as a link; the list shows who added each and removes as the person.
/// Synthetic values only (alpha-project, bob-example, example.com); no network.
@MainActor
final class AddedSourcesTests: XCTestCase {
    private func row(_ entity: String, _ ref: String, who: String = "you", agent: String? = nil,
                     addedBy: String = "user", predicate: String? = nil, at: String = "2026-10-20") -> AddedSourceRow {
        AddedSourceRow(entityId: entity, entityName: entity.replacingOccurrences(of: "-", with: " ").capitalized,
                       who: who, agent: agent, addedBy: addedBy, ref: ref, kind: "url", predicate: predicate,
                       addedAt: at)
    }

    func testOnlyAWebLinkIsAccepted() {
        XCTAssertEqual(AddedSourcesLogic.link("https://example.com/team"), "https://example.com/team")
        XCTAssertEqual(AddedSourcesLogic.link("  example.com/changelog "), "https://example.com/changelog")
        XCTAssertNil(AddedSourcesLogic.link("/Users/someone/notes.md"))
        XCTAssertNil(AddedSourcesLogic.link("ask me about it"))
        XCTAssertNil(AddedSourcesLogic.link("ftp://example.com/x"))
        XCTAssertNil(AddedSourcesLogic.link("localhost"))
        XCTAssertNil(AddedSourcesLogic.link(""))
    }

    func testThePageSearchFindsLivePagesAndNeverGuesses() {
        let nodes = [GraphNode(id: "alpha-project", name: "Alpha Project", type: .project),
                     GraphNode(id: "project-alpha-notes", name: "Notes on alpha", type: .concept),
                     GraphNode(id: "bob-example", name: "Bob Example", type: .person)]
        XCTAssertEqual(AddedSourcesLogic.pages(matching: "alpha", in: nodes).map(\.id),
                       ["alpha-project", "project-alpha-notes"], "a name starting with the words comes first")
        XCTAssertEqual(AddedSourcesLogic.pages(matching: "", in: nodes).count, 0, "no words, no page")
        XCTAssertEqual(AddedSourcesLogic.pages(matching: "zzz", in: nodes).count, 0)
    }

    func testEachRowSaysWhoAddedItAndWhen() {
        let today = ISODay("2026-10-26")!
        let mine = row("alpha-project", "https://example.com/alpha", at: "2026-10-26")
        let theirs = row("bob-example", "https://example.com/team", who: "agent", agent: "Claude Code",
                         addedBy: "claude-code", predicate: "works-at", at: "2026-10-25")
        XCTAssertTrue(AddedSourcesLogic.credit(mine, today: today).hasPrefix("You"))
        let credit = AddedSourcesLogic.credit(theirs, today: today)
        XCTAssertTrue(credit.hasPrefix("Claude Code"))
        XCTAssertTrue(credit.contains("works at"))
        XCTAssertEqual(AddedSourcesLogic.shown("https://www.example.com/team/"), "example.com/team")
    }

    // MARK: The model

    private final class Calls {
        var added: [(String, String)] = []
        var saved: [String] = []
        var removed: [AddedSourceRow] = []
        var fetches = 0
        var failRemove = false
    }

    private func model(_ calls: Calls, rows: [AddedSourceRow]) -> AddedSourcesModel {
        AddedSourcesModel(deps: .init(
            fetch: { _ in
                calls.fetches += 1
                return Conditional(value: AddedSourcesResponse(items: rows, total: rows.count), etag: "e1",
                                   notModified: false)
            },
            addSource: { calls.added.append(($0, $1)) },
            saveLink: { calls.saved.append($0) },
            remove: { row in
                if calls.failRemove { throw APIError.httpError(400, #"{"detail":"Nothing under that key"}"#) }
                calls.removed.append(row)
            }))
    }

    func testALinkWithAPageIsThatPagesSourceAndWithoutOneIsSaved() async {
        let calls = Calls()
        let m = model(calls, rows: [])
        let page = GraphNode(id: "alpha-project", name: "Alpha Project", type: .project)
        let ok = await m.add("example.com/alpha/changelog", page: page)
        XCTAssertTrue(ok)
        XCTAssertEqual(calls.added.map(\.0), ["alpha-project"])
        XCTAssertEqual(calls.added.map(\.1), ["https://example.com/alpha/changelog"])
        XCTAssertEqual(m.note, Copy.QuickSources.added("Alpha Project"))
        XCTAssertEqual(calls.fetches, 1, "the list is read again after the write")

        _ = await m.add("https://example.com/post", page: nil)
        XCTAssertEqual(calls.saved, ["https://example.com/post"])
        XCTAssertEqual(m.note, Copy.QuickSources.savedAsLink)

        let refused = await m.add("not a link at all", page: page)
        XCTAssertFalse(refused)
        XCTAssertEqual(m.note, Copy.QuickSources.notALink)
        XCTAssertEqual(calls.added.count, 1, "nothing sent for words")
    }

    func testARemovalGoesThroughThePagesRouteAndRollsBackOnFailure() async {
        let calls = Calls()
        let theirs = row("bob-example", "https://example.com/team", who: "agent", agent: "Claude Code",
                         addedBy: "claude-code", predicate: "works-at")
        let m = model(calls, rows: [theirs])
        await m.load()
        XCTAssertEqual(m.rows, [theirs])
        XCTAssertEqual(theirs.source.ref, "https://example.com/team")
        XCTAssertEqual(SourceChange.remove.body(for: theirs.source)["predicate"] as? String, "works-at")
        XCTAssertEqual(SourceChange.remove.body(for: theirs.source)["action"] as? String, "remove")

        calls.failRemove = true
        await m.remove(theirs)
        XCTAssertEqual(m.rows, [theirs], "a failed removal puts the row back")
        XCTAssertEqual(m.note, "Nothing under that key", "the server's sentence")

        calls.failRemove = false
        await m.remove(theirs)
        XCTAssertEqual(calls.removed.map(\.id), [theirs.id])
        XCTAssertEqual(m.note, Copy.QuickSources.removed)
    }

    func testANotModifiedAnswerKeepsTheList() async {
        var answers: [Conditional<AddedSourcesResponse>] = [
            Conditional(value: AddedSourcesResponse(items: [row("alpha-project", "https://example.com/a")], total: 1),
                        etag: "e1", notModified: false),
            Conditional(value: nil, etag: "e1", notModified: true),
        ]
        var sent: [String?] = []
        let m = AddedSourcesModel(deps: .init(fetch: { etag in sent.append(etag); return answers.removeFirst() },
                                              addSource: { _, _ in }, saveLink: { _ in }, remove: { _ in }))
        await m.load()
        await m.load()
        XCTAssertEqual(m.rows.count, 1, "never blank on a 304")
        XCTAssertEqual(sent, [nil, "e1"])
    }
}
