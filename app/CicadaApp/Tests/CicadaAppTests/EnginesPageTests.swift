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

    /// D6 (2026-10-22): Engines and Plans & keys became Settings → Intelligence. The "use my Claude plan" switch keeps
    /// its rule — only under an API key — and still reloads the engine after writing the pref.
    func testIntelligenceKeepsTheEnginesSwitches() throws {
        let page = try source("Views/Settings/IntelligenceView.swift")
        XCTAssertTrue(page.contains("engineVM.response?.mode == \"byok\""))
        let setter = try XCTUnwrap(page.range(of: "setUseForSleep(plan.id, on: on)"))
        XCTAssertTrue(page[setter.upperBound...].contains("await engineVM.load()"))
        XCTAssertTrue(page.contains("EngineOption.showsOverageToggle"), "extra usage stays reachable (R-E13)")
        XCTAssertTrue(page.contains("SettingsRow(.sleepUsePlan"), "ruling 4c's switch, under its own words")
        XCTAssertFalse(Copy.useClaudePlanWhenIStart.lowercased().contains("auto"))
        XCTAssertTrue(try source("Views/Settings/EngineCard.swift").contains("EngineChooser()"),
                      "onboarding keeps the card")
    }

    func testThePreviewMarksAreTheCardsMarks() {
        XCTAssertEqual(EngineOption.previewMark(engine: "claude-cli"), EngineOption.logoName(for: "agent"))
        XCTAssertEqual(EngineOption.previewMark(engine: "codex-cli"), EngineOption.logoName(for: "codex"))
        XCTAssertEqual(EngineOption.previewMark(engine: "ollama"), EngineOption.logoName(for: "local"))
        XCTAssertNil(EngineOption.previewMark(engine: "litellm"))
        // R-AG12 / DR-52 — a key run through OpenRouter wears OpenRouter's mark and name.
        XCTAssertEqual(EngineOption.previewMark(engine: "litellm", model: "openrouter/~openai/gpt-mini-latest"),
                       EngineOption.logoName(for: "openrouter"))
        XCTAssertNil(EngineOption.previewMark(engine: "litellm", model: "gpt-5.4-mini"))
        XCTAssertEqual(EngineOption.previewName(engine: "litellm", model: "openrouter/~openai/gpt-mini-latest"),
                       "OpenRouter")
        XCTAssertEqual(EngineOption.previewName(engine: "litellm", model: "gpt-5.4-mini"), Copy.engineLabel("litellm"))
        XCTAssertEqual(EngineMark.source(for: "litellm", model: "openrouter/~openai/gpt-mini-latest"),
                       .logo("openrouter"))
        XCTAssertEqual(EngineMark.source(for: "litellm"), .symbol("key"))
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
