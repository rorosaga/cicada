import XCTest
@testable import CicadaApp

/// Review r1 — a page whose claims fence `/entities` withholds (`rawOmitted`, F4).
final class RawFileTests: XCTestCase {
    private func page(raw: String, omitted: Bool, type: String = "project") throws -> Entity {
        let object: [String: Any] = ["id": "alpha-location", "name": "Alpha Location", "type": type, "status": "active",
                                     "confidence": 1, "created": "2024-01-01", "lastReferenced": "2024-01-01",
                                     "decayRate": 0, "markdownContent": "## Summary\nAlpha.", "rawMarkdown": raw,
                                     "rawOmitted": omitted]
        return try JSONDecoder().decode(Entity.self, from: JSONSerialization.data(withJSONObject: object))
    }

    /// #5: a failed `/raw` read is a failure — nothing cached, nothing to copy — and the next attempt asks again.
    @MainActor
    func testAFailedReadIsNeverTheFileAndIsRetried() async throws {
        let entity = try page(raw: "---\nname: Alpha\n---\n## Summary\nAlpha.\n\n", omitted: true)
        let loader = RawFileLoader()
        await loader.load(entity.id) { _ in throw URLError(.networkConnectionLost) }
        XCTAssertNil(loader.text)
        XCTAssertTrue(loader.failed)
        XCTAssertNil(RawFile.verbatim(entity, fetched: loader.text), "Copy has nothing to copy, not a reconstruction")
        let whole = "---\nname: Alpha\nowner: true\n---\n## Summary\nAlpha.\n\n```claims\n- id: a\n```\n"
        await loader.load(entity.id) { _ in whole }
        XCTAssertFalse(loader.failed)
        XCTAssertEqual(RawFile.verbatim(entity, fetched: loader.text), whole)
    }

    /// An inline file is the file; a withheld one's head is never mistaken for the whole file.
    func testOnlyAWholeFileIsVerbatim() throws {
        let small = try page(raw: "---\nname: Alpha\n---\nAlpha.\n", omitted: false)
        XCTAssertEqual(RawFile.verbatim(small, fetched: nil), small.rawMarkdown)
        let head = try page(raw: "---\nname: Alpha\n---\nAlpha.\n", omitted: true)
        XCTAssertNil(RawFile.verbatim(head, fetched: nil))
        XCTAssertFalse(head.isStub)
    }

    /// #4: a large location page keeps its declared coordinates — the withheld payload still carries the frontmatter.
    func testALargeLocationKeepsItsDeclaredCoordinates() throws {
        let entity = try page(raw: "---\nname: Alpha Location\ntype: location\nlat: 10.0\nlon: 20.0\n---\n## Summary\nA place.\n\n",
                              omitted: true, type: "location")
        let coordinate = try XCTUnwrap(LocationHero.declaredCoordinate(from: entity.rawMarkdown))
        XCTAssertEqual(coordinate.latitude, 10.0)
        XCTAssertEqual(coordinate.longitude, 20.0)
    }
}
