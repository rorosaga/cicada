import XCTest
@testable import CicadaApp

/// G245 (owner 2026-11-24, answer 6) — the card that shows the one shell line for the person's own scheduler. Cicada
/// starts nothing and schedules nothing, so the card's words are the whole safety story: what it runs, who is watching,
/// whose posts are read as whom, what is recommended and what Cicada cannot do. Provider-neutral ("your AI app").
final class ListRunCopyTests: XCTestCase {
    private let everything = [Copy.ListRun.title, Copy.ListRun.sentence, Copy.ListRun.exposure, Copy.ListRun.copyCommand,
                              Copy.ListRun.copyCommandHelp, Copy.ListRun.copied, Copy.ListRun.unavailable,
                              Copy.ListRun.exampleFold, Copy.ListRun.launchdIntro, Copy.ListRun.launchdExample]

    func testTheExposureIsSaidPlainlyAndNothingIsPromised() {
        let words = Copy.ListRun.exposure
        for phrase in ["runs your AI app with its normal tools with nobody watching",
                       "reads other people’s posts while signed in as you",
                       "separate browser profile signed in only to the sites being read is recommended",
                       "Cicada cannot limit what your AI app does in your browser"] {
            XCTAssertTrue(words.contains(phrase), phrase)
        }
        for promise in ["read-only", "never posts", "safe", "guarantee", "cannot click"] {
            XCTAssertFalse(words.lowercased().contains(promise), promise)
        }
    }

    func testTheSentenceSaysCicadaStartsAndSchedulesNothing() {
        XCTAssertTrue(Copy.ListRun.sentence.contains("Cicada starts nothing and schedules nothing"))
        XCTAssertTrue(Copy.ListRun.sentence.contains("your own scheduler"))
    }

    func testTheCopyNamesNoProviderOrProduct() {
        let banned = ["claude", "chatgpt", "codex", "openai", "anthropic", "gemini", "cursor", "ollama", "gpt-", "haiku"]
        for text in everything {
            for name in banned { XCTAssertFalse(text.lowercased().contains(name), "\(name) in: \(text)") }
        }
    }

    func testTheLaunchdExampleIsAPlaceholderNotAPathOnAnyOneMachine() {
        let example = Copy.ListRun.launchdExample
        XCTAssertTrue(example.contains("/Users/you/cicada-daily.sh"))
        XCTAssertTrue(example.contains("StartCalendarInterval") && example.contains("ProgramArguments"))
        XCTAssertFalse(example.contains("rorosaga"))
        XCTAssertTrue(example.hasPrefix("<?xml") && example.contains("</plist>"))
        XCTAssertTrue(Copy.ListRun.launchdIntro.contains("full path"), "launchd's PATH is short")
    }

    @MainActor
    func testTheModelHandsOverTheBackendsLineAndSaysNothingWhenItCannot() async {
        var deps = ReadingAgentModel.Deps(
            fetch: { ReadingSettingsResponse(agentEnabled: true, ackCurrent: true) },
            write: { _, _, _ in ReadingSettingsResponse() },
            prompt: { "" },
            fetchSites: { ReadingSitesResponse() },
            fetchMethods: { throw APIError.serverUnreachable },
            setMethod: { _, _ in throw APIError.serverUnreachable },
            addPage: { _ in throw APIError.serverUnreachable })
        deps.dailyCommand = { "my-app -p 'the words'" }
        let model = ReadingAgentModel(deps: deps)
        let line = await model.dailyCommand()
        XCTAssertEqual(line, "my-app -p 'the words'")
        deps.dailyCommand = { throw APIError.serverUnreachable }
        let older = ReadingAgentModel(deps: deps)
        let none = await older.dailyCommand()
        XCTAssertNil(none, "an older backend has no daily variant: nothing is copied")
    }
}
