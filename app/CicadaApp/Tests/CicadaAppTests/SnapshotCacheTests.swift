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
}
