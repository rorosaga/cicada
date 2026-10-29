import XCTest
import SwiftUI
import AppKit
@testable import CicadaApp

/// Owner page, 2026-10-14 — the owner's card lagged on open. Its Details row drew `entity.related` as one chip per entry
/// (2,024 for the owner), each chip scanning the whole graph for its page. Details now shows the first few and
/// "and K more", which opens the page's own Related section (DR-38, DR-5 link, DR-39 collapsed by default). Synthetic
/// names only (`Alpha 0001`).
final class RelatedLinksRowTests: XCTestCase {
    private static func entity(_ id: String, name: String, related: [String] = [], markdown: String = "") -> Entity {
        Entity(id: id, name: name, type: .project, status: .active, confidence: 1, created: "2026-01-01",
               lastReferenced: "2026-10-01", decayRate: 0, sourceEpisodes: [], tags: [], related: related, version: 1,
               markdownContent: markdown, history: [])
    }

    private static let graph: [Entity] = (0..<2_000).map { entity("alpha-\(String(format: "%04d", $0))",
                                                                  name: "Alpha \(String(format: "%04d", $0))") }
    private static let related: [String] = (0..<2_000).map { "alpha-\(String(format: "%04d", $0))" }

    func testDetailsShowsAFewAndCountsTheRest() {
        let preview = DetailsWords.relatedPreview(Self.related)
        XCTAssertEqual(preview.shown.count, DetailsWords.relatedShown)
        XCTAssertEqual(preview.more, 2_000 - DetailsWords.relatedShown)
        XCTAssertEqual(preview.shown, Array(Self.related.prefix(DetailsWords.relatedShown)))
        let small = DetailsWords.relatedPreview(["alpha-0001", "alpha-0002"])
        XCTAssertEqual(small.shown, ["alpha-0001", "alpha-0002"])
        XCTAssertEqual(small.more, 0)
    }

    func testTheMoreLinkSaysTheCountInTheReadersLocale() {
        XCTAssertEqual(Copy.Graph.relatedMore(1_988), "and \(UsageFormat.count(1_988)) more")
        XCTAssertTrue(Copy.Graph.relatedMore(1_988).contains("more"))
    }

    /// "and K more" leads to the page's own `## Related` heading: found among the article's rows, with a scroll anchor
    /// of its own (a string, never another section's id).
    func testTheRelatedSectionIsFoundAndAnchored() {
        let markdown = "## Summary\nOwner.\n\n## Key Facts\n- A fact.\n\n## Related\n- [[Alpha 0001]] — linked\n"
        let article = WikiArticle.build(markdown)
        let heading = article.rows.first { WikiPageView.isSection($0, Copy.Graph.related) }
        XCTAssertNotNil(heading)
        XCTAssertFalse(article.rows.contains { WikiPageView.isSection($0, "Nothing like it") })
        XCTAssertEqual(heading.map { WikiPageView.anchor($0.id) }, heading.map { "wiki-row-\($0.id)" })
        XCTAssertEqual(Set(article.rows.map(\.anchor)).count, article.rows.count, "every row has its own anchor")
    }

    /// The app-scale render: the owner's Details row with 2,000 related names against a 2,000-page graph, laid out
    /// in an offscreen window. Before this change the row built 2,000 chips, each scanning the graph (seconds); it
    /// now builds `relatedShown` + 1. A generous budget for a debug build on a loaded machine.
    @MainActor
    func testTheOwnerSizedRowRendersWithinBudget() {
        var opened: [String] = []
        let row = RelatedLinksRow(related: Self.related, entities: Self.graph, onOpen: { opened.append($0) },
                                  onMore: {})
            .frame(width: 560)
            .environment(\.colorScheme, .dark)
        _ = NSApplication.shared
        let started = DispatchTime.now().uptimeNanoseconds
        let hosting = NSHostingView(rootView: row)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 600, height: 400), styleMask: [.titled],
                              backing: .buffered, defer: false)
        window.contentView = hosting
        hosting.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        let ms = Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000
        print(String(format: "BENCH owner Related row (2,000 names, 2,000 pages) %.1f ms", ms))
        XCTAssertLessThan(ms, 500, "the owner's Details row must not lay out thousands of chips")
        XCTAssertLessThan(hosting.fittingSize.height, 200, "a few lines of names, not thousands")
        window.orderOut(nil)
    }

    /// What the row cost before (opt-in, `CICADA_APP_BENCH=1`, prints only): every name a chip, each looked up.
    @MainActor
    func testPrintTheUncappedRowsCost() throws {
        guard ProcessInfo.processInfo.environment["CICADA_APP_BENCH"] == "1" else {
            throw XCTSkip("set CICADA_APP_BENCH=1 to print the uncapped row's cost")
        }
        let entities = Self.graph
        let row = FlowLayout(spacing: CicadaTheme.spacingMD) {
            ForEach(Self.related, id: \.self) { rel in
                if let id = DetailsWords.relatedTarget(rel, in: entities) {
                    Button(rel) { _ = id }.buttonStyle(.cicadaPlain)
                } else {
                    Text(rel)
                }
            }
        }
        _ = NSApplication.shared
        let started = DispatchTime.now().uptimeNanoseconds
        let hosting = NSHostingView(rootView: row.frame(width: 560))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 600, height: 400), styleMask: [.titled],
                              backing: .buffered, defer: false)
        window.contentView = hosting
        hosting.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        print(String(format: "BENCH uncapped Related row (2,000 chips) %.1f ms",
                     Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000))
        window.orderOut(nil)
    }

    /// A page with no Related section of its own: the count is words, not a link (nowhere to lead).
    @MainActor
    func testWithNowhereToLeadTheCountIsPlainWords() {
        let row = RelatedLinksRow(related: Self.related, entities: [], onOpen: { _ in }, onMore: nil)
        let hosting = NSHostingView(rootView: row.frame(width: 560))
        hosting.layoutSubtreeIfNeeded()
        XCTAssertGreaterThan(hosting.fittingSize.height, 0)
    }

    // MARK: - rawOmitted, everywhere rawMarkdown is read

    private func hubPage() throws -> Entity {
        // A page whose older claims live in its ledger: `/entities` sends its frontmatter alone (rawOmitted).
        let object: [String: Any] = ["id": "owner-example", "name": "Owner Example", "type": "location",
                                     "status": "active", "confidence": 1, "created": "2024-01-01",
                                     "lastReferenced": "2024-01-01", "decayRate": 0,
                                     "markdownContent": "## Summary\nOwner.\n\n## Related\n- [[Alpha 0001]]",
                                     "rawMarkdown": "---\nname: Owner Example\nlat: 40.4\nlon: -3.7\n---\n",
                                     "rawOmitted": true]
        return try JSONDecoder().decode(Entity.self, from: JSONSerialization.data(withJSONObject: object))
    }

    /// Source and Copy show and copy the file only once `/raw` answered — never the frontmatter-only head, never a
    /// reconstruction. The page is a full page (not the graph stub), and a frontmatter reader (a location's declared
    /// lat/lon) still reads its input. The app has no flow that writes a page body back, so nothing can save the head.
    func testAFrontmatterOnlyHeadIsNeverTakenForTheFile() throws {
        let page = try hubPage()
        XCTAssertFalse(page.isStub)
        XCTAssertNil(RawFile.verbatim(page, fetched: nil))
        XCTAssertEqual(RawFile.verbatim(page, fetched: "---\nname: Owner Example\n---\nwhole file\n"),
                       "---\nname: Owner Example\n---\nwhole file\n")
        XCTAssertNotNil(LocationHero.declaredCoordinate(from: page.rawMarkdown))
    }

    /// Every reader of `rawMarkdown` in the app, pinned: a new one must handle `rawOmitted` (Source and Copy through
    /// `RawFile`, frontmatter-only readers by design) or this test names it.
    func testEveryRawMarkdownReaderIsKnown() throws {
        // APIClient.swift reads `/raw`'s own answer, the whole file.
        let known: Set<String> = ["APIClient.swift", "Entity.swift", "EntityDetailCard.swift", "EntityProse.swift",
                                  "HeroPreview.swift",
                                  // Part B: the map's fallback reads the frontmatter's declared lat/lon only.
                                  "PlaceMap.swift"]
        for file in try ThemeTokenTests.swiftSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            if text.contains(".rawMarkdown") || text.contains("rawMarkdown:") {
                XCTAssertTrue(known.contains(file.lastPathComponent),
                              "\(file.lastPathComponent) reads rawMarkdown: handle rawOmitted, then add it here")
            }
        }
    }
}
