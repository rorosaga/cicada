import XCTest
@testable import CicadaApp

/// Ruling 48 (2026-10-28) — the entity page, part A: the article carries the beliefs (DR-80), Where to check is one box
/// of mention rows (DR-79), Ongoing on every page, References close the page, and nothing on the page folds (DR-81).
final class PagesV2Tests: XCTestCase {
    private let today = ISODay(year: 2026, month: 10, day: 28)
    private let en = Locale(identifier: "en_US")

    /// The served prose of `api/tests/page_citation_fixture.py`'s page — the shared fixture's markers index it.
    private static let served = """
    ## Summary

    A place.

    ## Article

    ### The place

    Alpha Place is where the alpha-project studio is being built. It opens in December.

    ### Around it

    It sits next to Beta City's old market.

    ## Key Facts

    - It is in Beta City.
    - Open on Saturdays.
    """

    // MARK: Markers land on their own line (DR-80)

    func testEachCitedLineDrawsItsOwnMarkersAndNoOther() throws {
        let citations = PageBlocks.Citations(markers: [.init(at: 132, refs: [1]), .init(at: 188, refs: [2]),
                                                       .init(at: 225, refs: [2]), .init(at: 246, refs: [3])])
        let article = WikiArticle.build(Self.served)
        var cited: [String: [Int]] = [:]
        for row in article.rows {
            let keys = WikiPageView.cites(row, in: citations)
            // The inline renderer may curl an apostrophe; compare on the words.
            let words = String(row.text.characters).replacingOccurrences(of: "\u{2019}", with: "'")
            if !keys.isEmpty { cited[words] = keys.map(\.n) }
        }
        XCTAssertEqual(cited, [
            "Alpha Place is where the alpha-project studio is being built. It opens in December.": [1],
            "It sits next to Beta City's old market.": [2],
            "It is in Beta City.": [2],
            "Open on Saturdays.": [3],
        ], "every cited line carries its own markers, and no heading carries one")
    }

    func testAMarkerLinkRoundTrips() throws {
        let key = CiteKey(n: 3, at: 246)
        XCTAssertEqual(CiteKey(url: try XCTUnwrap(key.url)), key)
        let belief = CiteKey(n: 2, claim: "c-was", inferred: true)
        XCTAssertEqual(CiteKey(url: try XCTUnwrap(belief.url)), belief)
        XCTAssertNil(CiteKey(url: URL(string: "cicada://entity/alpha")!), "a wikilink is no marker")
    }

    @MainActor
    func testHeldPopoversAreForgottenWhenThePagesBlocksChange() throws {
        let cache = CitationDetailCache()
        let first = PageBlocks.Citations(markers: [.init(at: 132, refs: [1])], total: 1, conversations: 1)
        var blocks = try JSONDecoder().decode(PageBlocks.self, from: Data(#"{"shape":"blocks-2","order":[]}"#.utf8))
        blocks.citations = first
        cache.track("alpha", blocks: blocks)
        cache.held["alpha|1|132|"] = PageCitationDetail(n: 1, kind: "conversation")
        cache.track("alpha", blocks: blocks)
        XCTAssertNotNil(cache.held["alpha|1|132|"], "the same blocks keep what was read")
        blocks.citations = PageBlocks.Citations(markers: [.init(at: 132, refs: [2])], total: 2, conversations: 2)
        cache.track("alpha", blocks: blocks)
        XCTAssertNil(cache.held["alpha|1|132|"], "a renumbered page never shows an old source")
    }

    // MARK: Where to check (DR-79)

    private func source(_ state: String, checked: String? = nil, label: String? = nil, site: String? = "example.org",
                        ref: String = "https://example.org/alpha") -> PageBlocks.Source {
        PageBlocks.Source(ref: ref, kind: "url", label: label, linkKind: "website", state: state, site: site,
                          checkedAt: checked, addedBy: "user", iconSite: nil)
    }

    func testARowsStateIsSaidInWords() {
        XCTAssertEqual(PageWords.state(source("checked", checked: "2026-10-27"), today: today, locale: en),
                       "checked yesterday")
        XCTAssertEqual(PageWords.state(source("stale", checked: "2026-08-01"), today: today, locale: en),
                       "looks stale · last checked aug 1")
        XCTAssertEqual(PageWords.state(source("stale"), today: today, locale: en), "looks stale")
        XCTAssertEqual(PageWords.state(source("changed"), today: today), "the page changed")
        XCTAssertEqual(PageWords.state(source("dead"), today: today), "not reachable")
        XCTAssertEqual(PageWords.state(source("unchecked"), today: today), "not checked yet")
    }

    func testProposalsAreOneReviewLineNeverRows() {
        let sources = PageBlocks.Sources(total: 3, proposed: 1, tracked: 2,
                                         items: [source("checked"), source("proposed", ref: "https://example.com/x"),
                                                 source("stale", ref: "https://example.io/y")])
        XCTAssertEqual(PageWords.rows(sources).map(\.state), ["checked", "stale"])
        XCTAssertEqual(PageWords.proposals(sources), 1)
    }

    func testAMentionShowsTheSiteAndTheLinksOwnWords() {
        XCTAssertEqual(PageWords.mention(source("checked", label: "Opening hours")).title, "Opening hours")
        XCTAssertEqual(PageWords.mention(source("checked", label: "example.org")).title, "alpha",
                       "a label that only repeats the site gives way to the link's path")
        XCTAssertEqual(PageWords.mention(source("checked", label: "example.org")).site, "example.org")
        let home = PageWords.mention(source("checked", label: "example.org", ref: "https://example.org"))
        XCTAssertNil(home.site, "a site's home page names the site once")
        XCTAssertEqual(home.title, "example.org")
    }

    // MARK: References and belief sentences (DR-80)

    func testAReferenceSaysWhoAndWhere() {
        let said = PageBlocks.Citations.Ref(n: 1, kind: "conversation", title: "Studio plan", origin: "claude-code")
        XCTAssertTrue(PageWords.refWho(said).hasPrefix("You, in "))
        let texted = PageBlocks.Citations.Ref(n: 2, kind: "conversation", title: "Market walk", origin: "messages",
                                              correspondent: "Bob Example")
        XCTAssertTrue(PageWords.refWho(texted).hasSuffix(" · with Bob Example"))
        XCTAssertEqual(PageWords.refWho(.init(n: 3, kind: "web", title: "Opening hours")), "Looked up")
        XCTAssertEqual(PageWords.refWhen(first: "2026-06-04T10:00:00Z", last: "2026-10-27", today: today, locale: en),
                       "Jun 4 – yesterday")
        XCTAssertEqual(PageWords.refWhen(first: "2026-10-09", last: "2026-10-09", today: today, locale: en), "Oct 9")
    }

    func testReferencesCloseWithTheCountsInAll() {
        XCTAssertEqual(PageWords.closing(.init(total: 11, conversations: 9, web: 2)),
                       "9 conversations and 2 web pages in all")
        XCTAssertEqual(PageWords.closing(.init(total: 1, conversations: 1)), "1 conversation in all")
        XCTAssertEqual(PageWords.closingLine(.init(total: 2, conversations: 2)),
                       "2 conversations in all · who wrote each change is in History")
        XCTAssertNil(PageWords.closingLine(.init()))
    }

    func testWhatEndedAndWhatWasInferredAreSaidInTheSentence() {
        let ended = PageBlocks.Citations.Belief(claimId: "c", text: "Alpha Place was a warehouse.", until: "2025-03-01")
        XCTAssertEqual(PageWords.sentence(ended, locale: en), "Alpha Place was a warehouse (until March 2025).")
        let guess = PageBlocks.Citations.Belief(claimId: "g", text: "The studio seems busy on weekends.", inferred: true)
        XCTAssertEqual(PageWords.sentence(guess), "It seems that the studio seems busy on weekends.")
        let named = PageBlocks.Citations.Belief(claimId: "n", text: "Bob prefers mornings.", inferred: true)
        XCTAssertEqual(PageWords.sentence(named), "It seems that Bob prefers mornings.", "a name keeps its capital")
    }

    // MARK: In short, Ongoing, the brand block

    func testInShortCarriesWhatTheFactsStripRepeated() {
        let r = EntityRelevance(tense: "is", line: "Why it matters to you: x.", conversations: 9,
                                lastMentioned: "2026-10-27")
        XCTAssertEqual(PageInShort.counts(r, today: today), "9 conversations · the latest yesterday")
        XCTAssertNil(PageInShort.counts(EntityRelevance(tense: "is", line: "x"), today: today))
    }

    func testOngoingSaysSinceOrPlanned() {
        let open = PageBlocks.Ongoing(claimId: "a", kind: "happening", status: "ongoing", text: "Building it.",
                                      since: "2026-06-04", target: "", verbatim: true)
        XCTAssertEqual(PageWords.ongoingMeta(open, today: today, locale: en), "Since Jun 4 · in your words")
        let planned = PageBlocks.Ongoing(claimId: "b", kind: "milestone", status: "planned", text: "Open it.",
                                         since: "2026-10-02", target: "2026-10-29", verbatim: false)
        XCTAssertEqual(PageWords.ongoingMeta(planned, today: today, locale: en), "planned for Tomorrow")
    }

    func testTheBrandLeadsWhenLooksAreWhatThePageIsAbout() {
        XCTAssertTrue(PageBrandBlock.leads(looks: 2, articleEmpty: false))
        XCTAssertTrue(PageBrandBlock.leads(looks: 1, articleEmpty: true))
        XCTAssertFalse(PageBrandBlock.leads(looks: 1, articleEmpty: false))
        XCTAssertFalse(PageBrandBlock.leads(looks: 0, articleEmpty: true))
        let looks = [PageBlocks.Look(id: "a", palette: ["#0E0D0B", "#F5A93B"], fonts: ["Inter"]),
                     PageBlocks.Look(id: "b", palette: ["#f5a93b", "#E9E4DA"], fonts: ["inter", "Georgia"])]
        XCTAssertEqual(PageBrandBlock.palette(looks), ["#0E0D0B", "#F5A93B", "#E9E4DA"])
        XCTAssertEqual(PageBrandBlock.fonts(looks), ["Inter", "Georgia"])
        XCTAssertTrue(PageBrandBlock.tokens(looks).contains("--brand-color-2: #F5A93B;"))
    }

    // MARK: No folds on the page (DR-81)

    func testTheEntityPageDrawsNoFold() throws {
        let dir = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/Views/Graph")
        for file in ["EntityDetailCard.swift", "PageBlockViews.swift", "PageCitations.swift"] {
            let text = try String(contentsOf: dir.appendingPathComponent(file), encoding: .utf8)
            for fold in ["CardDisclosure(", "DisclosureHeader(", "DisclosureButton(", "InPlaceDisclosureRow("] {
                XCTAssertFalse(text.contains(fold), "\(file) draws \(fold) — DR-81: a page never folds")
            }
        }
    }
}
