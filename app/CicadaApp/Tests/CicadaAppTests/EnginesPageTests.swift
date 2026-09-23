import XCTest
@testable import CicadaApp

/// G139 / A3 — Engines owns engine choice; Sleep keeps when; Plans & keys
/// keeps credentials (R-O8, R-O9, R-O10).
final class EnginesPageTests: XCTestCase {
    private func source(_ relative: String) throws -> String {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp")
        return try String(contentsOf: root.appendingPathComponent(relative), encoding: .utf8)
    }

    func testEnginesSitsFirstInEnginesAndKeys() {
        XCTAssertEqual(SettingsGroup.enginesAndKeys.sections.first, .engines)
        XCTAssertEqual(SettingsSection.engines.title, Copy.engines)
        XCTAssertEqual(SettingsSection.engines.icon, "cpu")
        XCTAssertEqual(Copy.settingsEngines, "\(Copy.settings) → \(Copy.engines)")
    }

    func testTheChooserIsTheOnePickerAndOnboardingStillEmbedsTheCard() throws {
        XCTAssertTrue(try source("Views/Settings/EngineCard.swift").contains("EngineChooser()"))
        XCTAssertTrue(try source("Views/Settings/EnginesView.swift").contains("EngineChooser()"))
        XCTAssertFalse(try source("Views/Settings/SettingsSleepView.swift").contains("EngineCard("),
                       "Sleep shows one read-only engine line now (A3)")
        XCTAssertTrue(try source("Views/Onboarding/FirstRunSheet.swift").contains("EngineCard()"),
                      "onboarding is another track's; it keeps the card until it moves (R-O8)")
    }

    /// K4 / R-O9 — no price, no cost-estimate control, no engine switch left on Plans & keys.
    func testPlansAndKeysIsCredentialsOnly() throws {
        for file in ["Views/Connections/ConnectionsView.swift", "Views/Settings/EnginesView.swift",
                     "Views/Settings/EngineChooser.swift", "Views/Settings/SettingsSleepView.swift"] {
            let text = try source(file)
            for needle in ["priceUsdMonth", "priceNote", "showsTierPicker", "yourMaxTier", "setTier("] {
                XCTAssertFalse(text.contains(needle), "\(file) still reaches \(needle)")
            }
        }
        XCTAssertFalse(try source("Views/Connections/ConnectionsView.swift").contains("setUseForSleep"),
                       "the Auto switch lives on Engines now (A3)")
        XCTAssertTrue(try source("Views/Settings/EnginesView.swift").contains("setUseForSleep"))
    }

    func testThePreviewMarksAreTheCardsMarks() {
        XCTAssertEqual(EngineOption.previewMark(engine: "claude-cli"), EngineOption.logoName(for: "agent"))
        XCTAssertEqual(EngineOption.previewMark(engine: "codex-cli"), EngineOption.logoName(for: "codex"))
        XCTAssertEqual(EngineOption.previewMark(engine: "ollama"), EngineOption.logoName(for: "local"))
        XCTAssertNil(EngineOption.previewMark(engine: "litellm"))
    }

    // MARK: Next run (R-O10 — the server's value, never the local picker's)

    private var utc: Calendar { var c = Calendar(identifier: .gregorian); c.timeZone = TimeZone(identifier: "UTC")!; return c }
    private let en = Locale(identifier: "en_US")
    private let now = ISO8601DateFormatter().date(from: "2026-09-23T10:00:00Z")!

    func testManualNeverClaimsARun() {
        XCTAssertEqual(SleepScheduleText.detail(mode: "manual", nextSleepAt: "2026-09-23T15:00:00Z",
                                                now: now, calendar: utc, locale: en),
                       "Only when you press Consolidate now.")
    }

    func testNextRunNamesTodayTomorrowOrTheWeekday() {
        func d(_ iso: String) -> String {
            SleepScheduleText.detail(mode: "interval", nextSleepAt: iso, now: now, calendar: utc, locale: en)
        }
        XCTAssertTrue(d("2026-09-23T15:00:00Z").hasPrefix("Next run: today at "))
        XCTAssertTrue(d("2026-09-24T03:00:00Z").hasPrefix("Next run: tomorrow at "))
        XCTAssertTrue(d("2026-09-26T03:00:00Z").hasPrefix("Next run: Saturday at "))
    }

    func testAfterImportsWithNothingQueuedSaysWhatItWaitsFor() {
        XCTAssertEqual(SleepScheduleText.detail(mode: "after_import", nextSleepAt: nil, now: now, calendar: utc, locale: en),
                       "Starts about 10 minutes after the last import lands, if nothing is running.")
        XCTAssertEqual(SleepScheduleText.everyHours(1), "Every hour")
        XCTAssertEqual(SleepScheduleText.everyHours(6), "Every 6 hours")
        XCTAssertEqual(SleepScheduleText.modes.map(\.value), ["manual", "daily", "interval", "after_import"])
    }
}
