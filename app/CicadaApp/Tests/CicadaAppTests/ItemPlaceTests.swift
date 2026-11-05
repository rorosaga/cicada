import XCTest
@testable import CicadaApp

/// G161 (ROR-111) — opening a source's item where it lives. No `osascript` runs and nothing opens: every call goes
/// through fakes.
@MainActor
final class ItemPlaceTests: XCTestCase {
    private let noteId = "x-coredata://0000AAAA-1111-2222-3333-444455556666/ICNote/p7"

    private func output(_ status: Int32, stderr: String = "", timedOut: Bool = false) -> AppleNotesReader.Output {
        AppleNotesReader.Output(status: status, stdout: "", stderr: stderr, timedOut: timedOut)
    }

    func testOnlyAPlainWebLinkOpens() {
        for good in ["https://example.com/a?b=c#d", "http://example.com", "HTTPS://Example.com/a"] {
            XCTAssertNotNil(ItemPlaceOpen.webURL(good), good)
        }
        for bad in ["file:///etc/hosts", "cicada://open", "x-apple.systempreferences:foo", "javascript:alert(1)",
                    "ftp://example.com/a", "mailto:someone@example.com", "https:no-host", "https://", "//example.com/a",
                    "example.com/a", "", " https://example.com/", "https://exa mple.com/", "https://example.com/\n",
                    "https://user:pw@example.com/", "https://github.com@example.com/",
                    "https://example.com\\@github.com/"] {
            XCTAssertNil(ItemPlaceOpen.webURL(bad), bad)
        }
    }

    func testTheKindDecidesTheTargetAndTheHostDecidesGitHub() throws {
        let url = try XCTUnwrap(URL(string: "https://github.com/owner/repo"))
        XCTAssertEqual(ItemPlaceOpen.target(ItemPlace(kind: "github", url: url.absoluteString)), .web(url))
        XCTAssertNil(ItemPlaceOpen.target(ItemPlace(kind: "github", url: "https://github.com.example.net/o/r")))
        XCTAssertNil(ItemPlaceOpen.target(ItemPlace(kind: "web", url: "file:///etc/hosts")))
        XCTAssertNil(ItemPlaceOpen.target(ItemPlace(kind: "notes", url: url.absoluteString)), "a note needs its id")
        XCTAssertEqual(ItemPlaceOpen.target(ItemPlace(kind: "notes", noteId: noteId)), .note(noteId))
        XCTAssertNil(ItemPlaceOpen.target(ItemPlace(kind: "notes", noteId: "x-coredata://a\" & (do shell script \"x")))
        XCTAssertNil(ItemPlaceOpen.target(ItemPlace(kind: "something-new", url: url.absoluteString)))
    }

    func testAWebPlaceOpensInTheBrowserAndNeverAsksNotes() async throws {
        var opened: [URL] = []
        let deps = ItemPlaceOpen.Deps(openURL: { opened.append($0) }, showNote: { _, _ in
            XCTFail("a web place never reaches Notes")
            return AppleNotesReader.Output(status: 0, stdout: "", stderr: "", timedOut: false)
        })
        let problem = await ItemPlaceOpen.open(resolve: { ItemPlace(kind: "web", url: "https://example.com/a") }, deps: deps)
        XCTAssertNil(problem)
        XCTAssertEqual(opened, [try XCTUnwrap(URL(string: "https://example.com/a"))])
    }

    func testAStoredFileLinkOpensNothingAndSaysSo() async {
        var opened = 0
        let deps = ItemPlaceOpen.Deps(openURL: { _ in opened += 1 }, showNote: { _, _ in
            AppleNotesReader.Output(status: 0, stdout: "", stderr: "", timedOut: false)
        })
        let problem = await ItemPlaceOpen.open(resolve: { ItemPlace(kind: "web", url: "file:///etc/hosts") }, deps: deps)
        XCTAssertEqual(problem, Copy.Place.notFound)
        XCTAssertEqual(opened, 0)
    }

    func testABackendThatCannotAnswerSaysSo() async {
        let problem = await ItemPlaceOpen.open(resolve: { throw APIError.serverUnreachable }, deps: ItemPlaceOpen.Deps(
            openURL: { _ in XCTFail("nothing opens") },
            showNote: { _, _ in AppleNotesReader.Output(status: 0, stdout: "", stderr: "", timedOut: false) }))
        XCTAssertEqual(problem, Copy.Place.notFound)
    }

    func testANoteIsShownByItsIdAlone() async {
        let shown = ShownNotes()
        let deps = ItemPlaceOpen.Deps(openURL: { _ in XCTFail("a note never reaches the browser") }, showNote: { id, _ in
            await shown.add(id)
            return AppleNotesReader.Output(status: 0, stdout: "", stderr: "", timedOut: false)
        })
        let id = noteId
        let problem = await ItemPlaceOpen.open(resolve: { ItemPlace(kind: "notes", noteId: id) }, deps: deps)
        XCTAssertNil(problem)
        let ids = await shown.ids
        XCTAssertEqual(ids, [noteId])
    }

    func testTheScriptReadsNothingAndTheIdIsAnArgument() {
        let script = AppleNotesReader.showScript.lowercased()
        for read in ["body", "plaintext", "name of", "password", "get ", "every note"] {
            XCTAssertFalse(script.contains(read), read)
        }
        XCTAssertFalse(AppleNotesReader.showScript.contains(noteId))
        XCTAssertEqual(AppleNotesReader.showArguments(noteId), ["-e", AppleNotesReader.showScript, noteId])
    }

    func testWhatAShowThatFailedSays() {
        XCTAssertNil(AppleNotesReader.showProblem(output(0)))
        XCTAssertEqual(AppleNotesReader.showProblem(output(1, stderr: "Not authorized (-1743)")),
                       AppleNotesReader.ReadError.notAllowed.errorDescription, "the same words as a read")
        XCTAssertEqual(AppleNotesReader.showProblem(output(1, stderr: "Can't get note id (-1728)")), Copy.Place.noteGone)
        XCTAssertEqual(AppleNotesReader.showProblem(output(1, stderr: "other")), Copy.Place.noteFailed)
        XCTAssertEqual(AppleNotesReader.showProblem(output(0, timedOut: true)),
                       AppleNotesReader.ReadError.timedOut.errorDescription)
    }

    func testARowSaysItsKindAndAnUnknownWordIsNoControl() throws {
        func row(_ extra: String) throws -> ChannelItem {
            try JSONDecoder().decode(ChannelItem.self, from: Data("""
            {"kind":"episode","id":"ep","title":"T"\(extra)}
            """.utf8))
        }
        XCTAssertEqual(try row(#","place":"notes""#).placeKind, .notes)
        XCTAssertEqual(try row(#","place":"github""#).placeKind, .github)
        XCTAssertEqual(try row(#","place":"web""#).placeKind, .web)
        XCTAssertNil(try row(#","place":"new""#).placeKind)
        XCTAssertNil(try row("").placeKind, "an older backend, or no known place")
        XCTAssertNil(try row(#","place":7"#).placeKind, "a malformed field drops the field, never the row")
        let again = try JSONDecoder().decode(ChannelItem.self, from: JSONEncoder().encode(row(#","place":"web""#)))
        XCTAssertEqual(again.placeKind, .web)
    }

    func testTheCopyNamesTheSource() {
        XCTAssertEqual(ItemPlaceKind.notes.help, "Open in Notes")
        XCTAssertEqual(ItemPlaceKind.github.help, "Open on GitHub")
        XCTAssertEqual(ItemPlaceControl.reserve(nil), 0)
        XCTAssertGreaterThan(ItemPlaceControl.reserve(.web), 0)
    }

    func testThePathEncodesTheChannelAndTheItem() {
        XCTAssertEqual(APIClient.itemPlacePath(channel: "folder:a/b", item: "ep_1?x"),
                       "/sources/channels/folder:a%2Fb/items/ep_1%3Fx/place")
    }
}

private actor ShownNotes {
    private(set) var ids: [String] = []
    func add(_ id: String) { ids.append(id) }
}
