import XCTest
@testable import CicadaApp

/// Vision item 5 (2026-10-28) — `GET /entities/{id}`'s `blocks` decode from the backend's own
/// `api/tests/fixtures/page_blocks.json` (`test_page_blocks.py` builds the same file), the card's "why it matters"
/// line, and the card's ETag mapping (`EntityCardCache`).
final class PageBlocksTests: XCTestCase {
    private static func fixtureData() throws -> Data {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/page_blocks.json")
        let object = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as? [String: Any]
        return try JSONSerialization.data(withJSONObject: object?["blocks"] ?? [:])
    }

    func testTheBackendsBlocksDecodeWhole() throws {
        let b = try JSONDecoder().decode(PageBlocks.self, from: Self.fixtureData())
        XCTAssertEqual(b.order, ["relevance", "sources", "coordinates", "looks", "ongoing", "history"])
        XCTAssertEqual(b.relevance?.tense, "is")
        XCTAssertEqual(b.coordinates?.lat, 40.4168)
        XCTAssertEqual(b.coordinates?.label, "Alpha Place")
        XCTAssertEqual(b.ongoing.map(\.claimId), ["c-planned", "c-ongoing"])
        XCTAssertEqual(b.ongoingTotal, 2)
        XCTAssertEqual(b.looks.first?.palette, ["#112233", "#F4F1EA"])
        XCTAssertEqual(b.sources?.total, 4)
        XCTAssertEqual(Set(b.sources?.items?.map(\.state) ?? []), ["unchecked", "proposed", "checked", "stale"])
        XCTAssertEqual(b.history?.bySleep, 2)
        XCTAssertEqual(b.history?.contributors?.first?.author, "claude-haiku-4-5")
    }

    func testAMissingOrUnknownBlockNeverFailsTheCard() throws {
        let json = #"{"shape":"blocks-9","order":["relevance","weather"],"weather":{"x":1},"coordinates":{"lat":"no"}}"#
        let b = try JSONDecoder().decode(PageBlocks.self, from: Data(json.utf8))
        XCTAssertEqual(b.order, ["relevance", "weather"])
        XCTAssertNil(b.coordinates)
        XCTAssertTrue(b.looks.isEmpty)
    }

    func testTheEntityCarriesRelevanceAndBlocksAndAnOlderBackendDecodes() throws {
        let base = #""id":"alpha","name":"Alpha","type":"location","status":"active","confidence":0.8,"created":"2026-09-01","lastReferenced":"2026-10-20","decayRate":0.01,"version":1,"markdownContent":"x","history":[{"date":"2026-10-20","changeType":"updated","description":"d","author":"user","commitHash":"abc","sessions":[],"trigger":"sleep/extraction","via":"sleep"}]"#
        let blocks = String(data: try Self.fixtureData(), encoding: .utf8) ?? "{}"
        let now = try JSONDecoder().decode(Entity.self, from: Data(
            ("{" + base + #","relevance":{"tense":"was","line":"Why it mattered to you: x."},"blocks":"# + blocks + "}").utf8))
        XCTAssertEqual(now.relevance?.shownLine, "Why it mattered to you: x.")
        XCTAssertEqual(now.blocks?.coordinates?.lon, -3.7038)
        XCTAssertEqual(now.history.first?.via, "sleep")
        XCTAssertEqual(now.history.first?.trigger, "sleep/extraction")
        let older = try JSONDecoder().decode(Entity.self, from: Data(("{" + base.replacingOccurrences(
            of: #","trigger":"sleep/extraction","via":"sleep""#, with: "") + "}").utf8))
        XCTAssertNil(older.relevance)
        XCTAssertNil(older.blocks)
        XCTAssertEqual(older.history.first?.via, "unknown")
    }

    func testTheOwnersOwnPageShowsNoRelevanceLine() {
        XCTAssertNil(EntityRelevance(tense: "self", line: "This is you.").shownLine)
        XCTAssertNil(EntityRelevance(tense: "is", line: "  ").shownLine)
        XCTAssertEqual(EntityRelevance(tense: "none", line: "No personal relation on the record.").shownLine,
                       "No personal relation on the record.")
    }

    // MARK: EntityCardCache — the ETag's client mapping

    private func entity(_ name: String) -> Entity {
        Entity(id: "alpha", name: name, type: .concept, status: .active, confidence: 0.5, created: "", lastReferenced: "",
               decayRate: 0, sourceEpisodes: [], tags: [], related: [], version: 1, markdownContent: "", history: [])
    }

    func testA304HandsBackTheHeldPageAndAFreshBodyReplacesIt() throws {
        var cache = EntityCardCache()
        XCTAssertNil(cache.held("alpha"))
        let first = try cache.settle("alpha", Conditional(value: entity("One"), etag: "\"e1\"", notModified: false),
                                     held: nil)
        XCTAssertEqual(first.name, "One")
        let held = cache.held("alpha")
        XCTAssertEqual(held?.etag, "\"e1\"")
        let same = try cache.settle("alpha", Conditional(value: nil, etag: "\"e1\"", notModified: true), held: held)
        XCTAssertEqual(same.name, "One")
        let fresh = try cache.settle("alpha", Conditional(value: entity("Two"), etag: "\"e2\"", notModified: false),
                                     held: held)
        XCTAssertEqual(fresh.name, "Two")
        XCTAssertEqual(cache.held("alpha")?.etag, "\"e2\"")
    }

    func testAnAnswerWithNoETagIsNotHeldAndA304WithNothingHeldThrows() {
        var cache = EntityCardCache()
        _ = try? cache.settle("alpha", Conditional(value: entity("One"), etag: nil, notModified: false), held: nil)
        XCTAssertNil(cache.held("alpha"))
        XCTAssertThrowsError(try cache.settle("alpha", Conditional(value: nil, etag: nil, notModified: true), held: nil))
    }

    func testTheCacheIsBounded() throws {
        var cache = EntityCardCache()
        for i in 0..<(EntityCardCache.capacity + 5) {
            _ = try cache.settle("p\(i)", Conditional(value: entity("n"), etag: "\"\(i)\"", notModified: false), held: nil)
        }
        XCTAssertEqual(cache.count, EntityCardCache.capacity)
    }
}
