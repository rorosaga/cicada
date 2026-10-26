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

    /// Review B2: a URL with balanced parentheses is one URL — a plain link in a sentence, now a mention (site, then its
    /// words), keeps the whole URL in both runs.
    func testAWikipediaLinkStaysOneLink() {
        let text = WikiInline.attributed("See [Foo](https://en.wikipedia.org/wiki/Foo_(bar)) here.")
        XCTAssertEqual(String(text.characters), "See en.wikipedia.org Foo here.")
        XCTAssertTrue(runs(text).filter { $0.1 != nil }.allSatisfy { $0.1 == "https://en.wikipedia.org/wiki/Foo_(bar)" })
    }

    func testAViewWordIsNeverShownAndAMentionReadsAsSiteThenTitle() {
        let titled = WikiInline.attributed(#"See [the guide](https://docs.example.com/g "The setup guide") now."#)
        XCTAssertEqual(String(titled.characters), "See docs.example.com the guide now.", "a tooltip is no view word")
        let mention = WikiInline.attributed(#"Read [How we priced seats](https://blog.example.com/seats "bookmark") today."#)
        XCTAssertEqual(String(mention.characters), "Read blog.example.com How we priced seats today.")
        XCTAssertTrue(runs(mention).filter { $0.1 != nil }.allSatisfy { $0.1 == "https://blog.example.com/seats" })
        XCTAssertTrue(WikiInline.hasSitePart(mention))
        let site = mention.runs.first { $0[WikiInline.SitePart.self] != nil }
        XCTAssertEqual(site.map { String(mention[$0.range].characters) }, "blog.example.com ")
        XCTAssertEqual(site.flatMap { $0[WikiInline.SitePart.self] }, "https://blog.example.com/seats")
        let title = mention.runs.first { $0[WikiInline.MentionTitle.self] != nil }
        XCTAssertEqual(title.map { String(mention[$0.range].characters) }, "How we priced seats")
        XCTAssertEqual(WikiInline.mentionURLs(mention), ["https://blog.example.com/seats"])
    }

    // MARK: Notion's model (owner 2026-10-26)

    /// The fixture's `drawn` cases, the same ones `link_views.drawn` passes: in a sentence a mention, alone on its line
    /// a bookmark, a bare URL its address, a view word wins, never an embed by default.
    func testALinkWithNoViewWordDrawsByItsContextAsTheBackendSays() throws {
        struct DrawnCase: Decodable { let line: String; let drawn: [String] }
        struct Drawn: Decodable { let drawn: [DrawnCase] }
        let cases = try JSONDecoder().decode(
            Drawn.self, from: Data(contentsOf: VideoFixtures.apiFixtures.appendingPathComponent("link_views.json"))).drawn
        XCTAssertFalse(cases.isEmpty)
        for c in cases {
            XCTAssertEqual(LinkGrammar.links(in: c.line).map { LinkGrammar.drawn($0).rawValue }, c.drawn, c.line)
        }
    }

    /// A plain link in prose is a mention (the site's mark is added when the row is drawn); one the person chose as
    /// URL reads as its own words, the plain link.
    func testAPlainLinkInASentenceIsAMentionAndAChosenURLIsItsWords() {
        let plain = WikiInline.attributed("The team wrote it up in [the write-up](https://blog.example.com/seats).")
        XCTAssertEqual(String(plain.characters), "The team wrote it up in blog.example.com the write-up.")
        XCTAssertTrue(WikiInline.hasSitePart(plain))
        let chosen = WikiInline.attributed(#"The team wrote it up in [the write-up](https://blog.example.com/seats "url")."#)
        XCTAssertEqual(String(chosen.characters), "The team wrote it up in the write-up.")
        XCTAssertFalse(WikiInline.hasSitePart(chosen))
        XCTAssertEqual(runs(chosen).first { $0.1 != nil }?.0, "the write-up")
    }

    /// A row's text with each mention led by its site's mark: one `Text`, so the line still wraps and selects.
    func testAMentionIsLedByItsSitesMark() {
        let mention = WikiInline.attributed("See [A](https://a.example.com/x) and [B](https://b.example.com/y).")
        var asked: [String] = []
        _ = WikiInline.composed(WikiInline.themed(mention, font: CicadaTheme.bodyFont)) { url in
            asked.append(url)
            return Text(verbatim: "•")
        }
        XCTAssertEqual(asked, ["https://a.example.com/x", "https://b.example.com/y"])
        let themed = WikiInline.themed(mention)
        let site = themed.runs.first { $0[WikiInline.SitePart.self] != nil }
        XCTAssertNil(site?.underlineStyle, "a mention's site is not underlined; its title is")
        XCTAssertNotNil(themed.runs.first { $0[WikiInline.MentionTitle.self] != nil }?.underlineStyle)
        let icon = MentionIcon.rounded(NSImage(size: NSSize(width: 64, height: 64)))
        XCTAssertEqual(icon.size.width, CicadaTheme.scaled(MentionIcon.side))
    }

    /// Owner 2026-10-26: a plain link alone on its line — a `## Links` bullet (Sleep's own shape, `- [T](url) — note`),
    /// any other bullet, or a paragraph — draws as a bookmark card; two links on a bullet stay mentions; a link in a
    /// sentence is a mention; a bare URL stays its address. Nothing is written to the page.
    func testAPlainLinkAloneOnItsLineIsACardAndInASentenceAMention() {
        let markdown = """
        ## Article
        ### Pricing
        The team wrote it up in [the write-up](https://blog.example.com/seats).

        [Roadmap](https://alpha.example.org/roadmap)

        ## Links
        - [How we priced seats](https://blog.example.com/seats) — the write-up
        - [Docs](https://docs.example.com/a) and [the blog](https://blog.example.com/b)
        - https://bare.example.com/page
        """
        let rows = WikiArticle.build(markdown).rows
        let prose = rows.first { $0.kind == .paragraph }!
        XCTAssertEqual(String(prose.text.characters), "The team wrote it up in blog.example.com the write-up.")
        let cards = rows.compactMap { row -> (LinkRef, String?)? in
            if case .link(let ref, let note) = row.kind { return (ref, note) }
            return nil
        }
        XCTAssertEqual(cards.map(\.0.url), ["https://alpha.example.org/roadmap", "https://blog.example.com/seats"])
        XCTAssertEqual(cards.map(\.1), [nil, "the write-up"])
        for (ref, _) in cards {
            XCTAssertEqual(ref.asked, .link, "the page's token is untouched: no view word is written")
            XCTAssertEqual(LinkCardModel.current(ref), .bookmark)
            XCTAssertEqual(LinkCardModel.offered(ref, fact: .unknown(ref.url)), [.mention, .bookmark, .url])
        }
        let items = rows.filter { if case .item = $0.kind { return true }; return false }
        XCTAssertEqual(items.count, 2, "two links on a bullet and a bare URL stay lines")
        XCTAssertEqual(LinkCardModel.current(items[0].links[0]), .mention)
        XCTAssertEqual(items[1].links.first?.asked, .raw)
    }

    func testABlockViewAloneOnItsLineIsARowOfItsOwnWithItsNote() {
        let markdown = """
        [How we priced seats](https://blog.example.com/seats "bookmark")

        ## Links
        - [Getting started](https://docs.example.com/start "screenshot 2026-10-14") — the setup guide we followed
        - [Roadmap](https://alpha.example.org/roadmap "look") and more words, so a mention
        - [Seats](https://blog.example.com/seats "mention")
        - [Seats](https://blog.example.com/seats "url") — chosen plain
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
        guard case .item = rows[4].kind, case .item = rows[5].kind else {
            return XCTFail("a chosen Mention or URL stays a line, even alone: \(rows[4].kind), \(rows[5].kind)")
        }
        XCTAssertEqual(LinkCardModel.current(rows[4].links[0]), .mention)
        XCTAssertEqual(LinkCardModel.current(rows[5].links[0]), .url)
    }

    /// Embed is offered only for what can be embedded — a video with a provider's own player, a PDF — and only alone on
    /// its line; it draws the player URL `VideoRef` derives, never the link itself, and nothing else ever embeds.
    func testEmbedIsOfferedOnlyForAVideoOrAPDFAndNeverByDefault() throws {
        let video = LinkGrammar.links(in: "[A talk](https://www.youtube.com/watch?v=dQw4w9WgXcQ)")[0]
        let pdf = LinkGrammar.links(in: "- [The paper](https://papers.example.org/seats.PDF) — read it")[0]
        let arxiv = LinkGrammar.links(in: "[Paper](https://arxiv.org/pdf/2608.27454)")[0]
        let site = LinkGrammar.links(in: "[Seats](https://blog.example.com/seats)")[0]
        let inSentence = LinkGrammar.links(in: "In [the talk](https://www.youtube.com/watch?v=dQw4w9WgXcQ) she says so.")[0]
        guard case .video(let player) = try XCTUnwrap(LinkEmbed.of(video.url)) else { return XCTFail("not a video") }
        XCTAssertEqual(player, VideoRef.resolve(video.url)?.embedURL, "the provider's own player URL, derived")
        XCTAssertNotEqual(player.absoluteString, video.url)
        XCTAssertEqual(LinkEmbed.of(pdf.url), .pdf)
        XCTAssertEqual(LinkEmbed.of(arxiv.url), .pdf)
        XCTAssertNil(LinkEmbed.of(site.url))
        XCTAssertNil(LinkEmbed.of("https://example.com/notes?file=a.pdf"), "a query is not a path")
        XCTAssertEqual(LinkCardModel.offered(video, fact: .unknown(video.url)), [.mention, .bookmark, .embed, .url])
        XCTAssertEqual(LinkCardModel.offered(pdf, fact: .unknown(pdf.url)), [.mention, .bookmark, .embed, .url])
        XCTAssertEqual(LinkCardModel.offered(site, fact: .unknown(site.url)), [.mention, .bookmark, .url])
        XCTAssertEqual(LinkCardModel.offered(inSentence, fact: .unknown(inSentence.url)), [.mention, .url])
        for ref in [video, pdf, arxiv, site, inSentence] {
            XCTAssertNotEqual(LinkCardModel.current(ref), .embed, "never an embed by default: \(ref.markdown)")
        }
        XCTAssertEqual(Copy.Links.menuName(.embed, url: video.url), "Embed video")
        XCTAssertEqual(Copy.Links.menuName(.embed, url: pdf.url), "Embed")
        // An `embed` word on a page that has nothing to embed is research-hub's screenshot.
        let old = LinkGrammar.links(in: #"[Seats](https://blog.example.com/seats "embed")"#)[0]
        XCTAssertEqual(LinkCardModel.current(old), .screenshot)
        let chosen = LinkGrammar.links(in: #"[A talk](https://www.youtube.com/watch?v=dQw4w9WgXcQ "embed")"#)[0]
        XCTAssertEqual(LinkCardModel.current(chosen), .embed)
        guard case .link = WikiArticle.build(chosen.markdown).rows[0].kind else { return XCTFail("an embed is a block") }
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

    func testTheMenuOffersAViewOnlyWhereCicadaHasSomethingForIt() {
        let alone = LinkGrammar.links(in: "[Seats](https://blog.example.com/seats)")[0]
        let inSentence = LinkGrammar.links(in: "Read [Seats](https://blog.example.com/seats) now")[0]
        let bare = LinkFact(url: seats)
        XCTAssertEqual(LinkCardModel.offered(alone, fact: bare), [.mention, .bookmark, .url])
        XCTAssertEqual(LinkCardModel.offered(inSentence, fact: bare), [.mention, .url])
        // A bare URL or an autolink is the page's own words: never offered a switch (review B1).
        for raw in LinkGrammar.links(in: "See https://x.example.com/a and <https://x.example.com/b>.") {
            XCTAssertEqual(LinkCardModel.offered(raw, fact: bare), [], raw.markdown)
        }
        let withLook = LinkFact(url: seats, looks: [LinkFact.Look(id: "2026-10-14-a", day: "2026-10-14", image: "/d", palette: [])])
        XCTAssertEqual(LinkCardModel.offered(alone, fact: withLook), [.mention, .bookmark, .url, .screenshot, .look])
        // The view a link draws as is always offered, so the menu can check it — a screenshot with no picture yet too.
        let asked = LinkGrammar.links(in: #"[Seats](https://blog.example.com/seats "screenshot")"#)[0]
        XCTAssertEqual(LinkCardModel.offered(asked, fact: bare), [.mention, .bookmark, .url, .screenshot])
        XCTAssertEqual(LinkCardModel.current(asked), .screenshot)
    }

    /// A choice is the same link with its view word — always written, so a later change of the context's default
    /// never undoes it — and round-trips through the grammar to the view chosen; choosing what is already written
    /// writes nothing.
    func testAChoiceIsTheSameLinkWithItsViewWordAndRoundTrips() {
        let ref = LinkGrammar.links(in: "- [Seats](https://blog.example.com/seats) — the write-up")[0]
        XCTAssertEqual(LinkCardModel.token(ref, choosing: .bookmark), #"[Seats](https://blog.example.com/seats "bookmark")"#)
        XCTAssertEqual(LinkCardModel.token(ref, choosing: .url), #"[Seats](https://blog.example.com/seats "url")"#)
        XCTAssertEqual(ref.markdown, "[Seats](https://blog.example.com/seats)")
        for view in LinkViewKind.switcher {
            guard let token = LinkCardModel.token(ref, choosing: view) else { return XCTFail("\(view) wrote nothing") }
            let back = LinkGrammar.links(in: "- \(token) — the write-up")[0]
            XCTAssertEqual(back.asked, view, token)
            XCTAssertEqual(back.url, ref.url)
            XCTAssertEqual(LinkGrammar.plain(token), ref.markdown, "a quote never shows the view word")
            XCTAssertNil(LinkCardModel.token(back, choosing: view), "choosing it again writes nothing")
        }
        XCTAssertEqual(Copy.Links.reason(.bookmark), "Shown as a bookmark.")
        XCTAssertEqual(Copy.Links.reason(.url), "Shown as a plain link.")
        XCTAssertEqual(Copy.Links.savedAs(.embed), "Saved · shown as an embed")
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

    /// A bank switch empties the cache (`reset()`); an answer for the old bank that lands after it — a response already
    /// on its way when the task was cancelled — is dropped, never painted under the new bank's page of the same id.
    @MainActor
    func testAnAnswerLandingAfterABankSwitchIsDropped() async throws {
        actor Gate {
            private var waiting: CheckedContinuation<Void, Never>?
            var isWaiting: Bool { waiting != nil }
            func wait() async { await withCheckedContinuation { waiting = $0 } }
            func open() { waiting?.resume(); waiting = nil }
        }
        let gate = Gate()
        let page = PageLinkFacts(entityId: "alpha-project", links: [LinkFact(url: seats, title: "Seats")])
        let cache = LinkFactsCache(fetch: { _, _ in
            await gate.wait()   // ignores cancellation, like a response already received
            return Conditional(value: page, etag: "\"v1\"", notModified: false)
        })
        let first = Task { await cache.refresh("alpha-project") }
        let deadline = ContinuousClock.now + .seconds(3)
        while !(await gate.isWaiting) {
            guard ContinuousClock.now < deadline else { return XCTFail("the fetch never started") }
            try await Task.sleep(for: .milliseconds(10))
        }
        cache.reset()   // the bank switch
        await gate.open()
        await first.value
        XCTAssertNil(cache.fact(seats, on: "alpha-project").title, "the old bank's answer is not this bank's")
    }
}
