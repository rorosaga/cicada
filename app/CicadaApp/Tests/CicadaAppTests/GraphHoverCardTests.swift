import XCTest
@testable import CicadaApp

/// ROR-135 — the graph's hover card: what it says for each kind of page, when it opens, where it sits, and that it is
/// instant at the owner's scale (the numbers print; the bounds are loose on purpose).
@MainActor
final class GraphHoverCardTests: XCTestCase {
    private func node(_ id: String, _ type: EntityType, name: String? = nil, summary: String? = nil, byline: String? = nil,
                      isHub: Bool = false, memberCount: Int = 0, isFacet: Bool = false) -> GraphNode {
        GraphNode(id: id, name: name ?? id, type: type, isHub: isHub, memberCount: memberCount, isFacet: isFacet,
                  summary: summary, byline: byline)
    }

    func testABookNamesItsAuthorAPersonOnlyTheirName() {
        let book = GraphHoverCardContent.make(node("dune", .media, name: "Dune", summary: "A novel.", byline: "Author One, Author Two"))
        XCTAssertEqual(book, .init(title: "Dune", line: "Author One, Author Two"), "the byline, not the summary")
        let person = GraphHoverCardContent.make(node("bob-example", .person, name: "Bob Example", summary: "Runs the lab."))
        XCTAssertEqual(person, .init(title: "Bob Example", line: nil), "a person: picture and name")
    }

    func testAnythingElseGetsItsFirstSentenceAsOneShortLine() {
        let company = GraphHoverCardContent.make(node("acme", .company, name: "Acme", summary: "A client of the lab. It signed in May."))
        XCTAssertEqual(company?.line, "A client of the lab")
        XCTAssertNil(GraphHoverCardContent.make(node("x", .concept))?.line, "no summary, no line")
        let long = String(repeating: "word ", count: 60)
        let cut = GraphHoverCardContent.firstSentence(long)
        XCTAssertNotNil(cut)
        XCTAssertLessThanOrEqual(cut!.count, GraphHoverCardContent.lineLimit + 1)
        XCTAssertTrue(cut!.hasSuffix("…"))
        XCTAssertEqual(GraphHoverCardContent.firstSentence("Version 2.0 is out"), "Version 2.0 is out", "a dot inside a number ends nothing")
    }

    func testAHubSaysHowManyPagesAndAFacetHasNoCard() {
        XCTAssertEqual(GraphHoverCardContent.make(node("h", .concept, isHub: true, memberCount: 12))?.line, "12 pages")
        XCTAssertEqual(GraphHoverCardContent.make(node("h", .concept, isHub: true, memberCount: 1))?.line, "1 page")
        XCTAssertNil(GraphHoverCardContent.make(node("alpha#engineering", .concept, isFacet: true)), "a facet is a view, not a page")
    }

    func testACardOpensAtOnceOnlyWhileOneIsUpOrJustClosed() {
        XCTAssertFalse(GraphHoverModel.opensAtOnce(cardUp: false, closedAgo: nil))
        XCTAssertTrue(GraphHoverModel.opensAtOnce(cardUp: true, closedAgo: nil))
        XCTAssertTrue(GraphHoverModel.opensAtOnce(cardUp: false, closedAgo: CicadaMotion.hoverCardWarmWindow / 2))
        XCTAssertFalse(GraphHoverModel.opensAtOnce(cardUp: false, closedAgo: CicadaMotion.hoverCardWarmWindow * 2))
        XCTAssertLessThan(CicadaMotion.hoverCardOpenDelay, CicadaMotion.linkPreviewOpenDelay, "the graph's card is the quicker one")
    }

    func testTheModelWaitsThenOpensThenSwapsAtOnce() async throws {
        let model = GraphHoverModel()
        model.hover(.init(id: "a", x: 10, y: 10, r: 5))
        XCTAssertNil(model.shown, "a pointer that has only just arrived opens nothing")
        try await Task.sleep(for: .seconds(CicadaMotion.hoverCardOpenDelay + 0.1))
        XCTAssertEqual(model.shown?.id, "a")
        model.hover(.init(id: "b", x: 40, y: 10, r: 5))
        XCTAssertEqual(model.shown?.id, "b", "with a card up the next opens at once")
        model.end()
        XCTAssertNil(model.shown)
        model.hover(.init(id: "c", x: 40, y: 10, r: 5))
        XCTAssertEqual(model.shown?.id, "c", "and within the warm window after it closes")
        model.end()
        // a pointer that sweeps on before the delay opens nothing
        let sweep = GraphHoverModel()
        sweep.hover(.init(id: "a", x: 1, y: 1, r: 5))
        sweep.end()
        try await Task.sleep(for: .seconds(CicadaMotion.hoverCardOpenDelay + 0.1))
        XCTAssertNil(sweep.shown)
    }

    func testTheCardSitsBesideTheNodeAndStaysOnTheCanvas() {
        let size = CGSize(width: 300, height: 70), box = CGSize(width: 800, height: 600)
        let right = GraphHoverPlacement.origin(anchor: CGPoint(x: 100, y: 300), radius: 6, size: size, container: box)
        XCTAssertEqual(right.x, 116); XCTAssertEqual(right.y, 265)
        let flipped = GraphHoverPlacement.origin(anchor: CGPoint(x: 700, y: 300), radius: 6, size: size, container: box)
        XCTAssertEqual(flipped.x, 700 - 6 - 10 - 300, "no room on the right: the left")
        let top = GraphHoverPlacement.origin(anchor: CGPoint(x: 100, y: 4), radius: 6, size: size, container: box)
        XCTAssertEqual(top.y, 8)
        let bottom = GraphHoverPlacement.origin(anchor: CGPoint(x: 100, y: 598), radius: 6, size: size, container: box)
        XCTAssertEqual(bottom.y, 600 - 8 - 70)
    }

    func testAPictureAlreadySeenIsOnTheFirstFrameAndAThirdPartysIsNeverFetched() async {
        let picture = EntityPictureRef(url: "/entities/hover-test/picture?v=abc123", source: .upload)
        let bank = "hover-test-bank"
        XCTAssertNil(PictureMemory.cached(id: "hover-test", picture: picture, bank: bank))
        let url = PictureURL.parse(picture.url)!
        ImageMemory.pictures.set("\(bank)|\(url.cacheKey)", NSImage(size: NSSize(width: 4, height: 4)))
        XCTAssertNotNil(PictureMemory.cached(id: "hover-test", picture: picture, bank: bank), "memory answers without an await")
        let external = EntityPictureRef(url: "https://img.example.com/never-fetched.jpg", source: .thumbnail)
        let none = await HoverPictures.image(id: "x", picture: external, bank: bank)
        XCTAssertNil(none, "a provider's thumbnail not already here is not fetched by a hover")
    }

    /// The owner's scale: 9,000 pages. Everything a hover reads is a dictionary lookup and a small string; print it.
    func testAHoverCostsAMicrosecondsAtNineThousandPages() {
        let nodes = (0..<9000).map { i in
            node("p\(i)", i % 7 == 0 ? .person : .company, name: "Page \(i)", summary: "Page \(i) is a thing. It has a second sentence.")
        }
        let index = Dictionary(nodes.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        var samples: [Double] = []
        for i in stride(from: 0, to: 9000, by: 3) {
            let t0 = DispatchTime.now().uptimeNanoseconds
            let content = GraphHoverCardContent.make(index["p\(i)"]!)
            samples.append(Double(DispatchTime.now().uptimeNanoseconds - t0) / 1000)
            XCTAssertNotNil(content)
        }
        samples.sort()
        let p95 = samples[Int(Double(samples.count) * 0.95)]
        print("hover card: content for a hovered page at 9,000 pages p50 \(samples[samples.count / 2]) µs, p95 \(p95) µs")
        XCTAssertLessThan(p95, 2_000, "under 2 ms even on a loaded machine")
    }
}
