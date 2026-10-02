import XCTest
@testable import CicadaApp

final class BookwormArtTests: XCTestCase {
    func testTagsAreDerivedFromEveryReachableLook() {
        for state in BookwormSpriteTests.states {
            for look in BookwormLook.reachable(for: state) {
                XCTAssertEqual(BookwormArt.tag(look), look.keySegment ?? "idle")
                XCTAssertEqual(BookwormArt.tag(look, cover: 2), "\(look.keySegment ?? "idle")@2")
            }
        }
    }

    func testRequiredTagCountsAndSmallTags() {
        let counts: [String: Int] = ["awake": 18, "hungry": 18, "happy": 19, "reading": 54,
                                    "digesting": 7, "sleeping": 4, "error": 1, "curious": 1]
        for state in BookwormSpriteTests.states { XCTAssertEqual(BookwormArt.requiredTags(state).count, counts[state.caseName]) }
        XCTAssertEqual(BookwormArt.smallRequiredTags(), Set(counts.keys))
    }

    func testFallbackChain() throws {
        let sheet = try SpriteSheetTests.fixture()
        XCTAssertEqual(BookwormArt.fallbackClip(in: sheet, tag: "talk.center@2")?.tag, "talk.center")
        XCTAssertEqual(BookwormArt.fallbackClip(in: sheet, tag: "missing@3")?.tag, "idle")
        XCTAssertEqual(BookwormArt.fallbackClip(in: sheet, tag: "talk.center")?.tag, "talk.center")
        let bare = try SpriteSheetTests.fixture("no-idle")
        XCTAssertEqual(BookwormArt.fallbackClip(in: bare, tag: "missing")?.order, [0])
        XCTAssertEqual(BookwormArt.fallbackClip(in: try SpriteSheetTests.fixture("no-tags"), tag: "missing")?.order, [0])
    }

    func testCoverCycleUsesTheReadingIdleTotal() throws {
        let clip = try XCTUnwrap(try SpriteTestAssets.sheet("bookworm-reading").clip("idle"))
        for (n, cover) in [(0, 1), (1, 2), (2, 3), (3, 1), (4, 2)] {
            XCTAssertEqual(BookwormArt.coverIndex(at: SpriteClock.origin.addingTimeInterval(Double(n) * clip.total), profile: .full), cover)
            XCTAssertEqual(BookwormArt.coverIndex(at: SpriteClock.origin.addingTimeInterval(Double(n) * clip.total * 2), profile: .gentle), cover)
        }
        XCTAssertEqual(BookwormArt.coverIndex(at: .now, profile: .still), 1)
    }

    func testSizesAtTheCallSites() {
        XCTAssertEqual(BookwormSize.resolve(pointSize: 96, uiScale: 1, latticeCell: 3), .init(set: .room, pixelScale: 3, size: .init(width: 192, height: 144)))
        XCTAssertEqual(BookwormSize.resolve(pointSize: 96, uiScale: 1, latticeCell: nil), .init(set: .room, pixelScale: 2, size: .init(width: 128, height: 96)))
        XCTAssertEqual(BookwormSize.resolve(pointSize: 48, uiScale: 1, latticeCell: nil), .init(set: .room, pixelScale: 1, size: .init(width: 64, height: 48)))
        XCTAssertEqual(BookwormSize.resolve(pointSize: 24, uiScale: 1, latticeCell: nil), .init(set: .small, pixelScale: 1, size: .init(width: 18, height: 18)))
        XCTAssertEqual(BookwormSize.resolve(pointSize: 24, uiScale: 1.2, latticeCell: nil).pixelScale, 2)
    }

    func testTransitionsAlwaysUseTheSleepingSheet() throws {
        _ = try SpriteTestAssets.sheet("bookworm-sleeping")
        for t in [BookwormTransition.yawn, .stretch] {
            let (sheet, clip) = try XCTUnwrap(BookwormArt.transitionClip(t))
            XCTAssertEqual(sheet.name, "bookworm-sleeping")
            XCTAssertEqual(clip.tag, t.rawValue)
        }
    }

    func testEyeAndLensSlicesAreEqualAcrossRoomSheets() throws {
        let first = try SpriteTestAssets.sheet("bookworm-awake")
        for state in BookwormSpriteTests.states {
            let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))
            for name in ["eye", "lensL", "lensR"] {
                XCTAssertEqual(try XCTUnwrap(sheet.slices[name]), try XCTUnwrap(first.slices[name]), "\(sheet.name)/\(name)")
            }
        }
    }
}
