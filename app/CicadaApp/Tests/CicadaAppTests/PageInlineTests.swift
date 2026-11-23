import XCTest
import SwiftUI
@testable import CicadaApp

/// Owner 2026-11-23 (DESIGN_RULES §9, amends DR-80 and how a page draws links): a link is a chip wearing the page's own
/// name, a cited passage ends in one cluster of its sources' marks, the References list has no numbers, and a source
/// cited twice is one row. Pure rules here; the look is in the screenshots of the PR.
final class PageInlineTests: XCTestCase {
    private let nodes = [
        GraphNode(id: "bob-example", name: "Bob Example", type: .person, aliases: ["Bobby E.", "B. Example"]),
        GraphNode(id: "alpha-project", name: "Alpha Project", type: .project),
        GraphNode(id: "gamma-ide", name: "Gamma", type: .concept, displayName: "Gamma (IDE)"),
        GraphNode(id: "gamma-program", name: "Gamma", type: .concept, displayName: "Gamma (program)"),
        GraphNode(id: "bob-example#work", name: "Bob Example", type: .person, isFacet: true, parentId: "bob-example"),
    ]
    private var index: PageLinkIndex { PageLinkIndex(nodes: nodes) }

    private func line(_ markdown: String) -> AttributedString { WikiInline.attributed(markdown) }

    // MARK: A link is a chip wearing the page's own name

    func testAnAliasSpelledLinkResolvesToThePagesOwnName() {
        for written in ["[[bob-example|Bob]]", "[[bob-example|Bobby E.]]", "[[Bobby E.]]", "[[B. Example]]", "[[bob example]]"] {
            let pieces = PageInline.pieces(of: line("Met \(written) today."), resolve: index.resolve)
            let chips = pieces.compactMap { piece -> String? in
                if case .entity(let target, _) = piece.token { return target.name }
                return nil
            }
            XCTAssertEqual(chips, ["Bob Example"], "\(written) is one chip with one face")
        }
    }

    func testEveryChipOpensThePageByItsIdSoAnAliasNeverAsksWhich() throws {
        let pieces = PageInline.pieces(of: line("[[Bobby E.]]"), resolve: index.resolve)
        guard case .entity(_, let url)? = pieces.first?.token else { return XCTFail("a chip") }
        XCTAssertEqual(PageInline.entityRef(url), "bob-example")
        XCTAssertEqual(MarkdownBody.entityIDs("bob-example", in: nodes), ["bob-example"])
    }

    func testAnAmbiguousOrUnknownRefKeepsItsWrittenWordsAndTodaysClickAsAQuietLink() throws {
        for written in ["[[Gamma]]", "[[Nobody Known]]"] {
            let pieces = PageInline.pieces(of: line("See \(written) now."), resolve: index.resolve)
            let quiet = pieces.compactMap { piece -> PageQuietWord? in
                if case .quiet(let word) = piece.token { return word }
                return nil
            }
            XCTAssertFalse(quiet.isEmpty, "\(written) is a quiet link, never blue underlined text in a Text")
            XCTAssertTrue(PageInline.needsFlow(pieces), "a quiet link is a view (its hover fill), so the line is a flow")
            let url = try XCTUnwrap(quiet.first?.url)
            XCTAssertNotNil(PageInline.entityRef(url), "\(written) keeps the click it always had, which asks which (G227)")
            XCTAssertEqual(quiet.map { String($0.text.characters) }.joined(separator: " "),
                           written.dropFirst(2).dropLast(2).description, "the written words")
            for word in quiet {
                XCTAssertNil(word.text.runs.first?.link, "no link attribute left to draw blue")
                XCTAssertNil(word.text.runs.first?.underlineStyle)
            }
            XCTAssertEqual(quiet.filter(\.first).count, 1, "one control: its first word carries the label")
            XCTAssertFalse(pieces.contains { if case .entity = $0.token { return true }; return false },
                           "no chip for a ref that means no single page")
        }
        XCTAssertNil(index.resolve("Gamma"), "two pages answer to the name")
        XCTAssertEqual(index.resolve("gamma-ide")?.name, "Gamma (IDE)", "an id names exactly one page, qualified")
    }

    func testTheFirstMentionOfAPageIsTheChipAndLaterOnesInThePassageAreQuietLinks() {
        let pieces = PageInline.pieces(
            of: line("[[bob-example]] met [[Bobby E.]] and [[B. Example]] with [[alpha-project]], then [[alpha-project]]."),
            resolve: index.resolve)
        var shape: [String] = []
        for piece in pieces {
            switch piece.token {
            case .entity(let target, _): shape.append("chip:\(target.id)")
            case .quiet(let word) where word.first: shape.append("quiet:\(word.label)")
            default: break
            }
        }
        XCTAssertEqual(shape, ["chip:bob-example", "quiet:Bob Example", "quiet:Bob Example", "chip:alpha-project",
                               "quiet:Alpha Project"],
                       "every spelling of one page counts once: the first is the chip, the rest are quiet")
        let quietWords = pieces.compactMap { piece -> String? in
            if case .quiet(let word) = piece.token, word.label == "Bob Example" { return String(word.text.characters) }
            return nil
        }
        XCTAssertEqual(quietWords, ["Bob", "Example", "Bob", "Example"], "the page's own name, a word each so it wraps")
        XCTAssertEqual(PageInline.plainText(pieces),
                       "Bob Example met Bob Example and Bob Example with Alpha Project, then Alpha Project.")
    }

    func testEachPassageCountsItsOwnFirstMention() {
        // A bullet and a paragraph are each one `pieces` call: the same page is a chip again in the next passage.
        for text in ["[[bob-example]] and [[bob-example]]", "[[bob-example]] again"] {
            let chips = PageInline.pieces(of: line(text), resolve: index.resolve).filter {
                if case .entity = $0.token { return true }
                return false
            }
            XCTAssertEqual(chips.count, 1)
        }
    }

    func testAQuietLinkOpensTheSamePageAsTheChip() throws {
        let pieces = PageInline.pieces(of: line("[[bob-example]] and [[Bobby E.]]"), resolve: index.resolve)
        guard case .entity(_, let chipURL)? = pieces.first?.token,
              case .quiet(let word)? = pieces.last?.token else { return XCTFail("a chip then a quiet link") }
        XCTAssertEqual(word.url, chipURL, "the page's id, so an alias never asks which")
    }

    func testAQuietLinksFirstWordTouchesWhatTouchedIt() {
        let pieces = PageInline.pieces(of: line("[[bob-example]] met ([[Bobby E.]])."), resolve: index.resolve)
        let shape = pieces.map { piece -> String in
            let glue = piece.glued ? "~" : ""
            switch piece.token {
            case .word(let attr): return glue + String(attr.characters)
            case .entity: return glue + "<chip>"
            case .quiet(let word): return glue + "q:" + String(word.text.characters)
            default: return "?"
            }
        }
        XCTAssertEqual(shape, ["<chip>", "met", "(", "~q:Bob", "q:Example", "~)."],
                       "brackets and a full stop hug a quiet link as they hug a word")
    }

    func testAnExternalLinkIsAChipWearingItsOwnWords() {
        let pieces = PageInline.pieces(of: line("Watch [the talk](https://www.youtube.com/watch?v=abc) soon."),
                                       resolve: index.resolve)
        let chips = pieces.compactMap { piece -> (String, URL)? in
            if case .external(let url, let label) = piece.token { return (label, url) }
            return nil
        }
        XCTAssertEqual(chips.map(\.0), ["the talk"])
        XCTAssertEqual(PageChipMark.bundled(url: chips[0].1, exists: { $0 == "youtube" }), "youtube")
        XCTAssertNil(PageChipMark.bundled(url: URL(string: "https://example.org/x")!, exists: { _ in true }),
                     "a site with no bundled mark draws none")
        XCTAssertNil(PageChipMark.bundled(url: chips[0].1, exists: { _ in false }), "a mark that does not ship is none")
    }

    func testAMentionsSiteRunNeverReachesTheChip() {
        // The old grammar led a mention's title with its site ("example.com "); the chip wears the title alone.
        let pieces = PageInline.pieces(of: line("Read [Opening hours](https://example.org/hours \"mention\")."),
                                       resolve: index.resolve)
        XCTAssertEqual(pieces.compactMap { piece -> String? in
            if case .external(_, let label) = piece.token { return label }
            return nil
        }, ["Opening hours"])
    }

    func testPiecesThatTouchedStayGluedAndWordsApartStayApart() {
        let pieces = PageInline.pieces(of: line("Hello [[bob-example]], and **bold**."), resolve: index.resolve)
        let shape = pieces.map { piece -> String in
            switch piece.token {
            case .word(let attr): return (piece.glued ? "~" : "") + String(attr.characters)
            case .entity: return (piece.glued ? "~" : "") + "<chip>"
            default: return "?"
            }
        }
        XCTAssertEqual(shape, ["Hello", "<chip>", "~,", "and", "bold", "~."], "a full stop touches the word before it")
    }

    func testALineOfOnlyWordsIsNeverCutUp() {
        let pieces = PageInline.pieces(of: line("A plain line with **bold** and `code`."), resolve: index.resolve)
        XCTAssertFalse(PageInline.needsFlow(pieces))
        XCTAssertEqual(PageInline.plainText(pieces), "A plain line with bold and code.")
    }

    // MARK: One cluster per passage, with the +N rule

    func testTheClusterIsTheFirstThreeKindsThenOneMore() {
        let one = SourceClusterModel(keys: ["chatgpt-export"])
        XCTAssertEqual(one.marks, ["chatgpt-export"])
        XCTAssertEqual(one.more, 0)
        XCTAssertNil(one.moreWords)

        let same = SourceClusterModel(keys: Array(repeating: "chatgpt-export", count: 6))
        XCTAssertEqual(same.marks, ["chatgpt-export"], "six conversations in one app are that app's mark once")
        XCTAssertEqual(same.more, 5)
        XCTAssertEqual(same.moreWords, "+5")

        let three = SourceClusterModel(keys: ["chatgpt-export", "claude-code", "notes"])
        XCTAssertEqual(three.marks.count, 3)
        XCTAssertEqual(three.more, 0, "three kinds fit, no +N")

        let five = SourceClusterModel(keys: ["chatgpt-export", "claude-code", "notes", "web", "chatgpt-export"])
        XCTAssertEqual(five.marks, ["chatgpt-export", "claude-code", "notes"])
        XCTAssertEqual(five.more, 2, "the marks and the N always add up to the passage's sources")
        XCTAssertEqual(five.marks.count + five.more, five.total)
    }

    func testASourceWithNoRealMarkCountsButDrawsNone() {
        // A key the backend gave no mark for, and a place the app has no real mark of: counted in the "+N", never a tile.
        let model = SourceClusterModel(keys: [nil, "notes", "some-folder"], drawn: { $0 == "notes" })
        XCTAssertEqual(model.marks, ["notes"])
        XCTAssertEqual(model.more, 2)
        XCTAssertEqual(model.total, 3)
        let none = SourceClusterModel(keys: ["some-folder"], drawn: { _ in false })
        XCTAssertTrue(none.marks.isEmpty)
        XCTAssertFalse(none.isEmpty, "the cluster still opens the popover; its words say how many")
        XCTAssertTrue(SourceClusterModel(keys: []).isEmpty)
        XCTAssertFalse(PageSourceMark.isDrawn(SourceClusterModel.unknown), "the unknown stand-in is never drawn")
        XCTAssertTrue(PageSourceMark.isDrawn("web"), "a looked-up page's globe is an explicit mark")
        XCTAssertTrue(PageSourceMark.isDrawn("page"))
    }

    func testAPassageEndsInExactlyOneClusterAfterItsLastWord() {
        let keys = [CiteKey(n: 1, at: 10), CiteKey(n: 2, at: 10), CiteKey(n: 4, at: 10)]
        let citations = PageBlocks.Citations(markKeys: ["web", "page", "unknown"], refMarks: [0, 1, 1, 2, 0, 2])
        let cluster = CitationMarks.cluster(keys, in: citations)
        XCTAssertEqual(cluster?.0.marks, ["web", "page"], "the unknown source is counted, not drawn")
        XCTAssertEqual(cluster?.0.more, 1)
        let pieces = PageInline.pieces(of: line("It opens in December."), resolve: index.resolve, cluster: cluster)
        let clusters = pieces.filter { if case .cluster = $0.token { return true }; return false }
        XCTAssertEqual(clusters.count, 1, "one cluster per passage, never a run of markers")
        XCTAssertEqual(pieces.last?.glued, true, "glued to the last word, so it never wraps onto a line of its own")
        XCTAssertNil(CitationMarks.cluster([], in: citations), "an uncited passage draws none")
        XCTAssertEqual(PageInline.plainText(pieces), "It opens in December.", "no number or mark is read as text")
    }

    func testEachReferenceKnowsItsMarkWhetherOrNotItHasALine() throws {
        let json = #"""
        {"markers":[[10,1,7]],"markersTotal":1,"refs":[{"n":1,"kind":"conversation","origin":"notes"}],
         "markKeys":["notes","chatgpt-export"],"refMarks":[0,0,0,0,0,0,1],"total":7,"conversations":7,"web":0,"pages":0,
         "beliefs":[],"beliefsTotal":0}
        """#
        let c = try JSONDecoder().decode(PageBlocks.Citations.self, from: Data(json.utf8))
        XCTAssertEqual(c.markKey(forRef: 1), "notes")
        XCTAssertEqual(c.markKey(forRef: 7), "chatgpt-export", "a source past the six References lines has its mark")
        XCTAssertNil(c.markKey(forRef: 8))
        XCTAssertNil(c.markKey(forRef: 0))
        let older = try JSONDecoder().decode(PageBlocks.Citations.self, from: Data(#"{"markers":[],"refs":[]}"#.utf8))
        XCTAssertNil(older.markKey(forRef: 1), "an older backend sends none: the cluster never guesses")
    }

    // MARK: References: no numbers, no repeats

    func testTheSameSourceListedTwiceIsOneRow() {
        func ref(_ n: Int, title: String, origin: String = "chatgpt-export", first: String = "2026-09-21") -> PageBlocks.Citations.Ref {
            PageBlocks.Citations.Ref(n: n, kind: "conversation", title: title, origin: origin, harness: nil,
                                     correspondent: nil, first: first, last: first, episodeId: nil, conversationId: nil,
                                     sourceRemoved: nil)
        }
        let refs = [ref(1, title: "Studio plan"), ref(2, title: "Studio plan"), ref(3, title: "Studio plan", first: "2026-09-22"),
                    ref(4, title: "Market walk", origin: "notes")]
        let rows = PageWords.referenceRows(refs, today: ISODay("2026-10-27")!, locale: Locale(identifier: "en_US"))
        XCTAssertEqual(rows.count, 3, "the same line and day collapse to one; another day or title stays")
        XCTAssertEqual(rows.map(\.markKey), ["chatgpt-export", "chatgpt-export", "notes"])
        XCTAssertEqual(rows.first?.who, "You, in ChatGPT")
        XCTAssertEqual(rows.first?.title, "Studio plan")
    }

    func testAMarkKeyIsTheAgentsProductElseTheChannel() {
        XCTAssertEqual(PageWords.markKey(kind: "conversation", harness: "claude-code", origin: "mcp"), "claude-code")
        XCTAssertEqual(PageWords.markKey(kind: "conversation", harness: "mcp", origin: "chatgpt-export"), "chatgpt-export")
        XCTAssertEqual(PageWords.markKey(kind: "conversation", harness: nil, origin: nil), SourceClusterModel.unknown)
        XCTAssertEqual(PageWords.markKey(kind: "web", harness: "claude-code", origin: "web-check"), "web")
        XCTAssertEqual(PageWords.markKey(kind: "page", harness: nil, origin: nil), "page")
    }

    // MARK: Related as cards

    func testARelatedItemIsACardWithThePagesNameAndTheWordsAfterIt() throws {
        let card = try XCTUnwrap(RelatedCardModel.make(line("[[Bobby E.]] — works with you on Alpha"), resolve: index.resolve))
        XCTAssertEqual(card.title, "Bob Example", "the page's own name, not the alias it was written under")
        XCTAssertEqual(card.meta, "works with you on Alpha")
        XCTAssertEqual(card.target?.id, "bob-example")
        let ambiguous = try XCTUnwrap(RelatedCardModel.make(line("[[Gamma]] — a tool"), resolve: index.resolve))
        XCTAssertNil(ambiguous.target)
        XCTAssertEqual(ambiguous.title, "Gamma", "an ambiguous ref keeps its written words")
        XCTAssertNil(RelatedCardModel.make(line("people: 120 pages — latest today"), resolve: index.resolve),
                     "a rolled-up line names no page and stays a bullet")
    }

    func testTheRelatedPictureColumnIsOneWidthForEveryCard() {
        XCTAssertEqual(RelatedCard.slotWidth([]), 0, "no card draws a picture: no column, names at the list's edge")
        XCTAssertEqual(RelatedCard.slotWidth([.person, .company]), 28)
        XCTAssertEqual(RelatedCard.slotWidth([.person, .media]), 42, "a media page's 3:2 well sets the column")
    }

    func testOnlyListItemsUnderRelatedBecomeCards() {
        let article = WikiArticle.build("""
        ## Key Facts

        - [[bob-example]] is a friend.

        ## Related

        - [[bob-example]] — knows
        - [[alpha-project]]
        - people: 12 pages — latest today
        """)
        let cards = RelatedCardModel.rows(in: article, resolve: index.resolve)
        XCTAssertEqual(cards.values.map(\.title).sorted(), ["Alpha Project", "Bob Example"])
        XCTAssertEqual(cards.count, 2)
    }

    // MARK: The layout keeps a cluster off a line of its own

    private func measure(_ width: CGFloat, glued: Bool = false, lead: CGFloat = 0, ascent: CGFloat = 12,
                         height: CGFloat = 17) -> InlineFlowLayout.Measure {
        .init(size: CGSize(width: width, height: height), ascent: ascent, glued: glued, lead: lead)
    }

    func testTheFlowBreaksLinesWithAGluedPieceNeverStartingOne() {
        // 4 words of 40 pt in a 100 pt line: two per line. The last word carries a 16 pt cluster, glued, 5 pt away.
        let items = [measure(40), measure(40), measure(40), measure(40), measure(16, glued: true, lead: 5)]
        let lines = InlineFlowLayout.arrange(items, width: 110, space: 4)
        XCTAssertEqual(lines.map { $0.entries.map(\.index) }, [[0, 1], [2, 3, 4]],
                       "the cluster stays on the last word's line")
        // A word that would only fit without its cluster moves to the next line WITH it.
        let tight = InlineFlowLayout.arrange([measure(40), measure(40), measure(16, glued: true, lead: 5)], width: 90, space: 4)
        XCTAssertEqual(tight.map { $0.entries.map(\.index) }, [[0], [1, 2]], "the last word takes its cluster with it")
        XCTAssertEqual(tight[1].entries[1].x, 40 + 5, accuracy: 0.01, "glued: no word space, the lead only")
    }

    func testTheFlowAlignsEveryPieceOnTheLinesBaseline() throws {
        // A chip taller than a word, and a cluster whose baseline guide sits lower: one baseline for the line, whose
        // height is the tallest above it plus the deepest below it.
        let items = [measure(30, ascent: 12, height: 17), measure(50, ascent: 14, height: 21),
                     measure(24, ascent: 14.5, height: 19)]
        let line = try XCTUnwrap(InlineFlowLayout.arrange(items, width: 400, space: 4).first)
        XCTAssertEqual(line.ascent, 14.5, accuracy: 0.01)
        XCTAssertEqual(line.descent, 7, accuracy: 0.01)
        XCTAssertEqual(line.height, 21.5, accuracy: 0.01)
    }

    func testAUnitWiderThanTheLineIsAloneAndOverflowsRatherThanLooping() {
        let lines = InlineFlowLayout.arrange([measure(30), measure(300), measure(30)], width: 100, space: 4)
        XCTAssertEqual(lines.map { $0.entries.map(\.index) }, [[0], [1], [2]])
    }

    func testAGluedRunWiderThanTheLineBreaksBetweenItsPiecesAndNeverOverflows() {
        // A 70 pt chip, a 5 pt full stop touching it and a 30 pt cluster 5 pt away, in a 90 pt column.
        let items = [measure(70), measure(5, glued: true), measure(30, glued: true, lead: 5)]
        let lines = InlineFlowLayout.arrange(items, width: 90, space: 4)
        XCTAssertEqual(lines.map { $0.entries.map(\.index) }, [[0, 1], [2]])
        XCTAssertTrue(lines.allSatisfy { $0.width <= 90 })
        // Wide enough, the same run stays one unit and moves whole to the next line.
        let whole = InlineFlowLayout.arrange([measure(60)] + items, width: 120, space: 4)
        XCTAssertEqual(whole.map { $0.entries.map(\.index) }, [[0], [1, 2, 3]])
    }

    func testAnUnboundedWidthIsOneLine() {
        let lines = InlineFlowLayout.arrange(Array(repeating: measure(50), count: 20), width: .infinity, space: 4)
        XCTAssertEqual(lines.count, 1)
    }

    // MARK: Cost at owner scale

    /// The first screen of an owner-sized page (~1,000 Key Facts, each with a wikilink and a cited source), laid out
    /// lazily as the card draws it: lines as one `Text` each (before chips) against chips and clusters. The budget test
    /// always runs; the numbers print with `CICADA_APP_BENCH=1`.
    @MainActor
    func testTheFirstScreenOfAnOwnerSizedPageStaysCheapWithChips() throws {
        CicadaTheme.uiScale = 1
        let nodes = (0..<400).map { GraphNode(id: String(format: "thing-%04d", $0), name: "Thing \($0)", type: .concept) }
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        store.graph.value = GraphResponse(nodes: nodes)
        store.graph.loadedAt = Date()
        let index = PageLinkIndex(nodes: nodes)
        let article = WikiArticle.build(WikiPageFixture.prose)
        let cluster = (SourceClusterModel(keys: ["claude-code", "notes", "chatgpt-export", "web"]),
                       [CiteKey(n: 1, at: 1), CiteKey(n: 2, at: 1)])
        func layout(_ flow: Bool) -> Double {
            PageInline.flowEnabled = flow
            defer { PageInline.flowEnabled = true }
            _ = NSApplication.shared
            let start = DispatchTime.now().uptimeNanoseconds
            let view = ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(article.rows) { WikiRowView(row: $0, onSource: nil, entityId: "owner-example",
                                                       cluster: cluster, index: index) }
                }
            }
            .environment(store)
            .frame(width: 504, height: 900)
            let hosting = NSHostingView(rootView: view)
            hosting.frame = NSRect(x: 0, y: 0, width: 504, height: 900)
            hosting.layoutSubtreeIfNeeded()
            return Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000
        }
        _ = layout(false)
        let plain = (0..<3).map { _ in layout(false) }.min() ?? 0
        let chips = (0..<3).map { _ in layout(true) }.min() ?? 0
        print(String(format: "BENCH first screen, lines as one Text   %8.2f ms", plain))
        print(String(format: "BENCH first screen, chips + clusters    %8.2f ms", chips))
        XCTAssertLessThan(chips, 2_500, "a generous bound for a debug build on a loaded machine")
    }

    /// Owner 2026-11-23: at rest nothing is under the tabs, so the page's first line is never faded.
    func testTheTabEdgeFadesOnlyWhatHasScrolledUnderTheBar() {
        XCTAssertEqual(FadedTopScrollEdge.depth(scrolled: 0, height: 16), 0, "a page at rest is drawn whole")
        XCTAssertEqual(FadedTopScrollEdge.depth(scrolled: -40, height: 16), 0, "pulled past the top")
        XCTAssertEqual(FadedTopScrollEdge.depth(scrolled: 8, height: 16), 0.5)
        XCTAssertEqual(FadedTopScrollEdge.depth(scrolled: 900, height: 16), 1)
        XCTAssertEqual(FadedTopScrollEdge.depth(scrolled: 10, height: 0), 0)
    }
}
