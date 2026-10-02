import XCTest
@testable import CicadaApp

final class BookwormSpriteTests: XCTestCase {
    static var states: [BookwormState] { BookwormArt.states }

    func testOverlayPaletteKeepsItsEightRolesWithoutRetiredErrorRed() {
        XCTAssertEqual(Set(BookwormPalette.colors.keys), ["o", "b", "l", "w", "r", "a", "z", "q"])
        XCTAssertEqual(BookwormPalette.transparent, ".")
    }

    func testEachRoomSheetHasExactlyTheRequiredTagsAndCanvas() throws {
        for state in Self.states {
            let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))
            let data = try SpriteTestAssets.data(sheet.name)
            XCTAssertEqual(Set(data.meta.frameTags.map(\.name)), BookwormArt.requiredTags(state), sheet.name)
            XCTAssertEqual(sheet.frameSize, BookwormArt.roomFrame)
            XCTAssertTrue(data.frames.allSatisfy { $0.sourceSize.w == 64 && $0.sourceSize.h == 48 && $0.frame.w == 64 && $0.frame.h == 48 })
            XCTAssertTrue(data.meta.frameTags.allSatisfy { $0.direction == "forward" })
            let idle = try SpriteTestAssets.clip(sheet, "idle")
            XCTAssertGreaterThanOrEqual(Set(idle.order.map { sheet.rectIndex[$0] }).count, 2, sheet.name)
            SpriteTestAssets.assertCaps(sheet)
        }
    }

    func testSmallSheetHasExactlyTheEightTagsAndCanvas() throws {
        let sheet = try SpriteTestAssets.sheet("bookworm-small")
        let data = try SpriteTestAssets.data(sheet.name)
        XCTAssertEqual(Set(data.meta.frameTags.map(\.name)), BookwormArt.smallRequiredTags())
        XCTAssertEqual(sheet.frameSize, BookwormArt.smallFrame)
        XCTAssertTrue(data.frames.allSatisfy { $0.sourceSize.w == 18 && $0.sourceSize.h == 18 && $0.frame.w == 18 && $0.frame.h == 18 })
        for clip in sheet.tags.values { XCTAssertGreaterThanOrEqual(Set(clip.order.map { sheet.rectIndex[$0] }).count, 2) }
        SpriteTestAssets.assertCaps(sheet)
    }

    func testReadingCoversShareDurationsFrameForFrame() throws {
        let sheet = try SpriteTestAssets.sheet("bookworm-reading")
        for look in BookwormLook.reachable(for: .reading) {
            let first = try SpriteTestAssets.clip(sheet, BookwormArt.tag(look))
            for k in 2...3 {
                let clip = try SpriteTestAssets.clip(sheet, BookwormArt.tag(look, cover: k))
                XCTAssertEqual(clip.seconds, first.seconds)
                XCTAssertEqual(clip.total, first.total)
            }
        }
        XCTAssertEqual(try SpriteTestAssets.clip(sheet, "idle").total, 21.84, accuracy: 0.000001)
    }

    func testBadgeUsesDarkDigitsOnGoldAtTheEighteenCellCorner() {
        let b = BookwormOverlays.badgeOverlay(47)
        XCTAssertEqual(b[11], ".........qqqqqqqqq")
        XCTAssertEqual(b[12], ".........qoqoqoooq")
        XCTAssertEqual(b[17], ".........qqqqqqqqq")
        XCTAssertEqual(BookwormOverlays.badgeOverlay(7)[11], ".............qqqqq")
        XCTAssertFalse(b.joined().contains("w"))
        XCTAssertEqual(BookwormOverlays.badgeOverlay(250), BookwormOverlays.badgeOverlay(99))
        XCTAssertEqual(BookwormOverlays.badgeOverlay(0), BookwormOverlays.badgeOverlay(1))
        XCTAssertEqual(BookwormOverlays.badgeOverlay(-4), BookwormOverlays.badgeOverlay(1))
    }

    func testStageDotsPersistInTheSmallOverlay() {
        XCTAssertEqual(BookwormOverlays.stageDots(3)[17], ".a...a...a...o...o")
        XCTAssertEqual(BookwormOverlays.stageDots(0)[17], ".o...o...o...o...o")
        XCTAssertEqual(BookwormOverlays.stageDots(9)[17], ".a...a...a...a...a")
        for stage in 1...5 { XCTAssertEqual(BookwormOverlays.grid(for: .sleeping(stage: stage)), BookwormOverlays.stageDots(stage)) }
        for count in [1, 47, 250] { XCTAssertEqual(BookwormOverlays.grid(for: .curious(count: count)), BookwormOverlays.badgeOverlay(count)) }
        for state in Self.states {
            let grid = BookwormOverlays.grid(for: state)
            XCTAssertEqual(grid.count, 18)
            XCTAssertTrue(grid.allSatisfy { $0.count == 18 })
        }
    }
}
