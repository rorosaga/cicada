import XCTest
@testable import CicadaApp

final class SnapshotCacheTests: XCTestCase {
    struct Thing: Codable, Equatable { let a: Int }
    func testRoundTripAndClear() async {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let cache = SnapshotCache(root: root)
        await cache.save([Thing(a: 1)], etag: "\"e1\"", domain: .inbox, bank: "b")
        await cache.flush()
        let hit = await cache.load(.inbox, bank: "b", as: [Thing].self)
        XCTAssertEqual(hit?.value, [Thing(a: 1)]); XCTAssertEqual(hit?.etag, "\"e1\"")
        let miss = await cache.load(.graph, bank: "b", as: [Thing].self)
        XCTAssertNil(miss)
        await cache.clear(bank: "b")
        let gone = await cache.load(.inbox, bank: "b", as: [Thing].self)
        XCTAssertNil(gone)
    }
    func testSchemaMismatchIsAMiss() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let dir = root.appendingPathComponent("b"); try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try "{\"schema\":0,\"payload\":[]}".write(to: dir.appendingPathComponent("inbox.json"), atomically: true, encoding: .utf8)
        let cache = SnapshotCache(root: root)
        let hit = await cache.load(.inbox, bank: "b", as: [Thing].self)
        XCTAssertNil(hit)
    }

    /// Final review, finding 2 — the reason the envelope version exists,
    /// pinned with the payload that needed it.
    ///
    /// `SourceOverview` decodes a pre-`activity` body happily (`[:]`, by
    /// design — an older backend must still yield a usable card). That
    /// tolerance is what makes the cache dangerous: a hydrate restores the old
    /// body **with its etag**, the next refresh sends `If-None-Match`, the
    /// server answers 304, and the Memory-sources card renders a flat
    /// sparkline and "0 of the last 4 weeks had captures" next to a count line
    /// reading "312 captured" until some unrelated write moves the etag. The
    /// envelope is the only thing that can catch it, so a v1 file — otherwise
    /// perfectly well-formed, etag and all — must be a miss.
    func testAPreActivityEnvelopeIsAMissSoTheSparklineCannotRenderEmptyBesideACount() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let dir = root.appendingPathComponent("b")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let v1 = """
        {"schema":1,"etag":"\\"o\\"","savedAt":800000000,\
        "payload":[{"id":"claude-code","label":"Claude Code","kind":"harness","episodes":312}]}
        """
        try v1.write(to: dir.appendingPathComponent("\(SyncDomain.sourcesOverview.rawValue).json"),
                     atomically: true, encoding: .utf8)
        let cache = SnapshotCache(root: root)

        let hydrated = await cache.load(.sourcesOverview, bank: "b", as: [SourceOverview].self)
        XCTAssertNil(hydrated,
                     "a v1 envelope must not hydrate — it would carry its etag and latch a 304")

        // The payload itself is fine; only the envelope refuses it. That is
        // the point: decode tolerance cannot see the staleness, the version can.
        let bare = try JSONDecoder().decode([SourceOverview].self,
                                            from: Data(#"[{"id":"claude-code","episodes":312}]"#.utf8))
        XCTAssertEqual(bare.first?.episodes, 312)
        XCTAssertTrue(bare.first?.activity.isEmpty ?? false)
    }
}
