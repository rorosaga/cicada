import AppKit
import XCTest
@testable import CicadaApp

/// G125 v3 Task 2: the rasterizer that `BookwormRenderer` used to BE is now
/// grid-size- and palette-agnostic, so the Sleep page's 24×24 desk props and
/// (later) its stage icons can share one code path with the mascot instead of
/// growing a second, subtly different one.
///
/// The four `Bookworm*Tests` files are the other half of this contract: they
/// pass unmodified, which is what proves the facade forwards rather than
/// re-implements. These tests pin the parts only the generalized entry points
/// can express — a grid size that is not 24, a caller-supplied palette, a
/// caller-supplied cache key, and the separate scene cache (P13) that keeps
/// the always-animating worm from being collateral damage of a scene render.
@MainActor
final class PixelRendererTests: XCTestCase {

    /// Copied, not shared, from `BookwormRendererTests.cell(_:col:row:)` — it
    /// is a `private func` on that class, so it cannot be called across files;
    /// the only change is that the grid size is a parameter here.
    ///
    /// `getPixel`, not `colorAt(…).usingColorSpace(.sRGB)`: the TIFF rep is
    /// tagged calibrated-RGB and converting it back to sRGB shifts every
    /// component by ~15% although the bytes are exact. The bitmap may come
    /// back at 1× or 2× depending on the host; sample the centre of the cell
    /// at whatever scale we got.
    private func cell(_ image: NSImage, col: Int, row: Int, gridSize: Int) throws -> [Int] {
        let rep = try XCTUnwrap(NSBitmapImageRep(data: try XCTUnwrap(image.tiffRepresentation)))
        XCTAssertEqual(rep.bitsPerSample, 8)
        XCTAssertEqual(rep.samplesPerPixel, 4, "RGBA — a pixel grid has transparent cells")
        let scale = rep.pixelsWide / gridSize
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

    private static let inkHex: UInt32 = 0x112233
    private static let ink = PixelRenderer.nsColors(["x": inkHex])

    /// A 16×16 grid with a single lit cell at row 3, col 5.
    private static func dotGrid(row: Int = 3, col: Int = 5, size: Int = 16) -> PixelGrid {
        (0..<size).map { r in
            (0..<size).map { c in (r == row && c == col) ? "x" : "." }.joined()
        }
    }

    // MARK: - snappedPointSize

    /// G130 R6 generalized: the snap is onto a multiple of the GRID, so a
    /// 16-cell icon snaps to 16s and the 24-cell worm still snaps to 24s. The
    /// floor is one whole cell, never 0, which a very small `pointSize` would
    /// otherwise round down to.
    func testSnapIsOntoTheGridsOwnMultiple() {
        XCTAssertEqual(PixelRenderer.snappedPointSize(32, gridSize: 16), 32)
        XCTAssertEqual(PixelRenderer.snappedPointSize(40, gridSize: 16), 48)
        XCTAssertEqual(PixelRenderer.snappedPointSize(1, gridSize: 16), 16)
        XCTAssertEqual(PixelRenderer.snappedPointSize(120, gridSize: 24), 120)
        XCTAssertEqual(PixelRenderer.snappedPointSize(132, gridSize: 24), 144)
    }

    /// The facade must not have drifted: the worm's own entry point is the
    /// 24-cell case of the same function.
    func testBookwormSnapIsTheTwentyFourCellCase() {
        for pt in stride(from: CGFloat(1), through: 300, by: 7) {
            XCTAssertEqual(BookwormRenderer.snappedPointSize(pt),
                           PixelRenderer.snappedPointSize(pt, gridSize: BookwormRenderer.gridSize),
                           "pointSize \(pt)")
        }
    }

    // MARK: - image

    func testImageHonoursTheRequestedSizeAndPalette() throws {
        let img = PixelRenderer.image(grid: Self.dotGrid(), gridSize: 16, pointSize: 32, palette: Self.ink)
        XCTAssertFalse(img.isTemplate)
        XCTAssertEqual(img.size, NSSize(width: 32, height: 32))
        assertColor(try cell(img, col: 5, row: 3, gridSize: 16), hex: Self.inkHex, "the lit cell")
        XCTAssertEqual(try cell(img, col: 5, row: 4, gridSize: 16)[3], 0, "'.' stays clear")
        XCTAssertEqual(try cell(img, col: 0, row: 0, gridSize: 16)[3], 0, "corner is transparent")
    }

    /// Grid row 0 is the TOP row. AppKit's origin is bottom-left, so this is
    /// the one thing a generalized `gridSize` can silently get wrong: the
    /// flip is `gridSize - 1 - r`, and a stale `24` there would put a 16-cell
    /// sprite eight cells off the canvas.
    func testRowZeroDrawsAtTheTop() throws {
        let img = PixelRenderer.image(grid: Self.dotGrid(row: 0, col: 0, size: 4),
                                      gridSize: 4, pointSize: 32, palette: Self.ink)
        assertColor(try cell(img, col: 0, row: 0, gridSize: 4), hex: Self.inkHex, "row 0 is the top row")
        XCTAssertEqual(try cell(img, col: 0, row: 3, gridSize: 4)[3], 0, "the bottom row is clear")
    }

    /// A short or ragged grid is padded rather than trapped — the worm's own
    /// renderer has always done this and the scene sprites rely on it while
    /// they are being authored.
    func testShortGridIsPaddedNotTrapped() {
        let img = PixelRenderer.image(grid: ["xx"], gridSize: 4, pointSize: 16, palette: Self.ink)
        XCTAssertEqual(img.size, NSSize(width: 16, height: 16))
    }

    // MARK: - cachedImage

    func testCachedImageIsKeyedByTheCallersKey() {
        let a = PixelRenderer.cachedImage(key: "test.dot|a|32", grid: Self.dotGrid(),
                                          gridSize: 16, pointSize: 32, palette: Self.ink)
        let b = PixelRenderer.cachedImage(key: "test.dot|a|32", grid: Self.dotGrid(),
                                          gridSize: 16, pointSize: 32, palette: Self.ink)
        XCTAssertTrue(a === b, "same key, same object — a repaint is a dictionary hit")
        let c = PixelRenderer.cachedImage(key: "test.dot|b|32", grid: Self.dotGrid(),
                                          gridSize: 16, pointSize: 32, palette: Self.ink)
        XCTAssertFalse(a === c)
    }

    /// P13: the scene cache is its own dictionary. The worm's cache wipes
    /// wholesale past 512 entries, so a page that renders scene layers and
    /// stage icons through a SHARED cache would make the always-animating
    /// mascot re-rasterize on every wipe. 600 scene keys is past that bound
    /// by construction; the worm's frame must survive it.
    func testSceneRendersNeverEvictTheWormsFrames() {
        let worm = BookwormRenderer.cachedImage(state: .happy, frameIndex: 0, pointSize: 264)
        for i in 0..<600 {
            _ = PixelRenderer.cachedImage(key: "test.flood|\(i)|8", grid: Self.dotGrid(size: 4),
                                          gridSize: 4, pointSize: 8, palette: Self.ink)
        }
        XCTAssertTrue(worm === BookwormRenderer.cachedImage(state: .happy, frameIndex: 0, pointSize: 264),
                      "a scene flood must not evict the mascot's cached frame")
    }

    // MARK: - nsColors

    func testNsColorsMapsEveryHexChannelExactly() throws {
        let colors = PixelRenderer.nsColors(["x": 0x112233, "y": 0xFFCB57])
        XCTAssertEqual(Set(colors.keys), ["x", "y"])
        let y = try XCTUnwrap(colors["y"])
        XCTAssertEqual(y.redComponent, 255.0 / 255, accuracy: 0.001)
        XCTAssertEqual(y.greenComponent, 203.0 / 255, accuracy: 0.001)
        XCTAssertEqual(y.blueComponent, 87.0 / 255, accuracy: 0.001)
        XCTAssertEqual(y.alphaComponent, 1, accuracy: 0.001)
    }
}
