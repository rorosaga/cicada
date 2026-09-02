import AppKit
import XCTest
@testable import CicadaApp

/// G107: the renderer draws palette colour (not a template) with hard pixel
/// edges, and caches one image per (state, frame, count, stage, size) so a
/// timer tick never re-rasterizes.
@MainActor
final class BookwormRendererTests: XCTestCase {

    /// Draw the image into a bitmap and read one sprite cell's RAW RGBA
    /// bytes. `getPixel`, not `colorAt(…).usingColorSpace(.sRGB)`: the TIFF
    /// rep is tagged calibrated-RGB, and converting that back to sRGB shifts
    /// every component by ~15% (measured 0x6F → 127) although the bytes are
    /// exact. The bitmap may come back at 1× or 2× depending on the host;
    /// sample the centre of the cell at whatever scale we got. Rows are
    /// top-down (verified: row 7 col 8 reads the pupil, row 16 col 8 body).
    private func cell(_ image: NSImage, col: Int, row: Int) throws -> [Int] {
        let rep = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation)))
        XCTAssertEqual(rep.bitsPerSample, 8)
        XCTAssertEqual(rep.samplesPerPixel, 4, "RGBA — the sprite has transparent cells")
        let scale = rep.pixelsWide / BookwormSprites.size
        XCTAssertGreaterThanOrEqual(scale, 1)
        var px = [Int](repeating: 0, count: rep.samplesPerPixel)
        rep.getPixel(&px, atX: col * scale + scale / 2, y: row * scale + scale / 2)
        return px
    }

    private func assertColor(_ px: [Int], hex: UInt32, _ what: String) {
        XCTAssertEqual(px[0], Int((hex >> 16) & 0xFF), accuracy: 3, what)
        XCTAssertEqual(px[1], Int((hex >> 8) & 0xFF), accuracy: 3, what)
        XCTAssertEqual(px[2], Int(hex & 0xFF), accuracy: 3, what)
        XCTAssertEqual(px[3], 255, what)
    }

    func testImageIsColourNotTemplateAtTheRequestedSize() {
        let img = BookwormRenderer.image(grid: BookwormSprites.awakeBase, pointSize: 96)
        XCTAssertFalse(img.isTemplate)
        XCTAssertEqual(img.size, NSSize(width: 96, height: 96))
    }

    func testPixelsCarryPaletteColours() throws {
        let img = BookwormRenderer.image(grid: BookwormSprites.awakeBase, pointSize: 24)
        assertColor(try cell(img, col: 10, row: 10), hex: 0x6FCF6A, "body")
        assertColor(try cell(img, col: 7, row: 6), hex: 0xFFFFFF, "lens white")
        assertColor(try cell(img, col: 8, row: 7), hex: 0x2B2140, "pupil = outline")
        assertColor(try cell(img, col: 7, row: 10), hex: 0xF28BAE, "blush")
        XCTAssertEqual(try cell(img, col: 0, row: 0)[3], 0, "corner is transparent")
        XCTAssertEqual(try cell(img, col: 23, row: 23)[3], 0)
    }

    func testCacheKeyDistinguishesCountStageFrameAndSize() {
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .awake, frameIndex: 0, pointSize: 18), "awake|0|18")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .curious(count: 47), frameIndex: 2, pointSize: 96), "curious|47|2|96")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .curious(count: 250), frameIndex: 0, pointSize: 18), "curious|99|0|18")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .sleeping(stage: 3), frameIndex: 1, pointSize: 18), "sleeping|3|1|18")
        XCTAssertNotEqual(BookwormRenderer.cacheKey(state: .curious(count: 3), frameIndex: 0, pointSize: 18),
                          BookwormRenderer.cacheKey(state: .curious(count: 4), frameIndex: 0, pointSize: 18))
    }

    func testCachedImageReturnsTheSameObjectForTheSameKey() {
        let a = BookwormRenderer.cachedImage(state: .hungry, frameIndex: 1, pointSize: 96)
        let b = BookwormRenderer.cachedImage(state: .hungry, frameIndex: 1, pointSize: 96)
        XCTAssertTrue(a === b)
        XCTAssertFalse(a === BookwormRenderer.cachedImage(state: .hungry, frameIndex: 2, pointSize: 96))
    }

    func testCachedImageWrapsFrameIndex() {
        let count = BookwormSprites.frames(for: .awake).frames.count
        XCTAssertTrue(BookwormRenderer.cachedImage(state: .awake, frameIndex: 0, pointSize: 48)
                      === BookwormRenderer.cachedImage(state: .awake, frameIndex: count, pointSize: 48))
    }
}
