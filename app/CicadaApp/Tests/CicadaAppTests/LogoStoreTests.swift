import AppKit
import XCTest
@testable import CicadaApp

/// Concurrent callers for the same entity must share one fetch (G59 / MED-3).
/// `LogoStore` is an actor, but it suspends across the network `await`, so a
/// second caller re-enters, misses the memory cache and issues a second `GET`
/// — the inbox row and the detail card for one entity render together, so this
/// is the common case. The in-flight task map is what prevents it.
final class LogoStoreTests: XCTestCase {

    private func pngData() -> Data {
        let image = NSImage(size: NSSize(width: 8, height: 8))
        image.lockFocus()
        NSColor.red.drawSwatch(in: NSRect(x: 0, y: 0, width: 8, height: 8))
        image.unlockFocus()
        guard let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:])
        else { return Data() }
        return png
    }

    private func makeStore(_ counter: Counter, data: Data?) -> LogoStore {
        let root = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("CicadaLogoStoreTests/\(UUID().uuidString)", isDirectory: true)
        return LogoStore(root: root) { id in
            await counter.bump(id)
            try? await Task.sleep(for: .milliseconds(40))  // hold both callers in flight
            return data
        }
    }

    actor Counter {
        private(set) var ids: [String] = []
        func bump(_ id: String) { ids.append(id) }
    }

    func testConcurrentCallersForOneEntityShareASingleFetch() async {
        let counter = Counter()
        let store = makeStore(counter, data: pngData())

        async let a = store.image(entityId: "acme", bank: "work")
        async let b = store.image(entityId: "acme", bank: "work")
        let (first, second) = await (a, b)

        XCTAssertNotNil(first)
        XCTAssertNotNil(second)
        let ids = await counter.ids
        XCTAssertEqual(ids, ["acme"], "the same entity must be fetched once, not \(ids.count) times")
    }

    func testDifferentEntitiesStillFetchIndependently() async {
        let counter = Counter()
        let store = makeStore(counter, data: pngData())

        async let a = store.image(entityId: "acme", bank: "work")
        async let b = store.image(entityId: "widget", bank: "work")
        _ = await (a, b)

        let ids = await counter.ids
        XCTAssertEqual(Set(ids), ["acme", "widget"])
        XCTAssertEqual(ids.count, 2)
    }

    func testASharedMissIsRememberedOnceAndNeverRefetched() async {
        let counter = Counter()
        let store = makeStore(counter, data: nil)  // 404: no logo for this entity

        async let a = store.image(entityId: "concept", bank: "work")
        async let b = store.image(entityId: "concept", bank: "work")
        let (first, second) = await (a, b)
        XCTAssertNil(first)
        XCTAssertNil(second)

        _ = await store.image(entityId: "concept", bank: "work")  // negative cache
        let ids = await counter.ids
        XCTAssertEqual(ids, ["concept"])
    }
}
