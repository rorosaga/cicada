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
        // Track I part b retired `FirstRunSheet`: the Welcome embeds the card's
        // `.compact` form through `EngineChoice` (R-IB13).
        XCTAssertTrue(try source("Views/Onboarding/EngineChoice.swift").contains("EngineCard(style: .compact"),
                      "onboarding keeps the card, in its compact form (R-O8, R-IB13)")
    }

    /// Review round 1: the Sleep page's read-only engine lines name services,
    /// so they draw through the Engines page's marked row, never bare text.
    func testTheSleepPagesEngineLinesWearTheirMarks() throws {
        let sleep = try source("Views/Settings/SettingsSleepView.swift")
        XCTAssertTrue(sleep.contains("EngineChooser.previewRow(preview.manual"))
        XCTAssertTrue(sleep.contains("EngineChooser.previewRow(preview.scheduled"))
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

    /// G139 final review — `use_for_sleep` only changes anything when the API
    /// key card is chosen (`engine_select.resolve_llm_mode`), so the switch
    /// lives there, says so, and reloads the engine view model: the chooser's
    /// "Next cycle you start" line and the Sleep page's engine line both read
    /// `preview.manual`, which this pref feeds.
    func testTheClaudePlanSwitchSitsUnderTheAPIKeyCardAndReloadsThePreview() throws {
        let engines = try source("Views/Settings/EnginesView.swift")
        XCTAssertTrue(engines.contains("engineVM.response?.mode == \"byok\""))
        XCTAssertTrue(engines.contains("Copy.apiKeyGroup"))
        let setter = try XCTUnwrap(engines.range(of: "setUseForSleep(plan.id, on: on)"))
        XCTAssertTrue(engines[setter.upperBound...].contains("await engineVM.load()"),
                      "the setter reloads SleepEngineViewModel after writing the pref")
        XCTAssertFalse(Copy.useClaudePlanWhenIStart.lowercased().contains("auto"),
                       "the switch does nothing under Auto; its label must not name it")
        XCTAssertEqual(Copy.apiKeyGroup, Copy.engineLabel("litellm"),
                       "the heading is the API key card's own name")
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

    /// Review round 1: `sleep_scheduler.next_run_at` sends a naive local ISO
    /// string for daily and interval (no offset). It must read as a run, not
    /// as "not scheduled yet" — the tests above only fed `Z` strings.
    func testANaiveServerValueIsReadAsLocalTime() {
        XCTAssertTrue(SleepScheduleText.detail(mode: "daily", nextSleepAt: "2026-09-24T03:00:00",
                                               now: now, calendar: utc, locale: en)
                        .hasPrefix("Next run: tomorrow at "))
        XCTAssertTrue(SleepScheduleText.detail(mode: "interval", nextSleepAt: "2026-09-23T13:54:02",
                                               now: now, calendar: utc, locale: en)
                        .hasPrefix("Next run: today at "))
        XCTAssertTrue(SleepScheduleText.detail(mode: "daily", nextSleepAt: "2026-09-24T03:00:00.123456",
                                               now: now, calendar: utc, locale: en)
                        .hasPrefix("Next run: tomorrow at "))
    }

    /// Naive means the calendar's zone, not UTC: 03:00 in Lima is 08:00Z.
    func testNaiveParseUsesTheGivenZoneAndLeavesOffsetStringsAlone() {
        let lima = TimeZone(identifier: "America/Lima")!
        XCTAssertEqual(StatusSnapshot.parseDate("2026-09-24T03:00:00", naiveTimeZone: lima),
                       ISO8601DateFormatter().date(from: "2026-09-24T08:00:00Z"))
        XCTAssertEqual(StatusSnapshot.parseDate("2026-09-24T03:00:00Z", naiveTimeZone: lima),
                       ISO8601DateFormatter().date(from: "2026-09-24T03:00:00Z"))
        XCTAssertNil(StatusSnapshot.parseDate("not a date"))
    }

    func testAfterImportsWithNothingQueuedSaysWhatItWaitsFor() {
        XCTAssertEqual(SleepScheduleText.detail(mode: "after_import", nextSleepAt: nil, now: now, calendar: utc, locale: en),
                       "Starts about 10 minutes after the last import lands, if nothing is running.")
        XCTAssertEqual(SleepScheduleText.everyHours(1), "Every hour")
        XCTAssertEqual(SleepScheduleText.everyHours(6), "Every 6 hours")
        XCTAssertEqual(SleepScheduleText.modes.map(\.value), ["manual", "daily", "interval", "after_import"])
    }
}
