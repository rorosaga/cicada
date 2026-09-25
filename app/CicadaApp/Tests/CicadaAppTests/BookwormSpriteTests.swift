import XCTest
@testable import CicadaApp

/// G107: the bookworm is one code-defined 24×24 palette sprite set. These
/// tests are the contract the brief set: every frame is exactly 24×24, every
/// character is a palette index (or transparent), every state has ≥ 2 frames
/// that actually differ (it is always moving), and every interval sits in the
/// 250–800 ms band. Overlays (badge, stage dots) are baked by `frames(for:)`
/// (ruling R2), so they are asserted on the frames themselves.
final class BookwormSpriteTests: XCTestCase {

    /// Every state the renderer can be asked for, with both a one- and a
    /// two-digit count and both ends of the stage range. Task 2 appends
    /// `.error` here; Task 5 (G125) appends `.reading`.
    static var states: [BookwormState] {
        [.awake, .sleeping(stage: 1), .sleeping(stage: 5), .digesting, .happy,
         .curious(count: 1), .curious(count: 47), .curious(count: 250), .hungry, .reading, .error]
    }

    private var allowed: Set<Character> {
        Set(BookwormPalette.colors.keys).union([BookwormPalette.transparent])
    }

    func testPaletteIsExactlyTheNineRoles() {
        XCTAssertEqual(Set(BookwormPalette.colors.keys), ["o", "b", "l", "w", "r", "a", "z", "q", "e"])
        XCTAssertEqual(BookwormPalette.transparent, ".")
        XCTAssertEqual(BookwormSprites.size, 24)
    }

    func testEveryFrameIs24x24AndInPalette() {
        for state in Self.states {
            let (frames, _) = BookwormSprites.frames(for: state)
            for (i, frame) in frames.enumerated() {
                XCTAssertEqual(frame.count, 24, "\(state.caseName) frame \(i) row count")
                for (r, row) in frame.enumerated() {
                    XCTAssertEqual(row.count, 24, "\(state.caseName) frame \(i) row \(r) width")
                    for ch in row where !allowed.contains(ch) {
                        XCTFail("\(state.caseName) frame \(i) row \(r): '\(ch)' is not a palette index")
                    }
                }
            }
        }
    }

    func testEveryStateHasAtLeastTwoFramesThatDiffer() {
        for state in Self.states {
            let (frames, _) = BookwormSprites.frames(for: state)
            XCTAssertGreaterThanOrEqual(frames.count, 2, state.caseName)
            XCTAssertTrue(frames.contains { $0 != frames[0] }, "\(state.caseName) never moves")
        }
    }

    func testEveryIntervalIsInsideTheBand() {
        for state in Self.states {
            let (_, interval) = BookwormSprites.frames(for: state)
            XCTAssertGreaterThanOrEqual(interval, 0.25, state.caseName)
            XCTAssertLessThanOrEqual(interval, 0.8, state.caseName)
        }
    }

    /// The glasses rim (row 5, cols 0…20 — the head's span; cols 21…23 are
    /// overlay air where a z or a sweat drop may sit) is the character's
    /// signature; it must be the same in the untilted first frame of every
    /// state so the worm stays recognisable across moods.
    func testGlassesRimIsIdenticalAcrossStates() {
        let rim = String(BookwormSprites.awakeBase[5].prefix(21))
        XCTAssertEqual(rim, "....obaaaaaaaaaaaaabo")
        for state in [BookwormState.happy, .digesting, .hungry, .curious(count: 3), .sleeping(stage: 2), .reading] {
            XCTAssertEqual(String(BookwormSprites.frames(for: state).frames[0][5].prefix(21)), rim, state.caseName)
        }
    }

    func testAwakeBaseIsTheCanonicalFrame() {
        XCTAssertEqual(BookwormSprites.frames(for: .awake).frames[0], BookwormSprites.awakeBase)
        XCTAssertEqual(BookwormSprites.awakeBase[7], "....obawoowabawoowabo...")   // pupils
        XCTAssertEqual(BookwormSprites.awakeBase[10], "....obbrrbbbbbbbbrrbo...")  // blush
    }

    // MARK: badge

    func testBadgeDigitsLandInsideThePill() {
        let b = BookwormSprites.badgeOverlay(47)
        // Two digits: pill is 9 wide, right edge col 22 → cols 14…22, rows 16…22.
        XCTAssertEqual(b[16], "..............qqqqqqqqq.")
        XCTAssertEqual(b[22], "..............qqqqqqqqq.")
        let row17 = Array(b[17])
        XCTAssertEqual(String(row17[15...17]), "oqo", "'4' top row")
        XCTAssertEqual(String(row17[19...21]), "ooo", "'7' top row")
        // One digit: pill is 5 wide → cols 18…22.
        XCTAssertEqual(BookwormSprites.badgeOverlay(7)[16], "..................qqqqq.")
    }

    func testBadgeClampsTo1Through99() {
        XCTAssertEqual(BookwormSprites.badgeOverlay(250), BookwormSprites.badgeOverlay(99))
        XCTAssertEqual(BookwormSprites.badgeOverlay(0), BookwormSprites.badgeOverlay(1))
        XCTAssertEqual(BookwormSprites.badgeOverlay(-4), BookwormSprites.badgeOverlay(1))
    }

    func testCuriousFramesCarryTheCount() {
        for frame in BookwormSprites.frames(for: .curious(count: 47)).frames {
            XCTAssertEqual(String(Array(frame[17])[19...21]), "ooo", "count baked into every frame")
        }
        // The head tilt never reaches the badge column.
        XCTAssertEqual(BookwormSprites.frames(for: .curious(count: 47)).frames[1][16].suffix(10),
                       BookwormSprites.frames(for: .curious(count: 47)).frames[0][16].suffix(10))
    }

    // MARK: stage dots

    func testStageDotsFillLeftToRightOnTheBottomRow() {
        XCTAssertEqual(BookwormSprites.stageDots(3)[23], "...a...a...a...o...o....")
        XCTAssertEqual(BookwormSprites.stageDots(0)[23], "...o...o...o...o...o....")
        XCTAssertEqual(BookwormSprites.stageDots(9)[23], "...a...a...a...a...a....")
        for frame in BookwormSprites.frames(for: .sleeping(stage: 2)).frames {
            XCTAssertEqual(frame[23], "...a...a...o...o...o....")
        }
    }

    // MARK: nightcap (G125 v3 Task 3, P14)

    /// Cells that exist only when the cap is on: two on the brim, one on the
    /// tassel's pom, one on the crown. Chosen inside cols 0…18 on purpose —
    /// see `testTheCapNeverEntersTheZDriftCorridor`.
    private static let capCells: [(row: Int, col: Int, char: Character)] =
        [(0, 10, "z"), (2, 5, "w"), (2, 16, "w"), (3, 3, "w")]

    /// The cap is BAKED into the frames, not merged by a consumer (mascot
    /// ruling R2): `frames(for:)` returns fully composed frames, and an
    /// accessory layer would reintroduce the seam R2 deleted. So it is
    /// asserted on the frames themselves, on EVERY frame — a cap that
    /// survived only the first frame would flicker once per interval.
    func testTheNightcapIsOnEveryFrameOfSleepingAndReading() {
        for state in [BookwormState.sleeping(stage: 1), .sleeping(stage: 5), .reading] {
            for (i, frame) in BookwormSprites.frames(for: state).frames.enumerated() {
                for cell in Self.capCells {
                    XCTAssertEqual(Array(frame[cell.row])[cell.col], cell.char,
                                   "\(state.caseName) frame \(i) at (\(cell.row), \(cell.col))")
                }
            }
        }
    }

    /// The cap is a function of the STATE, which is why it can be baked at
    /// all: `spriteKey` already distinguishes these states in the cache key,
    /// so no new cache dimension appears. Every other mood is bare-headed.
    func testNoOtherStateWearsTheCap() {
        for state in [BookwormState.awake, .happy, .hungry, .curious(count: 3), .digesting, .error] {
            for (i, frame) in BookwormSprites.frames(for: state).frames.enumerated() {
                for cell in Self.capCells {
                    XCTAssertNotEqual(Array(frame[cell.row])[cell.col], cell.char,
                                      "\(state.caseName) frame \(i) at (\(cell.row), \(cell.col))")
                }
            }
        }
    }

    /// The tassel is on the LEFT because the right-hand top corner is the
    /// `sleeping` z-glyph corridor: `zBig` is placed at `top: 0, left: 19`,
    /// so rows 0…4 / cols 19…23 belong to the drifting z. A cap cell there
    /// would be overwritten by a z on one frame and visible on the next,
    /// which reads as a rendering bug rather than a sleeping worm.
    func testTheCapNeverEntersTheZDriftCorridor() {
        for state in [BookwormState.sleeping(stage: 3), .reading] {
            let frames = BookwormSprites.frames(for: state).frames
            for (i, frame) in frames.enumerated() {
                for r in 0...4 {
                    for c in 19...23 {
                        let ch = Array(frame[r])[c]
                        XCTAssertTrue(ch == "." || ch == "z" || ch == "o" || ch == "b" || ch == "a",
                                      "\(state.caseName) frame \(i) (\(r), \(c)) = '\(ch)' — cap ink in the z corridor")
                    }
                }
            }
        }
    }

    /// Rows 5…9 are the glasses; the cap occupies rows 0…4 and replaces the
    /// head top and nothing else. Row 5 is already pinned across states by
    /// `testGlassesRimIsIdenticalAcrossStates`; this pins the whole band for
    /// the two capped states, so a cap that grew one row down is caught.
    func testTheCapNeverReachesTheGlassesBand() {
        for state in [BookwormState.sleeping(stage: 2), .reading] {
            let capped = BookwormSprites.frames(for: state).frames[0]
            for r in 5...9 where r != 6 && r != 7 && r != 8 {
                XCTAssertEqual(String(capped[r].prefix(19)),
                               String(BookwormSprites.awakeBase[r].prefix(19)),
                               "\(state.caseName) row \(r)")
            }
        }
    }

    // MARK: helpers

    func testShiftAndMergeNeverChangeDimensions() {
        let g = BookwormSprites.awakeBase
        for grid in [BookwormSprites.shift(g, dx: 1), BookwormSprites.shift(g, dy: -1),
                     BookwormSprites.shift(g, dx: -2, dy: 2), BookwormSprites.merge(g, BookwormSprites.badgeOverlay(9)),
                     BookwormSprites.shiftRows(g, 2..<13, dx: 1)] {
            XCTAssertEqual(grid.count, 24)
            XCTAssertTrue(grid.allSatisfy { $0.count == 24 })
        }
        XCTAssertEqual(BookwormSprites.shift(g, dy: 1)[3], g[2])
        XCTAssertEqual(BookwormSprites.shift(g, dx: 1)[5], "." + g[5].dropLast())
    }
}
