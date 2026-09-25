import XCTest
@testable import CicadaApp

/// Track Z §7 — the room's props as controls. Every label, help string and
/// popover line is a pure function, so what a spine or the lamp SAYS can be
/// read against what it does.
final class SpineAndLampTests: XCTestCase {

    private let en = Locale(identifier: "en_US")
    private let idleRow = StudyRow(origin: "claude-code", label: "Claude Code", count: 12, oldestAge: "3d", read: nil, total: nil)
    private let runningRow = StudyRow(origin: "claude-code", label: "Claude Code", count: 12, oldestAge: "3d", read: 4, total: 12)
    private let spine = BookSpec(origin: "claude-code", count: 12, height: 20, widthFraction: 1, isRemainder: false)
    private let remainder = BookSpec(origin: "+more", count: 4, height: 10, widthFraction: 1, isRemainder: true)

    // MARK: Spines (§7.1, I5)

    func test_thePileNamesHowManySources_notHowManyBooks() {
        XCTAssertEqual(pileAccessibilityLabel(sourceCount: 1), "The pile, 1 source")
        XCTAssertEqual(pileAccessibilityLabel(sourceCount: 3), "The pile, 3 sources")
    }

    func test_aSpineSaysWhatItsRowSays() {
        XCTAssertEqual(StudyListCard.rowAccessibilityLabel(idleRow), "Claude Code, 12 waiting, oldest 3d")
        XCTAssertEqual(spineAccessibilityLabel(spec: spine, row: idleRow), StudyListCard.rowAccessibilityLabel(idleRow))
        XCTAssertEqual(spineAccessibilityLabel(spec: remainder, row: nil), "4 more on the pile, in Details")
    }

    func test_aSpinesHelpIsItsNumbersWithTheirNouns() {
        XCTAssertEqual(spineHelp(spec: spine, row: idleRow, locale: en), "Claude Code · 12 waiting · oldest 3d")
        XCTAssertEqual(spineHelp(spec: spine, row: runningRow, locale: en), "Claude Code · 4 of 12 read")
        XCTAssertEqual(spineHelp(spec: remainder, row: nil, locale: en), "4 more on the pile, in Details")
    }

    func test_queueRowWords() {
        XCTAssertEqual(queueRowWords(.waiting(1234), locale: en), "1,234 waiting")
        XCTAssertEqual(queueRowWords(.reading(read: 4, total: 12, fill: 0.33), locale: en), "4 of 12 read")
        XCTAssertEqual(queueRowWords(.done, locale: en), "all read")
        XCTAssertEqual(queueRowWords(.nextCycle, locale: en), "next cycle")
    }

    private func episode(_ id: String, _ origin: String, day: Int) throws -> EpisodeQueueItem {
        try JSONDecoder().decode(EpisodeQueueItem.self, from: Data(
            #"{"id":"\#(id)","timestamp":"2026-09-\#(String(format: "%02d", day))T00:00:00Z","source":"x","origin":"\#(origin)","preview":"","processed":false}"#.utf8))
    }

    func test_thePopoverShowsSixNewestAndCountsTheRest() throws {
        let all = try (1...9).map { try episode("e\($0)", "claude-code", day: $0) } + [try episode("r", "rss", day: 20)]
        let shown = spinePopoverRows(origin: "claude-code", in: all)
        XCTAssertEqual(shown.rows.map(\.id), ["e9", "e8", "e7", "e6", "e5", "e4"])
        XCTAssertEqual(shown.more, 3)
        XCTAssertEqual(spinePopoverRows(origin: "rss", in: all).more, 0)
    }

    /// Design defect 7 / Z-P19 — spine text is a theme token, never `.white`.
    func test_thePileSpellsNoLiteralWhite() throws {
        let file = try SleepNumbersLintTests.sleepSources().first { $0.lastPathComponent == "BookPile.swift" }!
        XCTAssertFalse(try String(contentsOf: file, encoding: .utf8).contains(".white"))
    }

    // MARK: The lamp (§7.2, I8–I10)

    private func previews(scheduled: String, why: String) -> SleepEnginePreviews {
        SleepEnginePreviews(manual: SleepEnginePreview(engine: "claude-cli", model: "m", why: "your plan"),
                            scheduled: SleepEnginePreview(engine: scheduled, model: "m", why: why))
    }

    /// Ruling 4 at the moment of choice: the scheduled engine and its reason
    /// are ALWAYS on screen in the popover — before any flip, lit or not.
    func test_theEngineLineIsShownBeforeTheToggleCanFlip() {
        let lit = lampEngineLine(preview: previews(scheduled: "ollama", why: "Ollama is running — using the local engine"), lampLit: true)
        XCTAssertEqual(lit?.engine, "ollama")
        XCTAssertEqual(lit?.text, "Scheduled runs use Ollama (on this Mac). Ollama is running — using the local engine.")
        let dark = lampEngineLine(preview: previews(scheduled: "litellm", why: "scheduled cycle — Sleep engine selection is user-triggered only"), lampLit: false)
        XCTAssertEqual(dark?.text, "If you light it, scheduled runs would use API key. Scheduled cycle — Sleep engine selection is user-triggered only.")
        XCTAssertNil(lampEngineLine(preview: nil, lampLit: true), "absent until the preview loads — never guessed")
    }

    func test_theLampSaysItsStateInWords() {
        XCTAssertEqual(lampAccessibilityLabel(lampLit: true, scheduleText: "Every day at 03:00", nextRunText: "Next run Sep 24, 3:00 AM"),
                       "Lamp, on. Every day at 03:00. Next run Sep 24, 3:00 AM.")
        XCTAssertEqual(lampAccessibilityLabel(lampLit: false, scheduleText: Copy.nextRunManual, nextRunText: Copy.nextRunManual),
                       "Lamp, off. Sleep runs only when you ask.")
    }
}
