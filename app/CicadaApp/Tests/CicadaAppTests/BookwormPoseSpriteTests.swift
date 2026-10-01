import XCTest
@testable import CicadaApp

final class BookwormPoseSpriteTests: XCTestCase {
    static let pageStates: [BookwormState] = [.awake, .happy, .reading, .hungry, .digesting, .error] + (1...5).map { .sleeping(stage: $0) }

    func test_suppressedStatesIgnoreThePointer() {
        for state in [BookwormState.sleeping(stage: 2), .error, .digesting] {
            for gaze in Gaze.allCases { XCTAssertEqual(BookwormPose.attentive(gaze).effective(for: state, reduceMotion: false), .idle) }
        }
    }

    func test_theMatrix() {
        XCTAssertEqual(Self.pageStates.filter(\.acceptsGaze).map(\.caseName), ["awake", "happy", "reading", "hungry"])
        XCTAssertTrue(BookwormState.digesting.acceptsDropPose)
        XCTAssertFalse(BookwormState.sleeping(stage: 1).acceptsDropPose)
        XCTAssertTrue(BookwormState.sleeping(stage: 3).allows(.talk), "it talks in its sleep")
        XCTAssertFalse(BookwormState.error.allows(.talk), "words only")
        XCTAssertTrue(BookwormState.digesting.allows(.gulp))
        XCTAssertTrue(BookwormState.digesting.allows(.cheer))
        XCTAssertTrue(BookwormState.happy.allows(.cheer))
        XCTAssertFalse(BookwormState.reading.allows(.cheer))
        XCTAssertFalse(BookwormState.digesting.allows(.perk))
        XCTAssertNil(BookwormLook.beat(.talk, for: .error, gaze: .center))
        XCTAssertFalse(BookwormState.curious(count: 3).acceptsGaze, "the menu bar never gets a pose")
    }

    func testEveryRoomFrameKeepsTheBookGlassesAndStateMarks() throws {
        let palette = try SpriteTestAssets.palette()
        let roles = palette.roles
        let d = try palette.rgb("D"), l = try palette.rgb("L"), j = try palette.rgb("j"), w = try palette.rgb("W")
        let e = try palette.rgb("e"), sweat = try palette.rgb("S"), z = try palette.rgb("Z")
        for state in BookwormSpriteTests.states {
            let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))
            for tag in BookwormArt.requiredTags(state) {
                let clip = try SpriteTestAssets.clip(sheet, tag)
                for (step, index) in clip.order.enumerated() {
                    let frame = try SpriteTestAssets.plane(sheet, frame: index)
                    let label = "\(sheet.name)/\(tag) #\(step)"
                    XCTAssertGreaterThanOrEqual(frame.pixels.filter { $0.alpha > 0 && (roles[$0.rgb]?.hasPrefix("book.") ?? false) }.count, 20, label)
                    XCTAssertGreaterThanOrEqual(frame.count(d), 30, label)
                    XCTAssertGreaterThanOrEqual(frame.count(l), 6, label)
                    if state.caseName == "sleeping" && tag != "intro" && tag != "outro" {
                        XCTAssertGreaterThanOrEqual(frame.count(j), 4, label)
                        XCTAssertEqual(frame.count(w), 0, label)
                        if tag == "idle" && step == 0 { XCTAssertGreaterThanOrEqual(frame.count(z), 3, label) }
                    }
                    if state.caseName == "error" {
                        XCTAssertGreaterThanOrEqual(frame.count(e), 4, label)
                        XCTAssertGreaterThanOrEqual(frame.count(sweat), 1, label)
                    }
                }
            }
        }
    }

    func testSmallStateMarksAndOverlaySpace() throws {
        let sheet = try SpriteTestAssets.sheet("bookworm-small")
        let palette = try SpriteTestAssets.palette(), roles = palette.roles
        let k = try palette.rgb("K"), e = try palette.rgb("e"), sweat = try palette.rgb("S")
        for clip in sheet.tags.values {
            for frame in clip.order {
                let plane = try SpriteTestAssets.plane(sheet, frame: frame)
                XCTAssertTrue(plane.ink.allSatisfy { $0.y < 16 }, "rows 16–17 reserved for dots")
                if clip.tag == "sleeping" {
                    for lens in ["lensL", "lensR"] {
                        let rect = try XCTUnwrap(sheet.slices[lens])
                        let lids = plane.cells { $0.alpha > 0 && $0.rgb == k }.filter { rect.contains(CGPoint(x: Double($0.x) + 0.5, y: Double($0.y) + 0.5)) }
                        XCTAssertGreaterThanOrEqual(lids.count, 2)
                        XCTAssertEqual(Set(lids.map(\.y)).count, 1, "closed lid, never plus pupil")
                    }
                }
                if clip.tag == "error" { XCTAssertGreaterThanOrEqual(plane.count(e), 1); XCTAssertGreaterThanOrEqual(plane.count(sweat), 1) }
                if clip.tag == "reading" { XCTAssertGreaterThanOrEqual(plane.pixels.filter { $0.alpha > 0 && (roles[$0.rgb]?.hasPrefix("book.") ?? false) }.count, 8) }
            }
        }
        let curious = try SpriteTestAssets.clip(sheet, "curious")
        let lens = try XCTUnwrap(sheet.slices["lensR"])
        XCTAssertLessThanOrEqual(lens.maxY, 11, "the badge cannot cover the glasses")
        XCTAssertFalse(curious.order.isEmpty)
    }

    func testEveryBeatFitsTheMotionBudget() throws {
        for state in BookwormSpriteTests.states { SpriteTestAssets.assertCaps(try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))) }
    }

    func testGazeVariantsShareDurations() throws {
        for state in BookwormSpriteTests.states where state.acceptsGaze {
            let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))
            for family in ["attentive", "expectant", "perk", "talk", "shake"] {
                for cover in state.caseName == "reading" ? [1, 2, 3] : [1] {
                    let suffix = cover == 1 ? "" : "@\(cover)"
                    let center = try SpriteTestAssets.clip(sheet, "\(family).center\(suffix)")
                    for gaze in ["left", "right"] { XCTAssertEqual(try SpriteTestAssets.clip(sheet, "\(family).\(gaze)\(suffix)").seconds, center.seconds) }
                }
            }
        }
    }

    func testBlinksHaveIrregularCyclicGaps() throws {
        let w = try SpriteTestAssets.palette().rgb("W")
        for name in ["awake", "happy", "curious", "reading"] {
            let sheet = try SpriteTestAssets.sheet("bookworm-\(name)")
            var tags = name == "reading" ? ["idle", "idle@2", "idle@3"] : ["idle"]
            if name != "curious" {
                for gaze in Gaze.allCases {
                    tags += (name == "reading" ? [1, 2, 3] : [1]).map { "attentive.\(gaze.rawValue)" + ($0 == 1 ? "" : "@\($0)") }
                }
            }
            for tag in tags {
                let clip = try SpriteTestAssets.clip(sheet, tag)
                let key = try SpriteTestAssets.plane(sheet, frame: clip.order[0]).count(w)
                let blink = try clip.order.map { try SpriteTestAssets.plane(sheet, frame: $0).count(w) <= key - 2 }
                var starts: [Double] = [], t = 0.0
                for i in blink.indices {
                    if blink[i] && !blink[(i + blink.count - 1) % blink.count] { starts.append(t) }
                    t += clip.seconds[i]
                }
                let minimum = tag.hasPrefix("idle") && ["awake", "reading"].contains(name) ? 3 : 2
                XCTAssertGreaterThanOrEqual(starts.count, minimum, "\(sheet.name)/\(tag)")
                var gaps = zip(starts.dropFirst(), starts).map(-)
                if let first = starts.first, let last = starts.last { gaps.append(clip.total - last + first) }
                XCTAssertGreaterThanOrEqual(try XCTUnwrap(gaps.max()) / XCTUnwrap(gaps.min()), 1.6, "\(sheet.name)/\(tag)")
            }
        }
    }

    func testLiftsAndSleepGlyphsStayInTheirBoxes() throws {
        let palette = try SpriteTestAssets.palette()
        let zs = try Set(["Z", "Y", "X"].map { try palette.rgb($0) })
        for state in BookwormSpriteTests.states {
            let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))
            for clip in sheet.tags.values {
                let lifted = clip.tag.hasPrefix("perk.") || clip.tag.hasPrefix("eager") || clip.tag.hasPrefix("cheer.center")
                for frame in clip.order {
                    let plane = try SpriteTestAssets.plane(sheet, frame: frame)
                    let bottom = try XCTUnwrap(plane.ink.map(\.y).max())
                    XCTAssertTrue(lifted ? (44...47).contains(bottom) : bottom == 47, "\(sheet.name)/\(clip.tag)")
                    XCTAssertTrue(plane.cells { $0.alpha > 0 && zs.contains($0.rgb) }.allSatisfy { (40...63).contains($0.x) && (0...14).contains($0.y) })
                }
            }
        }
    }
}
