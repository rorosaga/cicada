import AppKit
import XCTest
@testable import CicadaApp

/// C11 / R-PE11 — one fetch per URL, then memory, then disk; a prime is never fetched; a bank clears alone.
final class PictureStoreTests: XCTestCase {
    private actor Counter {
        var value = 0
        func bump() { value += 1 }
    }

    private func root() -> URL { FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString) }

    private func png() throws -> Data {
        let rep = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 4, pixelsHigh: 4, bitsPerSample: 8,
                                                 samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
        return try XCTUnwrap(rep.representation(using: .png, properties: [:]))
    }

    private let upload = PictureURL.api(path: "/entities/bob-example/picture?v=3f9a1c0b2d4e")

    func testOneFetchPerURLThenMemoryThenDisk() async throws {
        let counter = Counter()
        let bytes = try png()
        let dir = root()
        let store = PictureStore(root: dir) { _ in await counter.bump(); return bytes }
        async let a = store.image(upload, bank: "work")
        async let b = store.image(upload, bank: "work")
        let (first, second) = await (a, b)
        XCTAssertNotNil(first)
        XCTAssertNotNil(second)
        let fetches = await counter.value
        XCTAssertEqual(fetches, 1)
        let cold = PictureStore(root: dir) { _ in nil }
        let fromDisk = await cold.image(upload, bank: "work")
        XCTAssertNotNil(fromDisk, "a restart reads the disk")
    }

    func testAPrimedUploadIsNeverFetchedAndAMissIsRememberedInMemory() async throws {
        let counter = Counter()
        let store = PictureStore(root: root()) { _ in await counter.bump(); return nil }
        await store.prime(upload, bank: "work", data: try png())
        let primed = await store.image(upload, bank: "work")
        XCTAssertNotNil(primed)
        let missing = PictureURL.api(path: "/entities/alpha-project/picture?v=000000000000")
        _ = await store.image(missing, bank: "work")
        _ = await store.image(missing, bank: "work")
        let fetches = await counter.value
        XCTAssertEqual(fetches, 1, "the prime answered, and the miss was asked once")
    }

    func testClearingOneBankLeavesTheOther() async throws {
        let bytes = try png()
        let store = PictureStore(root: root()) { _ in nil }
        await store.prime(upload, bank: "work", data: bytes)
        await store.prime(upload, bank: "demo", data: bytes)
        await store.clear(bank: "demo")
        let work = await store.image(upload, bank: "work")
        let demo = await store.image(upload, bank: "demo")
        XCTAssertNotNil(work)
        XCTAssertNotNil(demo, "clear forgets memory only; the disk copy answers again (LogoStore.clear's rule)")
    }
}
