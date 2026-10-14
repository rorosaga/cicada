import XCTest
import SwiftUI
@testable import CicadaApp

/// Links show as what they are (owner rulings 2026-10-14): one grammar on both sides, pinned by
/// `api/tests/fixtures/link_views.json`; bare URLs are live links shown as their address; titled links and images
/// keep their URL; a picture on the web is never loaded by the app. Synthetic URLs only.
final class LinkViewTests: XCTestCase {
    private struct Fixture: Decodable {
        struct TitleCase: Decodable { let title: String?; let view: String?; let day: String? }
        struct Link: Decodable, Equatable {
            let label: String; let url: String; let view: String; let asked: String; let day: String?
            let block: Bool; let markdown: String
        }
        struct LineCase: Decodable { let line: String; let links: [Link] }
        struct PlainCase: Decodable { let `in`: String; let out: String }
        struct MarkdownCase: Decodable { let label: String; let url: String; let view: String; let day: String?; let out: String }
        struct DisplayCase: Decodable { let url: String; let out: String }
        let titles: [TitleCase]
        let lines: [LineCase]
        let plain: [PlainCase]
        let markdown: [MarkdownCase]
        let display: [DisplayCase]
    }

    private func fixture() throws -> Fixture {
        try JSONDecoder().decode(Fixture.self,
                                 from: Data(contentsOf: VideoFixtures.apiFixtures.appendingPathComponent("link_views.json")))
    }

    // MARK: the grammar, shared with `api/services/link_views.py`

    func testEveryViewWordAndDateParsesAsTheFixtureSays() throws {
        for c in try fixture().titles {
            let parsed = LinkGrammar.parseTitle(c.title)
            XCTAssertEqual(parsed?.view.rawValue, c.view, "title \(String(describing: c.title))")
            XCTAssertEqual(parsed?.day, c.day, "title \(String(describing: c.title))")
        }
    }

    func testEveryLineYieldsTheFixturesLinks() throws {
        for c in try fixture().lines {
            let got = LinkGrammar.links(in: c.line).map {
                Fixture.Link(label: $0.label, url: $0.url, view: $0.view.rawValue, asked: $0.asked.rawValue, day: $0.day,
                             block: $0.block, markdown: $0.markdown)
            }
            XCTAssertEqual(got, c.links, c.line)
        }
    }

    func testPlainTokensAndDisplayMatchTheBackend() throws {
        let f = try fixture()
        for c in f.plain { XCTAssertEqual(LinkGrammar.plain(c.in), c.out) }
        for c in f.markdown {
            XCTAssertEqual(LinkGrammar.markdown(label: c.label, url: c.url, view: LinkViewKind(rawValue: c.view)!, day: c.day),
                           c.out)
        }
        for c in f.display { XCTAssertEqual(LinkGrammar.display(c.url), c.out) }
    }

    // MARK: the article

    private func runs(_ text: AttributedString) -> [(String, String?)] {
        text.runs.map { (String(text[$0.range].characters), $0.link?.absoluteString) }
    }

    /// The design guessed a bare URL in prose was dead text (Foundation's parser not autolinking). It is not: the
    /// parser links it. What was wrong is how it read — the whole URL with its scheme. Now it is a live link that
    /// reads as its address.
    func testABareURLIsALiveLinkThatReadsAsItsAddress() {
        let foundation = try! AttributedString(markdown: "see https://www.example.com/guide/ now",
                                               options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
        XCTAssertTrue(foundation.runs.contains { $0.link != nil }, "Foundation links a bare URL by itself")
        let text = WikiInline.attributed("see https://www.example.com/guide/ now")
        XCTAssertEqual(String(text.characters), "see example.com/guide now")
        let link = runs(text).first { $0.1 != nil }
        XCTAssertEqual(link?.0, "example.com/guide")
        XCTAssertEqual(link?.1, "https://www.example.com/guide/")
        XCTAssertEqual(String(WikiInline.attributed("at <https://example.com/x>.").characters), "at example.com/x.")
    }

    /// Review B2: a URL with balanced parentheses is one URL, so the link reads as its words.
    func testAWikipediaLinkStaysOneLink() {
        let text = WikiInline.attributed("See [Foo](https://en.wikipedia.org/wiki/Foo_(bar)) here.")
        XCTAssertEqual(String(text.characters), "See Foo here.")
        XCTAssertEqual(runs(text).first { $0.1 != nil }?.1, "https://en.wikipedia.org/wiki/Foo_(bar)")
    }

    func testAViewWordIsNeverShownAndAMentionReadsAsSiteThenTitle() {
        let titled = WikiInline.attributed(#"See [the guide](https://docs.example.com/g "The setup guide") now."#)
        XCTAssertEqual(String(titled.characters), "See the guide now.")
        let mention = WikiInline.attributed(#"Read [How we priced seats](https://blog.example.com/seats "bookmark") today."#)
        XCTAssertEqual(String(mention.characters), "Read blog.example.com How we priced seats today.")
        XCTAssertTrue(runs(mention).filter { $0.1 != nil }.allSatisfy { $0.1 == "https://blog.example.com/seats" })
        XCTAssertTrue(WikiInline.hasSitePart(mention))
        let site = mention.runs.first { $0[WikiInline.SitePart.self] == true }
        XCTAssertEqual(site.map { String(mention[$0.range].characters) }, "blog.example.com ")
    }

    func testAPlainLinkInTheLinksSectionIsAMentionAndElsewhereALink() {
        let markdown = """
        ## Article
        ### Pricing
        The team wrote it up in [the write-up](https://blog.example.com/seats).

        ## Links
        - [How we priced seats](https://blog.example.com/seats) — the write-up
        """
        let rows = WikiArticle.build(markdown).rows
        let prose = rows.first { $0.kind == .paragraph }!
        XCTAssertEqual(String(prose.text.characters), "The team wrote it up in the write-up.")
        XCTAssertFalse(prose.inLinks)
        let bullet = rows.first { if case .item = $0.kind { return true }; return false }!
        XCTAssertTrue(bullet.inLinks)
        XCTAssertEqual(String(bullet.text.characters), "blog.example.com How we priced seats — the write-up")
        XCTAssertEqual(bullet.links.map(\.url), ["https://blog.example.com/seats"])
        XCTAssertEqual(LinkCardModel.current(bullet.links[0], inLinks: true), .mention)
    }

    func testABlockViewAloneOnItsLineIsARowOfItsOwnWithItsNote() {
        let markdown = """
        [How we priced seats](https://blog.example.com/seats "bookmark")

        ## Links
        - [Getting started](https://docs.example.com/start "screenshot 2026-10-14") — the setup guide we followed
        - [Roadmap](https://alpha.example.org/roadmap "look") and more words, so a mention
        """
        let rows = WikiArticle.build(markdown).rows
        guard case .link(let first, let none) = rows[0].kind else { return XCTFail("\(rows[0].kind)") }
        XCTAssertEqual(first.asked, .bookmark)
        XCTAssertNil(none)
        guard case .link(let second, let note) = rows[2].kind else { return XCTFail("\(rows[2].kind)") }
        XCTAssertEqual(second.asked, .screenshot)
        XCTAssertEqual(second.day, "2026-10-14")
        XCTAssertEqual(note, "the setup guide we followed")
        guard case .item = rows[3].kind else { return XCTFail("\(rows[3].kind)") }
        XCTAssertEqual(rows[3].links.first?.view, .mention)
    }

    func testATitledImageKeepsItsURL() {
        let rows = WikiArticle.build(#"A chart: ![revenue](https://example.com/chart.png "Oct 14") and a stored one ![p](/design/2026-10-14-x/image?v=abc)"#).rows
        let images = rows.compactMap { row -> String? in
            if case .image(let url, _) = row.kind { return url }
            return nil
        }
        XCTAssertEqual(images, ["https://example.com/chart.png", "/design/2026-10-14-x/image?v=abc"])
    }

    // MARK: pictures through the gate

    func testOnlyAPictureCicadaStoresIsEverLoaded() {
        XCTAssertTrue(StoredPreviewPath.loads("/entities/alpha/preview?v=abc"))
        XCTAssertTrue(StoredPreviewPath.loads("/design/2026-10-14-x/image?v=abc"))
        XCTAssertFalse(StoredPreviewPath.loads("https://example.com/chart.png"))
        XCTAssertFalse(StoredPreviewPath.loads("http://example.com/chart.png"))
        XCTAssertFalse(StoredPreviewPath.loads("/entities/../secrets"))
    }

    /// The app never asks the web for a picture a page names: `AsyncImage` loads any URL it is handed, so it lives
    /// in no surface that draws a page. The one left is a contributor's avatar on the contributors view.
    func testNoPageSurfaceLoadsAPictureFromTheWeb() throws {
        let allowed = ["Views/Contributors/ContributorsView.swift"]
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !allowed.contains(where: { file.path.hasSuffix($0) }) {
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && line.contains("AsyncImage(") {
                offenders.append("\(file.lastPathComponent):\(i + 1)")
            }
        }
        XCTAssertEqual(offenders, [], "a picture is loaded only from Cicada's own API (StoredPreview / PictureStore)")
    }

    // MARK: the cards' words and the switcher

    private let seats = "https://blog.example.com/seats"

    func testOneDatePerCardTheDateOfWhatIsShown() {
        let locale = Locale(identifier: "en_US")
        XCTAssertEqual(LinkCardModel.dateLine(LinkFact(url: seats, savedAt: "2026-10-02", readAt: "2026-10-03T08:00:00Z"),
                                              locale: locale), "Read Oct 3")
        XCTAssertEqual(LinkCardModel.dateLine(LinkFact(url: seats, savedAt: "2026-10-02"), locale: locale), "Saved Oct 2")
        XCTAssertNil(LinkCardModel.dateLine(LinkFact(url: seats)))
    }

    func testAScreenshotIsAPictureFromThatDayElseTheNearestEarlierSaidInWords() throws {
        let looks = [LinkFact.Look(id: "2026-10-14-a", day: "2026-10-14", image: "/design/2026-10-14-a/image?v=1", palette: []),
                     LinkFact.Look(id: "2026-09-30-b", day: "2026-09-30", image: "/design/2026-09-30-b/image?v=2", palette: [])]
        let fact = LinkFact(url: seats, looks: looks)
        XCTAssertEqual(LinkCardModel.shot(fact)?.day, "2026-10-14")
        XCTAssertEqual(LinkCardModel.shot(fact, day: "2026-09-30")?.asked, nil)
        let nearest = try XCTUnwrap(LinkCardModel.shot(fact, day: "2026-10-05"))
        XCTAssertEqual(nearest.day, "2026-09-30")
        XCTAssertEqual(nearest.asked, "2026-10-05")
        XCTAssertTrue(nearest.fromLook)
        XCTAssertNil(LinkCardModel.shot(LinkFact(url: seats)))
        let now = try XCTUnwrap(InboxAge.date("2026-12-20"))
        let shot = LinkCardModel.Shot(image: "/x", day: "2026-10-14", asked: nil, fromLook: false)
        XCTAssertEqual(LinkCardModel.capturedLine(shot, now: now, locale: Locale(identifier: "en_US")),
                       "Captured Oct 14 · 2 months ago")
        let older = LinkCardModel.Shot(image: "/x", day: "2025-10-14", asked: nil, fromLook: false)
        XCTAssertEqual(LinkCardModel.capturedLine(older, now: now, locale: Locale(identifier: "en_US")),
                       "Captured Oct 14, 2025 · a year ago")
    }

    func testTheSwitcherOffersAViewOnlyWhereCicadaHasSomethingForIt() {
        let alone = LinkGrammar.links(in: "[Seats](https://blog.example.com/seats)")[0]
        let inSentence = LinkGrammar.links(in: "Read [Seats](https://blog.example.com/seats) now")[0]
        let bare = LinkFact(url: seats)
        XCTAssertEqual(LinkCardModel.offered(alone, fact: bare), [.link, .mention, .bookmark])
        XCTAssertEqual(LinkCardModel.offered(inSentence, fact: bare), [.link, .mention])
        // A bare URL or an autolink is the page's own words: never offered a switch (review B1).
        for raw in LinkGrammar.links(in: "See https://x.example.com/a and <https://x.example.com/b>.") {
            XCTAssertEqual(LinkCardModel.offered(raw, fact: bare), [], raw.markdown)
        }
        let withLook = LinkFact(url: seats, looks: [LinkFact.Look(id: "2026-10-14-a", day: "2026-10-14", image: "/d", palette: [])])
        XCTAssertEqual(LinkCardModel.offered(alone, fact: withLook), [.link, .mention, .bookmark, .screenshot, .look])
    }

    func testASwitchIsTheSameLinkWithItsViewWord() {
        let ref = LinkGrammar.links(in: "- [Seats](https://blog.example.com/seats) — the write-up")[0]
        XCTAssertEqual(LinkGrammar.markdown(label: ref.label, url: ref.url, view: .bookmark),
                       #"[Seats](https://blog.example.com/seats "bookmark")"#)
        XCTAssertEqual(ref.markdown, "[Seats](https://blog.example.com/seats)")
        XCTAssertEqual(Copy.Links.reason(.bookmark), "Shown as a bookmark.")
    }

    func testLinkFactsDecodeTheRoutesShape() throws {
        let json = #"""
        {"entityId": "alpha-project", "links": [
          {"url": "https://blog.example.com/seats", "views": ["link"], "site": "example.com", "pageId": "seats-post",
           "title": "How we priced seats", "savedAt": "2026-10-02", "readAt": "2026-10-03T08:00:00Z",
           "captures": [], "looks": [{"id": "2026-10-14-seats", "day": "2026-10-14",
           "image": "/design/2026-10-14-seats/image?v=abab", "palette": [{"hex": "#112233", "share": 0.6}]}],
           "icon": true},
          {"url": "https://alpha.example.org/roadmap", "views": ["bookmark"], "site": "example.org", "captures": [],
           "looks": [], "icon": false}]}
        """#
        let facts = try JSONDecoder().decode(PageLinkFacts.self, from: Data(json.utf8))
        XCTAssertEqual(facts.links.count, 2)
        XCTAssertEqual(facts.fact(for: seats)?.pageId, "seats-post")
        XCTAssertEqual(facts.fact(for: seats)?.looks.first?.palette.first?.hex, "#112233")
        XCTAssertNil(facts.fact(for: "https://alpha.example.org/roadmap")?.pageId)
    }

    @MainActor
    func testTheCacheKeepsTheLastAnswerAndAnUnknownURLIsOnlyItsSite() async {
        let page = PageLinkFacts(entityId: "alpha-project", links: [LinkFact(url: seats, title: "Seats")])
        let cache = LinkFactsCache(fetch: { _, etag in
            etag == nil ? Conditional(value: page, etag: "\"v1\"", notModified: false)
                        : Conditional(value: nil, etag: etag, notModified: true)
        })
        XCTAssertEqual(cache.fact(seats, on: "alpha-project").title, nil)
        await cache.refresh("alpha-project")
        XCTAssertEqual(cache.fact(seats, on: "alpha-project").title, "Seats")
        await cache.refresh("alpha-project")
        XCTAssertEqual(cache.fact(seats, on: "alpha-project").title, "Seats")
        XCTAssertEqual(cache.fact("https://other.example.net/x", on: "alpha-project").site, "other.example.net")
        cache.reset()
        XCTAssertNil(cache.fact(seats, on: "alpha-project").title)
    }
}
