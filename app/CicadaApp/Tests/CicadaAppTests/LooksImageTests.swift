import AppKit
import XCTest
@testable import CicadaApp

/// Looks v2 (2026-10-15) — a saved look's screenshot reaches the tile. The board showed a soft gradient where every
/// picture should be: `StoredPreview` accepted `/design/<id>/image`, but the bytes loader behind it
/// (`APIClient.fetchPictureBytes`) only took `/entities/…`, answered nil, and `PictureStore` remembered the miss — so the
/// palette placeholder was never replaced. These tests hold the two gates together and load a screenshot end to end
/// through the real loader against a fake transport.
final class LooksImageTests: XCTestCase {
    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    private static func png(width: Int = 48, height: Int = 30) -> Data {
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height, bitsPerSample: 8,
                                   samplesPerPixel: 3, hasAlpha: false, isPlanar: false, colorSpaceName: .deviceRGB,
                                   bytesPerRow: 0, bitsPerPixel: 0)!
        for x in 0..<width {
            for y in 0..<height { rep.setColor(NSColor(red: 0.07, green: 0.26, blue: 1, alpha: 1), atX: x, y: y) }
        }
        return rep.representation(using: .png, properties: [:])!
    }

    func testEveryPathTheTileWillLoadIsOneTheLoaderFetches() {
        let paths = ["/design/2026-10-15-example-com/image?v=abc123def456", "/entities/a-link/preview?v=5c0ffee12345",
                     "/entities/a-paper/picture?v=5c0ffee12345", "/explore/captures/a-link/cap-1/thumb",
                     "https://cdn.example.com/a.png", "/design/../entities/x", "/sources", ""]
        for path in paths {
            XCTAssertEqual(StoredPreviewPath.loads(path), APIClient.isPicturePath(path),
                           "the tile's gate and the loader's gate disagree on \(path)")
        }
        XCTAssertTrue(APIClient.isPicturePath("/design/2026-10-15-example-com/image?v=abc123def456"))
        XCTAssertFalse(APIClient.isPicturePath("https://cdn.example.com/a.png"), "never another host")
    }

    func testAReferenceWithAnImageLoadsTheImageNotThePlaceholder() async throws {
        let board = try JSONDecoder().decode(DesignBoard.self, from: Data(LooksTests.boardJSON.utf8))
        let path = try XCTUnwrap(board.refs[0].image?.url)
        let bytes = Self.png()
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/design/2026-10-13-dashboard-example-com/image")
            XCTAssertEqual(request.url?.query, "v=abc123def456")
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil,
                                           headerFields: ["Content-Type": "image/png"])!
            return (response, bytes)
        }
        let client = APIClient(session: MockURLProtocol.makeSession())
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("looks-image-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let pictures = PictureStore(root: root, fetch: { url in
            guard case .api(let p) = url else { return nil }
            return try await client.fetchPictureBytes(path: p)
        })
        let url = try XCTUnwrap(StoredPreviewPath.url(path), "the tile asks for the screenshot")
        let image = await pictures.image(url, bank: "looks-test")
        XCTAssertNotNil(image, "the screenshot loads, so the palette placeholder is replaced")
        XCTAssertEqual(image.map { Int($0.size.width) }, 48)
    }
}
