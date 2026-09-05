import XCTest
@testable import CicadaApp

/// G125 v3 Task 6 — "In the queue". The queue card stopped being a list with a
/// button in its footer and became the page's *schedule* statement: what is
/// waiting, how far a running cycle has read it, when the next run happens,
/// and — only when the two differ — which engine that scheduled run would use.
///
/// Every case here is a pure function over a value type; no view is stood up,
/// which is how the rest of `Views/Sleep/` is tested.
final class SleepQueueCardV3Tests: XCTestCase {

    // MARK: scheduleSentence — the lamp's mandatory text twin (P11 / R-A3)

    /// The desk lamp is lit iff `mode != "manual"`, and art alone is never
    /// allowed to carry a fact — this sentence is the twin that says the same
    /// thing in words. All four modes, and none of them inventing a time it
    /// was not given.
    func test_scheduleSentence_manualSaysManualOnly() {
        let s = ScheduleConfig(mode: "manual", hour: 3, minute: 0)
        XCTAssertEqual(scheduleSentence(s), Copy.nextRunManual)
        XCTAssertEqual(Copy.nextRunManual, "Manual only")
    }

    func test_scheduleSentence_dailyNamesTheZeroPaddedTime() {
        XCTAssertEqual(scheduleSentence(ScheduleConfig(mode: "daily", hour: 2, minute: 0)),
                       "Every day at 02:00")
        XCTAssertEqual(scheduleSentence(ScheduleConfig(mode: "daily", hour: 23, minute: 45)),
                       "Every day at 23:45")
    }

    func test_scheduleSentence_intervalPluralisesAndSaysHourAtOne() {
        XCTAssertEqual(scheduleSentence(ScheduleConfig(mode: "interval", hour: 3, minute: 0, intervalHours: 6)),
                       "Every 6 h")
        XCTAssertEqual(scheduleSentence(ScheduleConfig(mode: "interval", hour: 3, minute: 0, intervalHours: 1)),
                       "Every hour")
    }

    func test_scheduleSentence_afterImportNamesTheSettleRule() {
        XCTAssertEqual(scheduleSentence(ScheduleConfig(mode: "after_import", hour: 3, minute: 0)),
                       "After imports settle")
    }

    /// An unrecognized mode from a newer backend must read as "we do not know
    /// of a schedule", never as a fabricated one.
    func test_scheduleSentence_unknownModeFallsBackToManualOnly() {
        XCTAssertEqual(scheduleSentence(ScheduleConfig(mode: "weekly", hour: 3, minute: 0)),
                       Copy.nextRunManual)
    }

    // MARK: queueRowState

    private func row(count: Int, read: Int? = nil, total: Int? = nil) -> StudyRow {
        StudyRow(origin: "claude-code", label: "Claude Code", count: count,
                 oldestAge: "3d", read: read, total: total)
    }

    func test_queueRowState_idleIsThePlainWaitingCount() {
        XCTAssertEqual(queueRowState(row(count: 188)), .waiting(188))
        // Half a pair is still idle — `studyRows` only ever sets both.
        XCTAssertEqual(queueRowState(row(count: 188, read: 12, total: nil)), .waiting(188))
        XCTAssertEqual(queueRowState(row(count: 188, read: nil, total: 188)), .waiting(188))
    }

    func test_queueRowState_runningCarriesBothNumbersAndTheFill() {
        guard case .reading(let read, let total, let fill) = queueRowState(row(count: 188, read: 12, total: 188)) else {
            return XCTFail("a running row with 12 of 188 read must be .reading")
        }
        XCTAssertEqual(read, 12)
        XCTAssertEqual(total, 188)
        XCTAssertEqual(fill, 12.0 / 188.0, accuracy: 1e-9)
    }

    func test_queueRowState_readEqualsTotalIsTheDimmedCheck() {
        XCTAssertEqual(queueRowState(row(count: 188, read: 188, total: 188)), .done)
    }

    /// **Precedence, asserted rather than implied.** A source the episode cap
    /// left out of this cycle arrives as `total == 0` (`studyRows`'s own
    /// doc comment), which is ALSO `read == total`. If `.done` were tested
    /// first, a source that has not been touched at all would render the
    /// finished ✓ instead of "next cycle" — the exact inversion of the truth.
    func test_queueRowState_zeroTotalIsNextCycleNotDone() {
        XCTAssertEqual(queueRowState(row(count: 42, read: 0, total: 0)), .nextCycle)
    }

    // MARK: scheduledEngineLine — R-A9, the asymmetry is shown, never applied

    private func previews(manual: String, scheduled: String) -> SleepEnginePreviews {
        SleepEnginePreviews(
            manual: .init(engine: manual, model: "m", why: "why"),
            scheduled: .init(engine: scheduled, model: "m", why: "why")
        )
    }

    func test_scheduledEngineLine_isNilWhenBothPreviewsAgree() {
        XCTAssertNil(scheduledEngineLine(preview: previews(manual: "ollama", scheduled: "ollama")))
    }

    /// Ruling 4 (a scheduled cycle never spends plan quota) makes manual and
    /// scheduled genuinely different on a plan-backed bank. The footer says so
    /// in the reader's own words rather than letting the asymmetry apply
    /// silently.
    func test_scheduledEngineLine_namesTheScheduledEngineWhenTheyDiffer() throws {
        let line = try XCTUnwrap(scheduledEngineLine(preview: previews(manual: "claude-cli", scheduled: "ollama")))
        XCTAssertTrue(line.contains(Copy.engineLabel("ollama")), line)
        XCTAssertFalse(line.contains(Copy.engineLabel("claude-cli")),
                       "the line is about the SCHEDULED run — naming both engines is the settings card's job")
    }

    func test_scheduledEngineLine_isNilWithoutAPreview() {
        XCTAssertNil(scheduledEngineLine(preview: nil))
    }

    // MARK: Source lints

    private func source(_ relativePath: String) throws -> String {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp package root
            .appendingPathComponent("Sources/CicadaApp")
        return try String(contentsOf: root.appendingPathComponent(relativePath), encoding: .utf8)
    }

    /// The Consolidate control left this file for the hero in Task 4 (R-A7);
    /// `FixWaveTests` owns the folder-wide "exactly one" rule, this pins the
    /// half of it that is about the card the control used to live in.
    func test_theQueueCardNoLongerCarriesAConsolidateControl() throws {
        let text = try source("Views/Sleep/StudyListCard.swift")
        XCTAssertFalse(text.contains("Copy.consolidateNow"))
        XCTAssertFalse(text.contains("sleepVM.triggerManually()"))
    }

    /// P5 — **one writer**, deliberately not "one mention". The literal also
    /// appears in `SettingsScene.swift` (the `@AppStorage` READER, which must
    /// keep it) and in `SettingsSection.swift`'s doc comment, and both stay;
    /// what must never fork is the code that WRITES the seed before a
    /// `SettingsLink` opens the scene.
    func test_exactlyOneFileWritesTheSettingsSectionSeed() throws {
        let writers = try ThemeTokenTests.swiftSources()
            .filter { try String(contentsOf: $0, encoding: .utf8).contains(#"forKey: "cicada.settingsSection""#) }
            .map(\.lastPathComponent)
            .sorted()
        XCTAssertEqual(writers, ["SettingsSectionLink.swift"],
                       "the section seed must be written in exactly one place (P5)")
    }

    /// `EmptyStateView` adopted `SettingsSectionLink`, so the key must be gone
    /// from it entirely — comment included, since a doc comment repeating a
    /// key is how a second writer gets reintroduced by copy-paste.
    func test_emptyStateViewNoLongerMentionsTheSettingsSectionKey() throws {
        XCTAssertFalse(try source("Views/Common/EmptyStateView.swift").contains("cicada.settingsSection"))
    }
}
