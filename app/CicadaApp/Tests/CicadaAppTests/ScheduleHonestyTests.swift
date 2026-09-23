import XCTest
@testable import CicadaApp

/// Track I T6 (design §5.3) — every "when will it be read" sentence is a pure
/// function of schedule × the engine previews. Ruling 4 (a scheduled cycle
/// never spends plan quota) is shown, never promised away.
final class ScheduleHonestyTests: XCTestCase {
    private func inputs(manual: String, scheduled: String, mode: ScheduleMode = .manual, hasKey: Bool = false,
                        ollama: Bool = false, claude: Bool = true, hour: Int = 3, interval: Int = 6) -> HonestyInputs {
        HonestyInputs(
            schedule: ScheduleConfig(mode: mode.rawValue, hour: hour, minute: 0, intervalHours: interval),
            preview: SleepEnginePreviews(manual: .init(engine: manual, model: "m", why: "w"),
                                         scheduled: .init(engine: scheduled, model: "m", why: "w")),
            hasKey: hasKey, ollamaReady: ollama, claudeConnected: claude)
    }

    /// The invariant, over every plan and every mode.
    func testRuling4APlanNeverPromisesAScheduledRead() {
        for manual in ["claude-cli", "codex-cli"] {
            for mode in ScheduleMode.allCases {
                let i = inputs(manual: manual, scheduled: "litellm", mode: mode, hasKey: false)
                XCTAssertEqual(ScheduleHonesty.enabledModes(i), [.manual], "\(manual) \(mode)")
                XCTAssertTrue(ScheduleHonesty.offerEveningReminder(i))
                XCTAssertEqual(ScheduleHonesty.afterImportLine(i),
                               mode == .manual ? Copy.afterImportWhenYouAsk : Copy.afterImportPlanWaits)
            }
        }
    }

    func testAKeyOnTheScheduleUnlocksEveryModeAndSaysWhoReads() {
        let i = inputs(manual: "claude-cli", scheduled: "litellm", mode: .daily, hasKey: true)
        XCTAssertEqual(ScheduleHonesty.enabledModes(i), Set(ScheduleMode.allCases))
        XCTAssertFalse(ScheduleHonesty.offerEveningReminder(i))
        XCTAssertEqual(ScheduleHonesty.afterImportLine(i), "Cicada reads these tonight at 3:00, using your API key.")
    }

    func testWhenPhrases() {
        func when(_ mode: ScheduleMode, hour: Int = 3, interval: Int = 6) -> String? {
            ScheduleHonesty.whenPhrase(ScheduleConfig(mode: mode.rawValue, hour: hour, minute: 0, intervalHours: interval))
        }
        XCTAssertEqual(when(.daily), "tonight at 3:00")
        XCTAssertEqual(when(.daily, hour: 21), "tonight at 21:00")
        XCTAssertEqual(when(.daily, hour: 9), "at 9:00")
        XCTAssertEqual(when(.interval, interval: 1), "within the hour")
        XCTAssertEqual(when(.interval), "within 6 hours")
        XCTAssertEqual(when(.afterImport), "a few minutes after imports settle")
        XCTAssertNil(when(.manual))
    }

    func testLineCPrimeWhenNothingCanReadAndNoPlanIsInvolved() {
        let i = inputs(manual: "ollama", scheduled: "ollama", mode: .daily, ollama: false)
        XCTAssertEqual(ScheduleHonesty.afterImportLine(i), Copy.afterImportWaits)
    }

    func testEngineLinesMatchTheDesignTable() {
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "claude-cli", scheduled: "litellm", hasKey: true)),
                       Copy.honestyPlanThenKey)
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "claude-cli", scheduled: "litellm")),
                       Copy.honestyPlanOnly)
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "ollama", scheduled: "ollama", ollama: true)),
                       Copy.honestyOllama)
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "litellm", scheduled: "litellm", hasKey: true)),
                       Copy.honestyKey)
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "litellm", scheduled: "litellm")),
                       Copy.honestyNothingYet)
    }

    /// Track P R4: onboarding never downgrades an `interval` chosen in Settings.
    func testAnExistingIntervalIsPreservedNeverOffered() {
        XCTAssertEqual(ScheduleHonesty.preservedMode(inputs(manual: "claude-cli", scheduled: "litellm", mode: .interval)),
                       .interval)
        XCTAssertNil(ScheduleHonesty.preservedMode(inputs(manual: "claude-cli", scheduled: "litellm", mode: .daily)))
    }

    func testNoPreviewNeverPromises() {
        var i = inputs(manual: "claude-cli", scheduled: "litellm", mode: .daily, hasKey: true)
        i.preview = nil
        XCTAssertEqual(ScheduleHonesty.enabledModes(i), [.manual])
        XCTAssertEqual(ScheduleHonesty.afterImportLine(i), Copy.afterImportWaits)
    }

    /// F6: the byok candidate is always `connected: true`, even with no key.
    func testTheKeyComesFromConnectionsNotTheByokCandidate() {
        let response = SleepEngineResponse(
            mode: "auto", model: "", disambiguationModel: "", source: "prefs",
            candidates: [SleepEngineCandidate(id: "byok", label: "API key", available: true, connected: true,
                                              models: [], detail: nil)],
            preview: nil)
        let i = HonestyInputs.from(schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0),
                                   response: response, connections: [])
        XCTAssertFalse(i.hasKey)
    }
}
