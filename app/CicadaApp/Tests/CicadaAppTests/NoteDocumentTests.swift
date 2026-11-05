import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// ROR-15: an Apple Note as Notes draws it. Every body here is invented; the shapes are what Notes' `body` writes.
final class NoteDocumentTests: XCTestCase {
    private static let id = "x-coredata://AAAA-BBBB/ICNote/p1"

    /// What `notes_sync._episode_body` stores above a note's plain text.
    private func stored(_ plain: String, name: String = "Trip plan") -> String {
        "# \(name)\n\n**Folder:** Notes\n**Modified:** 2026-01-02\n\n\(plain)"
    }

    private func scalarRange(of quote: String, in text: String, last: Bool = false) throws -> Range<Int> {
        let found = try XCTUnwrap(text.range(of: quote, options: last ? .backwards : []))
        let lo = text.unicodeScalars.distance(from: text.unicodeScalars.startIndex, to: found.lowerBound)
        return lo..<(lo + quote.unicodeScalars.count)
    }

    private static let richHTML = """
    <div><h1>Trip plan</h1></div>
    <div><br></div>
    <div><h2>Packing</h2></div>
    <div>Bring <b>boots</b>, <i>maps</i>, <u>rope</u> and <strike>skis</strike>; see <a href="https://example.com/guide">the guide</a>.</div>
    <ul><li>Tent</li><li>Stove<ul><li>Fuel</li></ul></li></ul>
    <ul class="Apple-dash-list"><li>Dash item</li></ul>
    <ol><li>Book cabin</li><li>Pay deposit</li></ol>
    <div><h3>Costs</h3></div>
    <object><table><tbody><tr><td><div>Cabin</div></td><td><div>120</div></td></tr><tr><td><div>Food</div></td><td><div>80</div></td></tr></tbody></table></object>
    <div><tt>ssh example</tt></div>
    """

    private static let richPlain = """
    Trip plan

    Packing
    Bring boots, maps, rope and skis; see the guide.
    Tent
    Stove
    Fuel
    Dash item
    Book cabin
    Pay deposit
    Costs
    Cabin\t120
    Food\t80
    ssh example
    """

    // MARK: The script

    func testTheScriptAsksInsideNotesForAnUnlockedNotesBodyOnly() {
        let script = AppleNotesReader.formattedScript
        XCTAssertTrue(script.contains("body of (every note whose password protected is false and id is wanted)"))
        // One way to a body, and it is the filtered one.
        XCTAssertEqual(script.components(separatedBy: "body of").count, 2)
        XCTAssertFalse(script.contains("note id"), "a by-id reference would reach a locked note")
        XCTAssertFalse(script.contains("plaintext"))
        XCTAssertFalse(script.contains("activate"))
        XCTAssertTrue(script.contains("is not running then return \"\""), "a closed Notes is not launched")
    }

    func testTheIdIsAnArgumentNeverPartOfTheScript() {
        XCTAssertEqual(AppleNotesReader.formattedArguments(Self.id), ["-e", AppleNotesReader.formattedScript, Self.id])
        XCTAssertFalse(AppleNotesReader.formattedScript.contains("x-coredata"))
    }

    // MARK: Never an error, never a prompt

    func testNoAutomationGrantMeansNoScriptAtAll() async {
        let plain = stored("Trip plan")
        let result = await AppleNotesReader.formatted(noteId: Self.id, stored: plain, granted: { false }, run: { _, _ in
            XCTFail("nothing is sent to Notes without the grant")
            return .init(status: 0, stdout: "<div>Trip plan</div>", stderr: "", timedOut: false)
        })
        XCTAssertNil(result)
    }

    func testEveryFailureIsNilAndPlainText() async {
        let plain = stored("Trip plan")
        let outcomes: [AppleNotesReader.Output] = [
            .init(status: 1, stdout: "", stderr: "execution error (-1743)", timedOut: false),
            .init(status: 1, stdout: "", stderr: "(-1728)", timedOut: false),
            .init(status: 0, stdout: "", stderr: "", timedOut: true),
            .init(status: 0, stdout: "", stderr: "", timedOut: false), // closed, gone or locked: the script says nothing
            .init(status: 0, stdout: "<div>Other words</div>", stderr: "", timedOut: false),
        ]
        for outcome in outcomes {
            let result = await AppleNotesReader.formatted(noteId: Self.id, stored: plain, granted: { true },
                                                          run: { _, _ in outcome })
            XCTAssertNil(result)
        }
    }

    func testAnOddIdNeverReachesTheScript() async {
        let result = await AppleNotesReader.formatted(noteId: "\" & do shell script \"x", stored: "x", granted: { true },
                                                      run: { _, _ in
            XCTFail("an odd id is refused first")
            return .init(status: 0, stdout: "", stderr: "", timedOut: false)
        })
        XCTAssertNil(result)
    }

    func testAMatchingBodyArrives() async {
        let result = await AppleNotesReader.formatted(noteId: Self.id, stored: stored("Trip plan\nBoots"), granted: { true },
                                                      run: { _, _ in
            .init(status: 0, stdout: "<div>Trip plan</div><div>Boots</div>\n", stderr: "", timedOut: false)
        })
        XCTAssertEqual(result?.blocks.map(\.text), ["Trip plan", "Boots"])
    }

    // MARK: What comes through

    func testHeadingsListsStylesLinksAndTablesComeThrough() throws {
        let doc = try XCTUnwrap(NoteDocument.build(html: Self.richHTML, stored: stored(Self.richPlain)))
        let kinds = doc.blocks.filter { $0.kind != .blank }.map(\.kind)
        XCTAssertEqual(kinds.first, .title)
        XCTAssertTrue(kinds.contains(.heading(2)))
        XCTAssertTrue(kinds.contains(.heading(3)))
        XCTAssertTrue(kinds.contains(.item(.bullet, depth: 0)))
        XCTAssertTrue(kinds.contains(.item(.bullet, depth: 1)), "a nested list keeps its depth")
        XCTAssertTrue(kinds.contains(.item(.dash, depth: 0)))
        XCTAssertTrue(kinds.contains(.item(.number(1), depth: 0)))
        XCTAssertTrue(kinds.contains(.item(.number(2), depth: 0)))

        let line = try XCTUnwrap(doc.blocks.first { $0.text.hasPrefix("Bring") })
        func style(of word: String) throws -> NoteDocument.Style {
            let run = try XCTUnwrap(line.runs.first { String(String.UnicodeScalarView(line.scalars[$0.range])) == word })
            return run.style
        }
        XCTAssertEqual(try style(of: "boots"), .bold)
        XCTAssertEqual(try style(of: "maps"), .italic)
        XCTAssertEqual(try style(of: "rope"), .underline)
        XCTAssertEqual(try style(of: "skis"), .strike)
        XCTAssertEqual(line.runs.compactMap(\.link).map(\.absoluteString), ["https://example.com/guide"])

        let table = try XCTUnwrap(doc.blocks.first { if case .table = $0.kind { true } else { false } })
        guard case let .table(grid) = table.kind else { return XCTFail("a table") }
        XCTAssertEqual(grid.map(\.count), [2, 2])
    }

    func testChecklistTicksWhereTheHTMLCarriesThem() throws {
        let html = """
        <div>List</div>
        <ul class="Apple-checklist"><li class="checked">Done one</li><li>Open one</li></ul>
        <ul><li><input type="checkbox" checked>Input done</li><li><input type="checkbox">Input open</li></ul>
        """
        let doc = try XCTUnwrap(NoteDocument.build(html: html, stored: stored("List\nDone one\nOpen one\nInput done\nInput open")))
        XCTAssertEqual(doc.blocks.dropFirst().map(\.kind), [
            .item(.check(done: true), depth: 0), .item(.check(done: false), depth: 0),
            .item(.check(done: true), depth: 0), .item(.check(done: false), depth: 0),
        ])
    }

    // MARK: The one standard

    func testASpanWashesTheSameWordsInTheFormattedPage() throws {
        let text = stored(Self.richPlain)
        let doc = try XCTUnwrap(NoteDocument.build(html: Self.richHTML, stored: text))
        let span = try scalarRange(of: "boots, maps", in: text)
        let line = try XCTUnwrap(doc.blocks.first { $0.text.hasPrefix("Bring") })
        let ranges = doc.ranges(of: span, in: line)
        XCTAssertEqual(ranges.map { String(String.UnicodeScalarView(line.scalars[$0])) }, ["boots, maps"])
        XCTAssertTrue(doc.draws(span))
    }

    func testASpanOverTwoLinesWashesEach() throws {
        let text = stored(Self.richPlain)
        let doc = try XCTUnwrap(NoteDocument.build(html: Self.richHTML, stored: text))
        let span = try scalarRange(of: "Tent\nStove", in: text)
        let hit = doc.blocks.filter { !doc.ranges(of: span, in: $0).isEmpty }.map(\.text)
        XCTAssertEqual(hit, ["Tent", "Stove"])
    }

    func testASpanInATableCellWashesThatCell() throws {
        let text = stored(Self.richPlain)
        let doc = try XCTUnwrap(NoteDocument.build(html: Self.richHTML, stored: text))
        let span = try scalarRange(of: "Food", in: text)
        let table = try XCTUnwrap(doc.blocks.first { if case .table = $0.kind { true } else { false } })
        let ranges = doc.ranges(of: span, in: table)
        XCTAssertEqual(ranges.map { String(String.UnicodeScalarView(table.scalars[$0])) }, ["Food"])
    }

    func testASpanOnTheStoredTitleLineLandsOnTheNotesFirstLine() throws {
        let text = stored("Trip plan\nBoots")
        let doc = try XCTUnwrap(NoteDocument.build(html: "<div>Trip plan</div><div>Boots</div>", stored: text))
        let span = try scalarRange(of: "Trip plan", in: text) // the first hit: the `# name` line
        XCTAssertLessThan(span.lowerBound, 5)
        XCTAssertEqual(doc.ranges(of: span, in: doc.blocks[0]), [0..<9])
    }

    func testASpanOnAFilingLineIsNotDrawnSoThePlainPageStays() throws {
        let text = stored("Trip plan")
        let doc = try XCTUnwrap(NoteDocument.build(html: "<div>Trip plan</div>", stored: text))
        XCTAssertFalse(doc.draws(try scalarRange(of: "Folder", in: text)))
    }

    @MainActor func testTheLayoutFallsBackToPlainWhenASpanCannotBeDrawn() throws {
        let text = stored("Trip plan\nBoots")
        let doc = EpisodeText(episode: "ep_2026-01-02_001", text: text, title: "Trip plan",
                              turns: [EpisodeTurn(index: 0, start: 0, contentStart: 0, end: text.unicodeScalars.count, role: "user", marker: nil, speaker: nil, ts: nil)])
        let note = try XCTUnwrap(NoteDocument.build(html: "<div>Trip plan</div><div>Boots</div>", stored: text))
        let scalars = ScalarText(text)
        let state = SourceSpansState()
        let boots = try scalarRange(of: "Boots", in: text)
        let drawn = state.layout(doc, scalars: scalars, presentation: .spans(), others: [boots], note: note)
        XCTAssertEqual(drawn.noteRows?.map(\.block.text), ["Boots"], "the header already says the title")
        XCTAssertEqual(drawn.noteRows?.first?.reader.washes.map(\.range), [0..<5])
        let folder = try scalarRange(of: "Folder", in: text)
        XCTAssertNil(state.layout(doc, scalars: scalars, presentation: .spans(), others: [folder], note: note).noteRows)
    }

    func testTheMarksAreTheOneStandards() throws {
        let doc = try XCTUnwrap(NoteDocument.build(html: "<div>Say <b>hello there</b></div>", stored: stored("Say hello there")))
        let block = doc.blocks[0]
        let text = NoteText.attributed(block, range: 0..<block.scalars.count,
                                       washes: [ReaderWash(range: 4..<9, style: .focus)], reveal: 1)
        let runs = Array(text.runs)
        XCTAssertEqual(String(text.characters), "Say hello there")
        let cited = try XCTUnwrap(runs.first { String(text[$0.range].characters) == "hello" })
        XCTAssertEqual(cited.backgroundColor, CicadaTheme.wash.opacity(1))
        XCTAssertEqual(cited.inlinePresentationIntent, .stronglyEmphasized, "the note's bold stays under the wash")
    }

    // MARK: Matching: exact, whitespace, case, never fuzzy

    func testWhitespaceAndCaseMatchButNothingLooser() {
        XCTAssertNotNil(NoteDocument.build(html: "<div>Pack  the\n boots</div>", stored: stored("Pack the   boots")))
        XCTAssertNotNil(NoteDocument.build(html: "<div>pack THE boots</div>", stored: stored("Pack the boots")))
        XCTAssertNil(NoteDocument.build(html: "<div>Pack the boot</div>", stored: stored("Pack the boots")), "one letter off")
        XCTAssertNil(NoteDocument.build(html: "<div>Pack the boots</div>", stored: stored("Pack the boot")), "one letter short")
        XCTAssertNil(NoteDocument.build(html: "<div>the boots</div>", stored: stored("Pack the boots")), "a part is no match")
        XCTAssertNil(NoteDocument.build(html: "<div>Packtheboots</div>", stored: stored("Pack the boots")))
    }

    func testAStoredTruncatedNoteStaysPlain() {
        XCTAssertNil(NoteDocument.build(html: "<div>Pack the boots and more</div>", stored: stored("Pack the\n\n… [truncated]")))
    }

    func testAStoredListMarkerOnlyAtAListItem() {
        XCTAssertNotNil(NoteDocument.build(html: "<ul><li>Tent</li></ul>", stored: stored("• Tent")))
        XCTAssertNotNil(NoteDocument.build(html: "<ol><li>Tent</li></ol>", stored: stored("1. Tent")))
        XCTAssertNotNil(NoteDocument.build(html: "<ul><li>- Tent</li></ul>", stored: stored("- Tent")), "a typed dash is a word")
        XCTAssertNil(NoteDocument.build(html: "<div>Tent</div>", stored: stored("• Tent")), "no marker on a paragraph")
    }

    func testAnAttachmentsObjectCharacterIsNoWord() throws {
        XCTAssertNotNil(NoteDocument.build(html: "<div>One</div><div><img src=\"data:image/png;base64,AAAA\"></div><div>Two</div>",
                                           stored: stored("One\n\u{FFFC}\nTwo")))
        let table = "<div>One</div><object><table><tr><td>A</td></tr></table></object>"
        let doc = try XCTUnwrap(NoteDocument.build(html: table, stored: stored("One\n\u{FFFC}")))
        XCTAssertEqual(doc.blocks.last?.map, [-1], "drawn, tied to no stored words")
    }

    func testEntitiesAndHugeInlineDataAreRead() throws {
        let data = String(repeating: "A", count: 200_000)
        let html = "<div>Fish &amp; chips&nbsp;&#x2014; now</div><div><img src=\"data:image/png;base64,\(data)\"></div>"
        let doc = try XCTUnwrap(NoteDocument.build(html: html, stored: stored("Fish & chips\u{00A0}— now")))
        XCTAssertEqual(doc.blocks.first?.text, "Fish & chips\u{00A0}— now")
    }

    // MARK: A hostile body

    func testAHostileBodyGivesOnlyItsWords() throws {
        let html = """
        <html><head><title>head words</title><style>div { background: url(https://evil.example/x.png) }</style></head><body>
        <script>alert("<div>script words</div>")</script><SCRIPT src="https://evil.example/x.js"></SCRIPT>
        <iframe src="https://evil.example/"><div>frame words</div></iframe>
        <svg onload="x()"><text>svg words</text></svg>
        <!-- <div>comment words</div> -->
        <div onclick="x()">Hello <img src="https://evil.example/pixel.png" onerror="x()"> there</div>
        <div><a href="file:///etc/passwd">local</a> <a href="javascript:x()">run</a> <a href="applenotes:note/1">app</a> <a href="https://user:pw@evil.example/">cred</a> <a href="https://example.com/ok">fine</a></div>
        </body></html>
        """
        let plain = "Hello there\nlocal run app cred fine"
        let doc = try XCTUnwrap(NoteDocument.build(html: html, stored: stored(plain)))
        XCTAssertEqual(doc.blocks.map(\.text), ["Hello there", "local run app cred fine"])
        XCTAssertEqual(doc.blocks.flatMap(\.runs).compactMap(\.link).map(\.absoluteString), ["https://example.com/ok"])
        XCTAssertNil(ItemPlaceOpen.webURL("file:///etc/passwd"))
    }

    func testBrokenMarkupNeverCrashes() {
        for html in ["<", "<div", "<div class=\"", "</", "<!--", "<script>", "&", "&#xFFFFFFFF;", "<table><td>x", "</div></ul>",
                     "<li>", "<ol start=\"99999999999\"><li>x", "<a href=x>"] {
            _ = NoteDocument.build(html: html, stored: "x")
        }
    }

    // MARK: Proof, on invented words: `NOTE_RENDER_DIR=<dir> swift test --filter NoteDocumentTests/testRender`

    @MainActor func testRenderASyntheticNote() throws {
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        guard let dir = ProcessInfo.processInfo.environment["NOTE_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set NOTE_RENDER_DIR to render a synthetic note")
        }
        let html = Self.richHTML + """
        <ul class="Apple-checklist"><li class="checked">Buy map</li><li>Call the cabin</li></ul>
        """
        let text = stored(Self.richPlain + "\nBuy map\nCall the cabin")
        let note = try XCTUnwrap(NoteDocument.build(html: html, stored: text))
        let doc = EpisodeText(episode: "ep_2026-01-02_001", text: text, title: "Another title",
                              turns: [EpisodeTurn(index: 0, start: 0, contentStart: 0, end: text.unicodeScalars.count, role: "user", marker: nil, speaker: nil, ts: nil)])
        let focus = try scalarRange(of: "boots, maps", in: text)
        let other = try scalarRange(of: "Pay deposit", in: text)
        let rows = note.rows(doc: doc, turn: 0, focus: focus, focusStyle: .focus, others: [other])
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            let view = VStack(alignment: .leading, spacing: 0) { NotePageRows(rows: rows, revealed: true) }
                .padding(28)
                .frame(width: 560)
                .background(CicadaTheme.bgPane)
                .environment(\.colorScheme, mode == .dark ? .dark : .light)
            let renderer = ImageRenderer(content: view)
            renderer.scale = 2
            let image = try XCTUnwrap(renderer.nsImage?.tiffRepresentation.flatMap(NSBitmapImageRep.init(data:)))
            let png = try XCTUnwrap(image.representation(using: .png, properties: [:]))
            try png.write(to: URL(fileURLWithPath: dir).appendingPathComponent("note-\(mode).png"))
        }
    }

    /// Measured on real notes: Notes writes entities with no semicolon, which left 10 of 39 notes plain.
    func testAnEntityWithNoSemicolonIsItsCharacterAndALinkQueryIsNot() {
        XCTAssertEqual(NoteHTML.Tokens.entities("a &gt b &quotword&quot &ampA &lt c"), "a > b \"word\" &A < c")
        XCTAssertEqual(NoteHTML.Tokens.entities("x?a=1&utm=2&rcm=3"), "x?a=1&utm=2&rcm=3")
        XCTAssertEqual(NoteHTML.Tokens.entities("&gt; &#x2014; &amp;"), "> \u{2014} &")
    }
}
