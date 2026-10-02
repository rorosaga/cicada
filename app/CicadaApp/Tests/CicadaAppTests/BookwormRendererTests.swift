import AppKit
import XCTest
@testable import CicadaApp

@MainActor
final class BookwormRendererTests: XCTestCase {
    func testSyntheticCropRendersUprightWithoutInterpolation() throws {
        let sheet = try SpriteSheetTests.fixture()
        let image = BookwormRenderer.composite(crop: sheet.frameImage(0), overlay: BookwormOverlays.blank(), pointSize: 18)
        var rect = CGRect(origin: .zero, size: image.size)
        let plane = SpriteTestAssets.Plane(try XCTUnwrap(image.cgImage(forProposedRect: &rect, context: nil, hints: nil)))
        XCTAssertEqual(image.size, NSSize(width: 18, height: 18))
        XCTAssertEqual(plane.w, plane.h)
        XCTAssertEqual(plane.w % 18, 0)
        let pixelScale = plane.w / 2
        let source = try SpriteTestAssets.plane(sheet, frame: 0)
        for y in 0..<plane.h { for x in 0..<plane.w {
            XCTAssertEqual(plane.at(x, y), source.at(x / pixelScale, y / pixelScale), "\(x),\(y)")
        } }
    }

    func testImageIsColourNotTemplateAtTheRequestedSize() {
        let image = BookwormRenderer.smallImage(state: .awake, frameStep: 0, pointSize: 18)
        XCTAssertFalse(image.isTemplate)
        XCTAssertEqual(image.size, NSSize(width: 18, height: 18))
    }

    func testPixelsCarryTheSmallSheetsLimeAndTransparentCorners() throws {
        let sheet = try SpriteTestAssets.sheet("bookworm-small")
        let clip = try SpriteTestAssets.clip(sheet, "awake")
        let image = BookwormRenderer.smallImage(state: .awake, frameStep: 0, pointSize: 18)
        var proposed = CGRect(origin: .zero, size: image.size)
        let cg = try XCTUnwrap(image.cgImage(forProposedRect: &proposed, context: nil, hints: nil))
        let plane = SpriteTestAssets.Plane(cg)
        let m = try SpriteTestAssets.palette().rgb("m")
        XCTAssertGreaterThan(plane.count(m), 0)
        XCTAssertEqual(plane.at(0, 0).alpha, 0)
        XCTAssertEqual(plane.at(plane.w - 1, plane.h - 1).alpha, 0)
        let original = try SpriteTestAssets.plane(sheet, frame: clip.order[0])
        let scale = plane.w / 18
        XCTAssertGreaterThanOrEqual(scale, 1)
        XCTAssertEqual(plane.w, 18 * scale); XCTAssertEqual(plane.h, 18 * scale)
        for y in 0..<plane.h { for x in 0..<plane.w {
            XCTAssertEqual(plane.at(x, y), original.at(x / scale, y / scale), "the CGImage must stay upright and nearest-neighbour")
        } }
    }

    func testCacheKeyDistinguishesCountStageRectAndSize() {
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .awake, rectIndex: 0, pointSize: 18), "small|bookworm|awake|0|18")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .curious(count: 47), rectIndex: 2, pointSize: 18), "small|bookworm|curious|47|2|18")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .curious(count: 250), rectIndex: 0, pointSize: 18), "small|bookworm|curious|99|0|18")
        XCTAssertEqual(BookwormRenderer.cacheKey(state: .sleeping(stage: 3), rectIndex: 1, pointSize: 18), "small|bookworm|sleeping|3|1|18")
    }

    func testTwoSkinsNeverShareAnImageCacheEntry() {
        // Reuse real art with a different id to isolate the cache key from pixel differences.
        let other = Mascot(id: "cache-test", displayName: "Test", roomSheetPrefix: MascotRegistry.bookworm.roomSheetPrefix,
                           menuBarSheet: MascotRegistry.bookworm.menuBarSheet, artFolder: MascotRegistry.bookworm.artFolder)
        let a = BookwormRenderer.smallImage(state: .awake, frameStep: 0, pointSize: 18, mascot: MascotRegistry.bookworm)
        let b = BookwormRenderer.smallImage(state: .awake, frameStep: 0, pointSize: 18, mascot: other)
        XCTAssertFalse(a === b)
        XCTAssertTrue(b === BookwormRenderer.smallImage(state: .awake, frameStep: 0, pointSize: 18, mascot: other))
    }

    func testCacheIdentityAndDeduplicatedFrames() throws {
        let sheet = try SpriteTestAssets.sheet("bookworm-small")
        let clip = try SpriteTestAssets.clip(sheet, "awake")
        let a = BookwormRenderer.smallImage(state: .awake, frameStep: 0, pointSize: 18)
        XCTAssertTrue(a === BookwormRenderer.smallImage(state: .awake, frameStep: clip.order.count, pointSize: 18))
        XCTAssertTrue(a === BookwormRenderer.smallImage(state: .awake, frameStep: -clip.order.count, pointSize: 18))
        for i in clip.order.indices {
            let image = BookwormRenderer.smallImage(state: .awake, frameStep: i, pointSize: 18)
            XCTAssertEqual(a === image, sheet.rectIndex[clip.order[i]] == sheet.rectIndex[clip.order[0]])
        }
    }

    func testMenuBarSizedImagesAreCachedPerCountAndStage() throws {
        _ = try SpriteTestAssets.sheet("bookworm-small")
        let a = BookwormRenderer.smallImage(state: .curious(count: 3), frameStep: 0, pointSize: MenuBarManager.spritePointSize)
        let b = BookwormRenderer.smallImage(state: .curious(count: 4), frameStep: 0, pointSize: MenuBarManager.spritePointSize)
        XCTAssertFalse(a === b)
        XCTAssertEqual(a.size, NSSize(width: 18, height: 18))
        XCTAssertFalse(a.isTemplate)
        XCTAssertTrue(a === BookwormRenderer.smallImage(state: .curious(count: 3), frameStep: 0, pointSize: 18))
    }

    func testMenuBarAccessibilityAndRestPolicy() throws {
        for state in BookwormSpriteTests.states {
            let label = MenuBarManager.accessibilityLabel(for: state)
            XCTAssertEqual(label, "Cicada — \(state.title), \(state.detail)")
            XCTAssertEqual(BookwormRenderer.smallImage(state: state, frameStep: 0, pointSize: 18).accessibilityDescription, label)
        }
        XCTAssertFalse(MenuBarManager.animationRuns(isVisible: false, displaysAsleep: false, reduceMotion: false))
        XCTAssertFalse(MenuBarManager.animationRuns(isVisible: true, displaysAsleep: true, reduceMotion: false))
        XCTAssertFalse(MenuBarManager.animationRuns(isVisible: true, displaysAsleep: false, reduceMotion: true))
        let text = try String(contentsOf: SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/MenuBarManager.swift"))
        XCTAssertTrue(text.contains("button.setAccessibilityLabel(label)"))
        XCTAssertTrue(text.contains("repeats: false"))
        XCTAssertTrue(text.contains("NSWorkspace.screensDidSleepNotification"))
        XCTAssertTrue(text.contains("NSWorkspace.screensDidWakeNotification"))
    }
}
