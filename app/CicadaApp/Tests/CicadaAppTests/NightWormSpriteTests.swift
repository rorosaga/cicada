import XCTest
@testable import CicadaApp

final class NightWormSpriteTests: XCTestCase {
    func testAllNightSheetsMatchDayTagsFramesTimingsSlicesAndSilhouettes() throws {
        for state in BookwormArt.states {
            let day = try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))
            for lit in [false, true] {
                let name = BookwormArt.sheetName(state, .room, lighting: .dark, lampLit: lit)
                let night = try SpriteTestAssets.sheet(name)
                XCTAssertEqual(night.frameSize, BookwormArt.roomFrame, name)
                XCTAssertEqual(Set(night.tags.keys), BookwormArt.requiredTags(state), name)
                XCTAssertEqual(night.frameRects.count, day.frameRects.count, name)
                XCTAssertEqual(night.frameSeconds, day.frameSeconds, name)
                XCTAssertEqual(night.slices, day.slices, name)
                SpriteTestAssets.assertCaps(night)
                for tag in BookwormArt.requiredTags(state) {
                    let a = try SpriteTestAssets.clip(day, tag), b = try SpriteTestAssets.clip(night, tag)
                    XCTAssertEqual(a.order.count, b.order.count, name + "/" + tag)
                    XCTAssertEqual(a.seconds, b.seconds, name + "/" + tag)
                    for (dayIndex, nightIndex) in zip(a.order, b.order) {
                        XCTAssertEqual(try SpriteTestAssets.plane(day, frame: dayIndex).ink,
                                       try SpriteTestAssets.plane(night, frame: nightIndex).ink, name + "/" + tag)
                    }
                    let look = try XCTUnwrap(BookwormLook.reachable(for: state).first)
                    XCTAssertEqual(try XCTUnwrap(BookwormArt.clip(state, look: look, lighting: .dark, lampLit: lit)).0.name, name)
                }
            }
        }
    }

    func testNightBeatsAndTransitionsUseTheSameLightingSet() throws {
        for lit in [false, true] {
            for state in BookwormArt.states {
                let name = BookwormArt.sheetName(state, .room, lighting: .dark, lampLit: lit)
                for kind in BookwormReaction.allCases {
                    for gaze in Gaze.allCases {
                        if let look = BookwormLook.beat(kind, for: state, gaze: gaze) {
                            let pair = try XCTUnwrap(BookwormArt.clip(state, look: look, lighting: .dark, lampLit: lit))
                            XCTAssertEqual(pair.0.name, name)
                            XCTAssertEqual(pair.1.tag, BookwormArt.tag(look))
                        }
                    }
                }
            }
            for kind in [BookwormTransition.yawn, .stretch] {
                let pair = try XCTUnwrap(BookwormArt.transitionClip(kind, lighting: .dark, lampLit: lit))
                XCTAssertEqual(pair.0.name, BookwormArt.sheetName(.sleeping(stage: 1), .room, lighting: .dark, lampLit: lit))
                XCTAssertEqual(pair.1.tag, kind.rawValue)
            }
        }
    }

    func testSmallSheetNeverReadsRoomLighting() {
        for state in BookwormArt.states { for lit in [false, true] {
            XCTAssertEqual(BookwormArt.sheetName(state, .small, lighting: .dark, lampLit: lit), "bookworm-small")
        } }
    }
}
