import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import CicadaApp

/// C11 / R-PE2 — a picture is made small on this Mac before it leaves: ≤ 512 px, EXIF orientation applied, JPEG when
/// opaque and PNG when it has alpha; the hash is the server's own.
final class PictureImportTests: XCTestCase {
    private func image(width: Int, height: Int, alpha: Bool) throws -> CGImage {
        let info = alpha ? CGImageAlphaInfo.premultipliedLast.rawValue : CGImageAlphaInfo.noneSkipLast.rawValue
        let space = try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB))
        let ctx = try XCTUnwrap(CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                                          space: space, bitmapInfo: info))
        ctx.setFillColor(CGColor(red: 0.2, green: 0.5, blue: 0.8, alpha: alpha ? 0.5 : 1))
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        return try XCTUnwrap(ctx.makeImage())
    }

    private func encoded(_ image: CGImage, as type: UTType, orientation: Int? = nil) throws -> Data {
        let out = NSMutableData()
        let dest = try XCTUnwrap(CGImageDestinationCreateWithData(out, type.identifier as CFString, 1, nil))
        let props: [CFString: Any] = orientation.map { [kCGImagePropertyOrientation: $0] } ?? [:]
        CGImageDestinationAddImage(dest, image, props as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(dest))
        return out as Data
    }

    func testAnOpaquePhotoShrinksTo512AsAJPEG() throws {
        let p = try PictureImport.prepare(data: encoded(image(width: 2000, height: 1000, alpha: false), as: .png))
        XCTAssertEqual(p.ext, "jpg")
        XCTAssertEqual(p.width, 512)
        XCTAssertEqual(p.height, 256)
        XCTAssertLessThanOrEqual(p.data.count, PictureImport.maxBytes)
        XCTAssertEqual(Array(p.data.prefix(3)), [0xFF, 0xD8, 0xFF], "the server sniffs JPEG by these bytes")
    }

    func testATransparentLogoStaysAPNGAndIsNeverUpscaled() throws {
        let p = try PictureImport.prepare(data: encoded(image(width: 300, height: 300, alpha: true), as: .png))
        XCTAssertEqual(p.ext, "png")
        XCTAssertEqual(p.width, 300)
        XCTAssertEqual(Array(p.data.prefix(8)), [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
    }

    func testTheCameraOrientationIsAppliedBeforeTheBytesLeave() throws {
        let p = try PictureImport.prepare(data: encoded(image(width: 800, height: 400, alpha: false), as: .jpeg,
                                                        orientation: 6))
        XCTAssertEqual(p.width, 256)
        XCTAssertEqual(p.height, 512)
    }

    func testWhatIsNotAPictureIsRefusedInWords() throws {
        XCTAssertThrowsError(try PictureImport.prepare(data: Data("not a picture".utf8))) {
            XCTAssertEqual($0 as? PictureImport.Failure, .unreadable)
        }
        XCTAssertThrowsError(try PictureImport.prepare(data: encoded(image(width: 8, height: 8, alpha: false), as: .png))) {
            XCTAssertEqual($0 as? PictureImport.Failure, .tooSmall)
        }
        for failure in [PictureImport.Failure.unreadable, .tooSmall, .tooLarge] {
            XCTAssertTrue(Copy.People.importFailed(failure).hasSuffix("."))
        }
    }

    func testTheHashIsTheServersOwn() {
        XCTAssertEqual(PreparedPicture(data: Data("abc".utf8), ext: "png", width: 1, height: 1).sha, "ba7816bf8f01",
                       "entity_picture.sha12(b'abc')")
    }
}
