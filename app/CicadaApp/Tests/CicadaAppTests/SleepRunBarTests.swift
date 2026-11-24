import XCTest
@testable import CicadaApp

/// 2026-11-24 — the run bar's words (the engine, the schedule in a few words) and the home strip's rule for drawing
/// at all, now that the machine chips say the rest. Synthetic names only.
final class SleepRunBarTests: XCTestCase {
    private let en = Locale(identifier: "en_US")

    func testTheScheduleIsAFewWords() {
        XCTAssertEqual(RunBarText.schedule(ScheduleConfig(mode: "manual", hour: 3, minute: 0), locale: en), "Off")
        XCTAssertEqual(RunBarText.schedule(ScheduleConfig(mode: "daily", hour: 3, minute: 0), locale: en), "Daily at 3:00 AM")
        XCTAssertEqual(RunBarText.schedule(ScheduleConfig(mode: "daily", hour: 15, minute: 30), locale: en), "Daily at 3:30 PM")
        XCTAssertEqual(RunBarText.schedule(ScheduleConfig(mode: "interval", hour: 0, minute: 0, intervalHours: 1), locale: en), "Hourly")
        XCTAssertEqual(RunBarText.schedule(ScheduleConfig(mode: "interval", hour: 0, minute: 0, intervalHours: 6), locale: en), "Every 6 h")
        XCTAssertEqual(RunBarText.schedule(ScheduleConfig(mode: "after_import", hour: 0, minute: 0), locale: en), "After imports")
    }

    /// The engine is the thing the person asked to see, so its full label goes last: the schedule gives way to its moon
    /// and switch, then the primary to its shorter word, and only then the engine to its mark and model. The primary
    /// itself is never dropped.
    func testTheBarDropsWordsInOrderAndTheEngineLast() {
        XCTAssertEqual(RunBarLevel.allCases, [.full, .scheduleGlyph, .primaryShort, .engineShort])
        XCTAssertEqual(RunBarLevel.allCases.map(\.schedule), [true, false, false, false])
        XCTAssertEqual(RunBarLevel.allCases.map(\.primaryIsShort), [false, false, true, true])
        XCTAssertEqual(RunBarLevel.allCases.map(\.engineIsShort), [false, false, false, true])
        XCTAssertEqual(Copy.SleepPage.consolidateShort, "Consolidate")
        XCTAssertTrue(Copy.consolidateNow.hasPrefix(Copy.SleepPage.consolidateShort), "the short word is the long one's start")
    }

    private func engineResponse(model: String) -> SleepEngineResponse {
        SleepEngineResponse(
            mode: "agent", model: model, disambiguationModel: "", source: "prefs",
            candidates: [SleepEngineCandidate(id: "agent", label: "Claude plan", available: true, connected: true,
                                              models: ["haiku"], detail: nil)],
            preview: SleepEnginePreviews(manual: SleepEnginePreview(engine: "claude-cli", model: model, why: "chosen"),
                                         scheduled: SleepEnginePreview(engine: "claude-cli", model: model, why: "ruling 4")))
    }

    /// The engine's label in full, the model alone when the bar is short, the full label again when there is no model to
    /// say, and nothing at all before the preview is known (a guessed engine is worse than silence).
    func testTheEngineLabelFallsBackToTheFullLabelWhenThereIsNoModel() {
        XCTAssertEqual(RunBarText.engine(engineResponse(model: "haiku"), short: false), "Claude plan · haiku")
        XCTAssertEqual(RunBarText.engine(engineResponse(model: "haiku"), short: true), "haiku")
        XCTAssertEqual(RunBarText.engine(engineResponse(model: ""), short: true),
                       EngineQuickMenuModel.buttonLabel(engineResponse(model: "")),
                       "an empty model says the full label, never an empty word")
        XCTAssertNil(RunBarText.engine(nil, short: true))
        XCTAssertNil(RunBarText.engine(nil, short: false))
        let noPreview = SleepEngineResponse(mode: "auto", model: "", disambiguationModel: "", source: "default",
                                            candidates: [], preview: nil)
        XCTAssertNil(RunBarText.engine(noPreview, short: true))
    }

    /// A key wears its provider's mark (read from the model it runs); the key glyph only when that is unknown.
    func testAKeyWearsItsProvidersMarkAndTheGlyphOnlyWhenUnknown() {
        XCTAssertEqual(EngineMark.source(for: "litellm", model: "claude-haiku-4-5"), .logo("claude"))
        XCTAssertEqual(EngineMark.source(for: "litellm", model: "gpt-5.4-mini"), .logo("chatgpt"))
        XCTAssertEqual(EngineMark.source(for: "litellm", model: "totally-unknown-model"), .symbol("key"))
        XCTAssertEqual(EngineMark.source(for: "litellm", model: nil), .symbol("key"))
        XCTAssertEqual(EngineMark.source(for: "claude-cli"), .origin("claude-code"), "a plan keeps its own mark")
    }

    private func overview(_ json: String) throws -> HomeOverview {
        try JSONDecoder().decode(HomeOverview.self, from: Data(json.utf8))
    }

    /// The strip is drawn only when there is something to do or to say: a device that can take the home, a take-over,
    /// or a line in words — never to name devices the chips already name.
    func testTheHomeStripDrawsOnlyWhatAChipCannotSay() throws {
        let quiet = try overview("""
        {"shared": true, "role": "home", "home": {"id": "aaaaaaaa", "name": "device-a", "me": true, "online": true},
         "devices": [{"id": "bbbbbbbb", "name": "device-b", "me": false, "online": false, "keepsCopy": false,
                      "canBeHome": false}]}
        """)
        XCTAssertFalse(HomeStrip.hasNews(quiet, movingLine: nil, problem: nil, isMoving: false))
        XCTAssertTrue(HomeStrip.movable(quiet, isMoving: false).isEmpty)

        let movable = try overview("""
        {"shared": true, "role": "home", "home": {"id": "aaaaaaaa", "name": "device-a", "me": true, "online": true},
         "devices": [{"id": "bbbbbbbb", "name": "device-b", "me": false, "online": true, "keepsCopy": true,
                      "behind": 0, "canBeHome": true}]}
        """)
        XCTAssertEqual(HomeStrip.movable(movable, isMoving: false).map(\.name), ["device-b"])
        XCTAssertTrue(HomeStrip.hasNews(movable, movingLine: nil, problem: nil, isMoving: false))
        XCTAssertTrue(HomeStrip.movable(movable, isMoving: true).isEmpty, "no second move while one is under way")
        XCTAssertTrue(HomeStrip.hasNews(quiet, movingLine: "Your memory is moving.", problem: nil, isMoving: true))
        XCTAssertTrue(HomeStrip.hasNews(quiet, movingLine: nil, problem: "That did not work.", isMoving: false))
    }
}
