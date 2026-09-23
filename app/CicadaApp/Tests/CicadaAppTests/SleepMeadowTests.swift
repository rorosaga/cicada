import XCTest
@testable import CicadaApp

/// Track Z Z10 — the Meadow pass on the Sleep page (spec decision 6; Z-B12 …
/// Z-B15): the sentence in Meadow's faces, one prominent action, one motion
/// budget, hover only where there is a control.
final class SleepMeadowTests: XCTestCase {

    private func sleepFile(_ name: String) throws -> [String] {
        let file = try XCTUnwrap(SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == name })
        return try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.hasPrefix("//") }
    }

    /// Z-B12, amended by F1 R-FX13 — the display face (SF Pro Display
    /// semibold, tracked) for the lead, its italic for the tail. The owner asked
    /// for a minimal sans, so the New York quote face left the sentence too.
    func test_theSentenceSpeaksInMeadowsFaces() throws {
        let code = try sleepFile("RoomSentence.swift")
        XCTAssertTrue(code.contains { $0.contains("CicadaTheme.displayFont(size: Self.leadSize)") })
        XCTAssertTrue(code.contains { $0.contains("CicadaTheme.displayTracking(size: Self.leadSize)") })
        XCTAssertTrue(code.contains { $0.contains("CicadaTheme.displayFont(size: Self.tailSize, italic: true)") })
        XCTAssertFalse(code.contains { $0.contains("quoteFont") }, "the sentence left the serif (R-FX13)")
        XCTAssertFalse(code.contains { $0.contains("design: .serif") }, "the New York stand-in part a used until M1")
        XCTAssertGreaterThanOrEqual(RoomSentenceView.leadSize, CicadaTheme.displayMinimumSize)
    }

    /// The lead may shrink to one line only as far as the display face's floor.
    func test_theLeadNeverShrinksBelowTheDisplayFloor() {
        XCTAssertEqual(RoomSentenceView.leadSize * RoomSentenceView.leadMinimumScale,
                       CicadaTheme.displayMinimumSize, accuracy: 0.001)
    }

    /// Z-B14 / R-M5 — one prominent action per page, and it is Consolidate.
    func test_consolidateIsThePagesOneProminentAction() throws {
        var prominent: [String] = []
        for file in try SleepNumbersLintTests.sleepSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            let count = text.components(separatedBy: "PrimaryActionButton(").count - 1
            if count > 0 { prominent.append("\(file.lastPathComponent)×\(count)") }
            for other in ["primaryActionStyle()", "meadowPillStyle()", "MeadowPill("] {
                XCTAssertFalse(text.contains(other), "\(file.lastPathComponent): \(other)")
            }
        }
        XCTAssertEqual(prominent, ["SleepHero.swift×1"])
        XCTAssertFalse(try sleepFile("SleepHero.swift").contains { $0.contains(".white") }, "the capsule's literal ink is gone")
    }

    /// Z-B13 — one motion budget, app-wide: where a name mirrors Meadow's, it IS Meadow's.
    func test_sleepMotionIsCicadaMotionWhereTheNamesMatch() {
        XCTAssertEqual(SleepMotion.maxDuration, CicadaMotion.maxDuration)
        XCTAssertEqual(SleepMotion.settleDuration, CicadaMotion.settleDuration)
        XCTAssertEqual(SleepMotion.hoverDuration, CicadaMotion.hoverDuration)
    }

    /// Z-B15 — hover acknowledges controls, never art.
    func test_hoverLivesOnControls() throws {
        let page = try sleepFile("SleepView.swift")
        XCTAssertGreaterThanOrEqual(page.filter { $0.contains(".iconHover(") }.count, 2, "the Details chevron and the whisper glyph")
        let room = try sleepFile("StudyRoom.swift")
        XCTAssertFalse(room.contains { $0.contains(".iconHover(") || $0.contains(".hoverLift(") },
                       "I8: the art never changes on hover")
    }
}
